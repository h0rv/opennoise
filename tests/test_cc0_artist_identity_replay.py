"""Real retained CC0 projections/raw-source replay through the production identity paths."""

import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from opennoise.pipeline.artist_identity_replay import CORE_SHA, CULTURAL_SHA, digest, replay

ROOT = Path(__file__).resolve().parents[1]
CORE = (
    ROOT
    / "data/release/musicbrainz-credit-catalog-v1/objects/musicbrainz-credit-catalog/sha256"
    / f"{CORE_SHA}.json"
)
CULTURAL = ROOT / "data/examples/independent-cultural-context"
RAW_SHA = "df1cf4e12a947ff18df1a7bcfb1cfda68e8c30b17e197275f07d4b336f772f19"


class RealExactArtistReplayTests(unittest.TestCase):
    """These permissive source artifacts are checked in, unlike research-only caches."""

    def test_complete_native_core_both_orders_with_independent_claim_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "joined"
            result = replay(CORE, CORE_SHA, CULTURAL, CULTURAL_SHA, output)
            self.assertEqual(result["source"]["native_artists"], 352)
            self.assertEqual(result["source"]["exact_overlap"], 7)
            self.assertEqual(result["source"]["unjoined_matched_cultural_artists"], 35)
            for name, order in result["orders"].items():
                self.assertEqual(
                    order["counts"],
                    {
                        "artists": 352,
                        "release_groups": 87,
                        "recordings": 1031,
                        "artist_genre_evidence": 40,
                    },
                )
                self.assertEqual(order["credited_entities_joined"], 87)
                self.assertEqual(len(order["source_shared_genre_neighbor_counts"]), 352)
                self.assertEqual(sum(order["source_shared_genre_neighbor_counts"].values()), 4)
                with sqlite3.connect(output / (name + ".sqlite")) as connection:
                    self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
                    provenance = connection.execute(
                        """SELECT DISTINCT p.artifact_sha256,r.policy_key,s.source_key
                           FROM artist_genre_evidence e
                           JOIN provenance_records p ON p.id=e.provenance_id
                           JOIN rights_policies r ON r.id=e.policy_id
                           JOIN data_sources s ON s.id=p.source_id"""
                    ).fetchall()
                    self.assertEqual(
                        provenance,
                        [
                            (
                                RAW_SHA,
                                "wikidata-cultural-exact-artist",
                                "wikidata_cultural_exact_artist",
                            )
                        ],
                    )
                    self.assertEqual(
                        connection.execute(
                            "SELECT count(*) FROM displayable_artist_genre_evidence"
                        ).fetchone()[0],
                        40,
                    )
                    stored = [
                        json.loads(r[0])
                        for r in connection.execute(
                            "SELECT normalized_value_json FROM entity_claims "
                            "WHERE claim_key='genre'"
                        )
                    ]
                    self.assertTrue(
                        all(
                            c["rank"] is None
                            and c["statement_id"] is None
                            and c["references"] == []
                            for c in stored
                        )
                    )
                    self.assertEqual(
                        connection.execute(
                            "SELECT count(DISTINCT artist_id) FROM artist_genre_evidence"
                        ).fetchone()[0],
                        7,
                    )
            self.assertEqual(digest(CORE), CORE_SHA)
            self.assertEqual(digest(CULTURAL / "receipt.json"), CULTURAL_SHA)

    def test_wrong_external_pin_or_changed_raw_source_leaves_no_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "result"
            with self.assertRaises(ValueError):
                replay(CORE, "0" * 64, CULTURAL, CULTURAL_SHA, output)
            self.assertFalse(output.exists())
            copied = root / "culture"
            shutil.copytree(CULTURAL, copied)
            raw = copied / "raw/batch-00.json"
            raw.write_bytes(raw.read_bytes() + b" ")
            with self.assertRaises(ValueError):
                replay(CORE, CORE_SHA, copied, CULTURAL_SHA, output)
            self.assertFalse(output.exists())

    def test_existing_destination_is_never_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "exists"
            output.mkdir()
            sentinel = output / "keep"
            sentinel.write_text("keep")
            with self.assertRaises(FileExistsError):
                replay(CORE, CORE_SHA, CULTURAL, CULTURAL_SHA, output)
            self.assertEqual(sentinel.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
