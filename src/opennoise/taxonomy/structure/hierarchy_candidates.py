"""Build public, overlapping genre-hierarchy candidates.

This is a candidate layer, not a replacement for source taxonomy.  It keeps
public taxonomy, lexical review priors, and artist-set asymmetry visible as
separate components.  Parent artist memberships are never copied into child
sets.  Historical H3 inputs are not accepted by this API.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

from pydantic import Field, FiniteFloat, model_validator

from opennoise.models import FrozenModel
from opennoise.models.modeling import PublicModelInput  # noqa: TC001
from opennoise.serving.public.taxonomy_expansion import (
    PublicTaxonomyExpansionArtifact,  # noqa: TC001
)
from opennoise.storage import ObjectKey, ObjectStore, ObjectWrite
from opennoise.taxonomy.relations.expansion import (
    TaxonomyRelationExpansionArtifact,
    verify_taxonomy_relation_expansion,
)
from opennoise.taxonomy.seeds.reconciliation import SeedReconciliationArtifact  # noqa: TC001
from opennoise.taxonomy.seeds.taxonomy import GenreSeedPublicTaxonomyArtifact  # noqa: TC001
from opennoise.types import Sha256  # noqa: TC001

_REVISION: Final = "genre-hierarchy-candidates-v1"
_GATE_REVISION: Final = "genre-hierarchy-candidates-gate-v1"
_RECEIPT_REVISION: Final = "genre-hierarchy-candidates-publication-v1"

type HierarchyStatus = Literal["accepted", "review", "abstained"]
type HierarchyReason = Literal[
    "factual_public_taxonomy",
    "meets_artist_containment_policy",
    "lexical_review_prior",
    "weak_directionality",
    "insufficient_artist_support",
    "no_relation_support",
    "cycle_detected",
]
type HierarchyCoverageStatus = Literal["supported", "review", "abstained", "isolated"]


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _sha(value: object) -> Sha256:
    return hashlib.sha256(_canonical(value)).hexdigest()


class GenreHierarchyCandidatePolicy(FrozenModel):
    """Bounded, deterministic policy for converting public signals to candidates."""

    revision: Literal["genre-hierarchy-candidate-policy-v1"] = "genre-hierarchy-candidate-policy-v1"
    expected_seed_count: int = Field(default=6291, ge=1, le=20_000)
    minimum_child_artist_count: int = Field(default=2, ge=1, le=1_000_000)
    minimum_parent_artist_count: int = Field(default=2, ge=1, le=1_000_000)
    minimum_shared_artist_count: int = Field(default=1, ge=1, le=1_000_000)
    minimum_child_coverage: FiniteFloat = Field(default=0.75, ge=0.0, le=1.0)
    minimum_directionality_gap: FiniteFloat = Field(default=0.10, ge=0.0, le=1.0)
    accepted_score: FiniteFloat = Field(default=0.50, ge=0.0, le=1.0)
    maximum_candidates: int = Field(default=250_000, ge=1, le=2_000_000)


class HierarchyComponent(FrozenModel):
    """One independently auditable signal in a directed edge."""

    raw_value: FiniteFloat = Field(ge=0.0)
    normalized_value: FiniteFloat = Field(ge=0.0, le=1.0)
    evidence_refs: tuple[str, ...] = Field(max_length=128)


class HierarchyScoreComponents(FrozenModel):
    """Keep taxonomy, lexical, containment, and support signals separate."""

    factual_public_taxonomy: HierarchyComponent
    lexical_head_review_prior: HierarchyComponent
    artist_set_containment: HierarchyComponent
    support_distinctness: HierarchyComponent
    child_artist_count: int = Field(ge=0)
    parent_artist_count: int = Field(ge=0)
    shared_artist_count: int = Field(ge=0)
    child_coverage: FiniteFloat = Field(ge=0.0, le=1.0)
    parent_coverage: FiniteFloat = Field(ge=0.0, le=1.0)
    directionality_gap: FiniteFloat = Field(ge=-1.0, le=1.0)


class GenreHierarchyCandidate(FrozenModel):
    """One directed child-to-parent candidate; multiple parents are allowed."""

    child_genre_id: str = Field(min_length=1, max_length=200)
    parent_genre_id: str = Field(min_length=1, max_length=200)
    status: HierarchyStatus
    reason: HierarchyReason
    score: FiniteFloat = Field(ge=0.0, le=1.0)
    components: HierarchyScoreComponents
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def require_direction_and_reason(self) -> GenreHierarchyCandidate:
        """Require a status and reason that agree with the visible signals."""
        if self.child_genre_id == self.parent_genre_id:
            raise ValueError("hierarchy candidates cannot be self edges")
        if self.status == "accepted" and self.reason not in {
            "factual_public_taxonomy",
            "meets_artist_containment_policy",
        }:
            raise ValueError("accepted hierarchy candidates need accepted evidence")
        if self.status == "review" and self.reason not in {
            "lexical_review_prior",
            "weak_directionality",
        }:
            raise ValueError("review hierarchy candidates need review evidence")
        if self.status == "abstained" and self.reason in {
            "factual_public_taxonomy",
            "meets_artist_containment_policy",
        }:
            raise ValueError("abstained hierarchy candidates need weak evidence")
        return self


class GenreHierarchySeedCoverage(FrozenModel):
    """Per-seed accounting, including seeds with no proposed parent."""

    source_item_id: str = Field(min_length=1, max_length=200)
    seed_name: str = Field(min_length=1, max_length=500)
    proposed_edge_count: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    review_count: int = Field(ge=0)
    abstained_count: int = Field(ge=0)
    status: HierarchyCoverageStatus

    @model_validator(mode="after")
    def require_partition(self) -> GenreHierarchySeedCoverage:
        """Ensure each seed's edge outcomes are fully accounted for."""
        if (
            self.proposed_edge_count
            != self.accepted_count + self.review_count + self.abstained_count
        ):
            raise ValueError("per-seed hierarchy counts do not partition candidates")
        if self.proposed_edge_count == 0 and self.status != "isolated":
            raise ValueError("seeds without candidates must be isolated")
        if self.proposed_edge_count > 0 and self.status == "isolated":
            raise ValueError("seeds with candidates cannot be isolated")
        return self


