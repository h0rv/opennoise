"""Strict boundaries for public metadata and graph reconstruction experiments."""

from typing import Literal

from pydantic import Field, FiniteFloat, model_validator

from opennoise.models import FrozenModel
from opennoise.types import Sha256

type PublicSource = Literal["listenbrainz", "musicbrainz", "wikidata"]
type MembershipFacet = Literal["musicbrainz_genre", "musicbrainz_tag", "wikidata_p136"]
type ProfileKind = Literal["direct", "one_hop"]
type SimilarityMetric = Literal["weighted_jaccard", "cosine"]
type MetadataKind = Literal["artist", "release_group", "recording"]
type MembershipComponentKind = MembershipFacet | Literal["listenbrainz_one_hop"]
type LayoutLensKey = Literal[
    "public",
    "public-community",
    "public-direct",
    "public-taxonomy",
]
type LayoutInputKind = ProfileKind | Literal["genre_hierarchy"]
type LayoutMethod = Literal[
    "community_packed_spectral",
    "normalized_laplacian_spectral",
    "taxonomy_spectral",
]
type LayoutMetric = SimilarityMetric | Literal["hierarchy_adjacency"]
type UnplacedReason = Literal[
    "no_direct_membership",
    "no_hierarchy_relation",
]


class PublicArtifact(FrozenModel):
    """Identify one immutable public input without accepting historical data."""

    source: PublicSource
    snapshot: str = Field(min_length=1, max_length=200)
    artifact_key: str = Field(min_length=1, max_length=300)
    content_sha256: Sha256
    export_allowed: bool


class DirectMembershipEvidence(FrozenModel):
    """Represent one public, direct artist-to-genre observation."""

    artist_id: str = Field(min_length=1, max_length=200)
    genre_id: str = Field(min_length=1, max_length=200)
    facet: MembershipFacet
    value: FiniteFloat = Field(gt=0.0)
    evidence_ref: str = Field(min_length=1, max_length=500)


class GenreIdentity(FrozenModel):
    """Name one public genre concept without historical vocabulary input."""

    genre_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=500)
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=32)


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


class GenreHierarchyEdge(FrozenModel):
    """Keep one direct taxonomy claim separate from learned similarity."""

    child_genre_id: str = Field(min_length=1, max_length=200)
    parent_genre_id: str = Field(min_length=1, max_length=200)
    evidence_ref: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def require_distinct_genres(self) -> "GenreHierarchyEdge":
        """Reject hierarchy self loops."""
        if self.child_genre_id == self.parent_genre_id:
            raise ValueError("genre hierarchy edges cannot be self loops")
        return self


class PublicModelInput(FrozenModel):
    """Bound all public-only observations accepted by the model core."""

    artifacts: tuple[PublicArtifact, ...] = Field(min_length=1, max_length=64)
    genres: tuple[GenreIdentity, ...] = Field(min_length=1, max_length=20_000)
    direct_memberships: tuple[DirectMembershipEvidence, ...] = Field(
        min_length=1, max_length=1_000_000
    )
    artist_pairs: tuple[ArtistPairEvidence, ...] = Field(default=(), max_length=5_000_000)
    metadata_candidates: tuple[MetadataCandidate, ...] = Field(default=(), max_length=1_000_000)
    hierarchy: tuple[GenreHierarchyEdge, ...] = Field(default=(), max_length=100_000)

    @model_validator(mode="after")
    def require_unique_inputs(self) -> "PublicModelInput":
        """Reject duplicates that would otherwise silently change model weight."""
        artifacts = {(item.source, item.snapshot, item.artifact_key) for item in self.artifacts}
        if len(artifacts) != len(self.artifacts):
            raise ValueError("public input artifacts must be unique")
        memberships = {
            (item.artist_id, item.genre_id, item.facet, item.evidence_ref)
            for item in self.direct_memberships
        }
        if len(memberships) != len(self.direct_memberships):
            raise ValueError("direct membership observations must be unique")
        genre_ids = {item.genre_id for item in self.genres}
        if len(genre_ids) != len(self.genres):
            raise ValueError("genre identities must be unique")
        referenced_genres = {item.genre_id for item in self.direct_memberships}
        referenced_genres.update(item.genre_id for item in self.metadata_candidates)
        if not referenced_genres <= genre_ids:
            raise ValueError("every referenced genre needs a public identity")
        pairs = {(item.left_artist_id, item.right_artist_id) for item in self.artist_pairs}
        if len(pairs) != len(self.artist_pairs):
            raise ValueError("artist pairs must already be aggregated")
        candidates = {
            (item.entity_kind, item.entity_id, item.genre_id) for item in self.metadata_candidates
        }
        if len(candidates) != len(self.metadata_candidates):
            raise ValueError("metadata candidates must be unique per genre")
        hierarchy = {(item.child_genre_id, item.parent_genre_id) for item in self.hierarchy}
        if len(hierarchy) != len(self.hierarchy):
            raise ValueError("genre hierarchy edges must be unique")
        hierarchy_genres = {
            genre_id
            for item in self.hierarchy
            for genre_id in (item.child_genre_id, item.parent_genre_id)
        }
        if not hierarchy_genres <= genre_ids:
            raise ValueError("every hierarchy endpoint needs a public genre identity")
        return self


