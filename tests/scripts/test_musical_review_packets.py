"""Check frozen review populations, source missingness and listener blinding."""

from __future__ import annotations

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from typing import Any, override
from unittest.mock import patch

import zstandard

from scripts import build_fma_musical_review_cohort as fma


class MusicalReviewPacketTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.paths = {
            name: self.root / (name + ".jsonl.zst")
            for name in ("tracks", "artists", "folds", "genres", "confirmation", "calibration")
        }
        tracks = []
        for track_id in range(12):
            track = {
                "track_id": track_id,
                "artist_id": track_id // 3,
                "artist_id_status": "source_known",
                "title": f"Track {track_id}",
                "genre_ids": [1, 2] if track_id % 2 else [],
                "album_id": 1,
                "album_title": "Album",
                "source_metadata_url": "https://example.com/track",
                "audio_license_title": "CC BY",
                "audio_license_url": "https://example.com/license",
            }
            if track_id % 3 == 0:
                del track["album_title"]
            tracks.append(track)
        self._write("tracks", tracks)
        self._write("artists", [{"artist_id": i, "name": f"Artist {i}"} for i in range(4)])
        self._write(
            "folds",
            [{"track_id": i, "component_id": i // 2, "fold": 1} for i in range(12)],
        )
        self._write(
            "genres",
            [
                {"genre_id": 1, "title": "Parent", "parent_id": None},
                {"genre_id": 2, "title": "Child", "parent_id": 1},
            ],
        )
        self._write(
            "confirmation",
            [{"track_id": i, "memberships": [{"genre_id": 2}]} for i in (0, 1, 8, 9, 10)],
        )
        self._write(
            "calibration",
            [{"track_id": i, "memberships": [{"genre_id": 1}]} for i in (2, 3, 11)],
        )
        methods = (
            "standardized_euclidean",
            "training_annotation_frequency",
            "fixed_hash_order",
        )
        self.queries = self.root / "queries.json"
        self.queries.write_text(
            json.dumps(
                [
                    {
                        "track_id": i,
                        "component_id": i // 2,
                        "arms": {
                            method: {
                                "track_ids": [5 + i, 6 + i],
                                "observed_positives": [1],
                                "recovered_positives": [1],
                                "musical_precision_available": False,
                            }
                            for method in methods
                        },
                    }
                    for i in range(4)
                ]
            ),
            encoding="utf-8",
        )
        # Enter patches now; stop them when the fixture is released.
        source_constants: dict[str, Any] = {
            name.upper() + "_SHA256": fma.digest(self.paths[name])
            for name in ("tracks", "artists", "folds", "genres")
        }
        self.patches = patch.multiple(fma, FULL_TRACK_COUNT=12, QUERY_COUNT=4, **source_constants)
        self.patches.start()
        self.addCleanup(self.patches.stop)

    def _write(self, name: str, rows: list[dict[str, Any]]) -> None:
        with zstandard.open(self.paths[name], "wt", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row) + "\n")

    def _sources(self, name: str, track_ids: Path | None = None) -> fma.ReviewSources:
        return fma.ReviewSources(
            tracks=self.paths["tracks"],
            artists=self.paths["artists"],
            folds=self.paths["folds"],
            genres=self.paths["genres"],
            sonic_queries=self.queries,
            membership_results=self.paths["confirmation"],
            calibration_results=self.paths["calibration"],
            track_ids=track_ids,
            output=self.root / name / "fma",
            size=6,
        )

    def test_confirmation_join_withholds_calibration_and_blinds_public_packets(self) -> None:
        result = fma.build(self._sources("packet"))
        packet = self.root / "packet"
        membership = json.loads(
            (packet / "fma-validation-membership-review/items.json").read_text()
        )["items"]
        self.assertEqual({item["query_track"]["native_track_id"] for item in membership}, {0, 1})
        key = json.loads(
            (
                packet
                / "fma-validation-membership-review-coordinator/membership-output-source-key.json"
            ).read_text()
        )["items"]
        withheld = [
            item
            for item in key
            if item["model_output_status"] == "calibration_partition_prediction_withheld"
        ]
        self.assertEqual({item["track_id"] for item in withheld}, {2, 3})
        self.assertTrue(all(item["model_output"] is None for item in withheld))
        self.assertEqual(
            result["validation_query_review"]["membership_review"]["confirmation_results"], 5
        )
        queries = json.loads((packet / "fma-validation-query-review/queries.json").read_text())
        self.assertEqual(len(queries["queries"]), 4)
        for item in queries["queries"]:
            for slot in ("A", "B", "C"):
                # Only each arm's top-ranked track is displayed; rank two is hidden.
                self.assertEqual(
                    item["candidate_" + slot]["native_track_id"],
                    item["query"]["native_track_id"] + 5,
                )
                self.assertNotIn("genre_ids", item["candidate_" + slot])
            self.assertNotIn("slot_to_method", item)
        for directory in ("fma", "fma-validation-query-review", "fma-validation-membership-review"):
            manifest = json.loads((packet / directory / "manifest.json").read_text())
            self.assertFalse(any("coordinator" in name for name in manifest["sha256"]))
            assignments = next((packet / directory).glob("*assignments.json"))
            rows = json.loads(assignments.read_text())
            self.assertTrue(
                all(row["reviewer_id"] == "" and row["status"] == "unassigned" for row in rows)
            )

    def test_repeated_builds_are_identical_for_sampled_and_frozen_id_inputs(self) -> None:
        frozen = self.root / "ids.txt"
        frozen.write_text("0\n2\n4\n5\n6\n8\n", encoding="utf-8")
        for suffix, ids in (("sample", None), ("ids", frozen)):
            with self.subTest(mode=suffix):
                first = fma.build(self._sources("first-" + suffix, ids))
                second = fma.build(self._sources("second-" + suffix, ids))
                self.assertEqual(first, second)
                left = self.root / ("first-" + suffix)
                right = self.root / ("second-" + suffix)
                first_files = {
                    path.relative_to(left): path.read_bytes()
                    for path in left.rglob("*")
                    if path.is_file()
                }
                second_files = {
                    path.relative_to(right): path.read_bytes()
                    for path in right.rglob("*")
                    if path.is_file()
                }
                self.assertEqual(first_files, second_files)

    def test_explicit_empty_frozen_query_source_is_rejected(self) -> None:
        self.queries.write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "240 validation queries"):
            fma.build(self._sources("empty"))

    def test_actual_missing_fields_and_minimum_positive_frequency_define_strata(self) -> None:
        strata = fma.SamplingStrata(Counter({7: 10}), Counter({1: 100, 2: 1}), (3, 8), (5, 50))
        track = {
            "title": "Track",
            "album_id": 1,
            "album_title": "Album",
            "source_metadata_url": "https://example.com/track",
            "audio_license_title": "CC BY",
            "audio_license_url": "https://example.com/license",
            "artist_id": 7,
            "artist_id_status": "source_known",
            "genre_ids": [1, 2],
        }
        self.assertEqual(strata(track), ("rare", "high", "metadata_complete"))
        del track["album_title"]
        self.assertEqual(fma.missing_feature_fields(track), ["album_title"])
        self.assertEqual(strata(track), ("rare", "high", "metadata_missing"))
        track["genre_ids"] = []
        self.assertEqual(strata(track)[0], "unlabelled")