class GenreHierarchyCoverage(FrozenModel):
    """Aggregate coverage and disposition counts for all stable seeds."""

    seed_count: int = Field(ge=1)
    candidate_count: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    review_count: int = Field(ge=0)
    abstained_count: int = Field(ge=0)
    supported_seed_count: int = Field(ge=0)
    review_seed_count: int = Field(ge=0)
    abstained_seed_count: int = Field(ge=0)
    isolated_seed_count: int = Field(ge=0)

    @model_validator(mode="after")
    def require_partition(self) -> GenreHierarchyCoverage:
        """Ensure edge and seed status counts form complete partitions."""
        if self.candidate_count != self.accepted_count + self.review_count + self.abstained_count:
            raise ValueError("hierarchy edge dispositions do not partition candidates")
        if self.seed_count != (
            self.supported_seed_count
            + self.review_seed_count
            + self.abstained_seed_count
            + self.isolated_seed_count
        ):
            raise ValueError("hierarchy seed coverage does not partition seeds")
        return self


class GenreHierarchyCandidateArtifact(FrozenModel):
    """Hash-bound public hierarchy candidates with no inherited memberships."""

    revision: Literal["genre-hierarchy-candidates-v1"] = _REVISION
    seed_reconciliation_output_sha256: Sha256
    taxonomy_output_sha256: Sha256
    taxonomy_relation_expansion_output_sha256: Sha256 | None = None
    public_model_input_sha256: Sha256
    policy_sha256: Sha256
    policy: GenreHierarchyCandidatePolicy
    seed_coverage: tuple[GenreHierarchySeedCoverage, ...] = Field(min_length=1)
    candidates: tuple[GenreHierarchyCandidate, ...]
    coverage: GenreHierarchyCoverage
    historical_data_used_for_construction: Literal[False] = False
    parent_artists_inherited_into_children: Literal[False] = False
    output_sha256: Sha256

    @model_validator(mode="after")
    def require_complete_artifact(self) -> GenreHierarchyCandidateArtifact:
        """Bind hashes and require one coverage row for every stable seed."""
        if _sha(self.policy.model_dump(mode="json")) != self.policy_sha256:
            raise ValueError("hierarchy policy hash does not replay")
        ids = tuple(item.source_item_id for item in self.seed_coverage)
        if len(ids) != len(set(ids)) or len(ids) != self.coverage.seed_count:
            raise ValueError("hierarchy coverage must contain every seed exactly once")
        pairs = tuple((item.child_genre_id, item.parent_genre_id) for item in self.candidates)
        if len(pairs) != len(set(pairs)):
            raise ValueError("hierarchy candidate edges must be unique")
        if len(self.candidates) != self.coverage.candidate_count:
            raise ValueError("hierarchy candidate count does not match coverage")
        return self


