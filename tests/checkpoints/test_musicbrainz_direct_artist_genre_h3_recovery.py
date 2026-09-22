"""Identity and duplicate boundaries for the exact H3 pair evaluator."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opennoise.checkpoints.musicbrainz_direct_artist_genre_h3_recovery import (
    DirectArtistGenreH3RecoveryError,
    _h3_pairs,
    evaluate_direct_artist_genre_h3_positive_recovery,
)
from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreCustodyError,
    DirectProperGenreCustodyReceipt,
    receipt_sha256,
)

_RAW = "a" * 64
_MBID = "123e4567-e89b-12d3-a456-426614174000"


class ExactH3PairTests(unittest.TestCase):
    def test_mutated_custody_stops_before_historical_inputs_open(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            receipt_path = directory / "receipt.json"
            receipt = DirectProperGenreCustodyReceipt(
                source_seed_target_byte_sha256=_RAW,
                source_seed_target_output_sha256=_RAW,
                reconciliation_byte_sha256=_RAW,
                reconciliation_output_sha256=_RAW,
                claims_object_key=f"musicbrainz-direct-proper-genre-custody/sha256/{_RAW}.jsonl.zst",
                claims_object_sha256=_RAW,
                claims_object_byte_size=1,
                claims_uncompressed_sha256=_RAW,
                claim_count=0,
                seed_count=0,
                artist_mbid_count=0,
                source_record_sha256_count=0,
                output_sha256="0" * 64,
            )
            receipt = receipt.model_copy(update={"output_sha256": receipt_sha256(receipt)})
            receipt_path.write_text(receipt.model_dump_json(), encoding="utf-8")
            with self.assertRaises(DirectProperGenreCustodyError):
                evaluate_direct_artist_genre_h3_positive_recovery(
                    custody_receipt_path=receipt_path,
                    custody_object_store=directory / "missing-object-store",
                    reconciliation_path=directory / "must-not-open.json",
                    bridge_path=directory / "must-not-open-bridge.json",
                    bridge_receipt_path=directory / "must-not-open-bridge-receipt.json",
                    bridge_receipt_sha256=_RAW,
                    historical_rebuild_receipt_path=directory / "must-not-open-h3-receipt.json",
                    historical_rebuild_receipt_sha256=_RAW,
                    expected_h3_raw_sha256=_RAW,
                    expected_h3_database_sha256=_RAW,
                    historical_database_path=directory / "must-not-open-h3.sqlite",
                )

    def test_duplicate_h3_rows_deduplicate_and_wrong_artist_does_not_match(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            database = _database(Path(name), duplicate_identifier=False)
            with patch(
                "opennoise.checkpoints.musicbrainz_direct_artist_genre_h3_recovery._H3_CROSSWALK_SEED_COUNT",
                1,
            ):
                pairs = _h3_pairs(
                    database, source_sha256=_RAW, spotify_to_mbid={"spotify-1": _MBID}
                )
        self.assertEqual(pairs.raw_observation_count, 2)
        self.assertEqual(pairs.pairs, {("item1", _MBID)})
        self.assertNotIn(("item1", "123e4567-e89b-12d3-a456-426614174001"), pairs.pairs)

    def test_duplicate_source_identifier_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            database = _database(Path(name), duplicate_identifier=True)
            with (
                patch(
                    "opennoise.checkpoints.musicbrainz_direct_artist_genre_h3_recovery._H3_CROSSWALK_SEED_COUNT",
                    1,
                ),
                self.assertRaisesRegex(DirectArtistGenreH3RecoveryError, "crosswalk"),
            ):
                _h3_pairs(database, source_sha256=_RAW, spotify_to_mbid={"spotify-1": _MBID})


def _database(directory: Path, *, duplicate_identifier: bool) -> Path:
    path = directory / "h3.sqlite"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE genres (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE identifier_types (id INTEGER PRIMARY KEY, type_key TEXT NOT NULL);
            CREATE TABLE entity_identifiers (
                entity_id INTEGER NOT NULL, identifier_type_id INTEGER NOT NULL,
                namespace TEXT NOT NULL, normalized_value TEXT NOT NULL
            );
            CREATE TABLE historical_genre_artist_observations (
                genre_id INTEGER NOT NULL, source_artist_id TEXT,
                observation_role TEXT NOT NULL, source_artifact_sha256 TEXT NOT NULL
            );
            INSERT INTO genres VALUES (1, 'ignored');
            INSERT INTO identifier_types VALUES (1, 'source_id');
            INSERT INTO entity_identifiers VALUES (1, 1, 'enao-legacy', 'item1');
            """
        )
        insert_observation = (
            "INSERT INTO historical_genre_artist_observations VALUES (1, ?, 'genre_page_member', ?)"
        )
        connection.executemany(
            insert_observation,
            (("spotify-1", _RAW), ("spotify-1", _RAW)),
        )
        if duplicate_identifier:
            connection.execute(
                "INSERT INTO entity_identifiers VALUES (1, 1, 'enao-legacy', 'item2')"
            )
    return path
