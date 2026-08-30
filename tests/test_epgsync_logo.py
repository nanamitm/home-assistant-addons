"""ARIB ロゴ PNG の変換のテスト"""

from __future__ import annotations

import pathlib
import struct
import sys
import unittest
import zlib

_APP_DIR = (
    pathlib.Path(__file__).resolve().parent.parent / "tvtest_epg_sync" / "app"
)
sys.path.insert(0, str(_APP_DIR))
import arib_png  # noqa: E402

PNG_SIGNATURE = bytes((0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A))


def chunk(kind: bytes, body: bytes) -> bytes:
    return (
        struct.pack(">I", len(body))
        + kind
        + body
        + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    )


def png(width=4, height=2, color_type=3, extra=b"", pixels=None):
    """テスト用の小さな PNG を組み立てる"""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    if pixels is None:
        # フィルタ種別 0 + 各行のインデックス
        pixels = b"".join(bytes([0]) + bytes([1] * width) for _ in range(height))
    return (
        PNG_SIGNATURE
        + chunk(b"IHDR", ihdr)
        + extra
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


def chunk_kinds(data: bytes) -> list[str]:
    kinds = []
    offset = 8
    while offset + 12 <= len(data):
        (length,) = struct.unpack_from(">I", data, offset)
        kinds.append(data[offset + 4:offset + 8].decode())
        offset += 12 + length
    return kinds


class AribPngTestCase(unittest.TestCase):
    def test_palette_matches_the_standard(self):
        self.assertEqual(len(arib_png.ARIB_PALETTE), 128)
        # 先頭は黒、インデックス 8 は完全な透明と決まっている。
        self.assertEqual(arib_png.ARIB_PALETTE[0], (0, 0, 0, 255))
        self.assertEqual(arib_png.ARIB_PALETTE[7], (255, 255, 255, 255))
        self.assertEqual(arib_png.ARIB_PALETTE[8], (0, 0, 0, 0))

    def test_inserts_the_palette_right_after_the_header(self):
        converted = arib_png.to_browser_png(png())
        self.assertEqual(
            chunk_kinds(converted), ["IHDR", "PLTE", "tRNS", "IDAT", "IEND"]
        )

        offset = 8 + 12 + 13
        (length,) = struct.unpack_from(">I", converted, offset)
        self.assertEqual(length, 128 * 3)
        palette = converted[offset + 8:offset + 8 + length]
        self.assertEqual(palette[:3], bytes((0, 0, 0)))
        self.assertEqual(palette[21:24], bytes((255, 255, 255)))

        offset += 12 + length
        (length,) = struct.unpack_from(">I", converted, offset)
        self.assertEqual(length, 128)
        self.assertEqual(converted[offset + 8 + 8], 0)  # インデックス 8 は透明

    def test_keeps_the_original_pixels(self):
        source = png()
        converted = arib_png.to_browser_png(source)
        self.assertIn(chunk(b"IDAT", zlib.compress(b"\x00\x01\x01\x01\x01" * 2)), converted)

    def test_leaves_a_png_that_already_has_a_palette(self):
        source = png(extra=chunk(b"PLTE", bytes(3 * 2)))
        self.assertEqual(arib_png.to_browser_png(source), source)

    def test_leaves_a_png_that_is_not_indexed(self):
        source = png(color_type=6)
        self.assertEqual(arib_png.to_browser_png(source), source)

    def test_converting_twice_changes_nothing(self):
        once = arib_png.to_browser_png(png())
        self.assertEqual(arib_png.to_browser_png(once), once)

    def test_rejects_data_that_is_not_a_png(self):
        with self.assertRaises(arib_png.AribPngError):
            arib_png.to_browser_png(b"not a png at all")

    def test_rejects_a_truncated_chunk(self):
        # 長さだけ大きく宣言して中身が足りないチャンク
        broken = (
            PNG_SIGNATURE
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 2, 8, 3, 0, 0, 0))
            + struct.pack(">I", 4096) + b"IDAT" + bytes(8)
        )
        with self.assertRaises(arib_png.AribPngError):
            arib_png.to_browser_png(broken)

    def test_rejects_a_header_of_the_wrong_length(self):
        broken = PNG_SIGNATURE + chunk(b"IHDR", bytes(12)) + chunk(b"IEND", b"")
        with self.assertRaises(arib_png.AribPngError):
            arib_png.to_browser_png(broken)


if __name__ == "__main__":
    unittest.main()