class GenreHierarchyCandidateGate(FrozenModel):
    """Publication gate for the candidate artifact."""

    revision: Literal["genre-hierarchy-candidates-gate-v1"] = _GATE_REVISION
    artifact_output_sha256: Sha256
    seed_count: int = Field(ge=1)
    candidate_count: int = Field(ge=0)
    deterministic_replay: Literal[True] = True
    complete_seed_coverage: Literal[True] = True
    acyclic: Literal[True] = True
    no_historical_inputs: Literal[True] = True
    no_parent_artist_inheritance: Literal[True] = True


class GenreHierarchyCandidatePublicationReceipt(FrozenModel):
    """Typed ObjectStore receipt for one immutable artifact."""

    revision: Literal["genre-hierarchy-candidates-publication-v1"] = _RECEIPT_REVISION
    artifact: ObjectWrite
    artifact_sha256: Sha256
    logical_output_sha256: Sha256
    historical_data_used_for_construction: Literal[False] = False


@dataclass
class _Proposal:
    taxonomy_refs: set[str] = field(default_factory=set)
    lexical_refs: set[str] = field(default_factory=set)
    artist_refs: set[str] = field(default_factory=set)
    cycle_detected: bool = False


def _input_hash(value: object) -> Sha256:
    return _sha(value)


def _assert_acyclic(edges: tuple[tuple[str, str], ...]) -> None:
    parents: dict[str, set[str]] = defaultdict(set)
    for child, parent in edges:
        parents[child].add(parent)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise ValueError("hierarchy candidate input contains a cycle")
        if node in visited:
            return
        visiting.add(node)
        for parent in sorted(parents[node]):
            visit(parent)
        visiting.remove(node)
        visited.add(node)

    for node in sorted(parents):
        visit(node)


def _path_exists(outgoing: dict[str, set[str]], start: str, target: str) -> bool:
    """Return whether ``target`` is reachable from ``start`` in the backbone."""
    pending = [start]
    visited: set[str] = set()
    while pending:
        node = pending.pop()
        if node == target:
            return True
        if node in visited:
            continue
        visited.add(node)
        pending.extend(sorted(outgoing[node]))
    return False


