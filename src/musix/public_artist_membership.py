"""Build a bounded, explainable artist-to-name-universe membership candidate.

This module accepts only public metadata already admitted by the public graph:
direct MusicBrainz/Wikidata evidence selected by policy and privacy-safe
aggregate ListenBrainz co-listens.
The retained name universe is an identity-only input.  It cannot carry artist
assignments, coordinates, rankings, recordings, or audio into this builder.

The output is deliberately a *candidate*, never a serving-model membership.
Direct tags remain direct observations; aggregate paths are separately marked
as candidates and require independent public gold before any promotion claim.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path  # noqa: TC003
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, TypeAdapter, model_validator

from musix.genre_seed_universe import SeedInput, load_seed_input, normalize_label
from musix.models.modeling import PublicModelInput  # noqa: TC001
from musix.storage import ObjectKey, ObjectStore, ObjectWrite
from musix.types import Sha256  # noqa: TC001

_REVISION: Literal["public-artist-membership-candidate-v2"] = (
    "public-artist-membership-candidate-v2"
)
_PUBLICATION_PREFIX = "public-artist-membership-candidates/sha256"

type DirectSource = Literal["musicbrainz", "wikidata"]
type DirectFacet = Literal["musicbrainz_tag", "wikidata_p136"]
type DirectEvidence = tuple[DirectFacet, tuple[str, ...], float]
type DirectSeed = tuple[str, float, tuple[DirectEvidence, ...]]
type CandidateKind = Literal["direct_source_claim", "aggregate_co_listen_candidate"]
type CandidateFacet = Literal[
    "musicbrainz_artist_genre_tag",
    "wikidata_p136",
    "listenbrainz_privacy_safe_aggregate_co_listen",
]
type GenreDispositionStatus = Literal["direct_evidence", "aggregate_candidate", "abstained"]
type GenreAbstentionReason = Literal[
    "no_public_genre_identity",
    "ambiguous_public_genre_identity",
    "no_approved_direct_evidence",
    "no_eligible_aggregate_candidate",
]


class StrictFrozenModel(BaseModel):
    """Use a forbidding Pydantic boundary for reproducible public artifacts."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


def _canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    )


def _sha256(value: object) -> Sha256:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def canonical_sha256(value: object) -> Sha256:
    """Return the public canonical JSON hash used by sealed input artifacts."""
    return _sha256(value)


class NameUniverseEntry(StrictFrozenModel):
    """One opaque, name-only member of the retained 6,291-name universe."""

    source_item_id: str = Field(min_length=1, max_length=200)
    external_id: str = Field(min_length=1, max_length=300)
    name: str = Field(min_length=1, max_length=500)


class NameUniverse(StrictFrozenModel):
    """Prove that only a fixed name vocabulary entered construction."""

    revision: Literal["public-name-universe-v1"] = "public-name-universe-v1"
    source_content_sha256: Sha256
    names: tuple[NameUniverseEntry, ...] = Field(min_length=6291, max_length=6291)
    coordinates_used: Literal[False] = False
    artist_memberships_used: Literal[False] = False
    representatives_used: Literal[False] = False
    recordings_used: Literal[False] = False
    audio_used: Literal[False] = False

    @model_validator(mode="after")
    def require_unique_opaque_names(self) -> NameUniverse:
        """Reject duplicate opaque identifiers before matching public metadata."""
        ids = tuple(item.source_item_id for item in self.names)
        external_ids = tuple(item.external_id for item in self.names)
        names = tuple(item.name for item in self.names)
        if len(ids) != len(set(ids)):
            raise ValueError("name-universe source item IDs must be unique")
        if len(external_ids) != len(set(external_ids)):
            raise ValueError("name-universe external IDs must be unique")
        if len(names) != len(set(names)):
            raise ValueError("name-universe names must be unique")
        return self


def load_name_universe(seed_artifact: Path) -> NameUniverse:
    """Parse only the permitted name projection from an established sealed input."""
    document = TypeAdapter(dict[str, object]).validate_json(seed_artifact.read_bytes())
    embedded = document.get("seed_input")
    # Open construction artifacts contain an already sealed name-only projection.
    # Parsing that object, rather than their nodes or edges, preserves the strict
    # boundary even if the enclosing artifact carries historical graph material.
    seed_input = (
        SeedInput.model_validate(embedded)
        if isinstance(embedded, dict)
        else load_seed_input(seed_artifact)
    )
    return NameUniverse(
        source_content_sha256=seed_input.source_content_sha256,
        names=tuple(
            NameUniverseEntry(
                source_item_id=item.source_item_id,
                external_id=item.source_external_id,
                name=item.name,
            )
            for item in seed_input.names
        ),
    )


