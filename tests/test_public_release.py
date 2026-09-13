"""Tests for sealed-cache publication storage boundaries."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from opennoise.pipeline.public_release import _snapshot_cache


class PublicReleaseStorageTests(unittest.TestCase):
    def test_snapshot_never_shares_writable_storage_with_sealed_cache(self) -> None:
        """A reflink or fallback copy must leave the source unchanged after writes."""
        source_payload = b"sealed schema 10 cache\x00"
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "qualified.sqlite"
            destination = directory / "serving.sqlite"
            source.write_bytes(source_payload)
            destination.touch()

            _snapshot_cache(source, destination)
            self.assertEqual(destination.read_bytes(), source_payload)
            destination.write_bytes(b"serving schema 11 cache\x00")
            self.assertEqual(source.read_bytes(), source_payload)


if __name__ == "__main__":
    unittest.main()
