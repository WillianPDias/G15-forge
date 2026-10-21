"""Synthetic parser regressions. Never format, boot or modify any disk image."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import p2_inspect_fat32 as inspect


def boot_sector(total=2097144, track=63):
    boot = bytearray(512)
    struct.pack_into("<H", boot, 11, 512)
    boot[13] = 8
    struct.pack_into("<H", boot, 14, 32)
    boot[16] = 2
    boot[21] = 0xF8
    struct.pack_into("<HHII", boot, 24, track, 16, 2048, total)
    struct.pack_into("<I", boot, 36, 2048)
    struct.pack_into("<IHH", boot, 44, 2, 1, 6)
    boot[82:90] = b"FAT32   "
    boot[510:512] = b"\x55\xaa"
    return boot


class FatGeometry(unittest.TestCase):
    def test_export_uses_exact_bounded_readonly_window(self):
        options = inspect.esp_readonly_options(Path('/lab/disk.qcow2'), 2048, 1073741824)
        fields = dict(item.split('=', 1) for item in options.split(','))
        self.assertEqual(fields['offset'], '1048576')
        self.assertEqual(fields['size'], '1073741824')
        self.assertEqual(fields['read-only'], 'on')
        self.assertEqual(fields['file.read-only'], 'on')
        self.assertEqual(fields['file.file.filename'], '/lab/disk.qcow2')
        with self.assertRaises(ValueError):
            inspect.esp_readonly_options(Path('/lab/bad,name'), 2048, 1073741824)

    def test_observed_track_rounding_reproduces_old_false_positive(self):
        g = inspect.fat_geometry(boot_sector(), 1073741824, 2048)
        self.assertFalse(g["old_equality_result"])
        self.assertEqual(g["fat32_bytes"], 1073737728)
        self.assertEqual(g["difference_sectors"], 8)
        self.assertEqual(g["difference_bytes"], 4096)
        self.assertEqual(g["size_explanation"], "dosfstools-4.2-track-rounding")

    def test_exact_size_also_valid(self):
        self.assertTrue(inspect.fat_geometry(boot_sector(total=2097152), 1073741824, 2048)["old_equality_result"])

    def test_arbitrary_truncation_even_one_sector_is_rejected(self):
        for total in (0, 2097143, 2097145, 2097151, 2097153, 2000000):
            with self.subTest(total=total), self.assertRaisesRegex(ValueError, "unexplained"):
                inspect.fat_geometry(boot_sector(total=total), 1073741824, 2048)

    def test_track_rounding_must_match_declared_geometry(self):
        with self.assertRaisesRegex(ValueError, "unexplained"):
            inspect.fat_geometry(boot_sector(track=32), 1073741824, 2048)

    def test_bad_bpb_fields_are_not_hidden_by_size_exception(self):
        mutations = ((11, "<H", 4096), (24, "<H", 0), (28, "<I", 0),
                     (19, "<H", 123), (36, "<I", 1), (40, "<H", 0x80),
                     (44, "<I", 0), (48, "<H", 32), (50, "<H", 0), (510, "<H", 0))
        for offset, fmt, value in mutations:
            boot = boot_sector()
            struct.pack_into(fmt, boot, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                inspect.fat_geometry(boot, 1073741824, 2048)


class FatStructures(unittest.TestCase):
    def fixture(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "synthetic-esp.raw"
        boot = boot_sector()
        geometry = inspect.fat_geometry(boot, 1073741824, 2048)
        fsinfo = bytearray(512)
        for offset, value in ((0, 0x41615252), (484, 0x61417272), (488, geometry["cluster_count"] - 1),
                              (492, 2), (508, 0xAA550000)):
            struct.pack_into("<I", fsinfo, offset, value)
        fat = struct.pack("<III", 0x0FFFFFF8, 0x0FFFFFFF, 0x0FFFFFF8)
        with path.open("wb") as stream:
            stream.truncate(1073741824)
            for sector, data in ((0, boot), (6, boot), (1, fsinfo), (7, fsinfo), (32, fat), (2080, fat)):
                stream.seek(sector * 512)
                stream.write(data)
        return path, geometry

    def test_intact_mirrors_and_unused_tail(self):
        path, geometry = self.fixture()
        self.assertTrue(inspect.inspect_fat(path, geometry)["unused_tail_zero"])

    def test_backup_fat_fsinfo_and_tail_corruption_rejected(self):
        for offset, message in ((6 * 512, "backup boot"), (2080 * 512 + 12, "FAT copies"),
                                (7 * 512, "backup FSInfo"), (2097144 * 512, "tail")):
            with self.subTest(offset=offset):
                path, geometry = self.fixture()
                with path.open("r+b") as stream:
                    stream.seek(offset)
                    stream.write(b"X")
                with self.assertRaisesRegex(ValueError, message):
                    inspect.inspect_fat(path, geometry)


class GptHeader(unittest.TestCase):
    def test_header_crc_corruption_rejected(self):
        header = bytearray(512)
        header[:8] = b"EFI PART"
        struct.pack_into("<II", header, 8, 0x10000, 92)
        struct.pack_into("<QQQQ", header, 24, 1, 134217727, 34, 134217694)
        struct.pack_into("<QIII", header, 72, 2, 128, 128, 0)
        struct.pack_into("<I", header, 16, zlib.crc32(header[:92]))
        self.assertEqual(inspect.gpt_header(header, 1, 134217727, 134217728)["last_usable"], 134217694)
        header[56] ^= 1
        with self.assertRaisesRegex(ValueError, "CRC"):
            inspect.gpt_header(header, 1, 134217727, 134217728)


if __name__ == "__main__":
    unittest.main()