class PublicArtistMembershipSourcePolicy(StrictFrozenModel):
    """Declare the only permitted construction sources and bounded thresholds."""

    revision: Literal["public-artist-membership-source-policy-v2"] = (
        "public-artist-membership-source-policy-v2"
    )
    expected_name_count: Literal[6291] = 6291
    direct_source: DirectSource = "musicbrainz"
    direct_facet: DirectFacet = "musicbrainz_tag"
    # A policy may explicitly admit a union of direct facets.  The singular
    # fields remain the compatibility/default spelling for existing callers;
    # when these tuples are populated they are the authoritative union.
    direct_sources: tuple[DirectSource, ...] = ()
    direct_facets: tuple[DirectFacet, ...] = ()
    direct_metadata_publicly_permitted: Literal[True] = True
    direct_metadata_export_allowed: Literal[True] = True
    aggregate_source: Literal["listenbrainz"] = "listenbrainz"
    aggregate_co_listen_publicly_permitted: bool = False
    aggregate_co_listen_export_allowed: bool = False
    include_aggregate_candidates: bool = False
    maximum_hops: Literal[1] = 1
    minimum_listener_day_support: int = Field(default=15, ge=1, le=100_000)
    minimum_supporting_windows: int = Field(default=2, ge=1, le=366)
    max_aggregate_candidates_per_genre: int = Field(default=100, ge=1, le=1_000)
    max_candidate_paths: int = Field(default=2_000_000, ge=1, le=20_000_000)
    historical_artist_memberships_used: Literal[False] = False
    external_gold_used_for_construction: Literal[False] = False
    audio_used_for_construction: Literal[False] = False

    @model_validator(mode="after")
    def require_explicit_aggregate_permission(self) -> PublicArtistMembershipSourcePolicy:
        """Require the same explicit decision for aggregate use and export."""
        permitted = (
            self.aggregate_co_listen_publicly_permitted and self.aggregate_co_listen_export_allowed
        )
        if self.include_aggregate_candidates != permitted:
            raise ValueError(
                "aggregate candidates require explicit public permission and export allowance"
            )
        expected_facet: dict[DirectSource, DirectFacet] = {
            "musicbrainz": "musicbrainz_tag",
            "wikidata": "wikidata_p136",
        }
        sources = self.direct_sources or (self.direct_source,)
        facets = self.direct_facets or (self.direct_facet,)
        if not sources or not facets or len(sources) != len(facets):
            raise ValueError("direct source/facet union must contain paired entries")
        if len(set(sources)) != len(sources) or len(set(facets)) != len(facets):
            raise ValueError("direct source/facet union entries must be unique")
        if any(
            expected_facet[source] != facet for source, facet in zip(sources, facets, strict=True)
        ):
            raise ValueError("direct source and facet must use the declared source mapping")
        return self

    @property
    def allowed_direct_sources(self) -> frozenset[DirectSource]:
        """Return the explicitly permitted direct source families."""
        return frozenset(self.direct_sources or (self.direct_source,))

    @property
    def allowed_direct_facets(self) -> frozenset[DirectFacet]:
        """Return the explicitly permitted direct evidence facets."""
        return frozenset(self.direct_facets or (self.direct_facet,))

    def facet_for_source(self, source: DirectSource) -> DirectFacet:
        """Resolve the direct facet paired with one permitted source."""
        sources = self.direct_sources or (self.direct_source,)
        facets = self.direct_facets or (self.direct_facet,)
        try:
            return facets[sources.index(source)]
        except ValueError as error:
            raise ValueError(f"direct source is not admitted by source policy: {source}") from error


class ApprovedPublicMembershipInput(StrictFrozenModel):
    """Bind exact public-model rows to the row-level export decision that admits them."""

    public_model_input: PublicModelInput
    input_file_sha256: Sha256
    public_model_input_sha256: Sha256
    row_export_policy_sha256: Sha256
    direct_rows_export_allowed: Literal[True] = True
    aggregate_rows_export_allowed: bool = False
    declared_direct_row_count: int = Field(ge=0)
    declared_aggregate_row_count: int = Field(ge=0)

    @model_validator(mode="after")
    def require_complete_exportable_row_binding(self) -> ApprovedPublicMembershipInput:
        """Bind normalized rows, declarations, and row-level export policy exactly."""
        if self.public_model_input_sha256 != _sha256(
            self.public_model_input.model_dump(mode="json")
        ):
            raise ValueError("public-model input hash does not match normalized immutable rows")
        if self.declared_direct_row_count != len(self.public_model_input.direct_memberships):
            raise ValueError("declared direct-row count does not match immutable public input")
        if self.declared_aggregate_row_count != len(self.public_model_input.artist_pairs):
            raise ValueError("declared aggregate-row count does not match immutable public input")
        if self.public_model_input.artist_pairs and not self.aggregate_rows_export_allowed:
            raise ValueError("aggregate rows require an explicit row-level export decision")
        return self


class CandidateEvidence(StrictFrozenModel):
    """One visible evidence facet, with no opaque score contribution."""

    facet: CandidateFacet
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=512)
    raw_value: FiniteFloat = Field(gt=0.0)

    @model_validator(mode="after")
    def require_unique_refs(self) -> CandidateEvidence:
        """Keep an evidence facet from double-counting the same record."""
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("candidate evidence references must be unique")
        return self


