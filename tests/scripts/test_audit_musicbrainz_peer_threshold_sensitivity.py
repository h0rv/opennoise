"""Behavior tests for the bounded peer-threshold sensitivity audit."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

from opennoise.peers.similarity.similarity import GenrePeerSimilarityArtifact

if TYPE_CHECKING:
    from types import ModuleType


_EXPECTED_ADDED_EDGE_COUNT = 2


def _module() -> ModuleType:
    path = Path("scripts/audit_musicbrainz_peer_threshold_sensitivity.py")
    specification = importlib.util.spec_from_file_location("peer_threshold_audit", path)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def _artifact(*, candidates: list[dict[str, object]]) -> GenrePeerSimilarityArtifact:
    base = {
        "input_sha256": "a" * 64,
        "settings_sha256": "b" * 64,
        "output_sha256": "c" * 64,
        "source_artifacts": (
            {
                "artifact_key": "x",
                "content_sha256": "d" * 64,
                "snapshot": "x",
                "source": "musicbrainz",
                "export_allowed": False,
            },
        ),
        "candidates": tuple(candidates),
        "abstentions": (),
        "coverage": {
            "genre_count": 3,
            "observed_direct_membership_count": 3,
            "observed_aggregate_pair_count": 0,
            "direct_artist_count": 2,
            "aggregate_artist_count": 0,
            "candidate_pair_count": len(candidates),
            "abstained_pair_count": 0,
            "directional_neighbor_count": 0,
            "all_inputs_export_allowed": False,
        },
    }
    return GenrePeerSimilarityArtifact.model_validate(base)


def _candidate(left: str, right: str, shared: int) -> dict[str, object]:
    return {
        "source_genre_id": left,
        "target_genre_id": right,
        "score": 0.5,
        "direct_score": 0.5,
        "aggregate_score": 0.0,
        "shared_direct_artist_count": shared,
        "aggregate_listener_day_support": 0,
        "aggregate_supporting_windows": 0,
        "sufficiency": "direct_only",
        "components": (
            {
                "component_kind": "direct_artist_overlap",
                "raw_value": float(shared),
                "normalized_value": 0.5,
                "configured_weight": 0.7,
                "evidence_refs": ("r",),
            },
        ),
        "evidence_refs": ("r",),
    }


class MusicBrainzPeerThresholdSensitivityTests(unittest.TestCase):
    """Keep threshold-one deltas distinct from already-admitted peer edges."""

    def test_sensitivity_counts_only_new_edges_and_placed_opportunities(self) -> None:
        """Added edges expose only scoped unplaced placement opportunities."""
        module = _module()
        baseline = _artifact(candidates=[_candidate("a", "b", 2)])
        replay = _artifact(
            candidates=[
                _candidate("a", "b", 2),
                _candidate("c", "d", 1),
                _candidate("c", "e", 1),
            ]
        )
        result = module.summarize_counts(
            baseline=baseline,
            sensitivity=replay,
            scoped_unplaced=frozenset({"c"}),
            placed_ids=frozenset({"d"}),
            structural_edges=(("d", "f"),),
        )
        self.assertEqual(result.added_candidate_edge_count, _EXPECTED_ADDED_EDGE_COUNT)
        self.assertEqual(result.scoped_unplaced_seeds_newly_connected, 1)
        self.assertEqual(result.scoped_unplaced_seeds_with_placed_neighbor, 1)
        self.assertEqual(result.distinct_existing_structural_components_reached, 1)
        self.assertTrue(result.all_added_edges_have_one_shared_artist)