class PublicModelSettings(FrozenModel):
    """Declare deterministic algorithms and fail-closed laptop limits."""

    revision: Literal["public-graph-v2"] = "public-graph-v2"
    minimum_pair_support: int = Field(default=2, gt=0)
    minimum_pair_windows: int = Field(default=1, gt=0)
    minimum_shared_artists: int = Field(default=1, gt=0)
    neighbors_per_genre: int = Field(default=25, ge=1, le=100)
    layout_neighbors_per_genre: int = Field(default=10, ge=2, le=50)
    community_seed: int = Field(default=20260831, ge=0)
    maximum_community_iterations: int = Field(default=100, gt=0, le=1_000)
    representatives_per_kind: int = Field(default=10, ge=1, le=100)
    inferred_memberships_per_genre: int = Field(default=100, ge=1, le=1_000)
    max_artists: int = Field(default=250_000, gt=0)
    max_genres: int = Field(default=20_000, gt=0)
    max_artist_pairs: int = Field(default=5_000_000, gt=0)
    max_direct_memberships: int = Field(default=1_000_000, gt=0)
    max_propagation_visits: int = Field(default=20_000_000, gt=0)
    max_similarity_pair_visits: int = Field(default=20_000_000, gt=0)


class MembershipComponent(FrozenModel):
    """Keep one direct facet or graph contribution visible in a score."""

    component_kind: MembershipComponentKind
    raw_value: FiniteFloat = Field(gt=0.0)
    normalized_value: FiniteFloat = Field(gt=0.0, le=1.0)
    evidence_refs: tuple[str, ...] = Field(min_length=1)


class MembershipScore(FrozenModel):
    """Publish a normalized score without hiding its evidence facet."""

    artist_id: str
    genre_id: str
    profile_kind: ProfileKind
    score: FiniteFloat = Field(gt=0.0, le=1.0)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    components: tuple[MembershipComponent, ...] = Field(min_length=1)


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


class UnplacedGenre(FrozenModel):
    """Explain why one named genre is absent from a layout lens."""

    genre_id: str = Field(min_length=1, max_length=200)
    reason: UnplacedReason


class LayoutQuality(FrozenModel):
    """Record comparable graph and coordinate quality for one lens."""

    neighbors_per_genre: int = Field(gt=0)
    layout_graph_edges: int = Field(ge=0)
    input_graph_edges: int = Field(ge=0)
    placed_genres: int = Field(ge=0)
    unplaced_genres: int = Field(ge=0)
    mean_knn_preservation: FiniteFloat = Field(ge=0.0, le=1.0)
    one_hop_reference_knn_preservation: FiniteFloat | None = Field(default=None, ge=0.0, le=1.0)
    mutual_neighbor_fraction: FiniteFloat = Field(ge=0.0, le=1.0)


class LayoutStability(FrozenModel):
    """Record deterministic repeat behavior for one layout lens."""

    exact_rerun: bool
    aligned_coordinate_rms: FiniteFloat = Field(ge=0.0)


class CommunityLayoutResult(FrozenModel):
    """Expose the bounded graph partition used by a community lens."""

    algorithm: Literal["seeded_weighted_label_propagation"] = "seeded_weighted_label_propagation"
    algorithm_version: Literal["1"] = "1"
    community_count: int = Field(ge=0)
    iterations: int = Field(ge=0)
    converged: bool
    modularity: FiniteFloat = Field(ge=-1.0, le=1.0)


