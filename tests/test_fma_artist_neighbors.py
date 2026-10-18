"""Rank-profile retrieval preserves native components and historical partition roles."""

# ruff: noqa: PLR2004 -- independent fixed six-neighbor policy and synthetic fixture IDs.

import copy
import json
import math
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from opennoise.common import sha256_file
from opennoise.ml.fma_artist_neighbors import MAX_ARTISTS, attach_neighbors
from scripts.materialize_fma_membership_example import RECIPE, materialize

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/examples/fma-acoustic-baseline"


def artist(identity: int, component: int, weights: dict[int, float]) -> dict[str, Any]:
    """Build native IDs with explicit saved-rank support and no target annotation inputs."""
    return {
        "artist_id": identity,
        "component_id": component,
        "track_ids": [identity],
        "ranking_supported_track_count": int(bool(weights)),
        "ranked_source_annotation_candidates": [
            {"genre_id": genre, "mean_reciprocal_track_rank": score}
            for genre, score in weights.items()
        ],
    }


def independently_verify(partition: dict[str, Any]) -> int:
    """Replay every edge by dictionary intersection, independent of matrix arithmetic."""
    rows = partition["artists"]
    vectors = {
        row["artist_id"]: {
            genre["genre_id"]: genre["mean_reciprocal_track_rank"]
            for genre in row["ranked_source_annotation_candidates"]
        }
        for row in rows
    }
    edge_count = 0
    for query in rows:
        vector = vectors[query["artist_id"]]
        norm = math.sqrt(math.fsum(value * value for value in vector.values()))
        candidates = []
        for candidate in rows:
            other = vectors[candidate["artist_id"]]
            shared = sorted(vector.keys() & other.keys())
            if not shared or candidate["component_id"] == query["component_id"]:
                continue
            other_norm = math.sqrt(math.fsum(value * value for value in other.values()))
            distance = 1 - math.fsum(vector[g] * other[g] for g in shared) / (norm * other_norm)
            candidates.append((distance, candidate["artist_id"], candidate, shared))
        expected = []
        seen = set()
        for distance, identity, candidate, shared in sorted(candidates):
            if candidate["component_id"] not in seen:
                seen.add(candidate["component_id"])
                expected.append((identity, distance, candidate, shared))
            if len(expected) == 6:
                break
        actual = query["profile_neighbors"]["neighbors"]
        assert [edge["artist_id"] for edge in actual] == [entry[0] for entry in expected]
        for edge, (_, distance, candidate, shared) in zip(actual, expected, strict=True):
            assert math.isclose(edge["cosine_distance"], max(0, distance), abs_tol=1e-12)
            assert edge["component_id"] == candidate["component_id"]
            assert edge["shared_profile_genre_ids"] == shared
            assert edge["nominated_track_count"] == len(candidate["track_ids"])
            assert (
                edge["ranking_supported_track_count"] == candidate["ranking_supported_track_count"]
            )
        edge_count += len(actual)
    return edge_count


class ArtistNeighborTests(unittest.TestCase):
    def test_ties_components_empty_and_disjoint_profiles(self) -> None:
        rows = [artist(i, 1 if i < 3 else i, {99: 1}) for i in range(1, 12)]
        rows += [artist(12, 12, {}), artist(13, 13, {100: 1})]
        partition = {"artists": list(reversed(rows))}
        original = copy.deepcopy(partition)
        attach_neighbors(partition)
        self.assertEqual(
            [e["artist_id"] for e in rows[0]["profile_neighbors"]["neighbors"]], list(range(3, 9))
        )
        self.assertEqual(rows[-2]["profile_neighbors"]["reason"], "empty_rank_profile")
        self.assertEqual(rows[-1]["profile_neighbors"]["reason"], "no_eligible_overlap")
        independently_verify(partition)
        for row in partition["artists"]:
            row.pop("profile_neighbors")
        self.assertEqual(partition, original)
        with self.assertRaisesRegex(ValueError, "resource cap"):
            attach_neighbors({"artists": [rows[0]] * (MAX_ARTISTS + 1)})

    def test_nonfinite_and_nonpositive_profile_weights_are_rejected(self) -> None:
        for weight in (float("nan"), float("inf"), -1.0, 0.0):
            with self.assertRaisesRegex(ValueError, "finite positive"):
                attach_neighbors({"artists": [artist(1, 1, {2: weight})]})

    def test_real_retained_pipeline_and_independent_all_edge_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            members = root / "members"
            materialize(RECIPE, members)
            output = root / "neighbors.json"
            command = [
                str(ROOT / ".venv/bin/python"),
                str(ROOT / "scripts/replay_fma_memberships.py"),
                "--saved-pack",
                str(SOURCE),
                "--memberships",
                str(members),
                "--export-artists",
                str(output),
                "--rank-artists",
                "--artist-neighbors",
                "--saved-pack-receipt-sha256",
                sha256_file(SOURCE / "pack-receipt.json")[0],
                "--membership-receipt-sha256",
                sha256_file(members / "pack-receipt.json")[0],
            ]
            subprocess.run(command, check=True, capture_output=True, timeout=120)  # noqa: S603
            report = json.loads(output.read_bytes())
            self.assertLess(output.stat().st_size, 24_000_000)
            self.assertEqual(sum(p["artist_count"] for p in report["partitions"].values()), 1714)
            self.assertFalse(report["scope"]["profile_neighbors"]["target_labels_consumed"])
            for partition in report["partitions"].values():
                self.assertGreater(independently_verify(partition), 0)
            plain_command = command.copy()
            plain_command.remove("--artist-neighbors")
            plain_command[plain_command.index(str(output))] = str(root / "ranked.json")
            subprocess.run(plain_command, check=True, capture_output=True, timeout=120)  # noqa: S603
            plain = json.loads((root / "ranked.json").read_bytes())
            for name, partition in report["partitions"].items():
                for row in partition["artists"]:
                    row.pop("profile_neighbors")
                self.assertEqual(partition, plain["partitions"][name])
            output.unlink()
            command.remove("--rank-artists")
            rejected = subprocess.run(command, check=False, capture_output=True, timeout=120)  # noqa: S603
            self.assertNotEqual(rejected.returncode, 0)
            self.assertFalse(output.exists())
