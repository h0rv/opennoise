import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from musix.historical_custody import HistoricalCustodyError, custody_historical_inputs
from musix.models.historical_signal import HistoricalSignalSettings
from musix.storage import LocalObjectStore


class HistoricalCustodyTests(unittest.TestCase):
    def _inputs(self, root: Path) -> tuple[Path, Path, str]:
        raw = root / "h3.json"
        payload = [
            {"genre": "pop", "artists": [{"artist_id": "artist-a"}, {"artist_id": "artist-b"}]},
            {"genre": "rock", "artists": [{"artist_id": "artist-a"}]},
        ]
        raw.write_text(json.dumps(payload), encoding="utf-8")
        source_sha = hashlib.sha256(raw.read_bytes()).hexdigest()
        database = root / "memberships.sqlite"
        with sqlite3.connect(database) as connection:
            connection.execute(
                """CREATE TABLE historical_genre_artist_observations (
                   genre_id INTEGER, source_artist_id TEXT, source_artifact_sha256 TEXT,
                   observation_role TEXT NOT NULL)"""
            )
            connection.executemany(
                """INSERT INTO historical_genre_artist_observations
                   (genre_id, source_artist_id, source_artifact_sha256, observation_role)
                   VALUES (?, ?, ?, 'genre_page_member')""",
                (
                    (1, "artist-a", source_sha),
                    (1, "artist-b", source_sha),
                    (2, "artist-a", source_sha),
                ),
            )
        return raw, database, source_sha

    def test_seals_both_inputs_under_content_addressed_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw, database, source_sha = self._inputs(root)
            receipt = custody_historical_inputs(
                LocalObjectStore(root / "vault"),
                raw,
                database,
                receipt_path=root / "receipt.json",
                expected_h3_source_sha256=source_sha,
                expected_h3_source_byte_size=raw.stat().st_size,
                h3_source_manifest_sha256="a" * 64,
                h2_manifest_sha256="b" * 64,
                expected_source_genre_rows=2,
                expected_source_memberships=3,
                expected_stored_memberships=3,
                expected_stored_genres=2,
                expected_stored_artists=2,
                local_display_policy_key=f"historical-membership:local-display:{source_sha}",
                model_settings=HistoricalSignalSettings(),
                rebuild_command=("python", "scripts/build_historical_signal_model.py"),
                code_revision="test-revision",
            )

            self.assertTrue(receipt.raw_h3.key.value.endswith(f"/{source_sha}.json"))
            self.assertTrue(receipt.membership_sqlite.key.value.endswith(".sqlite"))
            self.assertEqual(receipt.counts.stored_artists, 2)
            self.assertEqual(
                json.loads((root / "receipt.json").read_text())["code_revision"], "test-revision"
            )

    def test_count_mismatch_fails_before_publishing_or_receipt_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw, database, source_sha = self._inputs(root)
            receipt_path = root / "receipt.json"
            receipt_path.write_text("old", encoding="utf-8")
            with self.assertRaises(HistoricalCustodyError):
                custody_historical_inputs(
                    LocalObjectStore(root / "vault"),
                    raw,
                    database,
                    receipt_path=receipt_path,
                    expected_h3_source_sha256=source_sha,
                    expected_h3_source_byte_size=raw.stat().st_size,
                    h3_source_manifest_sha256="a" * 64,
                    h2_manifest_sha256="b" * 64,
                    expected_source_genre_rows=2,
                    expected_source_memberships=3,
                    expected_stored_memberships=4,
                    expected_stored_genres=2,
                    expected_stored_artists=2,
                    local_display_policy_key="historical-membership:local-display:test",
                    model_settings=HistoricalSignalSettings(),
                    rebuild_command=("python", "rebuild.py"),
                    code_revision="test-revision",
                )
            self.assertEqual(receipt_path.read_text(encoding="utf-8"), "old")
            self.assertEqual(tuple((root / "vault").rglob("*")), ())


if __name__ == "__main__":
    unittest.main()