class LayoutLens(FrozenModel):
    """Publish one independently reproducible view of the genre graph."""

    layout_key: LayoutLensKey
    is_default: bool
    method: LayoutMethod
    method_version: Literal["1"] = "1"
    input_kind: LayoutInputKind
    metric: LayoutMetric
    seed: int = Field(ge=0)
    input_sha256: Sha256
    output_sha256: Sha256
    coordinates: tuple[GenreCoordinate, ...]
    unplaced: tuple[UnplacedGenre, ...]
    quality: LayoutQuality
    stability: LayoutStability
    community: CommunityLayoutResult | None = None
    resources: "ModelResources"

    @model_validator(mode="after")
    def require_consistent_lens(self) -> "LayoutLens":
        """Reject mismatched method, input, and coverage declarations."""
        expected = {
            "public": (
                "normalized_laplacian_spectral",
                "one_hop",
                "weighted_jaccard",
            ),
            "public-direct": (
                "normalized_laplacian_spectral",
                "direct",
                "weighted_jaccard",
            ),
            "public-community": (
                "community_packed_spectral",
                "one_hop",
                "weighted_jaccard",
            ),
            "public-taxonomy": (
                "taxonomy_spectral",
                "genre_hierarchy",
                "hierarchy_adjacency",
            ),
        }
        if (self.method, self.input_kind, self.metric) != expected[self.layout_key]:
            raise ValueError("layout key does not match its declared method and input")
        if self.is_default != (self.layout_key == "public"):
            raise ValueError("the public one-hop lens must be the only default")
        if self.layout_key == "public-community" and self.community is None:
            raise ValueError("community layout requires community diagnostics")
        if self.layout_key != "public-community" and self.community is not None:
            raise ValueError("only the community layout may carry community diagnostics")
        coordinate_ids = {item.genre_id for item in self.coordinates}
        unplaced_ids = {item.genre_id for item in self.unplaced}
        if len(coordinate_ids) != len(self.coordinates) or len(unplaced_ids) != len(self.unplaced):
            raise ValueError("layout genre entries must be unique")
        if coordinate_ids & unplaced_ids:
            raise ValueError("a genre cannot be both placed and unplaced")
        if self.quality.placed_genres != len(self.coordinates):
            raise ValueError("placed genre count does not match coordinates")
        if self.quality.unplaced_genres != len(self.unplaced):
            raise ValueError("unplaced genre count does not match reasons")
        return self


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
    direct_observations: int = Field(ge=0)
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

    revision: Literal["public-graph-v2"] = "public-graph-v2"
    input_sha256: Sha256
    settings_sha256: Sha256
    output_sha256: Sha256
    export_allowed: bool
    artifacts: tuple[PublicArtifact, ...] = Field(min_length=1, max_length=64)
    genres: tuple[GenreIdentity, ...]
    profiles: tuple[GenreProfile, ...]
    neighbors: tuple[GenreNeighbor, ...]
    layouts: tuple[LayoutLens, ...] = Field(min_length=4, max_length=4)
    representatives: tuple[RepresentativeItem, ...]
    facet_agreement: tuple[FacetAgreement, ...]
    coverage: ModelCoverage
    resources: ModelResources

    @model_validator(mode="after")
    def require_complete_layout_set(self) -> "PublicModelArtifact":
        """Require one versioned lens for each declared public map view."""
        keys = tuple(item.layout_key for item in self.layouts)
        if len(keys) != len(set(keys)):
            raise ValueError("public layout keys must be unique")
        expected = {
            "public",
            "public-community",
            "public-direct",
            "public-taxonomy",
        }
        if set(keys) != expected:
            raise ValueError(
                "public model requires direct, one-hop, community, and taxonomy lenses"
            )
        if sum(item.is_default for item in self.layouts) != 1:
            raise ValueError("public model requires exactly one default layout")
        genre_ids = {item.genre_id for item in self.genres}
        for lens in self.layouts:
            covered = {item.genre_id for item in lens.coordinates}
            covered.update(item.genre_id for item in lens.unplaced)
            if covered != genre_ids:
                raise ValueError("every layout must account for every public genre identity")
        return self

    @property
    def coordinates(self) -> tuple[GenreCoordinate, ...]:
        """Expose default coordinates to existing validation callers."""
        return next(item.coordinates for item in self.layouts if item.is_default)