class CandidatePath(StrictFrozenModel):
    """One direct observation or one bounded aggregate path."""

    kind: CandidateKind
    seed_artist_id: str = Field(min_length=1, max_length=200)
    listener_day_support: int | None = Field(default=None, gt=0)
    supporting_windows: int | None = Field(default=None, gt=0)
    evidence: tuple[CandidateEvidence, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def require_kind_specific_evidence(self) -> CandidatePath:
        """Require direct anchors for every propagated path."""
        facets = tuple(item.facet for item in self.evidence)
        direct_evidence_facets = {
            "musicbrainz_artist_genre_tag",
            "wikidata_p136",
        }
        if self.kind == "direct_source_claim":
            if self.listener_day_support is not None or self.supporting_windows is not None:
                raise ValueError("direct tag paths cannot contain aggregate support")
            if not set(facets) <= direct_evidence_facets or not set(facets):
                raise ValueError("direct paths require typed direct evidence facets")
        elif (
            self.listener_day_support is None
            or self.supporting_windows is None
            or not (set(facets) - {"listenbrainz_privacy_safe_aggregate_co_listen"})
            <= direct_evidence_facets
            or not set(facets) & direct_evidence_facets
            or "listenbrainz_privacy_safe_aggregate_co_listen" not in facets
        ):
            raise ValueError("aggregate paths require direct and aggregate evidence facets")
        return self


class ArtistGenreMembershipCandidate(StrictFrozenModel):
    """One explainable candidate, kept distinct from an asserted membership."""

    artist_id: str = Field(min_length=1, max_length=200)
    genre_id: str = Field(min_length=1, max_length=200)
    source_item_id: str = Field(min_length=1, max_length=200)
    kind: CandidateKind
    score: FiniteFloat = Field(gt=0.0, le=1.0)
    paths: tuple[CandidatePath, ...] = Field(min_length=1, max_length=10_000)


class GenreDisposition(StrictFrozenModel):
    """Give every retained name a direct, aggregate, or explicit abstention outcome."""

    source_item_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=500)
    genre_id: str | None = Field(default=None, min_length=1, max_length=200)
    status: GenreDispositionStatus
    abstention_reason: GenreAbstentionReason | None = None
    direct_candidate_count: int = Field(ge=0)
    aggregate_candidate_count: int = Field(ge=0)

    @model_validator(mode="after")
    def require_complete_disposition(self) -> GenreDisposition:
        """Keep direct, propagated, and abstained states disjoint."""
        has_direct = self.direct_candidate_count > 0
        has_aggregate = self.aggregate_candidate_count > 0
        if self.status == "direct_evidence" and (
            self.genre_id is None or not has_direct or self.abstention_reason is not None
        ):
            raise ValueError("direct dispositions require direct candidates and no abstention")
        if self.status == "aggregate_candidate" and (
            self.genre_id is None
            or has_direct
            or not has_aggregate
            or self.abstention_reason is not None
        ):
            raise ValueError("aggregate dispositions require only aggregate candidates")
        if self.status == "abstained" and self.abstention_reason is None:
            raise ValueError("abstained dispositions require an explicit reason")
        if self.status == "abstained" and (has_direct or has_aggregate):
            raise ValueError("abstained dispositions cannot have candidates")
        return self


class CandidateCoverage(StrictFrozenModel):
    """Make full-universe coverage and abstention denominators inspectable."""

    name_count: Literal[6291] = 6291
    direct_candidate_count: int = Field(ge=0)
    aggregate_candidate_count: int = Field(ge=0)
    direct_genre_count: int = Field(ge=0)
    aggregate_only_genre_count: int = Field(ge=0)
    abstained_genre_count: int = Field(ge=0)
    no_public_genre_identity_count: int = Field(ge=0)
    ambiguous_public_genre_identity_count: int = Field(ge=0)
    no_approved_direct_evidence_count: int = Field(ge=0)
    no_eligible_aggregate_candidate_count: int = Field(ge=0)
    examined_candidate_path_count: int = Field(ge=0)

    @model_validator(mode="after")
    def require_name_partition(self) -> CandidateCoverage:
        """Prove all retained names and abstention reasons have one outcome."""
        if self.name_count != (
            self.direct_genre_count + self.aggregate_only_genre_count + self.abstained_genre_count
        ):
            raise ValueError("candidate coverage does not partition the name universe")
        if self.abstained_genre_count != (
            self.no_public_genre_identity_count
            + self.ambiguous_public_genre_identity_count
            + self.no_approved_direct_evidence_count
            + self.no_eligible_aggregate_candidate_count
        ):
            raise ValueError("candidate abstentions do not partition abstained names")
        return self


class PublicArtistMembershipCandidateArtifact(StrictFrozenModel):
    """Sealed public-input candidate with no quality or serving claim."""

    revision: Literal["public-artist-membership-candidate-v2"] = _REVISION
    non_production_candidate: Literal[True] = True
    serving_membership_claimed: Literal[False] = False
    quality_claim: Literal["not_evaluated_without_independent_public_gold"] = (
        "not_evaluated_without_independent_public_gold"
    )
    input_sha256: Sha256
    policy_sha256: Sha256
    output_sha256: Sha256
    name_universe: NameUniverse
    source_policy: PublicArtistMembershipSourcePolicy
    directly_observed_memberships: tuple[ArtistGenreMembershipCandidate, ...]
    propagated_candidates: tuple[ArtistGenreMembershipCandidate, ...]
    dispositions: tuple[GenreDisposition, ...] = Field(min_length=6291, max_length=6291)
    coverage: CandidateCoverage

    @model_validator(mode="after")
    def require_ordered_complete_artifact(self) -> PublicArtistMembershipCandidateArtifact:
        """Reject reordered or state-overlapping parsed artifacts."""
        disposition_ids = tuple(item.source_item_id for item in self.dispositions)
        universe_ids = tuple(item.source_item_id for item in self.name_universe.names)
        if disposition_ids != universe_ids:
            raise ValueError("dispositions must preserve the complete name-universe order")
        if any(item.kind != "direct_source_claim" for item in self.directly_observed_memberships):
            raise ValueError("directly observed memberships must contain direct observations")
        if any(item.kind != "aggregate_co_listen_candidate" for item in self.propagated_candidates):
            raise ValueError("propagated candidates must contain one-hop aggregate paths")
        memberships = (*self.directly_observed_memberships, *self.propagated_candidates)
        keys = tuple((item.artist_id, item.genre_id) for item in memberships)
        if len(keys) != len(set(keys)):
            raise ValueError(
                "artist-to-genre entries must be disjoint across direct and propagated states"
            )
        return self


