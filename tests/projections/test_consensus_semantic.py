from __future__ import annotations

import hashlib
import json
import unittest
from itertools import pairwise
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from musix.common import sha256_hex
from musix.peers.audit.strength_aware_peer_audit import (
    ArtifactBinding,
    ConsensusAbstention,
    ConsensusMicroNeighborhoodAudit,
    ConsensusPerturbationConfig,
    DerivedComponent,
    EgoAffiliation,
    StableConsensusPair,
)
from musix.projections.consensus_semantic import (
    ConsensusSemanticCommunity,
    ConsensusSemanticCoverage,
    ConsensusSemanticEdge,
    ConsensusSemanticLayoutQuality,
    ConsensusSemanticNode,
    ConsensusSemanticProjection,
    ConsensusSemanticProjectionConfig,
    ConsensusSemanticProjectionError,
    ProjectionInputBinding,
    _load_consensus,
    _lod_min,
    _projection_sha256,
    _spectral_layout,
    verify_consensus_semantic_projection,
)


class ConsensusSemanticProjectionTests(unittest.TestCase):
    def test_weighted_spectral_layout_is_deterministic_and_reports_quality(self) -> None:
        eligible_ids = {"a", "b", "c", "d", "e", "f"}
        stable_edges = (
            _edge("a", "b", "stable_consensus_peer"),
            _edge("b", "c", "stable_consensus_peer"),
            _edge("c", "d", "stable_consensus_peer"),
            _edge("d", "e", "stable_consensus_peer"),
        )
        factual_edges = (_edge("e", "f", "accepted_factual_taxonomy"),)
        weights = {
            ("a", "b"): 0.8,
            ("b", "c"): 0.8,
            ("c", "d"): 1.0,
            ("d", "e"): 0.8,
            ("e", "f"): 1.0,
        }

        first = _spectral_layout(eligible_ids, stable_edges, factual_edges, weights)
        second = _spectral_layout(eligible_ids, stable_edges, factual_edges, weights)

        self.assertEqual(first, second)
        communities, positions, degrees, quality = first
        self.assertGreaterEqual(len(communities), 1)
        self.assertEqual(set(positions), eligible_ids)
        self.assertEqual(degrees["a"], 1)
        self.assertEqual(degrees["c"], 2)
        self.assertEqual(quality.input_weighted_edge_count, 5)
        self.assertGreater(quality.weighted_mean_edge_distance, 0.0)
        self.assertGreaterEqual(quality.mean_knn_preservation, 0.0)
        self.assertLessEqual(quality.mean_knn_preservation, 1.0)

    def test_consensus_loader_binds_logical_and_byte_identity(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "consensus.json"
            artifact = _mini_consensus()
            payload = artifact.model_dump(mode="json", exclude={"output_sha256"})
            output_sha256 = hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            raw = (
                artifact.model_copy(update={"output_sha256": output_sha256})
                .model_dump_json()
                .encode()
            )
            path.write_bytes(raw)

            loaded, first_binding = _load_consensus(path)
            self.assertEqual(loaded.output_sha256, output_sha256)
            path.write_bytes(raw + b"\n")
            _loaded, second_binding = _load_consensus(path)
            self.assertEqual(first_binding.logical_sha256, second_binding.logical_sha256)
            self.assertNotEqual(first_binding.byte_sha256, second_binding.byte_sha256)
            tampered = json.loads(raw)
            tampered["eligible_seed_count"] = 1
            path.write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaisesRegex(ConsensusSemanticProjectionError, "logical hash"):
                _load_consensus(path)

    def test_verifier_requires_complete_explicit_abstention_partition(self) -> None:
        projection = _complete_fixture_projection()
        verify_consensus_semantic_projection(projection)
        overlap = projection.model_copy(
            update={
                "unplaced_abstentions": (
                    ConsensusAbstention(
                        genre_id="g0001", reason="no_cross_channel_stable_coassignment"
                    ),
                    *projection.unplaced_abstentions[1:],
                )
            }
        )
        overlap = overlap.model_copy(update={"output_sha256": _projection_sha256(overlap)})
        with self.assertRaisesRegex(ConsensusSemanticProjectionError, "placement abstention"):
            verify_consensus_semantic_projection(overlap)


def _edge(
    left: str,
    right: str,
    kind: Literal["stable_consensus_peer", "accepted_factual_taxonomy"],
) -> ConsensusSemanticEdge:
    return ConsensusSemanticEdge(source_genre_id=left, target_genre_id=right, kind=kind)


def _mini_consensus() -> ConsensusMicroNeighborhoodAudit:
    stable = StableConsensusPair(
        source_genre_id="a",
        target_genre_id="b",
        direct_coassignment_frequency=0.8,
        support_coassignment_frequency=0.8,
        direct_coassigned_runs=4,
        support_coassigned_runs=4,
    )
    binding = ArtifactBinding(
        artifact_bytes_sha256="a" * 64,
        artifact_logical_sha256="b" * 64,
        source_seed_reconciliation_bytes_sha256="c" * 64,
        artifact_bytes=1,
        seed_count=3,
        support_genre_count=2,
        support_membership_count=2,
        empty_input_seed_count=1,
        seeds_without_qualifying_neighbors_count=0,
        candidate_edge_count=1,
    )
    return ConsensusMicroNeighborhoodAudit(
        direct_input=binding,
        support_input=binding,
        seed_reconciliation_bytes_sha256="d" * 64,
        seed_reconciliation_logical_sha256="e" * 64,
        perturbation=ConsensusPerturbationConfig(),
        replay_sha256="f" * 64,
        stable_pair_count=1,
        covered_seed_count=3,
        eligible_seed_count=2,
        abstention_count=1,
        stable_pairs=(stable,),
        ego_affiliations=(
            EgoAffiliation(genre_id="a", member_genre_ids=("a", "b"), stable_peer_genre_ids=("b",)),
            EgoAffiliation(genre_id="b", member_genre_ids=("a", "b"), stable_peer_genre_ids=("a",)),
        ),
        derived_disjoint_components_not_taxonomy=(DerivedComponent(member_genre_ids=("a", "b")),),
        abstentions=(
            ConsensusAbstention(genre_id="c", reason="no_cross_channel_stable_coassignment"),
        ),
        output_sha256="0" * 64,
    )


def _complete_fixture_projection() -> ConsensusSemanticProjection:
    eligible_ids = tuple(f"g{number:04d}" for number in range(1, 959))
    edge_rows = tuple(
        _edge(left, right, "stable_consensus_peer") for left, right in pairwise(eligible_ids)
    )
    neighbors = {genre_id: set() for genre_id in eligible_ids}
    for edge in edge_rows:
        neighbors[edge.source_genre_id].add(edge.target_genre_id)
        neighbors[edge.target_genre_id].add(edge.source_genre_id)
    community_id = sha256_hex("\x1f".join(eligible_ids).encode())
    ordered = tuple(
        sorted(eligible_ids, key=lambda genre_id: (-len(neighbors[genre_id]), genre_id))
    )
    nodes = tuple(
        ConsensusSemanticNode(
            genre_id=genre_id,
            x=0.5,
            y=0.5,
            community_id=community_id,
            degree=len(neighbors[genre_id]),
            label_rank=rank,
            lod_min=_lod_min(rank),
        )
        for rank, genre_id in enumerate(ordered, start=1)
    )
    abstentions = tuple(
        ConsensusAbstention(
            genre_id=f"a{number:04d}", reason="no_cross_channel_stable_coassignment"
        )
        for number in range(1, 5_334)
    )
    base = ConsensusSemanticProjection(
        inputs=(
            ProjectionInputBinding(
                role="consensus_micro_neighborhoods",
                byte_sha256="a" * 64,
                byte_count=1,
                logical_sha256="b" * 64,
            ),
            ProjectionInputBinding(
                role="exact_qid_taxonomy",
                byte_sha256="c" * 64,
                byte_count=1,
                logical_sha256="d" * 64,
            ),
        ),
        config=ConsensusSemanticProjectionConfig(),
        coverage=ConsensusSemanticCoverage(
            eligible_placed_seed_count=len(nodes),
            explicit_unplaced_abstention_count=len(abstentions),
            stable_peer_edge_count=len(edge_rows),
            accepted_factual_taxonomy_edge_count=0,
            community_count=1,
        ),
        layout_quality=ConsensusSemanticLayoutQuality(
            input_weighted_edge_count=len(edge_rows),
            layout_weighted_edge_count=len(edge_rows),
            mean_knn_preservation=1.0,
            mutual_neighbor_fraction=1.0,
            weighted_mean_edge_distance=0.0,
            community_iterations=0,
            community_converged=True,
        ),
        nodes=nodes,
        edges=edge_rows,
        communities=(
            ConsensusSemanticCommunity(
                community_id=community_id,
                member_genre_ids=eligible_ids,
                stable_peer_edge_count=len(edge_rows),
                factual_taxonomy_edge_count=0,
            ),
        ),
        unplaced_abstentions=abstentions,
        output_sha256="0" * 64,
    )
    return base.model_copy(update={"output_sha256": _projection_sha256(base)})
