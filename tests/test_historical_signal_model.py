import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from pydantic import ValidationError

from musix.historical_signal_model import _graph_hierarchy, _idf_candidates, _knn
from musix.models.historical_signal import HistoricalSignalSettings

_MICROGENRE_LEVEL = 2
_MICROGENRE_MAX_MEMBERS = 2


class HistoricalSignalModelTests(unittest.TestCase):
    def test_idf_overlap_is_not_relabelled_weighted_jaccard(self) -> None:
        memberships = {
            "genre:a": {"artist:shared", "artist:a-only"},
            "genre:b": {"artist:shared"},
            "genre:c": {"artist:c-only"},
        }
        settings = HistoricalSignalSettings(neighbors_per_genre=2)
        candidates, _artist_degrees = _idf_candidates(memberships, settings)
        neighbors = _knn(tuple(sorted(memberships)), candidates, settings)
        relation = next(
            item
            for item in neighbors
            if item.genre_id == "genre:a" and item.neighbor_genre_id == "genre:b"
        )
        self.assertNotEqual(relation.idf_overlap, relation.weighted_jaccard)
        self.assertGreater(relation.idf_overlap, relation.weighted_jaccard)

    def test_embedding_method_and_method_identifier_are_bound(self) -> None:
        with self.assertRaises(ValidationError):
            HistoricalSignalSettings(embedding_method="normalized_laplacian_spectral")
        spectral = HistoricalSignalSettings(
            method="idf_membership_knn_spectral_v1",
            embedding_method="normalized_laplacian_spectral",
        )
        self.assertEqual(spectral.method, "idf_membership_knn_spectral_v1")

    def test_graph_hierarchy_is_deterministic_bounded_and_name_independent(self) -> None:
        genre_ids = tuple(f"genre:{index:02d}" for index in range(32))
        graph = [dict[int, float]() for _ in genre_ids]
        for index in range(len(genre_ids) - 1):
            weight = 0.9 if index // 8 == (index + 1) // 8 else 0.1
            graph[index][index + 1] = weight
            graph[index + 1][index] = weight
        settings = HistoricalSignalSettings(
            hierarchy_umbrella_max_members=32,
            hierarchy_subcommunity_max_members=8,
            hierarchy_microgenre_max_members=2,
        )
        positions = np.array([(index / 31, (31 - index) / 31) for index in range(32)])
        first, first_assignments = _graph_hierarchy(
            graph,
            graph,
            genre_ids,
            {genre_id: f"first {genre_id}" for genre_id in genre_ids},
            positions,
            settings,
        )
        second, second_assignments = _graph_hierarchy(
            graph,
            graph,
            genre_ids,
            {genre_id: f"second {genre_id}" for genre_id in genre_ids},
            positions,
            settings,
        )

        self.assertEqual(first_assignments, second_assignments)
        self.assertEqual(
            [(item.hierarchy_id, item.parent_id, item.children_ids) for item in first],
            [(item.hierarchy_id, item.parent_id, item.children_ids) for item in second],
        )
        self.assertEqual(set(first_assignments), set(range(len(genre_ids))))
        microgenres = [item for item in first if item.level == _MICROGENRE_LEVEL]
        self.assertTrue(microgenres)
        self.assertTrue(all(item.member_count <= _MICROGENRE_MAX_MEMBERS for item in microgenres))
        self.assertTrue(
            all(
                item.provenance == "graph_and_genre_name_derived"
                for item in first
                if item.level == 0
            )
        )
        self.assertTrue(
            all(
                item.provenance == "graph_derived_h3_similarity" for item in first if item.level > 0
            )
        )

    def test_graph_hierarchy_bundles_disconnected_components_at_the_umbrella_level(self) -> None:
        genre_ids = tuple(f"genre:{index:02d}" for index in range(16))
        graph = [dict[int, float]() for _ in genre_ids]
        for index in range(0, len(genre_ids), 2):
            graph[index][index + 1] = 0.8
            graph[index + 1][index] = 0.8
        positions = np.array([(index / 15, (15 - index) / 15) for index in range(16)])
        hierarchy, assignments = _graph_hierarchy(
            graph,
            graph,
            genre_ids,
            {genre_id: genre_id for genre_id in genre_ids},
            positions,
            HistoricalSignalSettings(
                hierarchy_umbrella_max_members=32,
                hierarchy_subcommunity_max_members=8,
                hierarchy_microgenre_max_members=2,
            ),
        )

        umbrellas = [item for item in hierarchy if item.level == 0]
        self.assertEqual(len(umbrellas), 1)
        self.assertEqual(umbrellas[0].member_count, len(genre_ids))
        self.assertEqual(len(assignments), len(genre_ids))

    def test_idf_candidate_reductions_are_stable_across_hash_seeds(self) -> None:
        """Set-backed memberships must not alter graph weights or top-k ties."""
        script = """
import json
from musix.historical_signal_model import _idf_candidates, _knn
from musix.models.historical_signal import HistoricalSignalSettings

memberships = {f"genre:{index:02d}": set() for index in range(40)}
for index in range(5_000):
    artist_id = f"artist:{index:04d}"
    memberships[f"genre:{(index * 3) % 40:02d}"].add(artist_id)
    memberships[f"genre:{(index * 7 + 1) % 40:02d}"].add(artist_id)
    if index % 3 == 0:
        memberships[f"genre:{(index * 11 + 2) % 40:02d}"].add(artist_id)

settings = HistoricalSignalSettings(neighbors_per_genre=20)
candidates, _artist_degrees = _idf_candidates(memberships, settings)
neighbors = _knn(tuple(sorted(memberships)), candidates, settings)
payload = {
    "candidates": [
        (pair, value.weighted_jaccard, value.cosine, value.idf_overlap, value.shared_artist_count)
        for pair, value in sorted(candidates.items())
    ],
    "neighbors": [item.model_dump(mode="json") for item in neighbors],
}
print(json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True))
"""
        repository = Path(__file__).parents[1]

        def run(hash_seed: str) -> bytes:
            environment = os.environ | {
                "PYTHONHASHSEED": hash_seed,
                "PYTHONPATH": str(repository / "src"),
            }
            result = subprocess.run(  # noqa: S603 # Trusted test interpreter and static script.
                [sys.executable, "-c", script],
                cwd=repository,
                env=environment,
                check=True,
                capture_output=True,
            )
            return result.stdout

        first, second = run("1"), run("2")
        self.assertEqual(hashlib.sha256(first).hexdigest(), hashlib.sha256(second).hexdigest())
        self.assertEqual(first, second)

    def test_historical_artifact_is_stable_across_hash_seed_processes(self) -> None:
        """A complete independently launched build has a stable internal and byte hash."""
        source_sha = "a" * 64
        script = """
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from musix.historical_signal_model import build_historical_signal_model
from musix.models.historical_signal import HistoricalSignalSettings

database = Path(sys.argv[1])
genres = tuple(
    SimpleNamespace(
        external_id=f"genre:{index:02d}",
        name=f"Genre {index:02d}",
        coordinate=SimpleNamespace(x_px=float(index), y_px=float(index % 7)),
    )
    for index in range(40)
)
historical = SimpleNamespace(
    artifact=SimpleNamespace(content_sha256="b" * 64),
    genres=genres,
)
artifact = build_historical_signal_model(
    historical=historical,
    membership_database=database,
    h3_artifact_sha256="a" * 64,
    settings=HistoricalSignalSettings(
        method="idf_membership_knn_spectral_force_v1",
        embedding_method="spectral_force_refined",
    ),
)
print(json.dumps({
    "artifact_sha256": artifact.quality.artifact_sha256,
    "artifact": artifact.model_dump(mode="json"),
}, allow_nan=False, separators=(",", ":"), sort_keys=True))
"""
        repository = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Path(temporary_directory) / "memberships.sqlite"
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "CREATE TABLE genres (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"
                )
                connection.execute(
                    """CREATE TABLE historical_genre_artist_observations (
                        genre_id INTEGER NOT NULL,
                        source_artist_id TEXT,
                        source_artifact_sha256 TEXT NOT NULL,
                        observation_role TEXT NOT NULL
                    )"""
                )
                connection.executemany(
                    "INSERT INTO genres (id, name) VALUES (?, ?)",
                    ((index, f"Genre {index:02d}") for index in range(40)),
                )
                rows = []
                for index in range(500):
                    artist_id = f"artist:{index:04d}"
                    rows.extend(
                        (
                            ((index * 3) % 40, artist_id, source_sha, "genre_page_member"),
                            ((index * 7 + 1) % 40, artist_id, source_sha, "genre_page_member"),
                        )
                    )
                    if index % 3 == 0:
                        rows.append(
                            ((index * 11 + 2) % 40, artist_id, source_sha, "genre_page_member")
                        )
                connection.executemany(
                    """INSERT INTO historical_genre_artist_observations
                       (genre_id, source_artist_id, source_artifact_sha256, observation_role)
                       VALUES (?, ?, ?, ?)""",
                    rows,
                )

            def run(hash_seed: str) -> bytes:
                environment = os.environ | {
                    "PYTHONHASHSEED": hash_seed,
                    "PYTHONPATH": str(repository / "src"),
                }
                result = subprocess.run(  # noqa: S603 # Trusted test interpreter and static script.
                    [sys.executable, "-c", script, str(database)],
                    cwd=repository,
                    env=environment,
                    check=True,
                    capture_output=True,
                )
                return result.stdout

            first, second = run("1"), run("47")
        self.assertEqual(first, second)
        self.assertEqual(hashlib.sha256(first).hexdigest(), hashlib.sha256(second).hexdigest())
        first_payload, second_payload = json.loads(first), json.loads(second)
        self.assertEqual(first_payload["artifact_sha256"], second_payload["artifact_sha256"])


if __name__ == "__main__":
    unittest.main()