class PublicArtistMembershipPublication(StrictFrozenModel):
    """Bind a local file and immutable object-store copy to one sealed artifact."""

    artifact_output_sha256: Sha256
    artifact_file_sha256: Sha256
    artifact_object: ObjectWrite

    @model_validator(mode="after")
    def require_content_addressed_object(self) -> PublicArtistMembershipPublication:
        """Bind local candidate bytes to the expected immutable object key."""
        expected = f"{_PUBLICATION_PREFIX}/{self.artifact_output_sha256}.json"
        if self.artifact_object.key.value != expected:
            raise ValueError("candidate object key must use the logical output hash")
        if self.artifact_object.sha256 != self.artifact_file_sha256:
            raise ValueError("candidate object checksum must match written artifact bytes")
        return self


class IndependentPublicGoldSource(StrictFrozenModel):
    """Declare a genuinely independent public reference before promotion is considered."""

    source_ref: str = Field(min_length=1, max_length=500)
    records_sha256: Sha256
    independent_of_construction: Literal[True] = True
    excludes_musicbrainz_tags: Literal[True] = True
    excludes_listenbrainz_aggregate_signals: Literal[True] = True
    excludes_historical_artist_memberships: Literal[True] = True


class IndependentPublicGoldLabel(StrictFrozenModel):
    """One positive or negative independently sourced evaluation label."""

    artist_id: str = Field(min_length=1, max_length=200)
    genre_id: str = Field(min_length=1, max_length=200)
    is_member: bool


class IndependentPublicGoldSet(StrictFrozenModel):
    """A bounded independently sourced gold set, parsed once at the gate boundary."""

    revision: Literal["independent-public-artist-membership-gold-v1"] = (
        "independent-public-artist-membership-gold-v1"
    )
    source: IndependentPublicGoldSource
    labels: tuple[IndependentPublicGoldLabel, ...] = Field(min_length=1, max_length=100_000)

    @model_validator(mode="after")
    def require_unique_hashed_labels(self) -> IndependentPublicGoldSet:
        """Require deterministic ordering and a hash over the complete gold set."""
        keys = tuple((item.artist_id, item.genre_id) for item in self.labels)
        if len(keys) != len(set(keys)):
            raise ValueError("independent gold labels must be unique")
        if keys != tuple(sorted(keys)):
            raise ValueError("independent gold labels must be sorted by artist and genre")
        digest = _sha256([item.model_dump(mode="json") for item in self.labels])
        if digest != self.source.records_sha256:
            raise ValueError("independent gold record hash does not match normalized labels")
        return self


class PromotionPolicy(StrictFrozenModel):
    """Set a conservative threshold without using gold labels in construction."""

    revision: Literal["public-artist-membership-promotion-policy-v1"] = (
        "public-artist-membership-promotion-policy-v1"
    )
    minimum_labeled_candidates: int = Field(default=100, ge=1, le=100_000)
    minimum_precision: FiniteFloat = Field(default=0.9, ge=0.0, le=1.0)
    minimum_recall: FiniteFloat = Field(default=0.5, ge=0.0, le=1.0)


class PromotionGateReport(StrictFrozenModel):
    """State whether promotion is allowed, never inferring quality from absence of gold."""

    revision: Literal["public-artist-membership-promotion-gate-v1"] = (
        "public-artist-membership-promotion-gate-v1"
    )
    artifact_output_sha256: Sha256
    policy_sha256: Sha256
    independent_gold_supplied: bool
    quality_claim: Literal[
        "not_evaluated_without_independent_public_gold", "independent_public_gold_evaluated"
    ]
    evaluation_scope: Literal["candidate_pairs_vs_all_independent_positive_labels"] = (
        "candidate_pairs_vs_all_independent_positive_labels"
    )
    labeled_candidate_count: int = Field(ge=0)
    unlabeled_candidate_count: int = Field(ge=0)
    independent_positive_label_count: int = Field(ge=0)
    true_positive_count: int = Field(ge=0)
    false_positive_count: int = Field(ge=0)
    false_negative_count: int = Field(ge=0)
    precision: FiniteFloat | None = Field(default=None, ge=0.0, le=1.0)
    recall: FiniteFloat | None = Field(default=None, ge=0.0, le=1.0)
    promotion_eligible: bool
    failures: tuple[str, ...]


class PublicArtistMembershipPromotionError(RuntimeError):
    """Raise when a candidate has not met the independent-gold promotion gate."""