def _prioritize_acyclic(proposals: dict[tuple[str, str], _Proposal]) -> None:
    """Keep a deterministic evidence-priority DAG and abstain lower-priority cycles.

    Factual public taxonomy is considered first, then lexical review links, then
    artist-set proposals.  This prevents noisy similarity links from deleting
    factual hierarchy rows while retaining every rejected row for audit.
    """

    def priority(edge: tuple[str, str]) -> tuple[int, str, str]:
        proposal = proposals[edge]
        signal_priority = 0 if proposal.taxonomy_refs else 1 if proposal.lexical_refs else 2
        return signal_priority, edge[0], edge[1]

    outgoing: dict[str, set[str]] = defaultdict(set)
    for edge in sorted(proposals, key=priority):
        child, parent = edge
        if _path_exists(outgoing, parent, child):
            proposals[edge].cycle_detected = True
            continue
        outgoing[child].add(parent)


def _catalog_seed_map(
    taxonomy: GenreSeedPublicTaxonomyArtifact,
) -> dict[str, str]:
    by_catalog: dict[str, set[str]] = defaultdict(set)
    for inference in taxonomy.inferences:
        if inference.status not in {"canonical_exact", "canonical_alias"}:
            continue
        for candidate in inference.exact_candidates:
            by_catalog[candidate.catalog_id].add(inference.source_item_id)
    return {
        catalog_id: next(iter(seed_ids))
        for catalog_id, seed_ids in by_catalog.items()
        if len(seed_ids) == 1
    }


def _proposals_from_taxonomy(
    taxonomy: GenreSeedPublicTaxonomyArtifact,
    catalog_to_seed: dict[str, str],
) -> dict[tuple[str, str], _Proposal]:
    proposals: dict[tuple[str, str], _Proposal] = {}

    def item(child: str, parent: str) -> _Proposal:
        if child == parent:
            return proposals.setdefault((child, parent), _Proposal())
        return proposals.setdefault((child, parent), _Proposal())

    for inference in taxonomy.inferences:
        if inference.status != "anchored_compositional" or inference.anchor is None:
            continue
        child = inference.source_item_id
        anchor_seed = catalog_to_seed.get(inference.anchor.catalog_id)
        if anchor_seed is not None and child != anchor_seed:
            item(child, anchor_seed).lexical_refs.add(
                f"taxonomy:lexical-anchor:{inference.source_item_id}:{inference.anchor.catalog_id}"
            )
        if anchor_seed is None:
            continue
        for ancestor in inference.anchor_ancestors:
            parent = catalog_to_seed.get(ancestor.catalog_id)
            if parent is not None and anchor_seed != parent:
                item(anchor_seed, parent).taxonomy_refs.add(
                    f"taxonomy:public-parent:{inference.anchor.catalog_id}:{ancestor.catalog_id}"
                )
    return proposals


def _proposals_from_expansion(  # noqa: C901
    expansion: PublicTaxonomyExpansionArtifact,
) -> dict[tuple[str, str], _Proposal]:
    """Project the sealed expansion's catalog edges onto stable seed IDs."""
    catalog_to_seeds: dict[str, set[str]] = defaultdict(set)
    for edge in expansion.edges:
        if edge.kind == "canonical_catalog_identity":
            catalog_id = edge.evidence.catalog_parent_id
            if catalog_id is not None and edge.source_node_id.startswith("legacy:"):
                catalog_to_seeds[catalog_id].add(edge.source_node_id.removeprefix("legacy:"))
    catalog_to_seed = {
        catalog_id: next(iter(seed_ids))
        for catalog_id, seed_ids in catalog_to_seeds.items()
        if len(seed_ids) == 1
    }
    proposals: dict[tuple[str, str], _Proposal] = {}
    for edge in expansion.edges:
        if edge.kind == "public_catalog_taxonomy_parent":
            child_catalog = edge.evidence.catalog_child_id
            parent_catalog = edge.evidence.catalog_parent_id
            if child_catalog is None or parent_catalog is None:
                continue
            child = catalog_to_seed.get(child_catalog)
            parent = catalog_to_seed.get(parent_catalog)
            if child is not None and parent is not None and child != parent:
                proposals.setdefault((child, parent), _Proposal()).taxonomy_refs.add(
                    f"taxonomy-expansion:{edge.edge_id}"
                )
        elif edge.kind == "compositional_review_anchor":
            parent_catalog = edge.evidence.catalog_parent_id
            if parent_catalog is None or not edge.source_node_id.startswith("legacy:"):
                continue
            child = edge.source_node_id.removeprefix("legacy:")
            parent = catalog_to_seed.get(parent_catalog)
            if parent is not None and child != parent:
                proposals.setdefault((child, parent), _Proposal()).lexical_refs.add(
                    f"taxonomy-expansion:lexical:{edge.edge_id}"
                )
    return proposals


