"""Strict boundaries for public metadata and graph reconstruction experiments."""

from typing import Literal

from pydantic import Field, FiniteFloat, model_validator

from musix.models import FrozenModel
from musix.types import Sha256

type PublicSource = Literal["listenbrainz", "musicbrainz", "wikidata"]
type MembershipFacet = Literal["musicbrainz_tag", "wikidata_p136"]
type ProfileKind = Literal["direct", "one_hop"]
type SimilarityMetric = Literal["weighted_jaccard", "cosine"]
type MetadataKind = Literal["artist", "release_group", "recording"]


class PublicArtifact(FrozenModel):
    """Identify one immutable public input without accepting historical data."""

    source: PublicSource
    snapshot: str = Field(min_length=1, max_length=200)
    content_sha256: Sha256


class DirectMembershipEvidence(FrozenModel):
    """Represent one public, direct artist-to-genre observation."""

    artist_id: str = Field(min_length=1, max_length=200)
    genre_id: str = Field(min_length=1, max_length=200)
    facet: MembershipFacet
    value: FiniteFloat = Field(gt=0.0)
    evidence_ref: str = Field(min_length=1, max_length=500)


class ArtistPairEvidence(FrozenModel):
    """Represent privacy-safe listener-day support for one artist pair."""

    left_artist_id: str = Field(min_length=1, max_length=200)
    right_artist_id: str = Field(min_length=1, max_length=200)
    listener_day_support: int = Field(gt=0)
    supporting_windows: int = Field(gt=0)
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=366)

    @model_validator(mode="after")
    def require_canonical_pair(self) -> "ArtistPairEvidence":
        """Keep pair identity deterministic and its evidence unambiguous."""
        if self.left_artist_id >= self.right_artist_id:
            raise ValueError("artist pairs must use ascending, distinct IDs")
        if self.supporting_windows > self.listener_day_support:
            raise ValueError("supporting windows cannot exceed listener-day support")
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("artist pair evidence references must be unique")
        return self


class MetadataCandidate(FrozenModel):
    """Expose non-audio metadata that can be ranked for one genre."""

    entity_kind: MetadataKind
    entity_id: str = Field(min_length=1, max_length=200)
    genre_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=500)
    direct_evidence_value: FiniteFloat = Field(gt=0.0)
    source_count: int = Field(gt=0)
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def require_unique_evidence(self) -> "MetadataCandidate":
        """Reject duplicated support references before ranking."""
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("metadata evidence references must be unique")
        return self


class PublicModelInput(FrozenModel):
    """Bound all public-only observations accepted by the model core."""

    artifacts: tuple[PublicArtifact, ...] = Field(min_length=1, max_length=64)
    direct_memberships: tuple[DirectMembershipEvidence, ...] = Field(
        min_length=1, max_length=1_000_000
    )
    artist_pairs: tuple[ArtistPairEvidence, ...] = Field(default=(), max_length=5_000_000)
    metadata_candidates: tuple[MetadataCandidate, ...] = Field(default=(), max_length=1_000_000)

    @model_validator(mode="after")
    def require_unique_inputs(self) -> "PublicModelInput":
        """Reject duplicates that would otherwise silently change model weight."""
        artifacts = {(item.source, item.snapshot) for item in self.artifacts}
        if len(artifacts) != len(self.artifacts):
            raise ValueError("public input artifacts must be unique")
        memberships = {
            (item.artist_id, item.genre_id, item.facet, item.evidence_ref)
            for item in self.direct_memberships
        }
        if len(memberships) != len(self.direct_memberships):
            raise ValueError("direct membership observations must be unique")
        pairs = {(item.left_artist_id, item.right_artist_id) for item in self.artist_pairs}
        if len(pairs) != len(self.artist_pairs):
            raise ValueError("artist pairs must already be aggregated")
        candidates = {
            (item.entity_kind, item.entity_id, item.genre_id) for item in self.metadata_candidates
        }
        if len(candidates) != len(self.metadata_candidates):
            raise ValueError("metadata candidates must be unique per genre")
        return self