def _require_public_inputs(  # noqa: C901
    name_universe: NameUniverse,
    approved_input: ApprovedPublicMembershipInput,
    policy: PublicArtistMembershipSourcePolicy,
) -> None:
    inputs = approved_input.public_model_input
    if len(name_universe.names) != policy.expected_name_count:
        raise ValueError("name universe does not match the fixed public candidate scope")
    sources = {item.source for item in inputs.artifacts}
    allowed: set[str] = set(policy.allowed_direct_sources)
    if policy.include_aggregate_candidates:
        allowed.add(policy.aggregate_source)
    if not sources <= allowed:
        raise ValueError("public membership input includes a source outside source policy")
    if not all(item.export_allowed for item in inputs.artifacts):
        raise ValueError("public membership input includes a non-exportable artifact")
    for item in inputs.direct_memberships:
        _require_candidate_direct_facet(item.facet)
    if any(item.facet not in policy.allowed_direct_facets for item in inputs.direct_memberships):
        raise ValueError("direct evidence includes a facet outside source policy")
    for facet in {item.facet for item in inputs.direct_memberships}:
        source = "musicbrainz" if facet == "musicbrainz_tag" else "wikidata"
        if source not in sources:
            raise ValueError("direct evidence requires its declared direct-source artifact")
    if inputs.artist_pairs and not policy.include_aggregate_candidates:
        raise ValueError("aggregate evidence is present but aggregate candidates are not permitted")
    if inputs.artist_pairs and policy.aggregate_source not in sources:
        raise ValueError("aggregate evidence requires its declared ListenBrainz artifact")


def _matched_genres(
    name_universe: NameUniverse, inputs: PublicModelInput
) -> dict[str, tuple[str, ...]]:
    by_name: dict[str, list[str]] = defaultdict(list)
    for item in inputs.genres:
        by_name[normalize_label(item.name)].append(item.genre_id)
    return {
        entry.source_item_id: tuple(sorted(by_name.get(normalize_label(entry.name), ())))
        for entry in name_universe.names
    }


def _unambiguous_genre_owners(
    matched: dict[str, tuple[str, ...]],
) -> tuple[dict[str, str], frozenset[str]]:
    """Reject both one-to-many identity matches and many-name normalized collisions."""
    owners: dict[str, list[str]] = defaultdict(list)
    for source_item_id, genre_ids in matched.items():
        if len(genre_ids) == 1:
            owners[genre_ids[0]].append(source_item_id)
    ambiguous_items = frozenset(
        source_item_id
        for source_item_id, genre_ids in matched.items()
        if len(genre_ids) > 1 or (len(genre_ids) == 1 and len(owners[genre_ids[0]]) > 1)
    )
    return (
        {
            genre_id: source_item_ids[0]
            for genre_id, source_item_ids in owners.items()
            if len(source_item_ids) == 1
        },
        ambiguous_items,
    )


def _direct_candidate_evidence_facet(facet: DirectFacet) -> CandidateFacet:
    return "musicbrainz_artist_genre_tag" if facet == "musicbrainz_tag" else "wikidata_p136"


def _require_candidate_direct_facet(facet: str) -> DirectFacet:
    """Admit only the facets this candidate artifact models."""
    if facet == "musicbrainz_tag":
        return "musicbrainz_tag"
    if facet == "wikidata_p136":
        return "wikidata_p136"
    raise ValueError(
        "musicbrainz_genre evidence is not admitted by the artist-membership candidate"
    )


def _direct_candidates(
    matched: dict[str, tuple[str, ...]],
    inputs: PublicModelInput,
) -> tuple[
    dict[str, list[ArtistGenreMembershipCandidate]],
    dict[str, list[DirectSeed]],
]:
    source_item_for_genre, _ambiguous_items = _unambiguous_genre_owners(matched)
    raw: dict[tuple[str, str], float] = defaultdict(float)
    refs: dict[tuple[str, str, DirectFacet], set[str]] = defaultdict(set)
    facet_values: dict[tuple[str, str, DirectFacet], float] = defaultdict(float)
    for evidence in inputs.direct_memberships:
        if evidence.genre_id not in source_item_for_genre:
            continue
        key = (evidence.artist_id, evidence.genre_id)
        raw[key] += float(evidence.value)
        direct_facet = _require_candidate_direct_facet(evidence.facet)
        refs[(*key, direct_facet)].add(evidence.evidence_ref)
        facet_values[(*key, direct_facet)] += float(evidence.value)
    maxima: dict[str, float] = defaultdict(float)
    for (_artist_id, genre_id), value in raw.items():
        maxima[genre_id] = max(maxima[genre_id], value)
    candidates: dict[str, list[ArtistGenreMembershipCandidate]] = defaultdict(list)
    seeds: dict[str, list[DirectSeed]] = defaultdict(list)
    for (artist_id, genre_id), value in sorted(raw.items()):
        source_item_id = source_item_for_genre[genre_id]
        pair_facets = sorted(
            direct_facet
            for candidate_artist, candidate_genre, direct_facet in facet_values
            if candidate_artist == artist_id and candidate_genre == genre_id
        )
        direct_evidence = tuple(
            (
                direct_facet,
                tuple(sorted(refs[(artist_id, genre_id, direct_facet)])),
                facet_values[(artist_id, genre_id, direct_facet)],
            )
            for direct_facet in pair_facets
        )
        evidence = tuple(
            CandidateEvidence(
                facet=_direct_candidate_evidence_facet(direct_facet),
                evidence_refs=evidence_refs,
                raw_value=value,
            )
            for direct_facet, evidence_refs, value in direct_evidence
        )
        candidates[source_item_id].append(
            ArtistGenreMembershipCandidate(
                artist_id=artist_id,
                genre_id=genre_id,
                source_item_id=source_item_id,
                kind="direct_source_claim",
                score=round(value / maxima[genre_id], 12),
                paths=(
                    CandidatePath(
                        kind="direct_source_claim",
                        seed_artist_id=artist_id,
                        evidence=evidence,
                    ),
                ),
            )
        )
        seeds[artist_id].append((genre_id, value, direct_evidence))
    return candidates, seeds