def _proposals_from_taxonomy_relation_expansion(
    expansion: TaxonomyRelationExpansionArtifact,
) -> dict[tuple[str, str], _Proposal]:
    """Project receipt-verified direct relation facts without name-based joins."""
    proposals: dict[tuple[str, str], _Proposal] = {}
    for edge in expansion.edges:
        if edge.disposition != "accepted_factual":
            continue
        proposal = proposals.setdefault((edge.child_seed_id, edge.parent_seed_id), _Proposal())
        proposal.taxonomy_refs.update(
            f"taxonomy-relation-expansion:{expansion.output_sha256}:{evidence.observation_id}"
            for evidence in edge.factual_evidence
        )
    return proposals


def _proposals_from_artist_sets(
    public_input: PublicModelInput,
    proposals: dict[tuple[str, str], _Proposal],
) -> dict[tuple[str, str], tuple[int, int, int, float, float, float, tuple[str, ...]]]:
    artists_by_genre: dict[str, set[str]] = defaultdict(set)
    refs_by_genre_artist: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in public_input.direct_memberships:
        artists_by_genre[row.genre_id].add(row.artist_id)
        refs_by_genre_artist[(row.genre_id, row.artist_id)].add(row.evidence_ref)
    pairs: dict[tuple[str, str], tuple[int, int, int, float, float, float, tuple[str, ...]]] = {}
    by_artist: dict[str, list[str]] = defaultdict(list)
    for genre, artists in artists_by_genre.items():
        for artist in artists:
            by_artist[artist].append(genre)
    for genres in by_artist.values():
        ordered = sorted(set(genres))
        for index, left in enumerate(ordered):
            for right in ordered[index + 1 :]:
                left_set = artists_by_genre[left]
                right_set = artists_by_genre[right]
                shared = left_set & right_set
                left_coverage = len(shared) / len(left_set) if left_set else 0.0
                right_coverage = len(shared) / len(right_set) if right_set else 0.0
                if left_coverage == right_coverage:
                    continue
                directed = (
                    (left, right, left_coverage, right_coverage)
                    if left_coverage > right_coverage
                    else (right, left, right_coverage, left_coverage)
                )
                for child, parent, child_cov, parent_cov in (directed,):
                    key = (child, parent)
                    candidate = proposals.setdefault(key, _Proposal())
                    candidate.artist_refs.update(
                        ref
                        for artist in shared
                        for ref in (
                            *refs_by_genre_artist[(child, artist)],
                            *refs_by_genre_artist[(parent, artist)],
                        )
                    )
                    pairs[key] = (
                        len(artists_by_genre[child]),
                        len(artists_by_genre[parent]),
                        len(shared),
                        child_cov,
                        parent_cov,
                        child_cov - parent_cov,
                        tuple(sorted(candidate.artist_refs)),
                    )
    return pairs


