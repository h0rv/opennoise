"""Saved native recordings retrieve other artists without source labels or feature fitting."""

# ruff: noqa: PLR2004 -- explicit fixture IDs and independently fixed top-six policy.

import copy
import json
import math
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

from opennoise.common import sha256_file
from opennoise.ml.fma_acoustic_baseline import _json_rows
from opennoise.ml.fma_recording_artists import query_recordings, validate_requests
from scripts.materialize_fma_membership_example import RECIPE, materialize
from tests.test_fma_artist_neighbors import artist

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/examples/fma-acoustic-baseline"
PROTOCOL = ROOT / "data/recipes/fma44-recording-artists-20261018/protocol.json"
PROTOCOL_SHA = "7ee032991f48dd8f3fb219fcb00eb734a0e72e47838c26bfc818b38b4d0f6e20"


def verify_queries(
    report: dict[str, Any], rankings: dict[int, Any], identities: dict[int, Any]
) -> int:
    """Independently verify every query/candidate score using dictionary intersections."""
    edges = 0
    for query in report["recording_artist_queries"]:
        identity = identities.get(query["track_id"])
        saved = rankings.get(query["track_id"])
        if query["reason"] is not None:
            assert not query["neighbors"]
            if saved and saved["reason"]:
                assert query["reason"] == query["saved_abstention"] == saved["reason"]
            continue
        assert identity is not None
        assert saved is not None
        assert query["artist_id"] == identity["artist_id"]
        assert query["component_id"] == identity["component_id"]
        vector = {genre: 1 / rank for rank, genre in enumerate(saved["ranked_genre_ids"][:10], 1)}
        assert query["query_rank_profile"] == [
            {"genre_id": genre, "reciprocal_rank": score} for genre, score in vector.items()
        ]
        norm = math.sqrt(math.fsum(v * v for v in vector.values()))
        candidates = []
        for row in report["partitions"][query["partition"]]["artists"]:
            other = {
                g["genre_id"]: g["mean_reciprocal_track_rank"]
                for g in row["ranked_source_annotation_candidates"]
            }
            shared = sorted(vector.keys() & other.keys())
            if not shared or row["component_id"] == identity["component_id"]:
                continue
            similarity = math.fsum(vector[g] * other[g] for g in shared) / (
                norm * math.sqrt(math.fsum(v * v for v in other.values()))
            )
            candidates.append((-similarity, row["artist_id"], row, shared))
        expected = []
        seen = set()
        for score, native_id, candidate, shared in sorted(candidates):
            if candidate["component_id"] not in seen:
                seen.add(candidate["component_id"])
                expected.append((native_id, score, candidate, shared))
            if len(expected) == 6:
                break
        assert [e["artist_id"] for e in query["neighbors"]] == [e[0] for e in expected]
        for edge, (_, score, candidate, shared) in zip(query["neighbors"], expected, strict=True):
            assert math.isclose(edge["cosine_distance"], max(0, 1 + score), abs_tol=1e-12)
            assert edge["shared_profile_genre_ids"] == shared
            assert edge["component_id"] == candidate["component_id"]
            assert edge["nominated_track_count"] == len(candidate["track_ids"])
            assert (
                edge["ranking_supported_track_count"] == candidate["ranking_supported_track_count"]
            )
        edges += len(expected)
    return edges


