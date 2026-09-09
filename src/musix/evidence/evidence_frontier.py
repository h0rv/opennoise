"""Sealed all-seed evidence frontier for open genre reconstruction."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from musix.genre_hierarchy_candidates import (
    GenreHierarchyCandidateArtifact,
    verify_genre_hierarchy_candidates,
)
from musix.models import FrozenModel
from musix.peer_similarity import GenrePeerSimilarityArtifact, peer_similarity_output_sha256
from musix.public_artist_membership import (
    ApprovedPublicMembershipInput,
    PublicArtistMembershipCandidateArtifact,
    canonical_sha256,
    public_artist_membership_candidate_output_sha256,
)
from musix.public_taxonomy_expansion import (
    PublicTaxonomyExpansionArtifact,
    verify_public_taxonomy_expansion,
)
from musix.seed_reconciliation import (
    ReconciledIdentity,
    ReconciliationDisposition,
    SeedReconciliationArtifact,
    verify_seed_reconciliation,
)
from musix.storage import ObjectKey, ObjectStore, ObjectWrite

if TYPE_CHECKING:
    from musix.listenbrainz_propagation import ListenBrainzPropagationFrontierSummary
    from musix.models.modeling import PublicModelInput
    from musix.public_artist_membership_adapter import CertifiedPublicMembershipAdapterReceipt

_REVISION: Final = "all-seed-evidence-frontier-v5"
_SEED_COUNT: Final = 6_291
_SHA256: Final = r"^[0-9a-f]{64}$"

type FrontierSignal = Literal[
    "public_identity",
    "musicbrainz_identity",
    "factual_hierarchy",
    "review_hierarchy",
    "direct_observed_membership",
    "peer_candidate",
    "hierarchy_candidate_accepted",
    "hierarchy_candidate_review",
    "hierarchy_candidate_abstained",
    "listenbrainz_review_candidate",
]
type FrontierMissingReason = Literal[
    "no_public_identity",
    "no_musicbrainz_identity",
    "no_factual_hierarchy",
    "no_review_hierarchy",
    "no_direct_observed_membership",
    "no_peer_candidate",
    "reconciliation_ambiguous",
    "reconciliation_unresolved",
    "hierarchy_candidates_not_provided",
    "hierarchy_candidate_abstained",
    "no_listenbrainz_review_candidate",
]
type HierarchyCandidateInputState = Literal["not_provided", "verified"]
type HierarchyCandidateDisposition = Literal[
    "supported", "review", "abstained", "isolated", "not_provided"
]
type FrontierSourceScope = Literal[
    "cc0_public_taxonomy",
    "cc0_wikidata_membership",
    "local_musicbrainz_research",
    "listenbrainz_derived_review",
]


class FrontierPeerCount(FrozenModel):
    """One source-preserving peer count for a retained seed."""

    source_item_id: str = Field(min_length=1, max_length=200)
    peer_count: int = Field(ge=0)


class FrontierPeerCoverage(FrozenModel):
    """Compact, hash-bound peer coverage upgraded from a sealed v3 frontier."""

    revision: Literal["frontier-peer-coverage-v1"] = "frontier-peer-coverage-v1"
    source_frontier_output_sha256: str = Field(pattern=_SHA256)
    source_peer_similarity_output_sha256: str = Field(pattern=_SHA256)
    counts: tuple[FrontierPeerCount, ...] = Field(min_length=_SEED_COUNT, max_length=_SEED_COUNT)
    output_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _complete_sorted_coverage(self) -> FrontierPeerCoverage:
        source_ids = tuple(item.source_item_id for item in self.counts)
        if source_ids != tuple(sorted(source_ids)) or len(set(source_ids)) != _SEED_COUNT:
            raise ValueError("peer coverage requires sorted, unique complete seed IDs")
        return self


class _LegacyFrontierPeerRow(BaseModel):
    """Parse only the peer fields needed from the sealed v3 upgrade boundary."""

    model_config = ConfigDict(frozen=True, strict=False, extra="ignore")

    source_item_id: str = Field(min_length=1, max_length=200)
    peer_count: int = Field(ge=0)


class _LegacyFrontierPeerSource(BaseModel):
    """Parse a v3 frontier solely to retain its already-sealed peer counts."""

    model_config = ConfigDict(frozen=True, strict=False, extra="ignore")

    revision: Literal["all-seed-evidence-frontier-v3"]
    peer_similarity_output_sha256: str = Field(pattern=_SHA256)
    rows: tuple[_LegacyFrontierPeerRow, ...] = Field(min_length=_SEED_COUNT, max_length=_SEED_COUNT)
    output_sha256: str = Field(pattern=_SHA256)


class FrontierObservedArtists(FrozenModel):
    """Distinct observed artists, never inferred membership, per source facet."""

    musicbrainz_genre: int = Field(ge=0)
    musicbrainz_tag: int = Field(ge=0)
    wikidata_p136: int = Field(ge=0)
    distinct_total: int = Field(ge=0)

    @model_validator(mode="after")
    def _bound_distinct_total(self) -> FrontierObservedArtists:
        if self.distinct_total > self.musicbrainz_genre + self.musicbrainz_tag + self.wikidata_p136:
            raise ValueError("distinct artist total exceeds facet observations")
        return self


class FrontierListenBrainzReview(FrozenModel):
    """Derived review candidates from the sealed ListenBrainz artifact, never facts."""

    candidate_count: int = Field(ge=0)
    candidate_artist_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _candidate_artist_count_is_bounded(self) -> FrontierListenBrainzReview:
        if self.candidate_artist_count > self.candidate_count:
            raise ValueError("ListenBrainz review artist count exceeds candidate count")
        return self


class FrontierHierarchy(FrozenModel):
    """Seed-to-seed projections of factual and review-only public taxonomy links."""

    factual_catalog_identity_ids: tuple[str, ...] = ()
    review_catalog_candidate_ids: tuple[str, ...] = ()
    factual_parent_source_item_ids: tuple[str, ...] = ()
    factual_child_source_item_ids: tuple[str, ...] = ()
    review_parent_source_item_ids: tuple[str, ...] = ()
    review_child_source_item_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _require_unique_links(self) -> FrontierHierarchy:
        collections = (
            self.factual_catalog_identity_ids,
            self.review_catalog_candidate_ids,
            self.factual_parent_source_item_ids,
            self.factual_child_source_item_ids,
            self.review_parent_source_item_ids,
            self.review_child_source_item_ids,
        )
        if any(len(values) != len(set(values)) for values in collections):
            raise ValueError("frontier hierarchy links must be unique")
        return self


class FrontierHierarchyCandidates(FrozenModel):
    """Per-seed candidate outcomes, never substituted for public taxonomy."""

    input_state: HierarchyCandidateInputState
    proposed_edge_count: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    review_count: int = Field(ge=0)
    abstained_count: int = Field(ge=0)
    disposition: HierarchyCandidateDisposition

    @model_validator(mode="after")
    def _require_explicit_partition(self) -> FrontierHierarchyCandidates:
        if self.input_state == "not_provided":
            if (
                any(
                    (
                        self.proposed_edge_count,
                        self.accepted_count,
                        self.review_count,
                        self.abstained_count,
                    )
                )
                or self.disposition != "not_provided"
            ):
                raise ValueError("missing hierarchy candidate input must remain explicitly empty")
            return self
        if self.proposed_edge_count != (
            self.accepted_count + self.review_count + self.abstained_count
        ):
            raise ValueError("hierarchy candidate counts must partition proposals")
        if self.proposed_edge_count == 0 and self.disposition != "isolated":
            raise ValueError("candidate-free verified rows must be isolated")
        if self.proposed_edge_count > 0 and self.disposition in {"isolated", "not_provided"}:
            raise ValueError("candidate-bearing verified rows require an evidence disposition")
        return self


class FrontierHierarchyCandidateRow(FrozenModel):
    """One upgraded per-seed hierarchy candidate state."""

    source_item_id: str = Field(min_length=1, max_length=200)
    hierarchy_candidates: FrontierHierarchyCandidates


class FrontierHierarchyCandidateCoverage(FrozenModel):
    """Hash-bound hierarchy candidate summaries upgraded from a sealed v3 frontier."""

    revision: Literal["frontier-hierarchy-candidate-coverage-v1"] = (
        "frontier-hierarchy-candidate-coverage-v1"
    )
    source_frontier_output_sha256: str = Field(pattern=_SHA256)
    input_state: HierarchyCandidateInputState
    output_sha256: str | None = Field(default=None, pattern=_SHA256)
    rows: tuple[FrontierHierarchyCandidateRow, ...] = Field(
        min_length=_SEED_COUNT, max_length=_SEED_COUNT
    )
    logical_output_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _complete_sorted_coverage(self) -> FrontierHierarchyCandidateCoverage:
        source_ids = tuple(item.source_item_id for item in self.rows)
        if source_ids != tuple(sorted(source_ids)) or len(set(source_ids)) != _SEED_COUNT:
            raise ValueError(
                "hierarchy candidate coverage requires sorted, unique complete seed IDs"
            )
        if (self.input_state == "verified") != (self.output_sha256 is not None):
            raise ValueError("hierarchy candidate coverage must bind its explicit input state")
        return self


class _LegacyFrontierHierarchyRow(BaseModel):
    """Parse only hierarchy candidate state from the sealed v3 frontier boundary."""

    model_config = ConfigDict(frozen=True, strict=False, extra="ignore")

    source_item_id: str = Field(min_length=1, max_length=200)
    hierarchy_candidates: FrontierHierarchyCandidates


class _LegacyFrontierHierarchySource(BaseModel):
    """Parse source hashes and hierarchy summaries from one sealed v3 frontier."""

    model_config = ConfigDict(frozen=True, strict=False, extra="ignore")

    revision: Literal["all-seed-evidence-frontier-v3"]
    hierarchy_candidate_input_state: HierarchyCandidateInputState
    hierarchy_candidate_output_sha256: str | None = Field(default=None, pattern=_SHA256)
    rows: tuple[_LegacyFrontierHierarchyRow, ...] = Field(
        min_length=_SEED_COUNT, max_length=_SEED_COUNT
    )
    output_sha256: str = Field(pattern=_SHA256)


class _LegacyV4FrontierCoverage(BaseModel):
    """The v4 coverage fields whose values v5 must preserve exactly."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    seed_count: Literal[6291]
    reconciled_count: int = Field(ge=0)
    public_only_count: int = Field(ge=0)
    musicbrainz_only_count: int = Field(ge=0)
    review_only_count: int = Field(ge=0)
    ambiguous_count: int = Field(ge=0)
    unresolved_count: int = Field(ge=0)
    factual_hierarchy_seed_count: int = Field(ge=0)
    review_hierarchy_seed_count: int = Field(ge=0)
    reconciliation_musicbrainz_identity_seed_count: int = Field(ge=0)
    direct_observed_seed_count: int = Field(ge=0)
    observed_musicbrainz_seed_count: int = Field(ge=0)
    observed_wikidata_seed_count: int = Field(ge=0)
    observed_musicbrainz_only_seed_count: int = Field(ge=0)
    observed_wikidata_only_seed_count: int = Field(ge=0)
    observed_cross_source_seed_count: int = Field(ge=0)
    peer_seed_count: int = Field(ge=0)
    hierarchy_candidate_input_state: HierarchyCandidateInputState
    hierarchy_candidate_count: int = Field(ge=0)
    hierarchy_candidate_accepted_count: int = Field(ge=0)
    hierarchy_candidate_review_count: int = Field(ge=0)
    hierarchy_candidate_abstained_count: int = Field(ge=0)
    hierarchy_candidate_supported_seed_count: int = Field(ge=0)
    hierarchy_candidate_review_seed_count: int = Field(ge=0)
    hierarchy_candidate_abstained_seed_count: int = Field(ge=0)
    hierarchy_candidate_isolated_seed_count: int = Field(ge=0)