def _aggregate_candidates(  # noqa: C901
    *,
    direct: dict[str, list[ArtistGenreMembershipCandidate]],
    seeds: dict[str, list[DirectSeed]],
    matched: dict[str, tuple[str, ...]],
    inputs: PublicModelInput,
    policy: PublicArtistMembershipSourcePolicy,
) -> tuple[dict[str, list[ArtistGenreMembershipCandidate]], int]:
    if not policy.include_aggregate_candidates:
        return defaultdict(list), 0
    source_item_for_genre, _ambiguous_items = _unambiguous_genre_owners(matched)
    direct_pairs = {
        (candidate.artist_id, candidate.genre_id)
        for items in direct.values()
        for candidate in items
    }
    raw: dict[tuple[str, str], float] = defaultdict(float)
    paths: dict[tuple[str, str], list[CandidatePath]] = defaultdict(list)
    examined = 0
    for pair in inputs.artist_pairs:
        if (
            pair.listener_day_support < policy.minimum_listener_day_support
            or pair.supporting_windows < policy.minimum_supporting_windows
        ):
            continue
        edge = math.log1p(pair.listener_day_support)
        for target, seed_artist in (
            (pair.left_artist_id, pair.right_artist_id),
            (pair.right_artist_id, pair.left_artist_id),
        ):
            for genre_id, tag_value, direct_evidence in seeds.get(seed_artist, ()):
                examined += 1
                if examined > policy.max_candidate_paths:
                    raise ValueError("aggregate candidate paths exceed source-policy bound")
                if (target, genre_id) in direct_pairs:
                    continue
                key = (target, genre_id)
                raw[key] += edge * tag_value
                paths[key].append(
                    CandidatePath(
                        kind="aggregate_co_listen_candidate",
                        seed_artist_id=seed_artist,
                        listener_day_support=pair.listener_day_support,
                        supporting_windows=pair.supporting_windows,
                        evidence=(
                            *tuple(
                                CandidateEvidence(
                                    facet=_direct_candidate_evidence_facet(direct_facet),
                                    evidence_refs=tag_refs,
                                    raw_value=facet_value,
                                )
                                for direct_facet, tag_refs, facet_value in direct_evidence
                            ),
                            CandidateEvidence(
                                facet="listenbrainz_privacy_safe_aggregate_co_listen",
                                evidence_refs=pair.evidence_refs,
                                raw_value=float(pair.listener_day_support),
                            ),
                        ),
                    )
                )
    maxima: dict[str, float] = defaultdict(float)
    for (_artist_id, genre_id), value in raw.items():
        maxima[genre_id] = max(maxima[genre_id], value)
    by_source_item: dict[str, list[ArtistGenreMembershipCandidate]] = defaultdict(list)
    by_genre: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for (artist_id, genre_id), value in raw.items():
        by_genre[genre_id].append((artist_id, value))
    for genre_id, values in sorted(by_genre.items()):
        source_item_id = source_item_for_genre[genre_id]
        for artist_id, value in sorted(values, key=lambda item: (-item[1], item[0]))[
            : policy.max_aggregate_candidates_per_genre
        ]:
            by_source_item[source_item_id].append(
                ArtistGenreMembershipCandidate(
                    artist_id=artist_id,
                    genre_id=genre_id,
                    source_item_id=source_item_id,
                    kind="aggregate_co_listen_candidate",
                    score=round(value / maxima[genre_id], 12),
                    paths=tuple(
                        sorted(
                            paths[(artist_id, genre_id)],
                            key=lambda item: (
                                item.seed_artist_id,
                                item.listener_day_support or 0,
                                item.evidence[-1].evidence_refs,
                            ),
                        )
                    ),
                )
            )
    return by_source_item, examined


