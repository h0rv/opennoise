"""Tests for hash-locked catalog snapshot restoration."""

from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from musix.catalog_snapshot import CatalogSnapshotRestoreError, restore_catalog_snapshot


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CatalogSnapshotRestoreTests(unittest.TestCase):
    """Keep pre-hydration restoration atomic and lineage-bound."""

    def _catalog(self, path: Path) -> None:
        with sqlite3.connect(path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
            connection.execute(
                "CREATE TABLE child (id INTEGER PRIMARY KEY, "
                "parent_id INTEGER REFERENCES parent(id))"
            )
            connection.execute("INSERT INTO parent VALUES (1)")
            connection.execute("INSERT INTO child VALUES (1, 1)")

    def test_restores_a_hash_locked_catalog_and_binds_both_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "sealed.sqlite"
            destination = root / "restored.sqlite"
            self._catalog(source)

            receipt = restore_catalog_snapshot(
                source, destination, expected_taxonomy_catalog_sha256=_sha256(source)
            )

            self.assertEqual(receipt.source_path, source.resolve())
            self.assertEqual(receipt.destination_path, destination.resolve())
            self.assertEqual(receipt.source_sha256, receipt.destination_sha256)
            self.assertEqual(receipt.byte_size, destination.stat().st_size)
            self.assertEqual(receipt.integrity_check, ("ok",))
            self.assertEqual(receipt.foreign_key_violation_count, 0)

    def test_wrong_hash_fails_before_touching_the_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "sealed.sqlite"
            destination = root / "existing.sqlite"
            self._catalog(source)
            destination.write_bytes(b"preserve existing destination")

            with self.assertRaisesRegex(CatalogSnapshotRestoreError, "source hash"):
                restore_catalog_snapshot(
                    source, destination, expected_taxonomy_catalog_sha256="0" * 64
                )

            self.assertEqual(destination.read_bytes(), b"preserve existing destination")

    def test_tampered_source_fails_before_replacing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "sealed.sqlite"
            destination = root / "existing.sqlite"
            self._catalog(source)
            expected = _sha256(source)
            source.write_bytes(source.read_bytes() + b"tampered")
            destination.write_bytes(b"preserve existing destination")

            with self.assertRaisesRegex(CatalogSnapshotRestoreError, "source hash"):
                restore_catalog_snapshot(
                    source, destination, expected_taxonomy_catalog_sha256=expected
                )

            self.assertEqual(destination.read_bytes(), b"preserve existing destination")


if __name__ == "__main__":
    unittest.main()