class _LegacyV4FrontierRow(BaseModel):
    """One v4 row before v5 adds a derived ListenBrainz review projection."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    source_item_id: str = Field(min_length=1, max_length=200)
    source_external_id: str = Field(min_length=1, max_length=300)
    seed_name: str = Field(min_length=1, max_length=500)
    normalized_name: str = Field(min_length=1, max_length=500)
    reconciliation_disposition: ReconciliationDisposition
    public_identities: tuple[ReconciledIdentity, ...] = ()
    musicbrainz_identities: tuple[ReconciledIdentity, ...] = ()
    hierarchy: FrontierHierarchy
    hierarchy_candidates: FrontierHierarchyCandidates
    observed_artists: FrontierObservedArtists
    peer_count: int = Field(ge=0)
    source_scope: tuple[FrontierSourceScope, ...]
    signal_scope: tuple[FrontierSignal, ...]
    missing_or_abstention_reasons: tuple[FrontierMissingReason, ...]
    reconciliation_reason: str | None = Field(default=None, max_length=500)


class _LegacyV4FrontierSource(BaseModel):
    """Strict full v4 source loaded only after receipt and logical-hash verification."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    revision: Literal["all-seed-evidence-frontier-v4"]
    seed_reconciliation_output_sha256: str = Field(pattern=_SHA256)
    taxonomy_expansion_output_sha256: str = Field(pattern=_SHA256)
    public_model_input_sha256: str = Field(pattern=_SHA256)
    peer_similarity_output_sha256: str = Field(pattern=_SHA256)
    peer_coverage_output_sha256: str | None = Field(default=None, pattern=_SHA256)
    wikidata_membership_candidate_output_sha256: str | None = Field(default=None, pattern=_SHA256)
    wikidata_approved_input_sha256: str | None = Field(default=None, pattern=_SHA256)
    wikidata_adapter_receipt_output_sha256: str | None = Field(default=None, pattern=_SHA256)
    hierarchy_candidate_coverage_output_sha256: str | None = Field(default=None, pattern=_SHA256)
    hierarchy_candidate_input_state: HierarchyCandidateInputState
    hierarchy_candidate_output_sha256: str | None = Field(default=None, pattern=_SHA256)
    historical_coordinates_read: Literal[False]
    historical_memberships_read: Literal[False]
    historical_neighbors_read: Literal[False]
    rows: tuple[_LegacyV4FrontierRow, ...] = Field(min_length=_SEED_COUNT, max_length=_SEED_COUNT)
    coverage: _LegacyV4FrontierCoverage
    output_sha256: str = Field(pattern=_SHA256)


class FrontierV4Baseline(FrozenModel):
    """Verified compact v4 custody and monotonic-coverage comparison boundary."""

    revision: Literal["frontier-v4-baseline-v1"] = "frontier-v4-baseline-v1"
    source_frontier_output_sha256: str = Field(pattern=_SHA256)
    coverage: _LegacyV4FrontierCoverage
    output_sha256: str = Field(pattern=_SHA256)


class EvidenceFrontierRow(FrozenModel):
    """Exactly one immutable, explicit evidence account for one retained seed."""

    source_item_id: str = Field(min_length=1, max_length=200)
    source_external_id: str = Field(min_length=1, max_length=300)
    seed_name: str = Field(min_length=1, max_length=500)
    normalized_name: str = Field(min_length=1, max_length=500)
    reconciliation_disposition: ReconciliationDisposition
    public_identities: tuple[ReconciledIdentity, ...] = ()
    musicbrainz_identities: tuple[ReconciledIdentity, ...] = ()
    hierarchy: FrontierHierarchy
    hierarchy_candidates: FrontierHierarchyCandidates
    observed_artists: FrontierObservedArtists
    listenbrainz_review: FrontierListenBrainzReview
    peer_count: int = Field(ge=0)
    source_scope: tuple[FrontierSourceScope, ...]
    signal_scope: tuple[FrontierSignal, ...]
    missing_or_abstention_reasons: tuple[FrontierMissingReason, ...]
    reconciliation_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _require_explicit_state(self) -> EvidenceFrontierRow:
        if len(self.source_scope) != len(set(self.source_scope)):
            raise ValueError("frontier source scope must be unique")
        if len(self.signal_scope) != len(set(self.signal_scope)):
            raise ValueError("frontier signal scope must be unique")
        if len(self.missing_or_abstention_reasons) != len(set(self.missing_or_abstention_reasons)):
            raise ValueError("frontier missing reasons must be unique")
        if (
            self.reconciliation_disposition in {"ambiguous", "unresolved"}
            and not self.reconciliation_reason
        ):
            raise ValueError(
                "ambiguous and unresolved frontier rows require their reconciliation reason"
            )
        return self


