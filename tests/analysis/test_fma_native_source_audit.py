"""Check independent FMA CSV integrity boundaries and native-ID interpretation."""

import bz2
import hashlib
import tempfile
import unittest
import zlib
from pathlib import Path

from scripts.audit_fma_native_source import native_genres, native_id, native_rows


class FMANativeSourceAuditTests(unittest.TestCase):
    def test_complete_csv_replay_checks_crc_and_sha_without_mutating_source(self) -> None:
        native = b'artist_id,artist_name\n1,"Artist\nwith newline"\n'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = b"prefix" + bz2.compress(native)
            path = root / "payload.range"
            path.write_bytes(payload)
            member: dict[str, object] = {
                "payload_path": path.name,
                "payload_prefix_bytes": 6,
                "uncompressed_bytes": len(native),
                "crc32": zlib.crc32(native),
            }
            self.assertEqual(
                list(native_rows(root, member)),
                [{"artist_id": "1", "artist_name": "Artist\nwith newline"}],
            )
            self.assertEqual(
                member["audited_uncompressed_sha256"], hashlib.sha256(native).hexdigest()
            )
            self.assertEqual(path.read_bytes(), payload)
            with self.assertRaisesRegex(ValueError, "CRC"):
                list(native_rows(root, {**member, "crc32": 0}))
            with self.assertRaisesRegex(ValueError, "length"):
                list(native_rows(root, {**member, "uncompressed_bytes": len(native) + 1}))

    def test_native_ids_do_not_bridge_names_or_accept_nonpositive_values(self) -> None:
        self.assertEqual(native_id("123"), 123)
        for invalid in ("artist name", "0", "-1", "1.0", "١٢٣"):
            self.assertIsNone(native_id(invalid))

    def test_native_genre_missingness_is_not_a_negative_label(self) -> None:
        self.assertIsNone(native_genres(""))
        self.assertIsNone(native_genres("not a list"))
        self.assertIsNone(native_genres("[{'genre_id': '0'}]"))
        self.assertEqual(native_genres("[]"), [])
        self.assertEqual(native_genres("[{'genre_id':'21'}, {'genre_id':'21'}]"), [21])


if __name__ == "__main__":
    unittest.main()