def _candidate(
    child: str,
    parent: str,
    proposal: _Proposal,
    artist_values: tuple[int, int, int, float, float, float, tuple[str, ...]] | None,
    policy: GenreHierarchyCandidatePolicy,
) -> GenreHierarchyCandidate:
    child_count, parent_count, shared_count, child_cov, parent_cov, gap, artist_refs = (
        artist_values or (0, 0, 0, 0.0, 0.0, 0.0, ())
    )
    artist_refs = tuple(sorted(artist_refs)[:128])
    support = min(shared_count / policy.minimum_shared_artist_count, 1.0)
    distinctness = support * max(0.0, 1.0 - parent_cov)
    containment = child_cov * (0.5 + 0.5 * max(gap, 0.0))
    taxonomy = 1.0 if proposal.taxonomy_refs else 0.0
    lexical = 1.0 if proposal.lexical_refs else 0.0
    score = round(
        min(1.0, 0.40 * taxonomy + 0.15 * lexical + 0.30 * containment + 0.15 * distinctness),
        12,
    )
    enough_support = (
        child_count >= policy.minimum_child_artist_count
        and parent_count >= policy.minimum_parent_artist_count
        and shared_count >= policy.minimum_shared_artist_count
    )
    if proposal.cycle_detected:
        status: HierarchyStatus = "abstained"
        reason: HierarchyReason = "cycle_detected"
    elif proposal.taxonomy_refs:
        status: HierarchyStatus = "accepted"
        reason: HierarchyReason = "factual_public_taxonomy"
    elif (
        enough_support
        and child_cov >= policy.minimum_child_coverage
        and gap >= policy.minimum_directionality_gap
        and score >= policy.accepted_score
    ):
        status = "accepted"
        reason = "meets_artist_containment_policy"
    elif proposal.lexical_refs:
        status = "review"
        reason = "lexical_review_prior"
    elif enough_support or shared_count > 0:
        status = "review"
        reason = "weak_directionality"
    else:
        status = "abstained"
        reason = "insufficient_artist_support" if artist_values else "no_relation_support"
    components = HierarchyScoreComponents(
        factual_public_taxonomy=HierarchyComponent(
            raw_value=taxonomy,
            normalized_value=taxonomy,
            evidence_refs=tuple(sorted(proposal.taxonomy_refs)),
        ),
        lexical_head_review_prior=HierarchyComponent(
            raw_value=lexical,
            normalized_value=lexical,
            evidence_refs=tuple(sorted(proposal.lexical_refs)),
        ),
        artist_set_containment=HierarchyComponent(
            raw_value=containment, normalized_value=containment, evidence_refs=artist_refs
        ),
        support_distinctness=HierarchyComponent(
            raw_value=distinctness, normalized_value=distinctness, evidence_refs=artist_refs
        ),
        child_artist_count=child_count,
        parent_artist_count=parent_count,
        shared_artist_count=shared_count,
        child_coverage=round(child_cov, 12),
        parent_coverage=round(parent_cov, 12),
        directionality_gap=round(gap, 12),
    )
    refs = tuple(
        sorted(set(proposal.taxonomy_refs) | set(proposal.lexical_refs) | set(artist_refs))[:256]
    )
    return GenreHierarchyCandidate(
        child_genre_id=child,
        parent_genre_id=parent,
        status=status,
        reason=reason,
        score=score,
        components=components,
        evidence_refs=refs or (f"candidate:{child}:{parent}",),
    )


