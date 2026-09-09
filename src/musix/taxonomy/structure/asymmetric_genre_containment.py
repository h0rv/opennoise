"""Build directed genre-containment candidates from public immutable evidence.

The public taxonomy supplies the direction (child to parent).  Direct artist
membership observations supply the independent set evidence used to score that
direction.  The builder never edits either input and never treats a review
link, a propagated membership, or a missing observation as a fact.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, FiniteFloat, model_validator

from musix.evidence.reconstruction import ReconstructionInputs  # noqa: TC001
from musix.models import FrozenModel
from musix.models.modeling import (
    DirectMembershipEvidence,
    GenreIdentity,
    PublicArtifact,
    PublicModelInput,
)
from musix.serving.public.artist_membership import (
    PublicArtistMembershipCandidateArtifact,
    verify_public_artist_membership_candidate,
)
from musix.serving.public.taxonomy_expansion import (
    ExpansionEdge,
    PublicTaxonomyExpansionArtifact,
    verify_public_taxonomy_expansion,
)
from musix.storage import ObjectKey, ObjectStore, ObjectWrite
from musix.taxonomy.seeds.taxonomy import InferenceStatus  # noqa: TC001
from musix.taxonomy.seeds.universe import normalize_label
from musix.types import Sha256  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Mapping

_REVISION: Final = "asymmetric-genre-containment-candidate-v1"
_MODEL_ID: Final = "public-asymmetric-genre-containment-v1"
_PUBLICATION_PREFIX: Final = "asymmetric-genre-containment-candidates/sha256"

type ContainmentStatus = Literal["accepted", "review", "abstained"]
type ContainmentReason = Literal[
    "meets_policy",
    "insufficient_artist_membership_evidence",
    "no_shared_artists",
    "weak_child_coverage",
    "weak_directionality",
    "identity_bridge_mismatch",
]
type NameDispositionStatus = Literal["supported", "review", "abstained", "isolated"]
type NameDispositionReason = Literal[
    "accepted_containment_support",
    "weak_directionality_review",
    "insufficient_artist_membership_evidence",
    "no_shared_artists",
    "weak_child_coverage",
    "no_containment_relation",
    "no_public_catalog_identity",
    "ambiguous_public_catalog_identity",
    "identity_bridge_mismatch",
]


def _canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    )


def _sha256(value: object) -> Sha256:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class AsymmetricGenreContainmentPolicy(FrozenModel):
    """A priori, bounded rules for converting set evidence into candidates."""

    revision: Literal["asymmetric-genre-containment-policy-v1"] = (
        "asymmetric-genre-containment-policy-v1"
    )
    model_id: Literal["public-asymmetric-genre-containment-v1"] = _MODEL_ID
    model_version: Literal["1"] = "1"
    minimum_child_artist_count: int = Field(default=2, ge=1, le=1_000_000)
    minimum_parent_artist_count: int = Field(default=2, ge=1, le=1_000_000)
    minimum_shared_artist_count: int = Field(default=1, ge=1, le=1_000_000)
    minimum_child_coverage: FiniteFloat = Field(default=0.75, ge=0.0, le=1.0)
    minimum_directionality_gap: FiniteFloat = Field(default=0.10, ge=0.0, le=1.0)
    maximum_taxonomy_edges: int = Field(default=100_000, ge=1, le=1_000_000)


class ContainmentScoreComponents(FrozenModel):
    """Visible inputs to the asymmetric containment score."""

    child_artist_count: int = Field(ge=0)
    parent_artist_count: int = Field(ge=0)
    shared_artist_count: int = Field(ge=0)
    child_coverage: FiniteFloat = Field(ge=0.0, le=1.0)
    parent_coverage: FiniteFloat = Field(ge=0.0, le=1.0)
    directionality_gap: FiniteFloat = Field(ge=-1.0, le=1.0)
    child_source_diversity: int = Field(ge=0)
    parent_source_diversity: int = Field(ge=0)
    evidence_ref_count: int = Field(ge=0)
    score_formula: Literal["child_coverage_x_half_plus_half_gap"] = (
        "child_coverage_x_half_plus_half_gap"
    )


class ContainmentEvidence(FrozenModel):
    """Provenance for one directed candidate, including all source refs."""

    taxonomy_edge_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    taxonomy_artifact_sha256: Sha256
    taxonomy_logical_output_sha256: Sha256
    public_catalog_sha256: Sha256
    membership_input_sha256: Sha256
    membership_evidence_refs: tuple[str, ...] = Field(max_length=10_000)
    membership_facets: tuple[str, ...] = Field(max_length=8)
    source_artifact_keys: tuple[str, ...] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def require_unique_provenance(self) -> ContainmentEvidence:
        """Do not allow a repeated source reference to inflate support."""
        if len(self.membership_evidence_refs) != len(set(self.membership_evidence_refs)):
            raise ValueError("containment evidence references must be unique")
        if len(self.membership_facets) != len(set(self.membership_facets)):
            raise ValueError("containment evidence facets must be unique")
        if len(self.source_artifact_keys) != len(set(self.source_artifact_keys)):
            raise ValueError("containment source artifacts must be unique")
        return self


class GenreContainmentCandidate(FrozenModel):
    """One directed taxonomy relation with an explicit decision outcome."""

    child_genre_id: str = Field(min_length=1, max_length=300)
    parent_genre_id: str = Field(min_length=1, max_length=300)
    status: ContainmentStatus
    reason: ContainmentReason
    score: FiniteFloat = Field(ge=0.0, le=1.0)
    components: ContainmentScoreComponents
    evidence: ContainmentEvidence

    @model_validator(mode="after")
    def require_direction_and_outcome(self) -> GenreContainmentCandidate:
        """Keep child-to-parent direction and abstentions mechanically visible."""
        if self.child_genre_id == self.parent_genre_id:
            raise ValueError("containment candidates cannot be self relations")
        if self.status == "accepted" and self.reason != "meets_policy":
            raise ValueError("accepted containment candidates require the policy reason")
        if self.status == "abstained" and self.reason in {
            "meets_policy",
            "weak_directionality",
        }:
            raise ValueError("abstained containment candidates require an abstention reason")
        if self.status == "review" and self.reason != "weak_directionality":
            raise ValueError("review containment candidates require weak directionality")
        return self


class ContainmentNameDisposition(FrozenModel):
    """Account for every retained legacy name, including unsupported names."""

    source_item_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=500)
    taxonomy_status: InferenceStatus
    status: NameDispositionStatus
    reason: NameDispositionReason
    catalog_genre_id: str | None = Field(default=None, min_length=1, max_length=300)
    candidate_count: int = Field(ge=0)

    @model_validator(mode="after")
    def require_status_reason(self) -> ContainmentNameDisposition:
        """Keep isolated and unsupported name outcomes explicit."""
        if self.status == "supported" and self.reason != "accepted_containment_support":
            raise ValueError("supported names require accepted containment support")
        if self.status == "review" and self.reason != "weak_directionality_review":
            raise ValueError("review names require a review reason")
        if self.status == "isolated" and self.reason != "no_containment_relation":
            raise ValueError("isolated names require the no-relation reason")
        if self.status == "abstained" and self.reason in {
            "accepted_containment_support",
            "weak_directionality_review",
            "no_containment_relation",
        }:
            raise ValueError("abstained names require an evidence abstention reason")
        return self


class ContainmentCoverage(FrozenModel):
    """Partition every immutable taxonomy edge into one explicit outcome."""

    taxonomy_edge_count: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    review_count: int = Field(ge=0)
    abstained_count: int = Field(ge=0)
    insufficient_artist_membership_evidence_count: int = Field(ge=0)
    no_shared_artists_count: int = Field(ge=0)
    weak_child_coverage_count: int = Field(ge=0)
    identity_bridge_mismatch_count: int = Field(ge=0)
    weak_directionality_count: int = Field(ge=0)
    legacy_seed_count: int = Field(ge=1)
    supported_name_count: int = Field(ge=0)
    review_name_count: int = Field(ge=0)
    abstained_name_count: int = Field(ge=0)
    isolated_name_count: int = Field(ge=0)

    @model_validator(mode="after")
    def require_partition(self) -> ContainmentCoverage:
        """Ensure no taxonomy relation disappears without an outcome."""
        if self.taxonomy_edge_count != (
            self.accepted_count + self.review_count + self.abstained_count
        ):
            raise ValueError("containment coverage does not partition taxonomy edges")
        if self.abstained_count != (
            self.insufficient_artist_membership_evidence_count
            + self.no_shared_artists_count
            + self.weak_child_coverage_count
            + self.identity_bridge_mismatch_count
        ):
            raise ValueError("containment abstentions do not partition abstention reasons")
        if self.review_count != self.weak_directionality_count:
            raise ValueError("containment review count does not match review reason count")
        if self.legacy_seed_count != (
            self.supported_name_count
            + self.review_name_count
            + self.abstained_name_count
            + self.isolated_name_count
        ):
            raise ValueError("legacy name coverage does not partition dispositions")
        return self


class AsymmetricGenreContainmentArtifact(FrozenModel):
    """Replayable public candidate artifact; it is not a membership assertion."""

    revision: Literal["asymmetric-genre-containment-candidate-v1"] = _REVISION
    model_id: Literal["public-asymmetric-genre-containment-v1"] = _MODEL_ID
    model_version: Literal["1"] = "1"
    serving_membership_claimed: Literal[False] = False
    taxonomy_artifact_sha256: Sha256
    taxonomy_logical_output_sha256: Sha256
    membership_input_sha256: Sha256
    policy_sha256: Sha256
    policy: AsymmetricGenreContainmentPolicy
    candidates: tuple[GenreContainmentCandidate, ...]
    legacy_seed_source_item_ids: tuple[str, ...] = Field(min_length=1)
    dispositions: tuple[ContainmentNameDisposition, ...]
    coverage: ContainmentCoverage
    output_sha256: Sha256

    @model_validator(mode="after")
    def require_model_and_unique_pairs(self) -> AsymmetricGenreContainmentArtifact:
        """Bind model identity, source hashes, and one row per taxonomy edge."""
        if self.policy.model_id != self.model_id or self.policy.model_version != self.model_version:
            raise ValueError("containment policy model identity does not match artifact")
        if _sha256(self.policy.model_dump(mode="json")) != self.policy_sha256:
            raise ValueError("containment policy hash does not match policy")
        pairs = tuple((item.child_genre_id, item.parent_genre_id) for item in self.candidates)
        if len(pairs) != len(set(pairs)):
            raise ValueError("containment candidate pairs must be unique")
        if len(self.candidates) != self.coverage.taxonomy_edge_count:
            raise ValueError("containment candidate count does not match coverage")
        disposition_ids = tuple(item.source_item_id for item in self.dispositions)
        if disposition_ids != self.legacy_seed_source_item_ids:
            raise ValueError("dispositions must cover legacy source items in taxonomy order")
        for item in self.candidates:
            if item.evidence.taxonomy_artifact_sha256 != self.taxonomy_artifact_sha256:
                raise ValueError("candidate taxonomy hash does not match artifact")
            if item.evidence.taxonomy_logical_output_sha256 != self.taxonomy_logical_output_sha256:
                raise ValueError("candidate taxonomy output hash does not match artifact")
            if item.evidence.membership_input_sha256 != self.membership_input_sha256:
                raise ValueError("candidate membership hash does not match artifact")
        return self


class AsymmetricGenreContainmentGate(FrozenModel):
    """Fail-closed checks required before an artifact can be published."""

    artifact_output_sha256: Sha256
    taxonomy_edge_count: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    review_count: int = Field(ge=0)
    abstained_count: int = Field(ge=0)
    deterministic_replay: Literal[True] = True
    source_observations_immutable: Literal[True] = True
    taxonomy_direction_preserved: Literal[True] = True
    no_membership_assertion: Literal[True] = True


class AsymmetricGenreContainmentPublicationReceipt(FrozenModel):
    """Bind exact artifact bytes to an immutable object-store object."""

    artifact_sha256: Sha256
    artifact_byte_size: int = Field(gt=0)
    object_key: str = Field(min_length=1)
    logical_output_sha256: Sha256
    gate: AsymmetricGenreContainmentGate


class GenreContainmentBridgeEntry(FrozenModel):
    """One explicit bridge between a local MusicBrainz genre and CC0 genre ID."""

    source_item_id: str = Field(min_length=1, max_length=200)
    musicbrainz_genre_id: str = Field(min_length=1, max_length=300)
    catalog_genre_id: str = Field(min_length=1, max_length=300)
    seed_name: str = Field(min_length=1, max_length=500)
    catalog_name: str = Field(min_length=1, max_length=500)
    evidence_ref: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def require_name_agreement(self) -> GenreContainmentBridgeEntry:
        """Make the cross-snapshot join explicit and name-checked."""
        if normalize_label(self.seed_name) != normalize_label(self.catalog_name):
            raise ValueError("genre bridge names must agree after normalization")
        return self


class GenreContainmentBridge(FrozenModel):
    """Immutable, hashed mapping required before local research IDs may join."""

    revision: Literal["genre-containment-bridge-v1"] = "genre-containment-bridge-v1"
    entries: tuple[GenreContainmentBridgeEntry, ...] = Field(min_length=1, max_length=100_000)
    bridge_sha256: Sha256

    @model_validator(mode="after")
    def require_unique_bridge_keys(self) -> GenreContainmentBridge:
        """Reject QID collisions and bind the bridge rows to their declared hash."""
        source_ids = tuple(item.source_item_id for item in self.entries)
        musicbrainz_ids = tuple(item.musicbrainz_genre_id for item in self.entries)
        catalog_ids = tuple(item.catalog_genre_id for item in self.entries)
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("genre bridge source items must be unique")
        if len(set(musicbrainz_ids)) != len(musicbrainz_ids):
            raise ValueError("genre bridge MusicBrainz genre IDs must be unique")
        if len(set(catalog_ids)) != len(catalog_ids):
            raise ValueError("genre bridge catalog genre IDs must be unique")
        payload = [item.model_dump(mode="json") for item in self.entries]
        if _sha256(payload) != self.bridge_sha256:
            raise ValueError("genre bridge hash does not match normalized entries")
        return self


@dataclass(frozen=True, slots=True)
class _MembershipSet:
    artists: frozenset[str]
    refs_by_artist: Mapping[str, frozenset[str]]
    facets_by_artist: Mapping[str, frozenset[str]]


def _membership_rows(
    value: PublicModelInput | PublicArtistMembershipCandidateArtifact,
) -> tuple[
    tuple[DirectMembershipEvidence, ...],
    Sha256,
    tuple[str, ...],
    Mapping[str, tuple[str, ...]],
]:
    """Read direct public observations from either established artifact boundary."""
    if isinstance(value, PublicModelInput):
        names = {item.genre_id: (item.name,) for item in value.genres}
        return (
            value.direct_memberships,
            _sha256(value.model_dump(mode="json")),
            tuple(sorted(item.artifact_key for item in value.artifacts)),
            names,
        )
    rows: list[DirectMembershipEvidence] = []
    verify_public_artist_membership_candidate(value)
    for candidate in value.directly_observed_memberships:
        for path in candidate.paths:
            for evidence in path.evidence:
                if evidence.facet == "musicbrainz_artist_genre_tag":
                    facet: Literal["musicbrainz_tag", "wikidata_p136"] = "musicbrainz_tag"
                elif evidence.facet == "wikidata_p136":
                    facet = "wikidata_p136"
                else:
                    continue
                if facet:
                    rows.extend(
                        DirectMembershipEvidence(
                            artist_id=candidate.artist_id,
                            genre_id=candidate.genre_id,
                            facet=facet,
                            value=float(evidence.raw_value),
                            evidence_ref=ref,
                        )
                        for ref in evidence.evidence_refs
                    )
    names_by_genre: dict[str, list[str]] = defaultdict(list)
    for disposition in value.dispositions:
        if disposition.genre_id is not None:
            names_by_genre[disposition.genre_id].append(disposition.name)
    return (
        tuple(rows),
        value.output_sha256,
        ("public-artist-membership-candidate",),
        {genre_id: tuple(names) for genre_id, names in names_by_genre.items()},
    )


def _identity_mismatch_genres(
    taxonomy: PublicTaxonomyExpansionArtifact,
    names_by_genre: Mapping[str, tuple[str, ...]],
) -> frozenset[str]:
    """Reject QID-only joins when the two immutable snapshots disagree by name."""
    taxonomy_names = {
        node.catalog_id: normalize_label(node.name)
        for node in taxonomy.nodes
        if node.node_kind == "public_catalog_genre" and node.catalog_id is not None
    }
    return frozenset(
        genre_id
        for genre_id, names in names_by_genre.items()
        if genre_id in taxonomy_names
        and (
            len({normalize_label(name) for name in names}) != 1
            or normalize_label(names[0]) != taxonomy_names[genre_id]
        )
    )


def _sets_by_genre(
    rows: tuple[DirectMembershipEvidence, ...],
) -> dict[str, _MembershipSet]:
    artists: dict[str, set[str]] = defaultdict(set)
    refs: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    facets: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row in rows:
        artists[row.genre_id].add(row.artist_id)
        refs[row.genre_id][row.artist_id].add(row.evidence_ref)
        facets[row.genre_id][row.artist_id].add(row.facet)
    return {
        genre_id: _MembershipSet(
            artists=frozenset(genre_artists),
            refs_by_artist=MappingProxyType(
                {artist: frozenset(values) for artist, values in refs[genre_id].items()}
            ),
            facets_by_artist=MappingProxyType(
                {artist: frozenset(values) for artist, values in facets[genre_id].items()}
            ),
        )
        for genre_id, genre_artists in artists.items()
    }


def _taxonomy_edges(taxonomy: PublicTaxonomyExpansionArtifact) -> tuple[ExpansionEdge, ...]:
    """Yield only factual public child-to-parent edges from the sealed artifact."""
    edges = tuple(
        edge
        for edge in taxonomy.edges
        if edge.kind == "public_catalog_taxonomy_parent"
        and edge.factual_relationship
        and not edge.review_candidate
    )
    adjacent: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        child = edge.evidence.catalog_child_id or edge.source_node_id
        parent = edge.evidence.catalog_parent_id or edge.target_node_id
        adjacent[child].add(parent)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise ValueError("public taxonomy containment input must be acyclic")
        if node in visited:
            return
        visiting.add(node)
        for parent in sorted(adjacent[node]):
            visit(parent)
        visiting.remove(node)
        visited.add(node)

    for node in sorted(adjacent):
        visit(node)
    return tuple(
        sorted(
            edges,
            key=lambda edge: (
                edge.evidence.catalog_child_id or edge.source_node_id,
                edge.evidence.catalog_parent_id or edge.target_node_id,
                edge.edge_id,
            ),
        )
    )


def _candidate(  # noqa: PLR0913
    edge: ExpansionEdge,
    child: _MembershipSet | None,
    parent: _MembershipSet | None,
    *,
    taxonomy: PublicTaxonomyExpansionArtifact,
    membership_hash: Sha256,
    source_artifact_keys: tuple[str, ...],
    policy: AsymmetricGenreContainmentPolicy,
    identity_bridge_mismatch: bool,
) -> GenreContainmentCandidate:
    child_artists = child.artists if child is not None else frozenset()
    parent_artists = parent.artists if parent is not None else frozenset()
    shared = child_artists & parent_artists
    child_count = len(child_artists)
    parent_count = len(parent_artists)
    child_coverage = len(shared) / child_count if child_count else 0.0
    parent_coverage = len(shared) / parent_count if parent_count else 0.0
    gap = child_coverage - parent_coverage
    child_facets = (
        frozenset().union(*(child.facets_by_artist[item] for item in child_artists))
        if child is not None and child_artists
        else frozenset()
    )
    parent_facets = (
        frozenset().union(*(parent.facets_by_artist[item] for item in parent_artists))
        if parent is not None and parent_artists
        else frozenset()
    )
    refs = (
        frozenset().union(*(child.refs_by_artist[item] for item in shared))
        | frozenset().union(*(parent.refs_by_artist[item] for item in shared))
        if shared and child is not None and parent is not None
        else frozenset()
    )
    components = ContainmentScoreComponents(
        child_artist_count=child_count,
        parent_artist_count=parent_count,
        shared_artist_count=len(shared),
        child_coverage=round(child_coverage, 12),
        parent_coverage=round(parent_coverage, 12),
        directionality_gap=round(gap, 12),
        child_source_diversity=len(child_facets),
        parent_source_diversity=len(parent_facets),
        evidence_ref_count=len(refs),
    )
    score = round(child_coverage * (0.5 + 0.5 * max(gap, 0.0)), 12)
    evidence_refs = tuple(sorted(refs))
    if identity_bridge_mismatch:
        status: ContainmentStatus = "abstained"
        reason: ContainmentReason = "identity_bridge_mismatch"
    elif (
        child_count < policy.minimum_child_artist_count
        or parent_count < policy.minimum_parent_artist_count
    ):
        status = "abstained"
        reason = "insufficient_artist_membership_evidence"
    elif len(shared) < policy.minimum_shared_artist_count:
        status = "abstained"
        reason = "no_shared_artists"
    elif child_coverage < policy.minimum_child_coverage:
        status = "abstained"
        reason = "weak_child_coverage"
    elif gap < policy.minimum_directionality_gap:
        status = "review"
        reason = "weak_directionality"
    else:
        status = "accepted"
        reason = "meets_policy"
    return GenreContainmentCandidate(
        child_genre_id=edge.evidence.catalog_child_id or edge.source_node_id,
        parent_genre_id=edge.evidence.catalog_parent_id or edge.target_node_id,
        status=status,
        reason=reason,
        score=score,
        components=components,
        evidence=ContainmentEvidence(
            taxonomy_edge_id=edge.edge_id,
            taxonomy_artifact_sha256=taxonomy.taxonomy_artifact_sha256,
            taxonomy_logical_output_sha256=taxonomy.taxonomy_logical_output_sha256,
            public_catalog_sha256=taxonomy.public_catalog_sha256,
            membership_input_sha256=membership_hash,
            membership_evidence_refs=evidence_refs,
            membership_facets=tuple(sorted(child_facets | parent_facets)),
            source_artifact_keys=source_artifact_keys,
        ),
    )


def build_asymmetric_genre_containment(  # noqa: C901, PLR0912, PLR0915
    taxonomy: PublicTaxonomyExpansionArtifact,
    memberships: PublicModelInput | PublicArtistMembershipCandidateArtifact,
    policy: AsymmetricGenreContainmentPolicy | None = None,
) -> AsymmetricGenreContainmentArtifact:
    """Build one deterministic directed candidate artifact from immutable inputs."""
    policy = policy or AsymmetricGenreContainmentPolicy()
    verify_public_taxonomy_expansion(taxonomy)
    taxonomy_input_hash = _sha256(taxonomy.model_dump(mode="json"))
    taxonomy_edges = _taxonomy_edges(taxonomy)
    if len(taxonomy_edges) > policy.maximum_taxonomy_edges:
        raise ValueError("taxonomy edges exceed containment policy bound")
    rows, membership_hash, input_artifacts, names_by_genre = _membership_rows(memberships)
    incompatible_genres = _identity_mismatch_genres(taxonomy, names_by_genre)
    by_genre = _sets_by_genre(rows)
    candidates = tuple(
        _candidate(
            edge,
            by_genre.get(edge.evidence.catalog_child_id or edge.source_node_id),
            by_genre.get(edge.evidence.catalog_parent_id or edge.target_node_id),
            taxonomy=taxonomy,
            membership_hash=membership_hash,
            source_artifact_keys=input_artifacts,
            policy=policy,
            identity_bridge_mismatch=(
                (edge.evidence.catalog_child_id or edge.source_node_id) in incompatible_genres
                or (edge.evidence.catalog_parent_id or edge.target_node_id) in incompatible_genres
            ),
        )
        for edge in taxonomy_edges
    )
    candidates_by_genre: dict[str, list[GenreContainmentCandidate]] = defaultdict(list)
    for item in candidates:
        candidates_by_genre[item.child_genre_id].append(item)
        candidates_by_genre[item.parent_genre_id].append(item)
    identity_by_legacy: dict[str, tuple[str, ...]] = defaultdict(tuple)
    for edge in taxonomy.edges:
        if edge.kind == "canonical_catalog_identity":
            source = edge.source_node_id.removeprefix("legacy:")
            catalog_id = edge.evidence.catalog_parent_id or edge.target_node_id.removeprefix(
                "catalog:"
            )
            identity_by_legacy[source] = (*identity_by_legacy[source], catalog_id)
    legacy_nodes = tuple(
        sorted(
            (node for node in taxonomy.nodes if node.node_kind == "legacy_name_seed"),
            key=lambda node: node.node_id,
        )
    )
    dispositions: list[ContainmentNameDisposition] = []
    for node in legacy_nodes:
        source_item_id = node.legacy_source_item_id
        if source_item_id is None:
            raise ValueError("legacy taxonomy node is missing its source item ID")
        identities = identity_by_legacy.get(source_item_id, ())
        if not identities:
            review_identity = any(
                edge.source_node_id == node.node_id and edge.review_candidate
                for edge in taxonomy.edges
            )
            reason: NameDispositionReason = (
                "ambiguous_public_catalog_identity"
                if review_identity
                else "no_public_catalog_identity"
            )
            dispositions.append(
                ContainmentNameDisposition(
                    source_item_id=source_item_id,
                    name=node.name,
                    taxonomy_status=node.taxonomy_status or "abstained",
                    status="abstained",
                    reason=reason,
                    candidate_count=0,
                )
            )
            continue
        if len(identities) != 1:
            dispositions.append(
                ContainmentNameDisposition(
                    source_item_id=source_item_id,
                    name=node.name,
                    taxonomy_status=node.taxonomy_status or "ambiguous_exact",
                    status="abstained",
                    reason="ambiguous_public_catalog_identity",
                    catalog_genre_id=identities[0],
                    candidate_count=0,
                )
            )
            continue
        genre_candidates = tuple(
            sorted(
                candidates_by_genre.get(identities[0], ()),
                key=lambda item: item.parent_genre_id,
            )
        )
        if not genre_candidates:
            dispositions.append(
                ContainmentNameDisposition(
                    source_item_id=source_item_id,
                    name=node.name,
                    taxonomy_status=node.taxonomy_status or "abstained",
                    status="isolated",
                    reason="no_containment_relation",
                    catalog_genre_id=identities[0],
                    candidate_count=0,
                )
            )
            continue
        if any(item.status == "accepted" for item in genre_candidates):
            disposition_status: NameDispositionStatus = "supported"
            disposition_reason: NameDispositionReason = "accepted_containment_support"
        elif any(item.status == "review" for item in genre_candidates):
            disposition_status = "review"
            disposition_reason = "weak_directionality_review"
        else:
            disposition_status = "abstained"
            match genre_candidates[0].reason:
                case "insufficient_artist_membership_evidence":
                    disposition_reason = "insufficient_artist_membership_evidence"
                case "no_shared_artists":
                    disposition_reason = "no_shared_artists"
                case "weak_child_coverage":
                    disposition_reason = "weak_child_coverage"
                case "identity_bridge_mismatch":
                    disposition_reason = "identity_bridge_mismatch"
                case _:
                    raise AssertionError("abstained candidate has an unsupported reason")
        dispositions.append(
            ContainmentNameDisposition(
                source_item_id=source_item_id,
                name=node.name,
                taxonomy_status=node.taxonomy_status or "abstained",
                status=disposition_status,
                reason=disposition_reason,
                catalog_genre_id=identities[0],
                candidate_count=len(genre_candidates),
            )
        )

    def reason_count(reason: ContainmentReason) -> int:
        return sum(item.reason == reason for item in candidates)

    coverage = ContainmentCoverage(
        taxonomy_edge_count=len(candidates),
        accepted_count=sum(item.status == "accepted" for item in candidates),
        review_count=sum(item.status == "review" for item in candidates),
        abstained_count=sum(item.status == "abstained" for item in candidates),
        insufficient_artist_membership_evidence_count=reason_count(
            "insufficient_artist_membership_evidence"
        ),
        no_shared_artists_count=reason_count("no_shared_artists"),
        weak_child_coverage_count=reason_count("weak_child_coverage"),
        identity_bridge_mismatch_count=reason_count("identity_bridge_mismatch"),
        weak_directionality_count=reason_count("weak_directionality"),
        legacy_seed_count=len(dispositions),
        supported_name_count=sum(item.status == "supported" for item in dispositions),
        review_name_count=sum(item.status == "review" for item in dispositions),
        abstained_name_count=sum(item.status == "abstained" for item in dispositions),
        isolated_name_count=sum(item.status == "isolated" for item in dispositions),
    )
    policy_hash = _sha256(policy.model_dump(mode="json"))
    payload = {
        "revision": _REVISION,
        "model_id": _MODEL_ID,
        "model_version": "1",
        "serving_membership_claimed": False,
        "taxonomy_artifact_sha256": taxonomy.taxonomy_artifact_sha256,
        "taxonomy_logical_output_sha256": taxonomy.taxonomy_logical_output_sha256,
        "membership_input_sha256": membership_hash,
        "policy_sha256": policy_hash,
        "policy": policy.model_dump(mode="json"),
        "candidates": [item.model_dump(mode="json") for item in candidates],
        "legacy_seed_source_item_ids": [item.source_item_id for item in dispositions],
        "dispositions": [item.model_dump(mode="json") for item in dispositions],
        "coverage": coverage.model_dump(mode="json"),
    }
    if taxonomy_input_hash != _sha256(taxonomy.model_dump(mode="json")):
        raise ValueError("taxonomy source observations changed during containment build")
    if isinstance(memberships, PublicModelInput):
        if membership_hash != _sha256(memberships.model_dump(mode="json")):
            raise ValueError("membership source observations changed during containment build")
    elif membership_hash != memberships.output_sha256:
        raise ValueError("membership candidate source changed during containment build")
    return AsymmetricGenreContainmentArtifact(
        taxonomy_artifact_sha256=taxonomy.taxonomy_artifact_sha256,
        taxonomy_logical_output_sha256=taxonomy.taxonomy_logical_output_sha256,
        membership_input_sha256=membership_hash,
        policy_sha256=policy_hash,
        policy=policy,
        candidates=candidates,
        legacy_seed_source_item_ids=tuple(item.source_item_id for item in dispositions),
        dispositions=tuple(dispositions),
        coverage=coverage,
        output_sha256=_sha256(payload),
    )


def build_asymmetric_genre_containment_from_reconstruction_inputs(
    taxonomy: PublicTaxonomyExpansionArtifact,
    reconstruction: ReconstructionInputs,
    bridge: GenreContainmentBridge,
    policy: AsymmetricGenreContainmentPolicy | None = None,
) -> AsymmetricGenreContainmentArtifact:
    """Adapt local MusicBrainz edges only after an explicit checked seed bridge."""
    if (
        reconstruction.historical_artifact is not None
        or reconstruction.historical_points
        or reconstruction.historical_neighbors
    ):
        raise ValueError("containment construction excludes historical reconstruction observations")
    if any(
        edge.facet not in {"genre", "musicbrainz_genre"} for edge in reconstruction.membership_edges
    ):
        raise ValueError(
            "genre containment construction accepts curated MusicBrainz genre edges only; "
            "tag edges require a separate facet-aware containment model"
        )
    catalog_names = {
        node.catalog_id: node.name
        for node in taxonomy.nodes
        if node.node_kind == "public_catalog_genre" and node.catalog_id is not None
    }
    bridge_by_musicbrainz = {item.musicbrainz_genre_id: item for item in bridge.entries}
    for item in bridge.entries:
        if item.catalog_genre_id not in catalog_names:
            raise ValueError("genre bridge points to a catalog ID absent from taxonomy snapshot")
        if normalize_label(item.catalog_name) != normalize_label(
            catalog_names[item.catalog_genre_id]
        ):
            raise ValueError("genre bridge catalog name does not match taxonomy snapshot")
    rows: list[DirectMembershipEvidence] = []
    for edge in reconstruction.membership_edges:
        matched = bridge_by_musicbrainz.get(edge.genre_id)
        if matched is None:
            matched = bridge_by_musicbrainz.get(
                f"musicbrainz:genre:{edge.genre_id.removeprefix('musicbrainz:genre:')}"
            )
        if matched is None:
            continue
        rows.extend(
            DirectMembershipEvidence(
                artist_id=edge.artist_id,
                genre_id=matched.catalog_genre_id,
                facet="musicbrainz_genre",
                value=float(edge.weight),
                evidence_ref=ref,
            )
            for ref in edge.evidence_refs
        )
    if not rows:
        raise ValueError("genre bridge produced no direct membership evidence")
    genre_ids = tuple(sorted({row.genre_id for row in rows}))
    model_input = PublicModelInput(
        artifacts=(
            PublicArtifact(
                source="musicbrainz",
                snapshot=reconstruction.membership_artifact.revision,
                artifact_key=(
                    f"{reconstruction.membership_artifact.artifact_key}"
                    f"::genre-bridge:{bridge.bridge_sha256}"
                ),
                content_sha256=reconstruction.membership_artifact.content_sha256,
                export_allowed=False,
            ),
        ),
        genres=tuple(
            GenreIdentity(
                genre_id=genre_id,
                name=catalog_names[genre_id],
                evidence_refs=(f"genre-bridge:{bridge.bridge_sha256}",),
            )
            for genre_id in genre_ids
        ),
        direct_memberships=tuple(rows),
    )
    return build_asymmetric_genre_containment(taxonomy, model_input, policy)


def asymmetric_genre_containment_output_sha256(
    artifact: AsymmetricGenreContainmentArtifact,
) -> Sha256:
    """Recompute the logical hash covered by a parsed artifact."""
    payload = artifact.model_dump(mode="json", exclude={"output_sha256"})
    return _sha256(payload)


def verify_asymmetric_genre_containment(
    artifact: AsymmetricGenreContainmentArtifact,
) -> AsymmetricGenreContainmentGate:
    """Fail closed if hashes, direction, or explicit outcomes do not replay."""
    if asymmetric_genre_containment_output_sha256(artifact) != artifact.output_sha256:
        raise ValueError("containment output hash does not replay")
    return AsymmetricGenreContainmentGate(
        artifact_output_sha256=artifact.output_sha256,
        taxonomy_edge_count=artifact.coverage.taxonomy_edge_count,
        accepted_count=artifact.coverage.accepted_count,
        review_count=artifact.coverage.review_count,
        abstained_count=artifact.coverage.abstained_count,
    )


def write_asymmetric_genre_containment(
    artifact: AsymmetricGenreContainmentArtifact,
    *,
    output: Path,
    store: ObjectStore,
) -> AsymmetricGenreContainmentPublicationReceipt:
    """Write canonical bytes and custody them through the shared object store."""
    gate = verify_asymmetric_genre_containment(artifact)
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
    artifact_sha256 = _sha256_bytes(payload)
    key = ObjectKey(value=f"{_PUBLICATION_PREFIX}/{artifact.output_sha256}.json")
    object_write: ObjectWrite = store.push(output, key)
    if object_write.sha256 != artifact_sha256 or object_write.byte_size != len(payload):
        raise ValueError("object store write does not match containment artifact bytes")
    return AsymmetricGenreContainmentPublicationReceipt(
        artifact_sha256=artifact_sha256,
        artifact_byte_size=len(payload),
        object_key=key.value,
        logical_output_sha256=artifact.output_sha256,
        gate=gate,
    )


# Compatibility spellings mirror the existing ``*_candidate`` modules.
AsymmetricGenreContainmentCandidatePolicy = AsymmetricGenreContainmentPolicy
AsymmetricGenreContainmentCandidateArtifact = AsymmetricGenreContainmentArtifact
build_asymmetric_genre_containment_candidate = build_asymmetric_genre_containment
verify_asymmetric_genre_containment_candidate = verify_asymmetric_genre_containment
write_asymmetric_genre_containment_candidate = write_asymmetric_genre_containment
