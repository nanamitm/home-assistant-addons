"""LibISDB EPGDataSerializer と互換な EPG-SVC1 デコーダーのテスト。"""

from __future__ import annotations

import pathlib
import struct
import sys
import unittest


_APP_DIR = (
    pathlib.Path(__file__).resolve().parent.parent
    / "tvtest_epg_sync"
    / "app"
)
sys.path.insert(0, str(_APP_DIR))
import epg_parser  # noqa: E402


def u8(value):
    return struct.pack("<B", value)


def u16(value):
    return struct.pack("<H", value)


def u32(value):
    return struct.pack("<I", value)


def u64(value):
    return struct.pack("<Q", value)


def string(value):
    encoded = value.encode("utf-16-le")
    return u16(len(encoded) // 2) + encoded


def chunk(tag, body=b""):
    return u8(tag) + u32(len(body)) + body


def event_blob(
    event_id=0x1000,
    updated_time=1000,
    common=False,
    name="テスト番組『表題』",
    hour=21,
):
    flags = 4 | 0x08 | 0x10 | 0x20
    if common:
        flags |= 0x100
    event = (
        u16(event_id)
        + u16(flags)
        + struct.pack("<HBBBBBB", 2026, 8, 29, 6, hour, 30, 0)
        + u32(3600)
        + u64(updated_time)
    )
    result = chunk(epg_parser.TAG_EVENT, event)
    result += chunk(epg_parser.TAG_EVENT_NAME, string(name))
    result += chunk(epg_parser.TAG_EVENT_TEXT, string("概要のテキスト\r\n2行目"))
    extended = (
        u8(2)
        + string("出演者")
        + string("山田太郎、鈴木花子")
        + string("番組内容")
        + string("サロゲートペアを含む U00020BB7 のテキスト")
    )
    result += chunk(epg_parser.TAG_EVENT_EXTENDED_TEXT, extended)
    video = u8(1) + bytes((1, 0xB1, 0, 0)) + u32(0x6A706E) + string("映像")
    result += chunk(epg_parser.TAG_EVENT_VIDEO, video)
    audio = (
        u8(1)
        + bytes((0x02, 0x02, 0x03, 0x10, 0xFF, 1, 7, 0))
        + u32(0x6A706E)
        + u32(0)
        + string("主音声")
    )
    result += chunk(epg_parser.TAG_EVENT_AUDIO, audio)
    result += chunk(epg_parser.TAG_EVENT_GENRE, u8(2) + bytes((0x73, 0xFF, 0x12, 0x01)))
    group = (
        u8(1)
        + bytes((1, 2))
        + struct.pack("<HHHH", 0xE4, 0x1234, 4, 0x4010)
        + struct.pack("<HHHH", 0xE5, 0x1235, 4, 0x4011)
    )
    result += chunk(epg_parser.TAG_EVENT_GROUP, group)
    if common:
        result += chunk(epg_parser.TAG_EVENT_COMMON, struct.pack("<HH", 0xE5, 0x2001))
    result += chunk(0x7F, b"future field")
    result += chunk(epg_parser.TAG_EVENT_END)
    return result


def service_blob(*events, declared_count=None, nid=4, tsid=0x4010, sid=0xE4):
    if declared_count is None:
        declared_count = len(events)
    header = epg_parser.HEADER_STRUCT.pack(
        epg_parser.HEADER_MAGIC,
        1,
        nid,
        tsid,
        sid,
        0,
        declared_count,
        2000,
    )
    return header + b"".join(events) + chunk(epg_parser.TAG_END)


class ParserTestCase(unittest.TestCase):
    def test_parses_libisdb_fields(self):
        service = epg_parser.parse_service(service_blob(event_blob()))

        self.assertEqual(service.key, epg_parser.ServiceKey(4, 0x4010, 0xE4))
        self.assertEqual(service.declared_event_count, 1)
        self.assertEqual(service.updated_time, 2000)
        self.assertEqual(len(service.events), 1)

        event = service.events[0]
        self.assertEqual(event.event_id, 0x1000)
        self.assertEqual(event.start.isoformat(), "2026-08-29T21:30:00+09:00")
        self.assertEqual(event.end.isoformat(), "2026-08-29T22:30:00+09:00")
        self.assertEqual(event.name, "テスト番組『表題』")
        self.assertEqual(event.text, "概要のテキスト\r\n2行目")
        self.assertEqual(event.extended_text[1].text, "サロゲートペアを含む U00020BB7 のテキスト")
        self.assertEqual(event.videos[0].component_type, 0xB1)
        self.assertEqual(event.audios[0].text, "主音声")
        self.assertTrue(event.audios[0].main_component)
        self.assertEqual((event.genres[0].level1, event.genres[0].level2), (7, 3))
        self.assertEqual(event.groups[0].events[1].transport_stream_id, 0x4011)

    def test_parses_common_event_reference(self):
        service = epg_parser.parse_service(service_blob(event_blob(common=True)))
        event = service.events[0]
        self.assertTrue(event.is_common_event)
        self.assertEqual(event.common_event.service_id, 0xE5)
        self.assertEqual(event.common_event.event_id, 0x2001)

    def test_event_to_dict_has_compact_and_detailed_forms(self):
        event = epg_parser.parse_service(service_blob(event_blob())).events[0]
        compact = epg_parser.event_to_dict(event)
        detailed = epg_parser.event_to_dict(event, include_details=True)
        self.assertNotIn("extended_text", compact)
        self.assertEqual(detailed["extended_text"][0]["description"], "出演者")
        self.assertEqual(compact["genres"], [[7, 3], [1, 2]])

    def test_unknown_service_chunk_is_skipped(self):
        header = service_blob()[: epg_parser.HEADER_SIZE]
        blob = header + chunk(0x7E, b"future") + chunk(epg_parser.TAG_END)
        self.assertEqual(epg_parser.parse_service(blob).events, [])

    def test_rejects_bad_header_and_future_version(self):
        with self.assertRaises(epg_parser.EpgParseError):
            epg_parser.parse_service(b"short")

        blob = bytearray(service_blob())
        blob[0] = ord("X")
        with self.assertRaises(epg_parser.EpgParseError):
            epg_parser.parse_service(bytes(blob))

        blob = bytearray(service_blob())
        struct.pack_into("<I", blob, 8, 2)
        with self.assertRaises(epg_parser.EpgParseError):
            epg_parser.parse_service(bytes(blob))

    def test_rejects_truncated_data(self):
        blob = service_blob(event_blob())
        with self.assertRaises(epg_parser.EpgParseError):
            epg_parser.parse_service(blob[:-10])

    def test_rejects_excessive_declared_event_count(self):
        blob = bytearray(service_blob())
        struct.pack_into("<I", blob, 20, epg_parser.MAX_EVENT_COUNT + 1)
        with self.assertRaises(epg_parser.EpgParseError):
            epg_parser.parse_service(bytes(blob))

    def test_rejects_invalid_start_time(self):
        event = bytearray(event_blob())
        # Event chunk header(5) + EventID/flags(4) + year(2) の直後が month
        event[11] = 13
        with self.assertRaises(epg_parser.EpgParseError):
            epg_parser.parse_service(service_blob(bytes(event)))


if __name__ == "__main__":
    unittest.main()
