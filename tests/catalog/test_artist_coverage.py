"""The electronic-artist coverage audit joins native identities by UUID."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from opennoise.catalog.artist_coverage import ARTIST_COVERAGE_COHORT, audit_artist_coverage


class ArtistCoverageTests(unittest.TestCase):
    def test_portable_feature_and_inferred_assignment_join_without_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            identity = ARTIST_COVERAGE_COHORT[0][1]
            other_id = "84b4c071-714d-4169-94e5-c26b0fefc3d2"
            features = directory / "features.jsonl"
            names = directory / "names.jsonl"
            assignments = directory / "assignments.jsonl"
            communities = directory / "communities.json"
            features.write_text(
                "".join(
                    json.dumps(row) + "\n"
                    for row in (
                        {
                            "artist_mbid": identity,
                            "features": [
                                {
                                    "namespace": "artist_tag",
                                    "value": "acid techno",
                                    "weight": 1.4,
                                    "evidence_refs": ["page-id|response-hash"],
                                }
                            ],
                        },
                        {
                            "artist_mbid": other_id,
                            "features": [{"namespace": "artist_tag", "value": "wrong artist"}],
                        },
                    )
                ),
                encoding="utf-8",
            )
            names.write_text(
                json.dumps({"artist_mbid": identity, "name": "Aphex Twin"}) + "\n",
                encoding="utf-8",
            )
            assignments.write_text(
                json.dumps(
                    {
                        "artist_mbid": identity,
                        "memberships": [
                            {
                                "community_id": "community-a",
                                "level": "micro",
                                "score": 0.8,
                                "role": "inferred_community_membership",
                            }
                        ],
                        "state": "assigned",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            communities.write_text(
                json.dumps(
                    {
                        "communities": [
                            {
                                "id": "community-a",
                                "label": "acid techno",
                                "level": "micro",
                                "descriptors": [
                                    {"namespace": "artist_tag", "value": "acid techno"}
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            rows = audit_artist_coverage(
                feature_jsonl=features,
                name_jsonl=names,
                assignments_jsonl=assignments,
                communities_json=communities,
            )
            aphex = rows[0]
            self.assertEqual(aphex.artist_mbid, identity)
            self.assertEqual(aphex.display_name, "Aphex Twin")
            assert aphex.features is not None
            assert aphex.assignments is not None
            self.assertEqual(aphex.features[0]["value"], "acid techno")
            self.assertEqual(aphex.assignments[0]["community"]["label"], "acid techno")
            self.assertIsNone(aphex.direct_claim_count)
            self.assertEqual(rows[1].features, None)

    def test_native_uuid_selects_one_of_same_named_artists_and_features(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            catalog_path = directory / "catalog.sqlite"
            feature_path = directory / "features.sqlite"
            first_id = ARTIST_COVERAGE_COHORT[4][1]
            unrelated_id = "836e8de5-cc76-47c1-997a-8b82b525d619"
            with sqlite3.connect(catalog_path) as catalog:
                catalog.executescript(
                    "CREATE TABLE artist (artist_mbid TEXT, canonical_name TEXT, name_status TEXT);"
                    "CREATE TABLE direct_claim (artist_mbid TEXT, musicbrainz_genre_id TEXT);"
                    "CREATE TABLE seed_artist (artist_mbid TEXT, seed_id TEXT);"
                )
                catalog.executemany(
                    "INSERT INTO artist VALUES (?, 'Burial', 'exact')",
                    [(first_id,), (unrelated_id,)],
                )
                catalog.executemany(
                    "INSERT INTO direct_claim VALUES (?, ?)",
                    [(first_id, "genre-dubstep"), (unrelated_id, "genre-metal")],
                )
                catalog.executemany(
                    "INSERT INTO seed_artist VALUES (?, ?)",
                    [(first_id, "seed-dubstep"), (unrelated_id, "seed-metal")],
                )
            with sqlite3.connect(feature_path) as features:
                features.execute(
                    "CREATE TABLE artist_tag_features "
                    "(artist_id TEXT, tag_identity TEXT, tag_count INTEGER)"
                )
                features.executemany(
                    "INSERT INTO artist_tag_features VALUES (?, ?, 1)",
                    [(first_id, "idm"), (first_id, "glitch"), (unrelated_id, "death metal")],
                )

            rows = audit_artist_coverage(catalog_path, feature_database=feature_path)
            burial = rows[4]
            self.assertEqual(burial.artist_mbid, first_id)
            self.assertEqual(burial.catalog_name, "Burial")
            self.assertEqual(burial.direct_claim_count, 1)
            self.assertEqual(burial.direct_seed_count, 1)
            self.assertEqual(burial.direct_genre_ids, ("genre-dubstep",))
            self.assertEqual(burial.open_tag_feature_count, 2)
            self.assertEqual(rows[0].catalog_name, None)
