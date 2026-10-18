"""Native artist joins and denominators from real historical saved FMA44 predictions."""

import json
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

from opennoise.common import sha256_file
from opennoise.ml.fma_acoustic_baseline import _json_rows
from opennoise.ml.fma_artist_evidence import aggregate_partition, export_artist_evidence
from scripts.materialize_fma_membership_example import RECIPE, materialize

SOURCE = Path(__file__).resolve().parents[1] / "data/examples/fma-acoustic-baseline"


class ArtistEvidenceTests(unittest.TestCase):
    def test_actual_artist_id_and_abstention_denominator_ignore_source_targets(self) -> None:
        identities = {
            i: {"artist_id": 7, "artist_known": True, "component_id": 999, "fold": 1}
            for i in (10, 11)
        }
        predictions = [
            {
                "track_id": 10,
                "component_id": 999,
                "abstention": None,
                "memberships": [{"genre_id": 3}],
                "observed_genre_ids": [12345],
            },
            {
                "track_id": 11,
                "component_id": 999,
                "abstention": "missing_descriptors",
                "memberships": [],
                "observed_genre_ids": [45678],
            },
        ]
        report = aggregate_partition(predictions, identities, "confirmation")
        artist = report["artists"][0]
        self.assertEqual(artist["artist_id"], 7)
        self.assertEqual(artist["component_id"], 999)
        self.assertEqual(artist["track_ids"], [10, 11])
        self.assertEqual(artist["abstention_counts"], {"missing_descriptors": 1})
        self.assertEqual(
            artist["genre_evidence"],
            [{"genre_id": 3, "contributing_track_ids": [10], "nominated_track_fraction": 0.5}],
        )
        self.assertEqual(
            report["genres"],
            [{"genre_id": 3, "artists": [{"artist_id": 7, "contributing_track_count": 1}]}],
        )
        identities[11]["artist_known"] = False
        report = aggregate_partition(predictions, identities, "confirmation")
        self.assertEqual(report["unresolved_artist_track_ids"], [11])

    def test_duplicate_missing_and_component_or_fold_conflict_fail(self) -> None:
        identity = {10: {"artist_id": 7, "artist_known": True, "component_id": 999, "fold": 1}}
        prediction = {"track_id": 10, "component_id": 999, "abstention": None, "memberships": []}
        for predictions, identities, partition in (
            ([prediction], identity, "unknown"),
            ([prediction, prediction], identity, "confirmation"),
            ([prediction], {}, "confirmation"),
            ([{**prediction, "component_id": 888}], identity, "confirmation"),
            ([prediction], identity, "test_diagnostic"),
        ):
            with self.assertRaises(ValueError):
                aggregate_partition(predictions, identities, partition)

    def test_real_saved_predictions_round_trip_with_independent_artist_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            members = root / "members"
            materialize(RECIPE, members)
            output = root / "artists.json"
            args = (
                SOURCE,
                sha256_file(SOURCE / "pack-receipt.json")[0],
                members,
                sha256_file(members / "pack-receipt.json")[0],
            )
            with patch(
                "opennoise.ml.fma_acoustic_baseline.fit_positive_gaussian",
                side_effect=AssertionError("no fit"),
            ):
                first = export_artist_evidence(*args, output)
                second = export_artist_evidence(*args, root / "replay.json")
            ranked_output = root / "ranked.json"
            export_artist_evidence(*args, ranked_output, rank_artists=True)
            ranked = json.loads(ranked_output.read_bytes())
            original = json.loads(output.read_bytes())
            for name, partition in ranked["partitions"].items():
                for row in partition["artists"]:
                    candidates = row.pop("ranked_source_annotation_candidates")
                    supported = row.pop("ranking_supported_track_count")
                    self.assertLessEqual(len(candidates), 10)
                    self.assertLessEqual(supported, len(row["track_ids"]))
                    if not supported:
                        self.assertEqual(candidates, [])
                self.assertEqual(partition, original["partitions"][name])
            self.assertFalse(ranked["scope"]["ranking"]["ranked_candidates_are_memberships"])
            self.assertEqual(first, second)
            report = json.loads(output.read_bytes())
            ledger = {r["track_id"]: r for r in _json_rows(SOURCE / "native-folds.jsonl.zst")}
            artists_seen = set()
            for name, partition in report["partitions"].items():
                tracks_by_artist = defaultdict(set)
                genres = defaultdict(lambda: defaultdict(set))
                for row in _json_rows(members / f"{name}-memberships.jsonl.zst"):
                    artist = ledger[row["track_id"]]["artist_id"]
                    tracks_by_artist[artist].add(row["track_id"])
                    for membership in row["memberships"]:
                        genres[artist][membership["genre_id"]].add(row["track_id"])
                self.assertFalse(artists_seen & set(tracks_by_artist))
                artists_seen.update(tracks_by_artist)
                for row in partition["artists"]:
                    artist = row["artist_id"]
                    self.assertEqual(set(row["track_ids"]), tracks_by_artist[artist])
                    self.assertEqual(
                        {
                            r["genre_id"]: set(r["contributing_track_ids"])
                            for r in row["genre_evidence"]
                        },
                        dict(genres[artist]),
                    )
            self.assertEqual(len(artists_seen), 1714)
            self.assertEqual(sum(p["track_count"] for p in report["partitions"].values()), 13800)
            self.assertFalse(report["scope"]["fma518_evaluation"])
            self.assertFalse(report["scope"]["artist_genre_facts"])
            with patch("opennoise.ml.fma_artist_evidence.replay_membership_pack") as replay:
                with self.assertRaisesRegex(ValueError, "external receipt"):
                    export_artist_evidence(SOURCE, "0" * 64, members, args[3], root / "bad.json")
                replay.assert_not_called()
            self.assertFalse((root / "bad.json").exists())
