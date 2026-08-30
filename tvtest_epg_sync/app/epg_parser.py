"""LibISDB のサービス単位 EPG-SVC1 データを読み取る。

同期サーバが保管する blob は引き続き正本とし、このモジュールは番組表表示に
必要な情報を読み出すだけにする。フォーマットはチャンク形式なので、未知のタグは
読み飛ばして前方互換性を保つ。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


HEADER_MAGIC = b"EPG-SVC1"
HEADER_STRUCT = struct.Struct("<8sIHHHHIQ")
HEADER_SIZE = HEADER_STRUCT.size
MAX_FORMAT_VERSION = 1

MAX_EVENT_COUNT = 100_000
MAX_STRING_LENGTH = 8_192
MAX_EXTENDED_TEXT_COUNT = 64
MAX_NIBBLE_COUNT = 7

JST = timezone(timedelta(hours=9), "JST")


class EpgParseError(ValueError):
    """EPG-SVC1 データが不正な場合の例外。"""


@dataclass(slots=True, frozen=True)
class ServiceKey:
    nid: int
    tsid: int
    sid: int


@dataclass(slots=True)
class ExtendedText:
    description: str
    text: str


@dataclass(slots=True)
class VideoInfo:
    stream_content: int
    component_type: int
    component_tag: int
    language_code: int
    text: str


@dataclass(slots=True)
class AudioInfo:
    multilingual: bool
    main_component: bool
    stream_content: int
    component_type: int
    component_tag: int
    simulcast_group_tag: int
    quality_indicator: int
    sampling_rate: int
    language_code: int
    language_code2: int
    text: str


@dataclass(slots=True)
class GenreInfo:
    level1: int
    level2: int
    user1: int
    user2: int


@dataclass(slots=True)
class GroupEvent:
    service_id: int
    event_id: int
    network_id: int
    transport_stream_id: int


@dataclass(slots=True)
class EventGroup:
    group_type: int
    events: list[GroupEvent] = field(default_factory=list)


@dataclass(slots=True)
class CommonEvent:
    service_id: int
    event_id: int


@dataclass(slots=True)
class EpgEvent:
    key: ServiceKey
    event_id: int
    start: datetime
    duration: int
    updated_time: int
    running_status: int
    free_ca_mode: bool
    has_basic: bool
    has_extended: bool
    is_present: bool
    is_following: bool
    is_common_event: bool
    name: str = ""
    text: str = ""
    extended_text: list[ExtendedText] = field(default_factory=list)
    videos: list[VideoInfo] = field(default_factory=list)
    audios: list[AudioInfo] = field(default_factory=list)
    genres: list[GenreInfo] = field(default_factory=list)
    groups: list[EventGroup] = field(default_factory=list)
    common_event: CommonEvent | None = None

    @property
    def end(self) -> datetime:
        return self.start + timedelta(seconds=self.duration)


@dataclass(slots=True)
class EpgService:
    key: ServiceKey
    format_version: int
    declared_event_count: int
    updated_time: int
    events: list[EpgEvent]


class _Reader:
    def __init__(self, data: bytes | bytearray | memoryview) -> None:
        self.data = memoryview(data)
        self.pos = 0

    @property
    def remaining(self) -> int:
        return len(self.data) - self.pos

    def take(self, size: int) -> memoryview:
        if size < 0 or size > self.remaining:
            raise EpgParseError("チャンクの範囲を超えて読み込もうとしました")
        result = self.data[self.pos : self.pos + size]
        self.pos += size
        return result

    def u8(self) -> int:
        return self.take(1)[0]

    def u16(self) -> int:
        return struct.unpack_from("<H", self.take(2))[0]

    def u32(self) -> int:
        return struct.unpack_from("<I", self.take(4))[0]

    def u64(self) -> int:
        return struct.unpack_from("<Q", self.take(8))[0]

    def string(self) -> str:
        length = self.u16()
        if length > MAX_STRING_LENGTH:
            raise EpgParseError(f"文字列が長すぎます: {length}")
        return self.take(length * 2).tobytes().decode("utf-16-le", errors="replace")

    def epg_time(self) -> datetime:
        year = self.u16()
        month = self.u8()
        day = self.u8()
        self.u8()  # DayOfWeek は年月日から再計算できるため使用しない
        hour = self.u8()
        minute = self.u8()
        second = self.u8()
        try:
            return datetime(year, month, day, hour, minute, second, tzinfo=JST)
        except ValueError as error:
            raise EpgParseError(f"番組の開始日時が不正です: {error}") from error

    def chunk(self) -> tuple[int, "_Reader"]:
        if self.remaining < 5:
            raise EpgParseError("チャンクヘッダーが途中で切れています")
        tag = self.u8()
        size = self.u32()
        return tag, _Reader(self.take(size))

    def require_end(self, label: str) -> None:
        if self.remaining:
            raise EpgParseError(f"{label} チャンクに未解釈のデータがあります")


TAG_END = 0x01
TAG_EVENT = 0x04
TAG_EVENT_END = 0x05
TAG_EVENT_AUDIO = 0x06
TAG_EVENT_VIDEO = 0x07
TAG_EVENT_GENRE = 0x08
TAG_EVENT_NAME = 0x09
TAG_EVENT_TEXT = 0x0A
TAG_EVENT_EXTENDED_TEXT = 0x0B
TAG_EVENT_GROUP = 0x0C
TAG_EVENT_COMMON = 0x0D

FLAG_RUNNING_STATUS = 0x0007
FLAG_FREE_CA_MODE = 0x0008
FLAG_BASIC = 0x0010
FLAG_EXTENDED = 0x0020
FLAG_PRESENT = 0x0040
FLAG_FOLLOWING = 0x0080
FLAG_COMMON_EVENT = 0x0100


def parse_service(blob: bytes) -> EpgService:
    """EPG-SVC1 blob 全体を解析する。"""
    if len(blob) < HEADER_SIZE:
        raise EpgParseError("データが短すぎます")

    magic, version, nid, tsid, sid, _reserved, event_count, updated_time = (
        HEADER_STRUCT.unpack_from(blob)
    )
    if magic != HEADER_MAGIC:
        raise EpgParseError("EPG-SVC1 形式ではありません")
    if version > MAX_FORMAT_VERSION:
        raise EpgParseError(f"未対応のフォーマットバージョンです: {version}")
    if event_count > MAX_EVENT_COUNT:
        raise EpgParseError(f"番組数が多すぎます: {event_count}")

    key = ServiceKey(nid, tsid, sid)
    reader = _Reader(blob[HEADER_SIZE:])
    events: list[EpgEvent] = []
    found_end = False

    while reader.remaining:
        tag, body = reader.chunk()
        if tag == TAG_END:
            found_end = True
            break
        if tag != TAG_EVENT:
            continue
        if len(events) >= MAX_EVENT_COUNT:
            raise EpgParseError("番組数が上限を超えています")
        events.append(_parse_event(key, body, reader))

    if not found_end:
        raise EpgParseError("サービス終端チャンクがありません")

    return EpgService(key, version, event_count, updated_time, events)


def _parse_event(key: ServiceKey, body: _Reader, parent: _Reader) -> EpgEvent:
    event_id = body.u16()
    flags = body.u16()
    event = EpgEvent(
        key=key,
        event_id=event_id,
        start=body.epg_time(),
        duration=body.u32(),
        updated_time=body.u64(),
        running_status=flags & FLAG_RUNNING_STATUS,
        free_ca_mode=bool(flags & FLAG_FREE_CA_MODE),
        has_basic=bool(flags & FLAG_BASIC),
        has_extended=bool(flags & FLAG_EXTENDED),
        is_present=bool(flags & FLAG_PRESENT),
        is_following=bool(flags & FLAG_FOLLOWING),
        is_common_event=bool(flags & FLAG_COMMON_EVENT),
    )
    body.require_end("Event")

    while parent.remaining:
        tag, chunk = parent.chunk()
        if tag == TAG_EVENT_END:
            return event
        if tag == TAG_EVENT_NAME:
            event.name = chunk.string()
            chunk.require_end("EventName")
        elif tag == TAG_EVENT_TEXT:
            event.text = chunk.string()
            chunk.require_end("EventText")
        elif tag == TAG_EVENT_EXTENDED_TEXT:
            _parse_extended_text(chunk, event)
        elif tag == TAG_EVENT_VIDEO:
            _parse_videos(chunk, event)
        elif tag == TAG_EVENT_AUDIO:
            _parse_audios(chunk, event)
        elif tag == TAG_EVENT_GENRE:
            _parse_genres(chunk, event)
        elif tag == TAG_EVENT_GROUP:
            _parse_groups(chunk, event)
        elif tag == TAG_EVENT_COMMON:
            event.common_event = CommonEvent(chunk.u16(), chunk.u16())
            chunk.require_end("EventCommon")
        # 未知のタグは chunk の生成時点で親 Reader から切り離されているため読み飛ばせる

    raise EpgParseError("番組終端チャンクがありません")


def _parse_extended_text(reader: _Reader, event: EpgEvent) -> None:
    count = reader.u8()
    if count > MAX_EXTENDED_TEXT_COUNT:
        raise EpgParseError(f"詳細説明の件数が多すぎます: {count}")
    event.extended_text = [ExtendedText(reader.string(), reader.string()) for _ in range(count)]
    reader.require_end("EventExtendedText")


def _parse_videos(reader: _Reader, event: EpgEvent) -> None:
    count = reader.u8()
    values: list[VideoInfo] = []
    for _ in range(count):
        stream_content = reader.u8()
        component_type = reader.u8()
        component_tag = reader.u8()
        reader.u8()
        language_code = reader.u32()
        values.append(
            VideoInfo(
                stream_content,
                component_type,
                component_tag,
                language_code,
                reader.string(),
            )
        )
    reader.require_end("EventVideo")
    event.videos = values


def _parse_audios(reader: _Reader, event: EpgEvent) -> None:
    count = reader.u8()
    values: list[AudioInfo] = []
    for _ in range(count):
        flags = reader.u8()
        stream_content = reader.u8()
        component_type = reader.u8()
        component_tag = reader.u8()
        simulcast_group_tag = reader.u8()
        quality_indicator = reader.u8()
        sampling_rate = reader.u8()
        reader.u8()
        language_code = reader.u32()
        language_code2 = reader.u32()
        values.append(
            AudioInfo(
                bool(flags & 0x01),
                bool(flags & 0x02),
                stream_content,
                component_type,
                component_tag,
                simulcast_group_tag,
                quality_indicator,
                sampling_rate,
                language_code,
                language_code2,
                reader.string(),
            )
        )
    reader.require_end("EventAudio")
    event.audios = values


def _parse_genres(reader: _Reader, event: EpgEvent) -> None:
    count = reader.u8()
    if count > MAX_NIBBLE_COUNT:
        raise EpgParseError(f"ジャンル数が多すぎます: {count}")
    values: list[GenreInfo] = []
    for _ in range(count):
        content = reader.u8()
        user = reader.u8()
        values.append(GenreInfo(content >> 4, content & 0x0F, user >> 4, user & 0x0F))
    reader.require_end("EventGenre")
    event.genres = values


def _parse_groups(reader: _Reader, event: EpgEvent) -> None:
    group_count = reader.u8()
    groups: list[EventGroup] = []
    for _ in range(group_count):
        group_type = reader.u8()
        event_count = reader.u8()
        items = [
            GroupEvent(reader.u16(), reader.u16(), reader.u16(), reader.u16())
            for _ in range(event_count)
        ]
        groups.append(EventGroup(group_type, items))
    reader.require_end("EventGroup")
    event.groups = groups


def event_to_dict(event: EpgEvent, include_details: bool = False) -> dict[str, Any]:
    """Web API で扱いやすい辞書へ変換する。"""
    data: dict[str, Any] = {
        "event_id": event.event_id,
        "start": event.start.isoformat(),
        "end": event.end.isoformat(),
        "duration": event.duration,
        "title": event.name,
        "text": event.text,
        "genres": [[item.level1, item.level2] for item in event.genres],
        "free_ca_mode": event.free_ca_mode,
    }
    if include_details:
        data.update(
            {
                "updated_time": event.updated_time,
                "running_status": event.running_status,
                "extended_text": [
                    {"description": item.description, "text": item.text}
                    for item in event.extended_text
                ],
                "video": [
                    {
                        "stream_content": item.stream_content,
                        "component_type": item.component_type,
                        "component_tag": item.component_tag,
                        "language_code": item.language_code,
                        "text": item.text,
                    }
                    for item in event.videos
                ],
                "audio": [
                    {
                        "multilingual": item.multilingual,
                        "main_component": item.main_component,
                        "stream_content": item.stream_content,
                        "component_type": item.component_type,
                        "component_tag": item.component_tag,
                        "simulcast_group_tag": item.simulcast_group_tag,
                        "quality_indicator": item.quality_indicator,
                        "sampling_rate": item.sampling_rate,
                        "language_code": item.language_code,
                        "language_code2": item.language_code2,
                        "text": item.text,
                    }
                    for item in event.audios
                ],
            }
        )
    return data