class EvidenceFrontierCoverage(FrozenModel):
    """Coverage matrix over every retained stable seed."""

    seed_count: Literal[6291] = _SEED_COUNT
    reconciled_count: int = Field(ge=0)
    public_only_count: int = Field(ge=0)
    musicbrainz_only_count: int = Field(ge=0)
    review_only_count: int = Field(ge=0)
    ambiguous_count: int = Field(ge=0)
    unresolved_count: int = Field(ge=0)
    factual_hierarchy_seed_count: int = Field(ge=0)
    review_hierarchy_seed_count: int = Field(ge=0)
    reconciliation_musicbrainz_identity_seed_count: int = Field(ge=0)
    direct_observed_seed_count: int = Field(ge=0)
    observed_musicbrainz_seed_count: int = Field(ge=0)
    observed_wikidata_seed_count: int = Field(ge=0)
    observed_musicbrainz_only_seed_count: int = Field(ge=0)
    observed_wikidata_only_seed_count: int = Field(ge=0)
    observed_cross_source_seed_count: int = Field(ge=0)
    listenbrainz_review_candidate_seed_count: int = Field(ge=0)
    listenbrainz_review_candidate_count: int = Field(ge=0)
    listenbrainz_review_overlap_direct_observed_seed_count: int = Field(ge=0)
    listenbrainz_review_only_seed_count: int = Field(ge=0)
    direct_observed_only_seed_count: int = Field(ge=0)
    direct_observed_or_listenbrainz_review_seed_count: int = Field(ge=0)
    peer_seed_count: int = Field(ge=0)
    hierarchy_candidate_input_state: HierarchyCandidateInputState
    hierarchy_candidate_count: int = Field(ge=0)
    hierarchy_candidate_accepted_count: int = Field(ge=0)
    hierarchy_candidate_review_count: int = Field(ge=0)
    hierarchy_candidate_abstained_count: int = Field(ge=0)
    hierarchy_candidate_supported_seed_count: int = Field(ge=0)
    hierarchy_candidate_review_seed_count: int = Field(ge=0)
    hierarchy_candidate_abstained_seed_count: int = Field(ge=0)
    hierarchy_candidate_isolated_seed_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _partition(self) -> EvidenceFrontierCoverage:  # noqa: C901
        if (
            sum(
                (
                    self.reconciled_count,
                    self.public_only_count,
                    self.musicbrainz_only_count,
                    self.review_only_count,
                    self.ambiguous_count,
                    self.unresolved_count,
                )
            )
            != self.seed_count
        ):
            raise ValueError("frontier dispositions must account for every seed")
        if (
            self.observed_musicbrainz_seed_count > self.direct_observed_seed_count
            or self.observed_wikidata_seed_count > self.direct_observed_seed_count
        ):
            raise ValueError("per-source observed seed counts exceed direct observed coverage")
        if self.direct_observed_seed_count != (
            self.observed_musicbrainz_only_seed_count
            + self.observed_wikidata_only_seed_count
            + self.observed_cross_source_seed_count
        ):
            raise ValueError("observed source-union coverage must partition direct coverage")
        if self.listenbrainz_review_candidate_seed_count != (
            self.listenbrainz_review_overlap_direct_observed_seed_count
            + self.listenbrainz_review_only_seed_count
        ):
            raise ValueError("ListenBrainz review/direct overlap must partition review coverage")
        if self.direct_observed_seed_count != (
            self.listenbrainz_review_overlap_direct_observed_seed_count
            + self.direct_observed_only_seed_count
        ):
            raise ValueError("ListenBrainz review/direct overlap must partition direct coverage")
        if self.direct_observed_or_listenbrainz_review_seed_count != (
            self.listenbrainz_review_overlap_direct_observed_seed_count
            + self.listenbrainz_review_only_seed_count
            + self.direct_observed_only_seed_count
        ):
            raise ValueError("ListenBrainz review/direct union must match its partitions")
        if self.hierarchy_candidate_input_state == "not_provided":
            if any(
                (
                    self.hierarchy_candidate_count,
                    self.hierarchy_candidate_accepted_count,
                    self.hierarchy_candidate_review_count,
                    self.hierarchy_candidate_abstained_count,
                    self.hierarchy_candidate_supported_seed_count,
                    self.hierarchy_candidate_review_seed_count,
                    self.hierarchy_candidate_abstained_seed_count,
                    self.hierarchy_candidate_isolated_seed_count,
                )
            ):
                raise ValueError("absent hierarchy candidate input must not have derived coverage")
        elif self.hierarchy_candidate_count != (
            self.hierarchy_candidate_accepted_count
            + self.hierarchy_candidate_review_count
            + self.hierarchy_candidate_abstained_count
        ):
            raise ValueError("hierarchy candidate edge coverage must partition candidates")
        elif self.seed_count != (
            self.hierarchy_candidate_supported_seed_count
            + self.hierarchy_candidate_review_seed_count
            + self.hierarchy_candidate_abstained_seed_count
            + self.hierarchy_candidate_isolated_seed_count
        ):
            raise ValueError("hierarchy candidate seed coverage must partition seeds")
        return self