def build_genre_hierarchy_candidates(  # noqa: C901, PLR0912, PLR0913
    reconciliation: SeedReconciliationArtifact,
    taxonomy: GenreSeedPublicTaxonomyArtifact,
    public_input: PublicModelInput,
    policy: GenreHierarchyCandidatePolicy | None = None,
    *,
    taxonomy_expansion: PublicTaxonomyExpansionArtifact | None = None,
    taxonomy_relation_expansion: TaxonomyRelationExpansionArtifact | None = None,
    taxonomy_relation_source_store: ObjectStore | None = None,
) -> GenreHierarchyCandidateArtifact:
    """Build deterministic, multi-parent public hierarchy candidates."""
    resolved = policy or GenreHierarchyCandidatePolicy()
    if reconciliation.seed_count != resolved.expected_seed_count:
        raise ValueError("seed reconciliation does not contain the expected stable seed universe")
    if taxonomy.output_sha256 != reconciliation.taxonomy_artifact_sha256:
        raise ValueError("taxonomy and reconciliation artifacts do not refer to the same snapshot")
    if taxonomy_expansion is not None and (
        taxonomy_expansion.taxonomy_artifact_sha256 != reconciliation.taxonomy_artifact_sha256
    ):
        raise ValueError(
            "taxonomy expansion and reconciliation artifacts do not refer to the same snapshot"
        )
    if taxonomy_relation_expansion is not None:
        if taxonomy_relation_source_store is None:
            raise ValueError("taxonomy relation expansion requires its custody object store")
        verify_taxonomy_relation_expansion(
            taxonomy_relation_expansion, source_store=taxonomy_relation_source_store
        )
        if taxonomy_relation_expansion.taxonomy_output_sha256 != taxonomy.output_sha256:
            raise ValueError("taxonomy relation expansion does not match the sealed taxonomy")
    seed_names = {item.source_item_id: item.seed_name for item in reconciliation.dispositions}
    if set(seed_names) != {item.source_item_id for item in taxonomy.inferences}:
        raise ValueError("taxonomy must cover exactly the reconciled seed universe")
    public_ids = {item.genre_id for item in public_input.genres}
    if not public_ids <= seed_names.keys():
        raise ValueError("public model input contains an unknown stable seed ID")
    if taxonomy_expansion is None:
        catalog_to_seed = _catalog_seed_map(taxonomy)
        proposals = _proposals_from_taxonomy(taxonomy, catalog_to_seed)
        taxonomy_output_sha256 = taxonomy.output_sha256
    else:
        if taxonomy_expansion.coverage.legacy_seed_node_count != resolved.expected_seed_count:
            raise ValueError("taxonomy expansion does not cover the expected seed universe")
        proposals = _proposals_from_expansion(taxonomy_expansion)
        taxonomy_output_sha256 = taxonomy_expansion.output_sha256
    if taxonomy_relation_expansion is not None:
        for pair, relation_proposal in _proposals_from_taxonomy_relation_expansion(
            taxonomy_relation_expansion
        ).items():
            proposal = proposals.setdefault(pair, _Proposal())
            proposal.taxonomy_refs.update(relation_proposal.taxonomy_refs)
    artist_values = _proposals_from_artist_sets(public_input, proposals)
    _prioritize_acyclic(proposals)
    if len(proposals) > resolved.maximum_candidates:
        raise ValueError("hierarchy candidate count exceeds policy bound")
    candidates = tuple(
        _candidate(
            child, parent, proposals[(child, parent)], artist_values.get((child, parent)), resolved
        )
        for child, parent in sorted(proposals)
    )
    by_child: dict[str, list[GenreHierarchyCandidate]] = defaultdict(list)
    for candidate in candidates:
        by_child[candidate.child_genre_id].append(candidate)
    seed_coverage: list[GenreHierarchySeedCoverage] = []
    for seed_id in sorted(seed_names):
        rows = by_child.get(seed_id, [])
        accepted = sum(row.status == "accepted" for row in rows)
        review = sum(row.status == "review" for row in rows)
        abstained = sum(row.status == "abstained" for row in rows)
        status: HierarchyCoverageStatus = (
            "isolated"
            if not rows
            else "supported"
            if accepted
            else "review"
            if review
            else "abstained"
        )
        seed_coverage.append(
            GenreHierarchySeedCoverage(
                source_item_id=seed_id,
                seed_name=seed_names[seed_id],
                proposed_edge_count=len(rows),
                accepted_count=accepted,
                review_count=review,
                abstained_count=abstained,
                status=status,
            )
        )
    coverage = GenreHierarchyCoverage(
        seed_count=len(seed_coverage),
        candidate_count=len(candidates),
        accepted_count=sum(row.status == "accepted" for row in candidates),
        review_count=sum(row.status == "review" for row in candidates),
        abstained_count=sum(row.status == "abstained" for row in candidates),
        supported_seed_count=sum(row.status == "supported" for row in seed_coverage),
        review_seed_count=sum(row.status == "review" for row in seed_coverage),
        abstained_seed_count=sum(row.status == "abstained" for row in seed_coverage),
        isolated_seed_count=sum(row.status == "isolated" for row in seed_coverage),
    )
    policy_hash = _sha(resolved.model_dump(mode="json"))
    payload = {
        "revision": _REVISION,
        "seed_reconciliation_output_sha256": reconciliation.output_sha256,
        "taxonomy_output_sha256": taxonomy_output_sha256,
        "taxonomy_relation_expansion_output_sha256": (
            taxonomy_relation_expansion.output_sha256
            if taxonomy_relation_expansion is not None
            else None
        ),
        "public_model_input_sha256": _input_hash(public_input.model_dump(mode="json")),
        "policy_sha256": policy_hash,
        "policy": resolved.model_dump(mode="json"),
        "seed_coverage": [row.model_dump(mode="json") for row in seed_coverage],
        "candidates": [row.model_dump(mode="json") for row in candidates],
        "coverage": coverage.model_dump(mode="json"),
        "historical_data_used_for_construction": False,
        "parent_artists_inherited_into_children": False,
    }
    return GenreHierarchyCandidateArtifact(
        seed_reconciliation_output_sha256=reconciliation.output_sha256,
        taxonomy_output_sha256=taxonomy_output_sha256,
        taxonomy_relation_expansion_output_sha256=(
            taxonomy_relation_expansion.output_sha256
            if taxonomy_relation_expansion is not None
            else None
        ),
        public_model_input_sha256=_input_hash(public_input.model_dump(mode="json")),
        policy_sha256=policy_hash,
        policy=resolved,
        seed_coverage=tuple(seed_coverage),
        candidates=candidates,
        coverage=coverage,
        output_sha256=_sha(payload),
    )