def build_public_artist_membership_candidate(
    name_universe: NameUniverse,
    approved_input: ApprovedPublicMembershipInput,
    policy: PublicArtistMembershipSourcePolicy,
) -> PublicArtistMembershipCandidateArtifact:
    """Build the one deterministic candidate without gold labels or audio inputs."""
    _require_public_inputs(name_universe, approved_input, policy)
    inputs = approved_input.public_model_input
    matched = _matched_genres(name_universe, inputs)
    _source_item_for_genre, ambiguous_items = _unambiguous_genre_owners(matched)
    direct, seeds = _direct_candidates(matched, inputs)
    aggregate, examined = _aggregate_candidates(
        direct=direct,
        seeds=seeds,
        matched=matched,
        inputs=inputs,
        policy=policy,
    )
    directly_observed = tuple(
        sorted(
            (candidate for items in direct.values() for candidate in items),
            key=lambda item: (item.source_item_id, item.artist_id),
        )
    )
    propagated = tuple(
        sorted(
            (candidate for items in aggregate.values() for candidate in items),
            key=lambda item: (item.source_item_id, item.artist_id),
        )
    )
    dispositions: list[GenreDisposition] = []
    reasons: dict[GenreAbstentionReason, int] = defaultdict(int)
    for entry in name_universe.names:
        genre_ids = matched[entry.source_item_id]
        direct_count = len(direct[entry.source_item_id])
        aggregate_count = len(aggregate[entry.source_item_id])
        if not genre_ids:
            reason: GenreAbstentionReason = "no_public_genre_identity"
            reasons[reason] += 1
            dispositions.append(
                GenreDisposition(
                    source_item_id=entry.source_item_id,
                    name=entry.name,
                    status="abstained",
                    abstention_reason=reason,
                    direct_candidate_count=0,
                    aggregate_candidate_count=0,
                )
            )
        elif len(genre_ids) > 1 or entry.source_item_id in ambiguous_items:
            reason = "ambiguous_public_genre_identity"
            reasons[reason] += 1
            dispositions.append(
                GenreDisposition(
                    source_item_id=entry.source_item_id,
                    name=entry.name,
                    status="abstained",
                    abstention_reason=reason,
                    direct_candidate_count=0,
                    aggregate_candidate_count=0,
                )
            )
        elif direct_count:
            dispositions.append(
                GenreDisposition(
                    source_item_id=entry.source_item_id,
                    name=entry.name,
                    genre_id=genre_ids[0],
                    status="direct_evidence",
                    direct_candidate_count=direct_count,
                    aggregate_candidate_count=aggregate_count,
                )
            )
        elif aggregate_count:
            dispositions.append(
                GenreDisposition(
                    source_item_id=entry.source_item_id,
                    name=entry.name,
                    genre_id=genre_ids[0],
                    status="aggregate_candidate",
                    direct_candidate_count=0,
                    aggregate_candidate_count=aggregate_count,
                )
            )
        else:
            reason = (
                "no_eligible_aggregate_candidate"
                if policy.include_aggregate_candidates
                else "no_approved_direct_evidence"
            )
            reasons[reason] += 1
            dispositions.append(
                GenreDisposition(
                    source_item_id=entry.source_item_id,
                    name=entry.name,
                    genre_id=genre_ids[0],
                    status="abstained",
                    abstention_reason=reason,
                    direct_candidate_count=0,
                    aggregate_candidate_count=0,
                )
            )
    coverage = CandidateCoverage(
        direct_candidate_count=sum(len(items) for items in direct.values()),
        aggregate_candidate_count=sum(len(items) for items in aggregate.values()),
        direct_genre_count=sum(item.status == "direct_evidence" for item in dispositions),
        aggregate_only_genre_count=sum(
            item.status == "aggregate_candidate" for item in dispositions
        ),
        abstained_genre_count=sum(item.status == "abstained" for item in dispositions),
        no_public_genre_identity_count=reasons["no_public_genre_identity"],
        ambiguous_public_genre_identity_count=reasons["ambiguous_public_genre_identity"],
        no_approved_direct_evidence_count=reasons["no_approved_direct_evidence"],
        no_eligible_aggregate_candidate_count=reasons["no_eligible_aggregate_candidate"],
        examined_candidate_path_count=examined,
    )
    input_sha = _sha256(
        {
            "name_universe": name_universe.model_dump(mode="json"),
            "approved_public_input": approved_input.model_dump(mode="json"),
        }
    )
    policy_sha = _sha256(policy.model_dump(mode="json"))
    return PublicArtistMembershipCandidateArtifact(
        input_sha256=input_sha,
        policy_sha256=policy_sha,
        output_sha256=_sha256(
            _candidate_output_payload(
                input_sha256=input_sha,
                policy_sha256=policy_sha,
                name_universe=name_universe,
                source_policy=policy,
                directly_observed=directly_observed,
                propagated=propagated,
                dispositions=tuple(dispositions),
                coverage=coverage,
            )
        ),
        name_universe=name_universe,
        source_policy=policy,
        directly_observed_memberships=directly_observed,
        propagated_candidates=propagated,
        dispositions=tuple(dispositions),
        coverage=coverage,
    )


def build_public_artist_membership_candidate_from_seed_artifact(
    seed_artifact: Path,
    approved_input: ApprovedPublicMembershipInput,
    policy: PublicArtistMembershipSourcePolicy,
) -> PublicArtistMembershipCandidateArtifact:
    """Build through the sealed name-only parser rather than caller-supplied source claims."""
    return build_public_artist_membership_candidate(
        load_name_universe(seed_artifact), approved_input, policy
    )


def _candidate_output_payload(  # noqa: PLR0913
    *,
    input_sha256: Sha256,
    policy_sha256: Sha256,
    name_universe: NameUniverse,
    source_policy: PublicArtistMembershipSourcePolicy,
    directly_observed: tuple[ArtistGenreMembershipCandidate, ...],
    propagated: tuple[ArtistGenreMembershipCandidate, ...],
    dispositions: tuple[GenreDisposition, ...],
    coverage: CandidateCoverage,
) -> dict[str, object]:
    return {
        "revision": _REVISION,
        "non_production_candidate": True,
        "serving_membership_claimed": False,
        "quality_claim": "not_evaluated_without_independent_public_gold",
        "input_sha256": input_sha256,
        "policy_sha256": policy_sha256,
        "name_universe": name_universe.model_dump(mode="json"),
        "source_policy": source_policy.model_dump(mode="json"),
        "directly_observed_memberships": [
            item.model_dump(mode="json") for item in directly_observed
        ],
        "propagated_candidates": [item.model_dump(mode="json") for item in propagated],
        "dispositions": [item.model_dump(mode="json") for item in dispositions],
        "coverage": coverage.model_dump(mode="json"),
    }