class AllSeedEvidenceFrontierArtifact(FrozenModel):
    """Hash-bound complete evidence state without historical inputs."""

    revision: Literal["all-seed-evidence-frontier-v5"] = _REVISION
    seed_reconciliation_output_sha256: str = Field(pattern=_SHA256)
    taxonomy_expansion_output_sha256: str = Field(pattern=_SHA256)
    public_model_input_sha256: str = Field(pattern=_SHA256)
    peer_similarity_output_sha256: str = Field(pattern=_SHA256)
    peer_coverage_output_sha256: str | None = Field(default=None, pattern=_SHA256)
    wikidata_membership_candidate_output_sha256: str | None = Field(default=None, pattern=_SHA256)
    wikidata_approved_input_sha256: str | None = Field(default=None, pattern=_SHA256)
    wikidata_adapter_receipt_output_sha256: str | None = Field(default=None, pattern=_SHA256)
    previous_frontier_output_sha256: str = Field(pattern=_SHA256)
    listenbrainz_propagation_output_sha256: str = Field(pattern=_SHA256)
    listenbrainz_propagation_file_sha256: str = Field(pattern=_SHA256)
    listenbrainz_propagation_receipt_artifact_sha256: str = Field(pattern=_SHA256)
    hierarchy_candidate_coverage_output_sha256: str | None = Field(default=None, pattern=_SHA256)
    hierarchy_candidate_input_state: HierarchyCandidateInputState
    hierarchy_candidate_output_sha256: str | None = Field(default=None, pattern=_SHA256)
    historical_coordinates_read: Literal[False] = False
    historical_memberships_read: Literal[False] = False
    historical_neighbors_read: Literal[False] = False
    rows: tuple[EvidenceFrontierRow, ...] = Field(min_length=_SEED_COUNT, max_length=_SEED_COUNT)
    coverage: EvidenceFrontierCoverage
    output_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _complete(self) -> AllSeedEvidenceFrontierArtifact:  # noqa: C901, PLR0912
        if len({row.source_item_id for row in self.rows}) != _SEED_COUNT:
            raise ValueError("frontier requires exactly one row per stable seed")
        if self.coverage.hierarchy_candidate_input_state != self.hierarchy_candidate_input_state:
            raise ValueError("frontier candidate input state must match coverage")
        wikidata_lineage = (
            self.wikidata_membership_candidate_output_sha256,
            self.wikidata_approved_input_sha256,
            self.wikidata_adapter_receipt_output_sha256,
        )
        if any(value is None for value in wikidata_lineage) and any(
            value is not None for value in wikidata_lineage
        ):
            raise ValueError("Wikidata candidate lineage must bind candidate, input, and receipt")
        if {row.hierarchy_candidates.input_state for row in self.rows} != {
            self.hierarchy_candidate_input_state
        }:
            raise ValueError("frontier rows must use one explicit hierarchy candidate input state")
        if self.hierarchy_candidate_input_state == "not_provided":
            if self.hierarchy_candidate_output_sha256 is not None:
                raise ValueError("absent hierarchy candidate input cannot bind an output hash")
        elif self.hierarchy_candidate_output_sha256 is None:
            raise ValueError("verified hierarchy candidate input requires an output hash")
        if self.hierarchy_candidate_input_state == "verified":
            candidate_rows = tuple(row.hierarchy_candidates for row in self.rows)
            if self.coverage.hierarchy_candidate_count != sum(
                row.proposed_edge_count for row in candidate_rows
            ):
                raise ValueError("frontier hierarchy candidate count does not match row coverage")
            if self.coverage.hierarchy_candidate_accepted_count != sum(
                row.accepted_count for row in candidate_rows
            ):
                raise ValueError("frontier accepted hierarchy candidates do not match rows")
            if self.coverage.hierarchy_candidate_review_count != sum(
                row.review_count for row in candidate_rows
            ):
                raise ValueError("frontier review hierarchy candidates do not match rows")
            if self.coverage.hierarchy_candidate_abstained_count != sum(
                row.abstained_count for row in candidate_rows
            ):
                raise ValueError("frontier abstained hierarchy candidates do not match rows")
            dispositions = tuple(row.disposition for row in candidate_rows)
            if (
                self.coverage.hierarchy_candidate_supported_seed_count
                != dispositions.count("supported")
                or self.coverage.hierarchy_candidate_review_seed_count
                != dispositions.count("review")
                or self.coverage.hierarchy_candidate_abstained_seed_count
                != dispositions.count("abstained")
                or self.coverage.hierarchy_candidate_isolated_seed_count
                != dispositions.count("isolated")
            ):
                raise ValueError("frontier hierarchy candidate seed states do not match rows")
        return self


class EvidenceFrontierGate(FrozenModel):
    """Fail-closed validation for a complete evidence frontier."""

    artifact_output_sha256: str = Field(pattern=_SHA256)
    seed_count: Literal[6291] = _SEED_COUNT
    deterministic_replay: Literal[True] = True
    complete_seed_coverage: Literal[True] = True
    historical_data_prohibited: Literal[True] = True
    review_is_not_factual: Literal[True] = True
    observed_is_not_inferred: Literal[True] = True
    hierarchy_candidate_input_explicit: Literal[True] = True


class EvidenceFrontierReceipt(FrozenModel):
    """Object-store custody receipt for one sealed frontier."""

    artifact_sha256: str = Field(pattern=_SHA256)
    artifact_byte_size: int = Field(ge=1)
    object_key: str = Field(min_length=1)
    logical_output_sha256: str = Field(pattern=_SHA256)
    gate: EvidenceFrontierGate


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1_048_576):
            digest.update(chunk)
    return digest.hexdigest()