def genre_hierarchy_candidate_output_sha256(artifact: GenreHierarchyCandidateArtifact) -> Sha256:
    """Recompute the logical artifact hash."""
    return _sha(artifact.model_dump(mode="json", exclude={"output_sha256"}))


def verify_genre_hierarchy_candidates(
    artifact: GenreHierarchyCandidateArtifact,
) -> GenreHierarchyCandidateGate:
    """Fail closed before publication."""
    if genre_hierarchy_candidate_output_sha256(artifact) != artifact.output_sha256:
        raise ValueError("hierarchy candidate output hash does not replay")
    _assert_acyclic(
        tuple(
            (row.child_genre_id, row.parent_genre_id)
            for row in artifact.candidates
            if row.status == "accepted"
        )
    )
    return GenreHierarchyCandidateGate(
        artifact_output_sha256=artifact.output_sha256,
        seed_count=artifact.coverage.seed_count,
        candidate_count=artifact.coverage.candidate_count,
    )


def publish_genre_hierarchy_candidates(
    artifact: GenreHierarchyCandidateArtifact,
    *,
    output: Path,
    store: ObjectStore,
) -> GenreHierarchyCandidatePublicationReceipt:
    """Write canonical JSON and publish it through the generic object store."""
    verify_genre_hierarchy_candidates(artifact)
    payload = (artifact.model_dump_json(indent=2) + "\n").encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    artifact_sha = hashlib.sha256(payload).hexdigest()
    object_write = store.push(
        output,
        ObjectKey(value=f"genre-hierarchy-candidates/sha256/{artifact.output_sha256}.json"),
    )
    if object_write.sha256 != artifact_sha or object_write.byte_size != len(payload):
        raise ValueError("object store write does not match hierarchy artifact bytes")
    return GenreHierarchyCandidatePublicationReceipt(
        artifact=object_write,
        artifact_sha256=artifact_sha,
        logical_output_sha256=artifact.output_sha256,
    )
