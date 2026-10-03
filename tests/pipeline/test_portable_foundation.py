"""Real native-source offline replay and output tamper checks."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from opennoise.common import canonical_json, sha256_file
from opennoise.pipeline.portable_foundation import (
    _database_rows,
    _logical_database_hash,
    build_portable_foundation,
    inspect_legacy_inputs,
    validate_portable_foundation,
)

ROOT = Path(__file__).resolve().parents[2]
APHEX = "f22942a1-6f70-4f48-866e-238cb2308fbd"
FOUR_TET = "3bcff06f-675a-451f-9075-99e8657047e8"


class PortableFoundationTests(unittest.TestCase):
    def test_real_sources_replay_and_outputs_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first, second = Path(temporary) / "first", Path(temporary) / "second"
            receipt = build_portable_foundation(ROOT, first)
            self.assertEqual(receipt, build_portable_foundation(ROOT, second))
            self.assertEqual(receipt, validate_portable_foundation(ROOT, first))
            data = json.loads((first / "data.json").read_bytes())
            artists = {row["artist_mbid"]: row for row in data["artists"]}
            self.assertEqual(data["counts"]["artists"], 150)
            self.assertEqual(data["counts"]["recordings"], 36)
            self.assertFalse(data["scope"]["full_foundation_complete"])
            self.assertFalse(data["scope"]["historical_inputs_used"])
            self.assertTrue(any(not row["direct_genres"] for row in artists.values()))
            for identity in (APHEX, FOUR_TET):
                self.assertTrue(artists[identity]["direct_genres"])
                self.assertEqual(len(artists[identity]["recordings"]), 6)
                self.assertEqual(
                    artists[identity]["missingness"]["semantic_position"], "unavailable"
                )
            self.assertEqual(
                list(_database_rows(first / "catalog.sqlite")),
                list(_database_rows(second / "catalog.sqlite")),
            )
            for name in receipt["files_sha256"]:
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())
            with self.assertRaises(FileExistsError):
                build_portable_foundation(ROOT, first)

    def test_sql_membership_tamper_fails_even_if_receipt_rehashed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            receipt = build_portable_foundation(ROOT, output)
            database = output / "catalog.sqlite"
            with sqlite3.connect(database) as connection:
                connection.execute("DELETE FROM direct_genre WHERE artist_mbid=?", (APHEX,))
            receipt["files_sha256"]["catalog.sqlite"] = sha256_file(database)[0]
            # The attacker can rewrite hashes but cannot substitute factual joins.
            receipt["catalog_logical_sha256"] = _logical_database_hash(database)
            (output / "receipt.json").write_bytes(canonical_json(receipt))
            with self.assertRaisesRegex(ValueError, "catalog tables differ"):
                validate_portable_foundation(ROOT, output)

    def test_static_asset_and_scope_tamper_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            receipt = build_portable_foundation(ROOT, output)
            (output / "index.html").write_text("false complete release", encoding="utf-8")
            receipt["files_sha256"]["index.html"] = sha256_file(output / "index.html")[0]
            (output / "receipt.json").write_bytes(canonical_json(receipt))
            with self.assertRaisesRegex(ValueError, "static asset differs"):
                validate_portable_foundation(ROOT, output)

    def test_unavailable_legacy_inputs_stay_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report = inspect_legacy_inputs(Path(temporary))
            self.assertFalse(report["exact_reconstruction_available"])
            self.assertTrue(all(not row["exists"] for row in report["inputs"]))
            self.assertTrue(all(row["actual_sha256"] is None for row in report["inputs"]))


if __name__ == "__main__":
    unittest.main()