def load_frontier_peer_coverage(path: Path) -> FrontierPeerCoverage:
    """Upgrade sealed v3 peer counts without replaying its large similarity artifact."""
    document = TypeAdapter(dict[str, object]).validate_json(path.read_bytes())
    declared_hash = document.get("output_sha256")
    if (
        not isinstance(declared_hash, str)
        or _sha({key: value for key, value in document.items() if key != "output_sha256"})
        != declared_hash
    ):
        raise ValueError("legacy frontier output hash does not replay")
    source = _LegacyFrontierPeerSource.model_validate(document)
    if source.output_sha256 != declared_hash:
        raise ValueError("legacy frontier parsed output hash does not match bytes")
    counts = tuple(
        FrontierPeerCount(source_item_id=row.source_item_id, peer_count=row.peer_count)
        for row in sorted(source.rows, key=lambda row: row.source_item_id)
    )
    preliminary = FrontierPeerCoverage(
        source_frontier_output_sha256=source.output_sha256,
        source_peer_similarity_output_sha256=source.peer_similarity_output_sha256,
        counts=counts,
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(
        update={
            "output_sha256": _sha(preliminary.model_dump(mode="json", exclude={"output_sha256"}))
        }
    )


def load_frontier_hierarchy_candidate_coverage(path: Path) -> FrontierHierarchyCandidateCoverage:
    """Upgrade sealed v3 hierarchy summaries without parsing the large candidate edge artifact."""
    document = TypeAdapter(dict[str, object]).validate_json(path.read_bytes())
    declared_hash = document.get("output_sha256")
    if (
        not isinstance(declared_hash, str)
        or _sha({key: value for key, value in document.items() if key != "output_sha256"})
        != declared_hash
    ):
        raise ValueError("legacy frontier output hash does not replay")
    source = _LegacyFrontierHierarchySource.model_validate(document)
    if source.output_sha256 != declared_hash:
        raise ValueError("legacy frontier parsed output hash does not match bytes")
    rows = tuple(
        FrontierHierarchyCandidateRow(
            source_item_id=row.source_item_id,
            hierarchy_candidates=row.hierarchy_candidates,
        )
        for row in sorted(source.rows, key=lambda row: row.source_item_id)
    )
    preliminary = FrontierHierarchyCandidateCoverage(
        source_frontier_output_sha256=source.output_sha256,
        input_state=source.hierarchy_candidate_input_state,
        output_sha256=source.hierarchy_candidate_output_sha256,
        rows=rows,
        logical_output_sha256="0" * 64,
    )
    return preliminary.model_copy(
        update={
            "logical_output_sha256": _sha(
                preliminary.model_dump(mode="json", exclude={"logical_output_sha256"})
            )
        }
    )


def load_frontier_v4_baseline(path: Path) -> FrontierV4Baseline:
    """Parse and hash-verify the sealed v4 frontier before its v5-only extension."""
    document = TypeAdapter(dict[str, object]).validate_json(path.read_bytes())
    declared_hash = document.get("output_sha256")
    if (
        not isinstance(declared_hash, str)
        or _sha({key: value for key, value in document.items() if key != "output_sha256"})
        != declared_hash
    ):
        raise ValueError("v4 frontier output hash does not replay")
    revision = document.get("revision")
    if revision != "all-seed-evidence-frontier-v4":
        raise ValueError("frontier baseline must be a v4 artifact")
    coverage_raw = document.get("coverage")
    coverage = _LegacyV4FrontierCoverage.model_validate(coverage_raw)
    preliminary = FrontierV4Baseline(
        source_frontier_output_sha256=declared_hash,
        coverage=coverage,
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(
        update={
            "output_sha256": _sha(preliminary.model_dump(mode="json", exclude={"output_sha256"}))
        }
    )


def load_frontier_v4_source(artifact_path: Path, receipt_path: Path) -> _LegacyV4FrontierSource:
    """Receipt-root a complete v4 frontier before adding the v5 review source."""
    receipt = EvidenceFrontierReceipt.model_validate_json(receipt_path.read_bytes())
    if receipt.artifact_sha256 != _file_sha256(artifact_path):
        raise ValueError("v4 frontier byte hash does not match its receipt")
    document = TypeAdapter(dict[str, object]).validate_json(artifact_path.read_bytes())
    declared_hash = document.get("output_sha256")
    if (
        not isinstance(declared_hash, str)
        or declared_hash != receipt.logical_output_sha256
        or _sha({key: value for key, value in document.items() if key != "output_sha256"})
        != declared_hash
    ):
        raise ValueError("v4 frontier logical hash does not replay")
    source = _LegacyV4FrontierSource.model_validate_json(artifact_path.read_bytes())
    if source.output_sha256 != declared_hash:
        raise ValueError("v4 frontier parsed output hash does not match its bytes")
    return source


def _public_input_hash(value: PublicModelInput) -> str:
    return _sha(value.model_dump(mode="json"))


def upgrade_frontier_v4_with_listenbrainz_review(
    source: _LegacyV4FrontierSource,
    listenbrainz_review: ListenBrainzPropagationFrontierSummary,
) -> AllSeedEvidenceFrontierArtifact:
    """Create v5 solely by extending a sealed v4 ledger with review-only counts.

    This upgrade never opens the raw MusicBrainz, Wikidata, taxonomy, peer, or
    hierarchy inputs used by v4.  Therefore its previous evidence is preserved
    byte-for-logical-field, while ListenBrainz is explicitly additive review
    evidence and not an observed membership source.
    """
    if listenbrainz_review.output_sha256 != _sha(
        listenbrainz_review.model_dump(mode="json", exclude={"output_sha256"})
    ):
        raise ValueError("ListenBrainz review summary hash does not replay")
    review_by_seed = {row.source_item_id: row for row in listenbrainz_review.rows}
    source_ids = {row.source_item_id for row in source.rows}
    if set(review_by_seed) != source_ids:
        raise ValueError("ListenBrainz review summary does not bind v4 frontier seeds")
    rows: list[EvidenceFrontierRow] = []
    for legacy_row in source.rows:
        review = review_by_seed[legacy_row.source_item_id]
        review_state = FrontierListenBrainzReview(
            candidate_count=review.candidate_count,
            candidate_artist_count=review.candidate_artist_count,
        )
        source_scope = list(legacy_row.source_scope)
        signals = list(legacy_row.signal_scope)
        missing = list(legacy_row.missing_or_abstention_reasons)
        if review_state.candidate_count:
            source_scope.append("listenbrainz_derived_review")
            signals.append("listenbrainz_review_candidate")
        else:
            missing.append("no_listenbrainz_review_candidate")
        rows.append(
            EvidenceFrontierRow(
                source_item_id=legacy_row.source_item_id,
                source_external_id=legacy_row.source_external_id,
                seed_name=legacy_row.seed_name,
                normalized_name=legacy_row.normalized_name,
                reconciliation_disposition=legacy_row.reconciliation_disposition,
                public_identities=legacy_row.public_identities,
                musicbrainz_identities=legacy_row.musicbrainz_identities,
                hierarchy=legacy_row.hierarchy,
                hierarchy_candidates=legacy_row.hierarchy_candidates,
                observed_artists=legacy_row.observed_artists,
                listenbrainz_review=review_state,
                peer_count=legacy_row.peer_count,
                source_scope=tuple(source_scope),
                signal_scope=tuple(signals),
                missing_or_abstention_reasons=tuple(missing),
                reconciliation_reason=legacy_row.reconciliation_reason,
            )
        )
    ordered_rows = tuple(sorted(rows, key=lambda row: row.source_item_id))
    overlap = sum(
        bool(row.listenbrainz_review.candidate_count) and bool(row.observed_artists.distinct_total)
        for row in ordered_rows
    )
    review_only = sum(
        bool(row.listenbrainz_review.candidate_count) and not row.observed_artists.distinct_total
        for row in ordered_rows
    )
    direct_only = sum(
        bool(row.observed_artists.distinct_total) and not row.listenbrainz_review.candidate_count
        for row in ordered_rows
    )
    coverage = EvidenceFrontierCoverage.model_validate(
        {
            **source.coverage.model_dump(),
            "listenbrainz_review_candidate_seed_count": sum(
                bool(row.listenbrainz_review.candidate_count) for row in ordered_rows
            ),
            "listenbrainz_review_candidate_count": sum(
                row.listenbrainz_review.candidate_count for row in ordered_rows
            ),
            "listenbrainz_review_overlap_direct_observed_seed_count": overlap,
            "listenbrainz_review_only_seed_count": review_only,
            "direct_observed_only_seed_count": direct_only,
            "direct_observed_or_listenbrainz_review_seed_count": overlap
            + review_only
            + direct_only,
        }
    )
    preliminary = AllSeedEvidenceFrontierArtifact(
        seed_reconciliation_output_sha256=source.seed_reconciliation_output_sha256,
        taxonomy_expansion_output_sha256=source.taxonomy_expansion_output_sha256,
        public_model_input_sha256=source.public_model_input_sha256,
        peer_similarity_output_sha256=source.peer_similarity_output_sha256,
        peer_coverage_output_sha256=source.peer_coverage_output_sha256,
        wikidata_membership_candidate_output_sha256=source.wikidata_membership_candidate_output_sha256,
        wikidata_approved_input_sha256=source.wikidata_approved_input_sha256,
        wikidata_adapter_receipt_output_sha256=source.wikidata_adapter_receipt_output_sha256,
        previous_frontier_output_sha256=source.output_sha256,
        listenbrainz_propagation_output_sha256=listenbrainz_review.propagation_output_sha256,
        listenbrainz_propagation_file_sha256=listenbrainz_review.propagation_file_sha256,
        listenbrainz_propagation_receipt_artifact_sha256=(
            listenbrainz_review.propagation_receipt_artifact_sha256
        ),
        hierarchy_candidate_coverage_output_sha256=source.hierarchy_candidate_coverage_output_sha256,
        hierarchy_candidate_input_state=source.hierarchy_candidate_input_state,
        hierarchy_candidate_output_sha256=source.hierarchy_candidate_output_sha256,
        historical_coordinates_read=False,
        historical_memberships_read=False,
        historical_neighbors_read=False,
        rows=ordered_rows,
        coverage=coverage,
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(
        update={
            "output_sha256": _sha(preliminary.model_dump(mode="json", exclude={"output_sha256"}))
        }
    )


def _catalog_id(node_id: str) -> str:
    prefix = "catalog:"
    if not node_id.startswith(prefix):
        raise ValueError("taxonomy expansion edge is not a catalog node")
    return node_id.removeprefix(prefix)


def build_all_seed_evidence_frontier(  # noqa: C901, PLR0912, PLR0913, PLR0915
    reconciliation: SeedReconciliationArtifact,
    taxonomy: PublicTaxonomyExpansionArtifact,
    public_input: PublicModelInput,
    peers: GenrePeerSimilarityArtifact | FrontierPeerCoverage,
    hierarchy_candidates: GenreHierarchyCandidateArtifact | None = None,
    *,
    listenbrainz_review: ListenBrainzPropagationFrontierSummary,
    v4_baseline: FrontierV4Baseline,
    wikidata_membership_candidate: PublicArtistMembershipCandidateArtifact | None = None,
    wikidata_approved_input: ApprovedPublicMembershipInput | None = None,
    wikidata_adapter_receipt: CertifiedPublicMembershipAdapterReceipt | None = None,
    hierarchy_candidate_coverage: FrontierHierarchyCandidateCoverage | None = None,
) -> AllSeedEvidenceFrontierArtifact:
    """Project sealed public evidence into a complete, review-safe seed ledger."""
    verify_seed_reconciliation(reconciliation)
    verify_public_taxonomy_expansion(taxonomy)
    if listenbrainz_review.output_sha256 != _sha(
        listenbrainz_review.model_dump(mode="json", exclude={"output_sha256"})
    ):
        raise ValueError("ListenBrainz review summary hash does not replay")
    reconciliation_ids = {row.source_item_id for row in reconciliation.dispositions}
    if {row.source_item_id for row in listenbrainz_review.rows} != reconciliation_ids:
        raise ValueError("ListenBrainz review summary does not bind reconciliation seeds")
    if v4_baseline.output_sha256 != _sha(
        v4_baseline.model_dump(mode="json", exclude={"output_sha256"})
    ):
        raise ValueError("v4 frontier baseline hash does not replay")
    peer_coverage_output_sha256: str | None = None
    match peers:
        case GenrePeerSimilarityArtifact():
            if peers.output_sha256 != peer_similarity_output_sha256(peers):
                raise ValueError("peer similarity logical hash does not replay")
            peer_counts = defaultdict(int)
            for neighbor in peers.directional_neighbors:
                peer_counts[neighbor.source_genre_id] += 1
            peer_similarity_sha256 = peers.output_sha256
        case FrontierPeerCoverage():
            expected_coverage_hash = _sha(peers.model_dump(mode="json", exclude={"output_sha256"}))
            if peers.output_sha256 != expected_coverage_hash:
                raise ValueError("peer coverage upgrade hash does not replay")
            peer_counts = {item.source_item_id: item.peer_count for item in peers.counts}
            peer_similarity_sha256 = peers.source_peer_similarity_output_sha256
            peer_coverage_output_sha256 = peers.output_sha256
    if taxonomy.taxonomy_logical_output_sha256 != reconciliation.taxonomy_artifact_sha256:
        raise ValueError("taxonomy expansion does not bind the seed reconciliation taxonomy")
    if {item.genre_id for item in public_input.genres} - {
        row.source_item_id for row in reconciliation.dispositions
    }:
        raise ValueError("public model contains a genre outside the seed reconciliation")
    wikidata_observed: dict[str, set[str]] = defaultdict(set)
    wikidata_candidate_output_sha256: str | None = None
    wikidata_approved_input_sha256: str | None = None
    wikidata_adapter_receipt_output_sha256: str | None = None
    wikidata_inputs = (
        wikidata_membership_candidate,
        wikidata_approved_input,
        wikidata_adapter_receipt,
    )
    if any(item is None for item in wikidata_inputs) and any(
        item is not None for item in wikidata_inputs
    ):
        raise ValueError(
            "Wikidata candidate integration requires candidate, approved input, and receipt"
        )
    if wikidata_membership_candidate is not None:
        if wikidata_approved_input is None or wikidata_adapter_receipt is None:
            raise AssertionError("complete Wikidata input tuple was validated above")
        if (
            public_artist_membership_candidate_output_sha256(wikidata_membership_candidate)
            != wikidata_membership_candidate.output_sha256
        ):
            raise ValueError("Wikidata candidate logical hash does not replay")
        if wikidata_membership_candidate.source_policy.direct_source != "wikidata":
            raise ValueError("Wikidata candidate must select Wikidata as its direct source")
        if wikidata_membership_candidate.source_policy.direct_facet != "wikidata_p136":
            raise ValueError("Wikidata candidate must select the Wikidata P136 direct facet")
        if (
            wikidata_approved_input.public_model_input_sha256
            != wikidata_adapter_receipt.approved_input_sha256
        ):
            raise ValueError("Wikidata approved input does not bind the adapter receipt")
        candidate_input_sha256 = canonical_sha256(
            {
                "name_universe": wikidata_membership_candidate.name_universe.model_dump(
                    mode="json"
                ),
                "approved_public_input": wikidata_approved_input.model_dump(mode="json"),
            }
        )
        if wikidata_membership_candidate.input_sha256 != candidate_input_sha256:
            raise ValueError("Wikidata candidate does not bind the approved input")
        candidate_ids = {
            row.source_item_id for row in wikidata_membership_candidate.name_universe.names
        }
        if candidate_ids != reconciliation_ids:
            raise ValueError("Wikidata candidate name universe does not bind reconciliation seeds")
        for membership in wikidata_membership_candidate.directly_observed_memberships:
            wikidata_observed[membership.source_item_id].add(membership.artist_id)
        if set(wikidata_observed) - reconciliation_ids:
            raise ValueError("Wikidata candidate observation is outside the reconciliation seeds")
        wikidata_candidate_output_sha256 = wikidata_membership_candidate.output_sha256
        wikidata_approved_input_sha256 = wikidata_approved_input.public_model_input_sha256
        wikidata_adapter_receipt_output_sha256 = wikidata_adapter_receipt.output_sha256
    if hierarchy_candidates is not None and hierarchy_candidate_coverage is not None:
        raise ValueError("select either hierarchy candidates or a sealed hierarchy summary")
    candidate_rows_by_seed: dict[str, FrontierHierarchyCandidates] = {}
    candidate_input_state: HierarchyCandidateInputState = "not_provided"
    candidate_output_sha256: str | None = None
    hierarchy_candidate_coverage_output_sha256: str | None = None
    if hierarchy_candidates is not None:
        verify_genre_hierarchy_candidates(hierarchy_candidates)
        if hierarchy_candidates.seed_reconciliation_output_sha256 != reconciliation.output_sha256:
            raise ValueError("hierarchy candidates do not bind the seed reconciliation")
        if hierarchy_candidates.taxonomy_output_sha256 != reconciliation.taxonomy_artifact_sha256:
            raise ValueError("hierarchy candidates do not bind the reconciliation taxonomy")
        if hierarchy_candidates.public_model_input_sha256 != _public_input_hash(public_input):
            raise ValueError("hierarchy candidates do not bind the public model input")
        if hierarchy_candidates.coverage.seed_count != _SEED_COUNT:
            raise ValueError("hierarchy candidates do not cover the complete stable seed universe")
        candidate_rows_by_seed = {
            row.source_item_id: FrontierHierarchyCandidates(
                input_state="verified",
                proposed_edge_count=row.proposed_edge_count,
                accepted_count=row.accepted_count,
                review_count=row.review_count,
                abstained_count=row.abstained_count,
                disposition=row.status,
            )
            for row in hierarchy_candidates.seed_coverage
        }
        reconciliation_ids = {row.source_item_id for row in reconciliation.dispositions}
        if set(candidate_rows_by_seed) != reconciliation_ids:
            raise ValueError("hierarchy candidate seed coverage does not bind reconciliation seeds")
        candidate_input_state = "verified"
        candidate_output_sha256 = hierarchy_candidates.output_sha256
    elif hierarchy_candidate_coverage is not None:
        expected_summary_hash = _sha(
            hierarchy_candidate_coverage.model_dump(mode="json", exclude={"logical_output_sha256"})
        )
        if hierarchy_candidate_coverage.logical_output_sha256 != expected_summary_hash:
            raise ValueError("hierarchy candidate summary hash does not replay")
        reconciliation_ids = {row.source_item_id for row in reconciliation.dispositions}
        candidate_rows_by_seed = {
            row.source_item_id: row.hierarchy_candidates
            for row in hierarchy_candidate_coverage.rows
        }
        if set(candidate_rows_by_seed) != reconciliation_ids:
            raise ValueError("hierarchy candidate summary does not bind reconciliation seeds")
        candidate_input_state = hierarchy_candidate_coverage.input_state
        candidate_output_sha256 = hierarchy_candidate_coverage.output_sha256
        hierarchy_candidate_coverage_output_sha256 = (
            hierarchy_candidate_coverage.logical_output_sha256
        )
    factual_catalogs: dict[str, set[str]] = defaultdict(set)
    review_catalogs: dict[str, set[str]] = defaultdict(set)
    catalog_parents: dict[str, set[str]] = defaultdict(set)
    catalog_children: dict[str, set[str]] = defaultdict(set)
    for edge in taxonomy.edges:
        if edge.kind == "canonical_catalog_identity":
            factual_catalogs[edge.source_node_id.removeprefix("legacy:")].add(
                _catalog_id(edge.target_node_id)
            )
        elif edge.kind in {"compositional_review_anchor", "ambiguous_identity_review_candidate"}:
            review_catalogs[edge.source_node_id.removeprefix("legacy:")].add(
                _catalog_id(edge.target_node_id)
            )
        elif edge.kind == "public_catalog_taxonomy_parent":
            child, parent = _catalog_id(edge.source_node_id), _catalog_id(edge.target_node_id)
            catalog_parents[child].add(parent)
            catalog_children[parent].add(child)
    factual_seeds_by_catalog: dict[str, set[str]] = defaultdict(set)
    for source_id, catalog_ids in factual_catalogs.items():
        for catalog_id in catalog_ids:
            factual_seeds_by_catalog[catalog_id].add(source_id)
    observed: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for membership in public_input.direct_memberships:
        observed[membership.genre_id][membership.facet].add(membership.artist_id)
    listenbrainz_by_seed = {row.source_item_id: row for row in listenbrainz_review.rows}
    rows: list[EvidenceFrontierRow] = []
    for disposition in reconciliation.dispositions:
        source_id = disposition.source_item_id
        factual_parents = {
            seed
            for catalog_id in factual_catalogs[source_id]
            for parent in catalog_parents[catalog_id]
            for seed in factual_seeds_by_catalog[parent]
        }
        factual_children = {
            seed
            for catalog_id in factual_catalogs[source_id]
            for child in catalog_children[catalog_id]
            for seed in factual_seeds_by_catalog[child]
        }
        review_parents = {
            seed
            for catalog_id in review_catalogs[source_id]
            for parent in catalog_parents[catalog_id]
            for seed in factual_seeds_by_catalog[parent]
        }
        review_children = {
            seed
            for catalog_id in review_catalogs[source_id]
            for child in catalog_children[catalog_id]
            for seed in factual_seeds_by_catalog[child]
        }
        artists = observed[source_id]
        wikidata_artists = wikidata_observed[source_id]
        musicbrainz_artists = set().union(artists["musicbrainz_genre"], artists["musicbrainz_tag"])
        facet_total = musicbrainz_artists | wikidata_artists
        hierarchy = FrontierHierarchy(
            factual_catalog_identity_ids=tuple(sorted(factual_catalogs[source_id])),
            review_catalog_candidate_ids=tuple(sorted(review_catalogs[source_id])),
            factual_parent_source_item_ids=tuple(sorted(factual_parents - {source_id})),
            factual_child_source_item_ids=tuple(sorted(factual_children - {source_id})),
            review_parent_source_item_ids=tuple(sorted(review_parents - {source_id})),
            review_child_source_item_ids=tuple(sorted(review_children - {source_id})),
        )
        candidate_row = candidate_rows_by_seed.get(source_id)
        hierarchy_candidate_state = (
            FrontierHierarchyCandidates(
                input_state="not_provided",
                proposed_edge_count=0,
                accepted_count=0,
                review_count=0,
                abstained_count=0,
                disposition="not_provided",
            )
            if candidate_row is None
            else candidate_row
        )
        observed_artists = FrontierObservedArtists(
            musicbrainz_genre=len(artists["musicbrainz_genre"]),
            musicbrainz_tag=len(artists["musicbrainz_tag"]),
            wikidata_p136=len(wikidata_artists),
            distinct_total=len(facet_total),
        )
        listenbrainz_row = listenbrainz_by_seed[source_id]
        listenbrainz_review_state = FrontierListenBrainzReview(
            candidate_count=listenbrainz_row.candidate_count,
            candidate_artist_count=listenbrainz_row.candidate_artist_count,
        )
        signals: list[FrontierSignal] = []
        missing: list[FrontierMissingReason] = []
        if disposition.public_identities:
            signals.append("public_identity")
        else:
            missing.append("no_public_identity")
        if disposition.musicbrainz_identities:
            signals.append("musicbrainz_identity")
        else:
            missing.append("no_musicbrainz_identity")
        if hierarchy.factual_parent_source_item_ids or hierarchy.factual_child_source_item_ids:
            signals.append("factual_hierarchy")
        else:
            missing.append("no_factual_hierarchy")
        if (
            hierarchy.review_parent_source_item_ids
            or hierarchy.review_child_source_item_ids
            or hierarchy.review_catalog_candidate_ids
        ):
            signals.append("review_hierarchy")
        else:
            missing.append("no_review_hierarchy")
        if observed_artists.distinct_total:
            signals.append("direct_observed_membership")
        else:
            missing.append("no_direct_observed_membership")
        if peer_counts[source_id]:
            signals.append("peer_candidate")
        else:
            missing.append("no_peer_candidate")
        if listenbrainz_review_state.candidate_count:
            signals.append("listenbrainz_review_candidate")
        else:
            missing.append("no_listenbrainz_review_candidate")
        if hierarchy_candidate_state.input_state == "not_provided":
            missing.append("hierarchy_candidates_not_provided")
        else:
            if hierarchy_candidate_state.accepted_count:
                signals.append("hierarchy_candidate_accepted")
            if hierarchy_candidate_state.review_count:
                signals.append("hierarchy_candidate_review")
            if hierarchy_candidate_state.abstained_count:
                signals.append("hierarchy_candidate_abstained")
                missing.append("hierarchy_candidate_abstained")
        if disposition.disposition == "ambiguous":
            missing.append("reconciliation_ambiguous")
        if disposition.disposition == "unresolved":
            missing.append("reconciliation_unresolved")
        source_scope: list[FrontierSourceScope] = ["cc0_public_taxonomy"]
        if disposition.musicbrainz_identities or musicbrainz_artists:
            source_scope.append("local_musicbrainz_research")
        if wikidata_artists:
            source_scope.append("cc0_wikidata_membership")
        if listenbrainz_review_state.candidate_count:
            source_scope.append("listenbrainz_derived_review")
        rows.append(
            EvidenceFrontierRow(
                source_item_id=source_id,
                source_external_id=disposition.source_external_id,
                seed_name=disposition.seed_name,
                normalized_name=disposition.normalized_name,
                reconciliation_disposition=disposition.disposition,
                public_identities=disposition.public_identities,
                musicbrainz_identities=disposition.musicbrainz_identities,
                hierarchy=hierarchy,
                hierarchy_candidates=hierarchy_candidate_state,
                observed_artists=observed_artists,
                listenbrainz_review=listenbrainz_review_state,
                peer_count=peer_counts[source_id],
                source_scope=tuple(source_scope),
                signal_scope=tuple(signals),
                missing_or_abstention_reasons=tuple(missing),
                reconciliation_reason=disposition.reason,
            )
        )
    ordered_rows = tuple(sorted(rows, key=lambda row: row.source_item_id))
    counts = {
        state: sum(row.reconciliation_disposition == state for row in ordered_rows)
        for state in (
            "reconciled",
            "public_only",
            "musicbrainz_only",
            "review_only",
            "ambiguous",
            "unresolved",
        )
    }
    coverage = EvidenceFrontierCoverage(
        reconciled_count=counts["reconciled"],
        public_only_count=counts["public_only"],
        musicbrainz_only_count=counts["musicbrainz_only"],
        review_only_count=counts["review_only"],
        ambiguous_count=counts["ambiguous"],
        unresolved_count=counts["unresolved"],
        factual_hierarchy_seed_count=sum(
            bool(
                row.hierarchy.factual_parent_source_item_ids
                or row.hierarchy.factual_child_source_item_ids
            )
            for row in ordered_rows
        ),
        review_hierarchy_seed_count=sum(
            bool(
                row.hierarchy.review_parent_source_item_ids
                or row.hierarchy.review_child_source_item_ids
                or row.hierarchy.review_catalog_candidate_ids
            )
            for row in ordered_rows
        ),
        reconciliation_musicbrainz_identity_seed_count=sum(
            bool(row.musicbrainz_identities) for row in ordered_rows
        ),
        direct_observed_seed_count=sum(
            bool(row.observed_artists.distinct_total) for row in ordered_rows
        ),
        observed_musicbrainz_seed_count=sum(
            bool(row.observed_artists.musicbrainz_genre or row.observed_artists.musicbrainz_tag)
            for row in ordered_rows
        ),
        observed_wikidata_seed_count=sum(
            bool(row.observed_artists.wikidata_p136) for row in ordered_rows
        ),
        observed_musicbrainz_only_seed_count=sum(
            bool(row.observed_artists.musicbrainz_genre or row.observed_artists.musicbrainz_tag)
            and not row.observed_artists.wikidata_p136
            for row in ordered_rows
        ),
        observed_wikidata_only_seed_count=sum(
            bool(row.observed_artists.wikidata_p136)
            and not (row.observed_artists.musicbrainz_genre or row.observed_artists.musicbrainz_tag)
            for row in ordered_rows
        ),
        observed_cross_source_seed_count=sum(
            bool(row.observed_artists.wikidata_p136)
            and bool(row.observed_artists.musicbrainz_genre or row.observed_artists.musicbrainz_tag)
            for row in ordered_rows
        ),
        listenbrainz_review_candidate_seed_count=sum(
            bool(row.listenbrainz_review.candidate_count) for row in ordered_rows
        ),
        listenbrainz_review_candidate_count=sum(
            row.listenbrainz_review.candidate_count for row in ordered_rows
        ),
        listenbrainz_review_overlap_direct_observed_seed_count=sum(
            bool(row.listenbrainz_review.candidate_count)
            and bool(row.observed_artists.distinct_total)
            for row in ordered_rows
        ),
        listenbrainz_review_only_seed_count=sum(
            bool(row.listenbrainz_review.candidate_count)
            and not row.observed_artists.distinct_total
            for row in ordered_rows
        ),
        direct_observed_only_seed_count=sum(
            bool(row.observed_artists.distinct_total)
            and not row.listenbrainz_review.candidate_count
            for row in ordered_rows
        ),
        direct_observed_or_listenbrainz_review_seed_count=sum(
            bool(row.observed_artists.distinct_total or row.listenbrainz_review.candidate_count)
            for row in ordered_rows
        ),
        peer_seed_count=sum(bool(row.peer_count) for row in ordered_rows),
        hierarchy_candidate_input_state=candidate_input_state,
        hierarchy_candidate_count=sum(
            row.proposed_edge_count for row in candidate_rows_by_seed.values()
        ),
        hierarchy_candidate_accepted_count=sum(
            row.accepted_count for row in candidate_rows_by_seed.values()
        ),
        hierarchy_candidate_review_count=sum(
            row.review_count for row in candidate_rows_by_seed.values()
        ),
        hierarchy_candidate_abstained_count=sum(
            row.abstained_count for row in candidate_rows_by_seed.values()
        ),
        hierarchy_candidate_supported_seed_count=sum(
            row.disposition == "supported" for row in candidate_rows_by_seed.values()
        ),
        hierarchy_candidate_review_seed_count=sum(
            row.disposition == "review" for row in candidate_rows_by_seed.values()
        ),
        hierarchy_candidate_abstained_seed_count=sum(
            row.disposition == "abstained" for row in candidate_rows_by_seed.values()
        ),
        hierarchy_candidate_isolated_seed_count=sum(
            row.disposition == "isolated" for row in candidate_rows_by_seed.values()
        ),
    )
    v5_preserved_coverage = (
        coverage.direct_observed_seed_count,
        coverage.observed_musicbrainz_seed_count,
        coverage.observed_wikidata_seed_count,
        coverage.observed_musicbrainz_only_seed_count,
        coverage.observed_wikidata_only_seed_count,
        coverage.observed_cross_source_seed_count,
        coverage.peer_seed_count,
        coverage.hierarchy_candidate_count,
        coverage.hierarchy_candidate_accepted_count,
        coverage.hierarchy_candidate_review_count,
        coverage.hierarchy_candidate_abstained_count,
        coverage.hierarchy_candidate_supported_seed_count,
        coverage.hierarchy_candidate_review_seed_count,
        coverage.hierarchy_candidate_abstained_seed_count,
        coverage.hierarchy_candidate_isolated_seed_count,
    )
    v4_preserved_coverage = (
        v4_baseline.coverage.direct_observed_seed_count,
        v4_baseline.coverage.observed_musicbrainz_seed_count,
        v4_baseline.coverage.observed_wikidata_seed_count,
        v4_baseline.coverage.observed_musicbrainz_only_seed_count,
        v4_baseline.coverage.observed_wikidata_only_seed_count,
        v4_baseline.coverage.observed_cross_source_seed_count,
        v4_baseline.coverage.peer_seed_count,
        v4_baseline.coverage.hierarchy_candidate_count,
        v4_baseline.coverage.hierarchy_candidate_accepted_count,
        v4_baseline.coverage.hierarchy_candidate_review_count,
        v4_baseline.coverage.hierarchy_candidate_abstained_count,
        v4_baseline.coverage.hierarchy_candidate_supported_seed_count,
        v4_baseline.coverage.hierarchy_candidate_review_seed_count,
        v4_baseline.coverage.hierarchy_candidate_abstained_seed_count,
        v4_baseline.coverage.hierarchy_candidate_isolated_seed_count,
    )
    if v5_preserved_coverage != v4_preserved_coverage:
        raise ValueError("v5 frontier must preserve v4 direct, peer, and hierarchy coverage")
    preliminary = AllSeedEvidenceFrontierArtifact(
        seed_reconciliation_output_sha256=reconciliation.output_sha256,
        taxonomy_expansion_output_sha256=taxonomy.output_sha256,
        public_model_input_sha256=_public_input_hash(public_input),
        peer_similarity_output_sha256=peer_similarity_sha256,
        peer_coverage_output_sha256=peer_coverage_output_sha256,
        wikidata_membership_candidate_output_sha256=wikidata_candidate_output_sha256,
        wikidata_approved_input_sha256=wikidata_approved_input_sha256,
        wikidata_adapter_receipt_output_sha256=wikidata_adapter_receipt_output_sha256,
        previous_frontier_output_sha256=v4_baseline.source_frontier_output_sha256,
        listenbrainz_propagation_output_sha256=listenbrainz_review.propagation_output_sha256,
        listenbrainz_propagation_file_sha256=listenbrainz_review.propagation_file_sha256,
        listenbrainz_propagation_receipt_artifact_sha256=(
            listenbrainz_review.propagation_receipt_artifact_sha256
        ),
        hierarchy_candidate_coverage_output_sha256=hierarchy_candidate_coverage_output_sha256,
        hierarchy_candidate_input_state=candidate_input_state,
        hierarchy_candidate_output_sha256=candidate_output_sha256,
        rows=ordered_rows,
        coverage=coverage,
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(
        update={
            "output_sha256": _sha(preliminary.model_dump(mode="json", exclude={"output_sha256"}))
        }
    )


def verify_all_seed_evidence_frontier(
    artifact: AllSeedEvidenceFrontierArtifact,
) -> EvidenceFrontierGate:
    """Verify deterministic content and the non-historical frontier contract."""
    if artifact.output_sha256 != _sha(artifact.model_dump(mode="json", exclude={"output_sha256"})):
        raise ValueError("evidence frontier output hash does not replay")
    return EvidenceFrontierGate(artifact_output_sha256=artifact.output_sha256)


def write_all_seed_evidence_frontier(
    artifact: AllSeedEvidenceFrontierArtifact, path: Path
) -> tuple[str, int]:
    """Atomically persist one verified frontier artifact."""
    verify_all_seed_evidence_frontier(artifact)
    payload = (artifact.model_dump_json(indent=2) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw_path)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return hashlib.sha256(payload).hexdigest(), len(payload)


def publish_all_seed_evidence_frontier(
    artifact: AllSeedEvidenceFrontierArtifact, *, output_path: Path, store: ObjectStore
) -> tuple[EvidenceFrontierReceipt, ObjectWrite]:
    """Publish the verified artifact with its deterministic gate result."""
    gate = verify_all_seed_evidence_frontier(artifact)
    artifact_sha, byte_size = write_all_seed_evidence_frontier(artifact, output_path)
    key = ObjectKey(
        value=f"all-seed-evidence-frontier/{artifact.output_sha256}/{artifact_sha}.json"
    )
    write = store.push(output_path, key)
    if write.sha256 != artifact_sha or write.byte_size != byte_size:
        raise ValueError("object store write does not match evidence frontier")
    return EvidenceFrontierReceipt(
        artifact_sha256=artifact_sha,
        artifact_byte_size=byte_size,
        object_key=key.value,
        logical_output_sha256=artifact.output_sha256,
        gate=gate,
    ), write