class RecordingArtistTests(unittest.TestCase):
    def test_recording_profiles_identity_ties_and_full_query_norm(self) -> None:
        rows = [
            artist(1, 10, {100: 1}),
            artist(2, 20, {100: 1}),
            artist(3, 20, {100: 1}),
            artist(4, 40, {200: 1}),
        ]
        rows[0]["track_ids"] = [11, 12]
        partitions = {"confirmation": {"artists": rows}}
        identities = {
            track: {"artist_id": 1, "component_id": 10, "artist_known": True, "fold": 1}
            for track in (11, 12)
        }
        ranks = {
            11: {"reason": None, "ranked_genre_ids": [100, 999]},
            12: {"reason": None, "ranked_genre_ids": [200, 999]},
        }
        before = copy.deepcopy(partitions)
        result = query_recordings([12, 11, 12], ranks, identities, partitions)
        self.assertEqual([r["track_id"] for r in result], [12, 11, 12])
        self.assertEqual([r["neighbors"][0]["artist_id"] for r in result], [4, 2, 4])
        self.assertEqual(len(result[1]["neighbors"]), 1)
        self.assertAlmostEqual(
            result[1]["neighbors"][0]["cosine_distance"], 1 - 1 / math.sqrt(1.25)
        )
        self.assertEqual(partitions, before)
        ranks[11]["observed_genre_ids"] = [99999]
        self.assertEqual(result, query_recordings([12, 11, 12], ranks, identities, partitions))

    def test_abstentions_and_request_bounds(self) -> None:
        rows = [artist(1, 1, {99: 1})]
        rows[0]["track_ids"] = [1, 2, 3, 4, 5]
        identities = {
            i: {"artist_id": 1, "artist_known": i != 3, "component_id": 1, "fold": 1}
            for i in range(1, 6)
        }
        ranks = {
            2: {"reason": "missing_descriptors", "ranked_genre_ids": []},
            3: {"reason": None, "ranked_genre_ids": [99]},
            4: {"reason": None, "ranked_genre_ids": []},
            5: {"reason": None, "ranked_genre_ids": [88]},
        }
        result = query_recordings(
            [999, 1, 2, 3, 4, 5], ranks, identities, {"calibration": {"artists": rows}}
        )
        self.assertEqual(
            [r["reason"] for r in result],
            [
                "unknown_native_track_id",
                "no_saved_prediction",
                "missing_descriptors",
                "unresolved_artist",
                "empty_rank_profile",
                "no_eligible_overlap",
            ],
        )
        self.assertTrue(all(not row["neighbors"] for row in result))
        for request in ([], [1] * 101, [0], [True], [2**32]):
            with self.assertRaises(ValueError):
                validate_requests(cast("list[int]", request))
        validate_requests([1] * 100)

    def test_retained_cli_replay_and_unchanged_existing_partitions(self) -> None:
        self.assertEqual(sha256_file(PROTOCOL)[0], PROTOCOL_SHA)
        requests = [r["track_id"] for r in json.loads(PROTOCOL.read_bytes())["requests"]]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            materialize(RECIPE, root / "members")
            command = [
                str(ROOT / ".venv/bin/python"),
                str(ROOT / "scripts/replay_fma_memberships.py"),
                "--saved-pack",
                str(SOURCE),
                "--memberships",
                str(root / "members"),
                "--rank-artists",
                "--artist-neighbors",
                "--export-artists",
                str(root / "plain.json"),
                "--saved-pack-receipt-sha256",
                sha256_file(SOURCE / "pack-receipt.json")[0],
                "--membership-receipt-sha256",
                sha256_file(root / "members/pack-receipt.json")[0],
            ]
            subprocess.run(command, check=True, capture_output=True, timeout=120)  # noqa: S603
            command[command.index(str(root / "plain.json"))] = str(root / "queries.json")
            command += [arg for track in requests for arg in ("--query-track-id", str(track))]
            subprocess.run(command, check=True, capture_output=True, timeout=120)  # noqa: S603
            report = json.loads((root / "queries.json").read_bytes())
            plain = json.loads((root / "plain.json").read_bytes())
            self.assertEqual(report["partitions"], plain["partitions"])
            self.assertEqual([r["track_id"] for r in report["recording_artist_queries"]], requests)
            identities = {r["track_id"]: r for r in _json_rows(SOURCE / "native-folds.jsonl.zst")}
            ranks = {
                r["track_id"]: r
                for name in ("validation", "test")
                for r in _json_rows(SOURCE / f"{name}-acoustic-ranks.jsonl.zst")
            }
            self.assertGreater(verify_queries(report, ranks, identities), 0)
            self.assertLess((root / "queries.json").stat().st_size, 24_000_000)
            self.assertFalse(report["recording_query_policy"]["target_labels_consumed"])
            command.remove("--rank-artists")
            rejected = subprocess.run(command, check=False, capture_output=True, timeout=120)  # noqa: S603
            self.assertNotEqual(rejected.returncode, 0)