class PublicModelSettings(FrozenModel):
    """Declare deterministic algorithms and fail-closed laptop limits."""

    revision: Literal["public-graph-v1"] = "public-graph-v1"
    minimum_pair_support: int = Field(default=2, gt=0)
    minimum_pair_windows: int = Field(default=1, gt=0)
    minimum_shared_artists: int = Field(default=1, gt=0)
    neighbors_per_genre: int = Field(default=25, ge=1, le=100)
    representatives_per_kind: int = Field(default=10, ge=1, le=100)
    inferred_memberships_per_genre: int = Field(default=100, ge=1, le=1_000)
    max_artists: int = Field(default=250_000, gt=0)
    max_genres: int = Field(default=20_000, gt=0)
    max_artist_pairs: int = Field(default=5_000_000, gt=0)
    max_direct_memberships: int = Field(default=1_000_000, gt=0)
    max_propagation_visits: int = Field(default=20_000_000, gt=0)
    max_similarity_pair_visits: int = Field(default=20_000_000, gt=0)


class MembershipScore(FrozenModel):
    """Publish a normalized score without hiding its evidence facet."""

    artist_id: str
    genre_id: str
    profile_kind: ProfileKind
    score: FiniteFloat = Field(gt=0.0, le=1.0)
    evidence_refs: tuple[str, ...] = Field(min_length=1)


class GenreProfile(FrozenModel):
    """Hold one sparse, source-explainable genre profile."""

    genre_id: str
    profile_kind: ProfileKind
    memberships: tuple[MembershipScore, ...] = Field(min_length=1)


class GenreNeighbor(FrozenModel):
    """Publish one directed top-k neighbor with shared support."""

    genre_id: str
    neighbor_genre_id: str
    profile_kind: ProfileKind
    metric: SimilarityMetric
    score: FiniteFloat = Field(gt=0.0, le=1.0)
    shared_artist_count: int = Field(gt=0)
    rank: int = Field(gt=0)


class GenreCoordinate(FrozenModel):
    """Store one deterministic graph coordinate with no semantic axis claim."""

    genre_id: str
    x: FiniteFloat = Field(ge=0.0, le=1.0)
    y: FiniteFloat = Field(ge=0.0, le=1.0)
    component: int = Field(ge=0)


class RepresentativeItem(FrozenModel):
    """Rank public metadata using direct evidence only."""

    genre_id: str
    entity_kind: MetadataKind
    entity_id: str
    name: str
    rank: int = Field(gt=0)
    direct_evidence_value: FiniteFloat = Field(gt=0.0)
    source_count: int = Field(gt=0)
    evidence_refs: tuple[str, ...] = Field(min_length=1)


class FacetAgreement(FrozenModel):
    """Report overlap between independent direct membership sources."""

    left_facet: MembershipFacet
    right_facet: MembershipFacet
    intersection_count: int = Field(ge=0)
    union_count: int = Field(ge=0)
    jaccard: FiniteFloat = Field(ge=0.0, le=1.0)
    left_recall_from_right: FiniteFloat = Field(ge=0.0, le=1.0)
    right_recall_from_left: FiniteFloat = Field(ge=0.0, le=1.0)


class ModelCoverage(FrozenModel):
    """Make absent evidence and output coverage visible."""

    input_artists: int = Field(ge=0)
    input_genres: int = Field(ge=0)
    direct_memberships: int = Field(ge=0)
    eligible_artist_pairs: int = Field(ge=0)
    inferred_memberships: int = Field(ge=0)
    neighbor_genres: int = Field(ge=0)
    coordinate_genres: int = Field(ge=0)
    unplaced_genres: tuple[str, ...]
    representative_items: int = Field(ge=0)


class ModelResources(FrozenModel):
    """Record measured local resource use for one build."""

    elapsed_ms: int = Field(ge=0)
    peak_rss_bytes: int = Field(ge=0)


class PublicModelArtifact(FrozenModel):
    """Publish one complete, content-addressed public reconstruction."""

    revision: Literal["public-graph-v1"] = "public-graph-v1"
    input_sha256: Sha256
    settings_sha256: Sha256
    output_sha256: Sha256
    profiles: tuple[GenreProfile, ...]
    neighbors: tuple[GenreNeighbor, ...]
    coordinates: tuple[GenreCoordinate, ...]
    representatives: tuple[RepresentativeItem, ...]
    facet_agreement: tuple[FacetAgreement, ...]
    coverage: ModelCoverage
    resources: ModelResources
