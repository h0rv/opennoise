"""Regression tests for scope-safe source coverage accounting."""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from opennoise.checkpoints.source_coverage_audit import (
    ArtifactBinding,
    ArtifactCoverage,
    EnrichmentOpportunity,
    MembershipCoverage,
    SourceCoverageAudit,
    source_coverage_audit_sha256,
    verify_source_coverage_audit,
)

_SHA = "a" * 64
_GRAPH_ROLES = (
    "sealed_frontier_v5",
    "musicbrainz_database",
    "musicbrainz_artifact",
    "reviewed_alias_context",
    "wikidata_factual_hierarchy",
    "direct_peer",
    "support_peer",
    "filtered_support_peer",
)


def _audit(
    *,
    train_seed_count: int = 2_435,
    frontier_seed_count: int = 2_378,
    heldout_pair_count: int = 356_200,
) -> SourceCoverageAudit:
    base = SourceCoverageAudit(
        rehashed_inputs=tuple(
            ArtifactBinding(
                role=f"input_{index}",
                path=f".cache/input_{index}.json",
                byte_sha256=_SHA,
                byte_count=1,
                logical_sha256=_SHA,
            )
            for index in range(5)
        ),
        receipt_declared_graph_inputs=tuple(
            ArtifactBinding(
                role=role,
                path=f".cache/{role}",
                byte_sha256=_SHA,
                byte_count=1,
                logical_sha256=_SHA,
            )
            for role in _GRAPH_ROLES
        ),
        direct_observed_frontier_seed_count=frontier_seed_count,
        musicbrainz_direct_frontier_seed_count=2_377,
        wikidata_only_direct_frontier_seed_count=1,
        memberships=(
            MembershipCoverage(
                scope="release_direct_anchor",
                seed_count=2_377,
                artist_count=0,
                pair_count=421_427,
                evidence_kinds=("artist_direct",),
                definition="Release direct anchors.",
            ),
            MembershipCoverage(
                scope="graph_direct_claim",
                seed_count=2_377,
                artist_count=207_328,
                pair_count=0,
                claim_count=815_723,
                evidence_kinds=("artist_direct",),
                definition="Direct graph claims.",
            ),
            MembershipCoverage(
                scope="graph_multi_channel_union",
                seed_count=2_570,
                artist_count=552_283,
                pair_count=1_773_093,
                evidence_kinds=("artist_direct", "release_group_support", "reviewed_alias_context"),
                definition="All graph membership channels.",
            ),
            MembershipCoverage(
                scope="pair_split_train_matrix",
                seed_count=train_seed_count,
                artist_count=552_283,
                pair_count=1_416_893,
                heldout_pair_count=heldout_pair_count,
                evidence_kinds=("artist_direct", "release_group_support", "reviewed_alias_context"),
                definition="Training matrix after pair_split.",
            ),
        ),
        artifact_inventory=(
            ArtifactCoverage(
                adapter="test",
                artifact_role="test",
                state="sealed",
                verification_scope="repository_documented_only",
                signals=("artist_membership",),
                boundary="test boundary",
            ),
        ),
        enrichment_ranking=(
            EnrichmentOpportunity(
                rank=1,
                source="test",
                status="repository_documented_unverified",
                expected_seed_artist_coverage="not measured",
                acquisition_cost="low",
                reproducibility="high",
                label_precision="contextual_review_only",
                recommendation="measure first",
            ),
        ),
        output_sha256="0" * 64,
    )
    return base.model_copy(update={"output_sha256": source_coverage_audit_sha256(base)})


class SourceCoverageAuditTests(unittest.TestCase):
    def test_valid_audit_replays_and_retains_separate_scopes(self) -> None:
        audit = _audit()

        verify_source_coverage_audit(audit)
        self.assertEqual(audit.memberships[1].seed_count, 2_377)
        self.assertEqual(audit.memberships[2].seed_count, 2_570)
        self.assertEqual(audit.memberships[3].seed_count, 2_435)

    def test_train_matrix_cannot_be_described_as_broader_than_union(self) -> None:
        with self.assertRaises(ValidationError):
            _audit(train_seed_count=2_571)

    def test_frontier_direct_observed_keeps_wikidata_only_seed_explicit(self) -> None:
        with self.assertRaises(ValidationError):
            _audit(frontier_seed_count=2_377)

    def test_pair_split_tamper_cannot_change_heldout_denominator(self) -> None:
        with self.assertRaises(ValidationError):
            _audit(heldout_pair_count=356_199)
