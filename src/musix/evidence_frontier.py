"""Sealed all-seed evidence frontier for open genre reconstruction."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, model_validator

from musix.genre_hierarchy_candidates import (
    GenreHierarchyCandidateArtifact,
    GenreHierarchySeedCoverage,
    verify_genre_hierarchy_candidates,
)
from musix.models import FrozenModel
from musix.peer_similarity import GenrePeerSimilarityArtifact, peer_similarity_output_sha256
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
    from musix.models.modeling import PublicModelInput

_REVISION: Final = "all-seed-evidence-frontier-v3"
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
]
type HierarchyCandidateInputState = Literal["not_provided", "verified"]
type HierarchyCandidateDisposition = Literal[
    "supported", "review", "abstained", "isolated", "not_provided"
]


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
    peer_count: int = Field(ge=0)
    source_scope: tuple[Literal["cc0_public_taxonomy", "local_musicbrainz_research"], ...]
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
    def _partition(self) -> EvidenceFrontierCoverage:
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

    revision: Literal["all-seed-evidence-frontier-v3"] = _REVISION
    seed_reconciliation_output_sha256: str = Field(pattern=_SHA256)
    taxonomy_expansion_output_sha256: str = Field(pattern=_SHA256)
    public_model_input_sha256: str = Field(pattern=_SHA256)
    peer_similarity_output_sha256: str = Field(pattern=_SHA256)
    hierarchy_candidate_input_state: HierarchyCandidateInputState
    hierarchy_candidate_output_sha256: str | None = Field(default=None, pattern=_SHA256)
    historical_coordinates_read: Literal[False] = False
    historical_memberships_read: Literal[False] = False
    historical_neighbors_read: Literal[False] = False
    rows: tuple[EvidenceFrontierRow, ...] = Field(min_length=_SEED_COUNT, max_length=_SEED_COUNT)
    coverage: EvidenceFrontierCoverage
    output_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _complete(self) -> AllSeedEvidenceFrontierArtifact:  # noqa: C901
        if len({row.source_item_id for row in self.rows}) != _SEED_COUNT:
            raise ValueError("frontier requires exactly one row per stable seed")
        if self.coverage.hierarchy_candidate_input_state != self.hierarchy_candidate_input_state:
            raise ValueError("frontier candidate input state must match coverage")
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


def _public_input_hash(value: PublicModelInput) -> str:
    return _sha(value.model_dump(mode="json"))


def _catalog_id(node_id: str) -> str:
    prefix = "catalog:"
    if not node_id.startswith(prefix):
        raise ValueError("taxonomy expansion edge is not a catalog node")
    return node_id.removeprefix(prefix)


def build_all_seed_evidence_frontier(  # noqa: C901, PLR0912, PLR0915
    reconciliation: SeedReconciliationArtifact,
    taxonomy: PublicTaxonomyExpansionArtifact,
    public_input: PublicModelInput,
    peers: GenrePeerSimilarityArtifact,
    hierarchy_candidates: GenreHierarchyCandidateArtifact | None = None,
) -> AllSeedEvidenceFrontierArtifact:
    """Project sealed public evidence into a complete, review-safe seed ledger."""
    verify_seed_reconciliation(reconciliation)
    verify_public_taxonomy_expansion(taxonomy)
    if peers.output_sha256 != peer_similarity_output_sha256(peers):
        raise ValueError("peer similarity logical hash does not replay")
    if taxonomy.taxonomy_logical_output_sha256 != reconciliation.taxonomy_artifact_sha256:
        raise ValueError("taxonomy expansion does not bind the seed reconciliation taxonomy")
    if {item.genre_id for item in public_input.genres} - {
        row.source_item_id for row in reconciliation.dispositions
    }:
        raise ValueError("public model contains a genre outside the seed reconciliation")
    candidate_rows_by_seed: dict[str, GenreHierarchySeedCoverage] = {}
    candidate_input_state: HierarchyCandidateInputState = "not_provided"
    candidate_output_sha256: str | None = None
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
            row.source_item_id: row for row in hierarchy_candidates.seed_coverage
        }
        reconciliation_ids = {row.source_item_id for row in reconciliation.dispositions}
        if set(candidate_rows_by_seed) != reconciliation_ids:
            raise ValueError("hierarchy candidate seed coverage does not bind reconciliation seeds")
        candidate_input_state = "verified"
        candidate_output_sha256 = hierarchy_candidates.output_sha256
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
    peer_counts: dict[str, int] = defaultdict(int)
    for neighbor in peers.directional_neighbors:
        peer_counts[neighbor.source_genre_id] += 1
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
        facet_total = set().union(*artists.values()) if artists else set()
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
            else FrontierHierarchyCandidates(
                input_state="verified",
                proposed_edge_count=candidate_row.proposed_edge_count,
                accepted_count=candidate_row.accepted_count,
                review_count=candidate_row.review_count,
                abstained_count=candidate_row.abstained_count,
                disposition=candidate_row.status,
            )
        )
        observed_artists = FrontierObservedArtists(
            musicbrainz_genre=len(artists["musicbrainz_genre"]),
            musicbrainz_tag=len(artists["musicbrainz_tag"]),
            wikidata_p136=len(artists["wikidata_p136"]),
            distinct_total=len(facet_total),
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
        source_scope: tuple[Literal["cc0_public_taxonomy", "local_musicbrainz_research"], ...] = (
            ("cc0_public_taxonomy", "local_musicbrainz_research")
            if disposition.musicbrainz_identities or observed_artists.distinct_total
            else ("cc0_public_taxonomy",)
        )
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
                peer_count=peer_counts[source_id],
                source_scope=source_scope,
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
        peer_seed_count=sum(bool(row.peer_count) for row in ordered_rows),
        hierarchy_candidate_input_state=candidate_input_state,
        hierarchy_candidate_count=(
            hierarchy_candidates.coverage.candidate_count if hierarchy_candidates is not None else 0
        ),
        hierarchy_candidate_accepted_count=(
            hierarchy_candidates.coverage.accepted_count if hierarchy_candidates is not None else 0
        ),
        hierarchy_candidate_review_count=(
            hierarchy_candidates.coverage.review_count if hierarchy_candidates is not None else 0
        ),
        hierarchy_candidate_abstained_count=(
            hierarchy_candidates.coverage.abstained_count if hierarchy_candidates is not None else 0
        ),
        hierarchy_candidate_supported_seed_count=(
            hierarchy_candidates.coverage.supported_seed_count
            if hierarchy_candidates is not None
            else 0
        ),
        hierarchy_candidate_review_seed_count=(
            hierarchy_candidates.coverage.review_seed_count
            if hierarchy_candidates is not None
            else 0
        ),
        hierarchy_candidate_abstained_seed_count=(
            hierarchy_candidates.coverage.abstained_seed_count
            if hierarchy_candidates is not None
            else 0
        ),
        hierarchy_candidate_isolated_seed_count=(
            hierarchy_candidates.coverage.isolated_seed_count
            if hierarchy_candidates is not None
            else 0
        ),
    )
    preliminary = AllSeedEvidenceFrontierArtifact(
        seed_reconciliation_output_sha256=reconciliation.output_sha256,
        taxonomy_expansion_output_sha256=taxonomy.output_sha256,
        public_model_input_sha256=_public_input_hash(public_input),
        peer_similarity_output_sha256=peers.output_sha256,
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
