"""Behavior tests for the source-neutral landscape layout contract."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

from opennoise.ml.semantic_layout import (
    SemanticLayoutInputs,
    build_semantic_map_layout,
    verify_semantic_map_layout,
)
from opennoise.ml.semantic_layout.builder import (
    _initial_camera,
    _overview_visibility,
    _OverviewSelectionContext,
)
from opennoise.ml.semantic_layout.contracts import (
    OverviewCommunity,
    SemanticLayoutArtifact,
    SemanticLayoutError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


def _digest(value: Mapping[str, object]) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


class SemanticLayoutTests(unittest.TestCase):
    """The builder must preserve evidence boundaries rather than fabricate positions."""

    def _inputs(self, directory: Path) -> SemanticLayoutInputs:
        peer = directory / "peer.sqlite"
        with closing(sqlite3.connect(peer)) as db:
            db.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute(
                "CREATE TABLE seed (source_item_id TEXT PRIMARY KEY, seed_name TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE peer_edge (source_genre_id TEXT, target_genre_id TEXT, score REAL)"
            )
            db.executemany(
                "INSERT INTO metadata VALUES (?, ?)",
                (("non_production_candidate", "true"), ("artifact_output_sha256", "a" * 64)),
            )
            db.executemany(
                "INSERT INTO seed VALUES (?, ?)",
                ((f"g{index}", f"genre {index}") for index in range(6_291)),
            )
            db.executemany(
                "INSERT INTO peer_edge VALUES (?, ?, ?)",
                (("g0", "g1", 1.0), ("g1", "g2", 0.5)),
            )
            db.commit()
        peer_bytes = sha256(peer.read_bytes()).hexdigest()
        manifold = {
            "publication_scope": "local_research_only",
            "export_allowed": False,
            "source_index_sha256": peer_bytes,
            "source_peer_similarity_output_sha256": "a" * 64,
            "coordinates": [
                {"genre_id": "g0", "x": 0.1, "y": 0.1, "component": 0},
                {"genre_id": "g1", "x": 0.5, "y": 0.5, "component": 0},
                {"genre_id": "g2", "x": 0.9, "y": 0.9, "component": 0},
            ],
        }
        manifold["output_sha256"] = _digest(manifold)
        manifold_path = directory / "peer-manifold.json"
        manifold_path.write_text(json.dumps(manifold), encoding="utf-8")
        hierarchy = {
            "historical_inputs_used_for_construction": False,
            "edges": [
                {
                    "included_in_dag": True,
                    "child_seed_id": "g2",
                    "parent_seed_id": "g3",
                    "review_score": 0.7,
                }
            ],
        }
        hierarchy["output_sha256"] = _digest(hierarchy)
        hierarchy_path = directory / "hierarchy.json"
        hierarchy_path.write_text(json.dumps(hierarchy), encoding="utf-8")
        cache = directory / "colisten.sqlite"
        with closing(sqlite3.connect(cache)) as db:
            db.execute(
                "CREATE TABLE neighbor ("
                "seed_id TEXT, neighbor_seed_id TEXT, shrunk_npmi REAL, channel TEXT)"
            )
            db.execute("INSERT INTO neighbor VALUES ('g0', 'g3', 0.2, 'artist_direct')")
            db.commit()
        cache_hash = __import__("hashlib").sha256(cache.read_bytes()).hexdigest()
        colisten = {
            "historical_inputs_read_for_construction": False,
            "audio_read_for_construction": False,
            "listener_identifiers_read_for_construction": False,
            "cache_database_sha256": cache_hash,
        }
        colisten["output_sha256"] = _digest(colisten)
        colisten_path = directory / "colisten.json"
        colisten_path.write_text(json.dumps(colisten), encoding="utf-8")
        return SemanticLayoutInputs(
            peer_index=peer,
            peer_manifold_artifact=manifold_path,
            hierarchy_artifact=hierarchy_path,
            colisten_artifact=colisten_path,
            colisten_cache=cache,
        )

    def test_builds_complete_partition_without_placing_unknowns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact = build_semantic_map_layout(self._inputs(Path(temporary)))
        verify_semantic_map_layout(artifact)
        self.assertEqual(len(artifact.coordinates), 4)
        self.assertEqual(len(artifact.unplaced), 6_287)
        self.assertGreater(artifact.metrics.occupied_world_width_fraction, 0.0)
        self.assertGreater(artifact.metrics.occupied_world_height_fraction, 0.0)
        self.assertEqual(artifact.metrics.exact_coordinate_collision_count, 0)

    def test_rejects_historical_construction_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            inputs = self._inputs(Path(temporary))
            raw = json.loads(inputs.hierarchy_artifact.read_text(encoding="utf-8"))
            raw["historical_inputs_used_for_construction"] = True
            raw["output_sha256"] = _digest(
                {key: value for key, value in raw.items() if key != "output_sha256"}
            )
            inputs.hierarchy_artifact.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(SemanticLayoutError):
                build_semantic_map_layout(inputs)

    def test_rejects_a_rehashed_forged_edge_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact = build_semantic_map_layout(self._inputs(Path(temporary)))
        forged = artifact.model_dump(mode="json")
        forged["metrics"]["source_peer_edge_count"] = 0
        forged["output_sha256"] = _digest(
            {key: value for key, value in forged.items() if key != "output_sha256"}
        )
        with self.assertRaises(ValueError):
            SemanticLayoutArtifact.model_validate(forged)

    def test_initial_camera_is_padded_aspect_envelope(self) -> None:
        camera = _initial_camera(((0.2, 0.2), (1.4, 0.75)), 1.777777777778, 1.0)
        self.assertLessEqual(camera.x0, 0.2)
        self.assertGreaterEqual(camera.x1, 1.4)
        self.assertLessEqual(camera.y0, 0.2)
        self.assertGreaterEqual(camera.y1, 0.75)
        self.assertAlmostEqual(
            (camera.x1 - camera.x0) / (camera.y1 - camera.y0),
            1.777777777778,
            places=10,
        )

    def test_overview_selection_spreads_across_structural_roots(self) -> None:
        names = {
            "a": "rock",
            "b": "jazz",
            "c": "electro",
        }
        positions = {"a": (0.1, 0.1), "b": (0.5, 0.5), "c": (0.9, 0.9)}
        records = [
            OverviewCommunity(
                community_id=index,
                label=name,
                anchor_seed_id=node,
                member_count=1,
                component_id=0,
                x=positions[node][0],
                y=positions[node][1],
            )
            for index, (node, name) in enumerate(names.items())
        ]
        selected = _overview_visibility(
            records,
            tuple((node,) for node in names),
            _OverviewSelectionContext(
                names=names,
                positions=positions,
                roots={"a": "rock-root", "b": "jazz-root", "c": "electro-root"},
                depths={"a": 0, "b": 0, "c": 0},
                degree={"a": 100.0, "b": 2.0, "c": 1.0},
                world_width=1.777777777778,
                budget=3,
            ),
        )
        self.assertEqual(
            {item.anchor_seed_id for item in selected if item.overview_visible},
            {"a", "b", "c"},
        )