def public_artist_membership_candidate_output_sha256(
    artifact: PublicArtistMembershipCandidateArtifact,
) -> Sha256:
    """Recompute the logical candidate hash after parsing a stored artifact."""
    return _sha256(
        _candidate_output_payload(
            input_sha256=artifact.input_sha256,
            policy_sha256=artifact.policy_sha256,
            name_universe=artifact.name_universe,
            source_policy=artifact.source_policy,
            directly_observed=artifact.directly_observed_memberships,
            propagated=artifact.propagated_candidates,
            dispositions=artifact.dispositions,
            coverage=artifact.coverage,
        )
    )


def verify_public_artist_membership_candidate(
    artifact: PublicArtistMembershipCandidateArtifact,
) -> None:
    """Reject an artifact whose declared logical hash does not cover its parsed contents."""
    if public_artist_membership_candidate_output_sha256(artifact) != artifact.output_sha256:
        raise ValueError("public artist membership candidate output hash does not match artifact")


def write_public_artist_membership_candidate(
    artifact: PublicArtistMembershipCandidateArtifact,
    *,
    output: Path,
    store: ObjectStore,
) -> PublicArtistMembershipPublication:
    """Write canonical candidate bytes and custody the exact file in object storage."""
    verify_public_artist_membership_candidate(artifact)
    payload = (_canonical_json(artifact.model_dump(mode="json")) + "\n").encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    file_sha = hashlib.sha256(payload).hexdigest()
    object_write = store.push(
        output,
        ObjectKey(value=f"{_PUBLICATION_PREFIX}/{artifact.output_sha256}.json"),
    )
    return PublicArtistMembershipPublication(
        artifact_output_sha256=artifact.output_sha256,
        artifact_file_sha256=file_sha,
        artifact_object=object_write,
    )


def evaluate_public_artist_membership_promotion(
    artifact: PublicArtistMembershipCandidateArtifact,
    policy: PromotionPolicy,
    gold: IndependentPublicGoldSet | None = None,
) -> PromotionGateReport:
    """Evaluate promotion eligibility only when independently sourced gold is supplied."""
    verify_public_artist_membership_candidate(artifact)
    policy_sha = _sha256(policy.model_dump(mode="json"))
    if gold is None:
        return PromotionGateReport(
            artifact_output_sha256=artifact.output_sha256,
            policy_sha256=policy_sha,
            independent_gold_supplied=False,
            quality_claim="not_evaluated_without_independent_public_gold",
            labeled_candidate_count=0,
            unlabeled_candidate_count=len(
                artifact.directly_observed_memberships + artifact.propagated_candidates
            ),
            independent_positive_label_count=0,
            true_positive_count=0,
            false_positive_count=0,
            false_negative_count=0,
            promotion_eligible=False,
            failures=("independent public gold is required before promotion",),
        )
    labels = {(item.artist_id, item.genre_id): item.is_member for item in gold.labels}
    candidate_pairs = {
        (item.artist_id, item.genre_id)
        for item in (*artifact.directly_observed_memberships, *artifact.propagated_candidates)
    }
    labeled_candidates = candidate_pairs & set(labels)
    true_positive = sum(labels[item] for item in labeled_candidates)
    false_positive = len(labeled_candidates) - true_positive
    positive_gold = {item for item, is_member in labels.items() if is_member}
    false_negative = len(positive_gold - candidate_pairs)
    precision = true_positive / len(labeled_candidates) if labeled_candidates else 0.0
    recall = true_positive / len(positive_gold) if positive_gold else 0.0
    failures: list[str] = []
    if len(labeled_candidates) < policy.minimum_labeled_candidates:
        failures.append("independent gold labels too few candidate pairs")
    if precision < policy.minimum_precision:
        failures.append("independent gold precision is below promotion threshold")
    if recall < policy.minimum_recall:
        failures.append("independent gold recall is below promotion threshold")
    return PromotionGateReport(
        artifact_output_sha256=artifact.output_sha256,
        policy_sha256=policy_sha,
        independent_gold_supplied=True,
        quality_claim="independent_public_gold_evaluated",
        labeled_candidate_count=len(labeled_candidates),
        unlabeled_candidate_count=len(candidate_pairs - set(labels)),
        independent_positive_label_count=len(positive_gold),
        true_positive_count=true_positive,
        false_positive_count=false_positive,
        false_negative_count=false_negative,
        precision=round(precision, 12),
        recall=round(recall, 12),
        promotion_eligible=not failures,
        failures=tuple(failures),
    )


def require_public_artist_membership_promotion(
    artifact: PublicArtistMembershipCandidateArtifact,
    policy: PromotionPolicy,
    gold: IndependentPublicGoldSet | None = None,
) -> PromotionGateReport:
    """Return a passing promotion report or fail closed with every unmet condition."""
    report = evaluate_public_artist_membership_promotion(artifact, policy, gold)
    if not report.promotion_eligible:
        raise PublicArtistMembershipPromotionError("; ".join(report.failures))
    return report
