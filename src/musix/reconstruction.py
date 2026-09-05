"""Deterministic baselines for testing an open Every Noise reconstruction."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from itertools import product
from typing import Annotated, Literal

from pydantic import Field, FiniteFloat, field_validator, model_validator

from musix.models import FrozenModel

MAX_EDGES = 500_000
MAX_GENRES = 100_000
MAX_GRID_RUNS = 16
MAX_NEIGHBORS = 128
MAX_SHARED_ARTISTS = 10_000
MAX_CANDIDATE_PAIRS = 100_000
MAX_PAIR_VISITS = 1_000_000
MAX_AGGREGATE_CANDIDATE_PAIRS = 500_000
MAX_AGGREGATE_PAIR_VISITS = 5_000_000
MAX_COORDINATE_KNN_POINTS = 10_000
MIN_ALIGNMENT_POINTS = 2

type EvidenceRef = Annotated[str, Field(min_length=1, max_length=2_000)]


@dataclass(frozen=True, slots=True)
class _GenreVector:
    weights: dict[str, float]
    weight_sum: float
    norm: float


class EvidenceStatus(StrEnum):
    """How strongly public evidence supports a historical method claim."""

    DISCLOSED = "disclosed"
    OBSERVED = "observed"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


class SimilarityMetric(StrEnum):
    """A transparent genre similarity baseline."""

    WEIGHTED_COSINE = "weighted_cosine"
    WEIGHTED_JACCARD = "weighted_jaccard"


class HistoricalClaim(FrozenModel):
    """One bounded claim about the historical system and its support."""

    claim_key: str = Field(min_length=1, max_length=100)
    statement: str = Field(min_length=1, max_length=2_000)
    evidence_status: EvidenceStatus
    evidence_refs: tuple[EvidenceRef, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def _require_support_for_known_claims(self) -> HistoricalClaim:
        if (
            self.evidence_status
            in {
                EvidenceStatus.DISCLOSED,
                EvidenceStatus.OBSERVED,
                EvidenceStatus.INFERRED,
            }
            and not self.evidence_refs
        ):
            raise ValueError("disclosed, observed, and inferred claims need an evidence reference")
        _require_unique_evidence_refs(self.evidence_refs)
        return self


class VersionedInput(FrozenModel):
    """Identity and content hash for one immutable input artifact."""

    artifact_key: str = Field(min_length=1, max_length=200)
    revision: str = Field(min_length=1, max_length=200)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class GenreArtistEdge(FrozenModel):
    """One weighted artist membership observation used by a baseline."""

    genre_id: str = Field(min_length=1, max_length=200)
    facet: Literal["genre", "tag", "musicbrainz_genre", "musicbrainz_tag"] = "genre"
    artist_id: str = Field(min_length=1, max_length=200)
    weight: FiniteFloat = Field(default=1.0, gt=0.0)
    evidence_refs: tuple[EvidenceRef, ...] = Field(min_length=1, max_length=32)

    @field_validator("evidence_refs")
    @classmethod
    def _require_distinct_evidence_refs(
        cls, evidence_refs: tuple[EvidenceRef, ...]
    ) -> tuple[EvidenceRef, ...]:
        _require_unique_evidence_refs(evidence_refs)
        return evidence_refs


class HistoricalGenrePoint(FrozenModel):
    """One observed historical genre coordinate and optional observed color."""

    genre_id: str = Field(min_length=1, max_length=200)
    x: FiniteFloat
    y: FiniteFloat
    color_hex: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    evidence_ref: EvidenceRef


class HistoricalNeighborList(FrozenModel):
    """One observed historical genre neighbor ranking."""

    genre_id: str = Field(min_length=1, max_length=200)
    neighbor_ids: tuple[str, ...] = Field(min_length=1, max_length=128)
    evidence_ref: EvidenceRef

    @model_validator(mode="after")
    def _require_distinct_neighbors(self) -> HistoricalNeighborList:
        if self.genre_id in self.neighbor_ids:
            raise ValueError("a genre cannot be its own historical neighbor")
        if len(set(self.neighbor_ids)) != len(self.neighbor_ids):
            raise ValueError("historical neighbor IDs must be unique")
        return self


class ReconstructionPoint(FrozenModel):
    """One coordinate produced by a candidate reconstruction method."""

    genre_id: str = Field(min_length=1, max_length=200)
    x: FiniteFloat
    y: FiniteFloat


class ReconstructionInputs(FrozenModel):
    """Versioned observations supplied to a reconstruction experiment."""

    membership_artifact: VersionedInput
    membership_edges: tuple[GenreArtistEdge, ...] = Field(min_length=1, max_length=MAX_EDGES)
    historical_artifact: VersionedInput | None = None
    historical_points: tuple[HistoricalGenrePoint, ...] = Field(default=(), max_length=MAX_GENRES)
    historical_neighbors: tuple[HistoricalNeighborList, ...] = Field(
        default=(), max_length=MAX_GENRES
    )

    @model_validator(mode="after")
    def _require_consistent_inputs(self) -> ReconstructionInputs:
        edge_keys = {(edge.facet, edge.genre_id, edge.artist_id) for edge in self.membership_edges}
        if len(edge_keys) != len(self.membership_edges):
            raise ValueError("genre and artist membership pairs must be unique")
        _require_unique_genre_ids(
            [point.genre_id for point in self.historical_points], "historical point"
        )
        _require_unique_genre_ids(
            [item.genre_id for item in self.historical_neighbors],
            "historical neighbor list",
        )
        has_historical_data = bool(self.historical_points or self.historical_neighbors)
        if has_historical_data != (self.historical_artifact is not None):
            raise ValueError("historical observations and their artifact must appear together")
        return self


class SimilarityParameters(FrozenModel):
    """Bounded settings for one artist membership similarity run."""

    metric: SimilarityMetric
    max_neighbors: int = Field(ge=1, le=128)
    min_shared_artists: int = Field(default=1, ge=1, le=10_000)
    max_candidate_pairs: int = Field(default=MAX_CANDIDATE_PAIRS, ge=1, le=MAX_CANDIDATE_PAIRS)
    max_pair_visits: int = Field(default=MAX_PAIR_VISITS, ge=1, le=MAX_PAIR_VISITS)


class ParameterGrid(FrozenModel):
    """A small deterministic grid of baseline settings."""

    metrics: tuple[SimilarityMetric, ...] = Field(min_length=1, max_length=2)
    max_neighbors: tuple[int, ...] = Field(min_length=1, max_length=16)
    min_shared_artists: tuple[int, ...] = Field(min_length=1, max_length=16)
    max_candidate_pairs: int = Field(default=MAX_CANDIDATE_PAIRS, ge=1, le=MAX_CANDIDATE_PAIRS)
    max_pair_visits: int = Field(default=MAX_PAIR_VISITS, ge=1, le=MAX_PAIR_VISITS)

    @model_validator(mode="after")
    def _require_unique_bounded_values(self) -> ParameterGrid:
        if len(set(self.metrics)) != len(self.metrics):
            raise ValueError("grid metrics must be unique")
        if any(value < 1 or value > MAX_NEIGHBORS for value in self.max_neighbors):
            raise ValueError("grid max_neighbors values must be between 1 and 128")
        if any(value < 1 or value > MAX_SHARED_ARTISTS for value in self.min_shared_artists):
            raise ValueError("grid min_shared_artists values must be between 1 and 10000")
        if len(set(self.max_neighbors)) != len(self.max_neighbors):
            raise ValueError("grid max_neighbors values must be unique")
        if len(set(self.min_shared_artists)) != len(self.min_shared_artists):
            raise ValueError("grid min_shared_artists values must be unique")
        run_count = len(self.metrics) * len(self.max_neighbors) * len(self.min_shared_artists)
        if run_count > MAX_GRID_RUNS:
            raise ValueError("parameter grid cannot contain more than 16 runs")
        if run_count * self.max_candidate_pairs > MAX_AGGREGATE_CANDIDATE_PAIRS:
            raise ValueError("parameter grid exceeds the aggregate candidate pair limit")
        if run_count * self.max_pair_visits > MAX_AGGREGATE_PAIR_VISITS:
            raise ValueError("parameter grid exceeds the aggregate pair visit limit")
        return self


class ReconstructionExperimentManifest(FrozenModel):
    """Complete immutable request for a deterministic reconstruction experiment."""

    experiment_key: str = Field(min_length=1, max_length=200)
    harness_revision: Literal["reconstruction-v1"] = "reconstruction-v1"
    claims: tuple[HistoricalClaim, ...] = Field(default=(), max_length=128)
    inputs: ReconstructionInputs
    grid: ParameterGrid
    candidate_artifact: VersionedInput | None = None
    candidate_points: tuple[ReconstructionPoint, ...] = Field(default=(), max_length=MAX_GENRES)
    evaluation_neighbor_count: int = Field(default=10, ge=1, le=128)

    @model_validator(mode="after")
    def _require_unique_candidate_points(self) -> ReconstructionExperimentManifest:
        _require_unique_genre_ids(
            [point.genre_id for point in self.candidate_points], "candidate point"
        )
        if bool(self.candidate_points) != (self.candidate_artifact is not None):
            raise ValueError("candidate points and their versioned artifact must appear together")
        if self.candidate_points and len(self.candidate_points) < MIN_ALIGNMENT_POINTS:
            raise ValueError("coordinate alignment needs at least two candidate points")
        claim_keys = [claim.claim_key for claim in self.claims]
        if len(set(claim_keys)) != len(claim_keys):
            raise ValueError("historical claim keys must be unique")
        return self


class GenreSimilarityEdge(FrozenModel):
    """One undirected genre relation from direct artist overlap."""

    source_genre_id: str
    target_genre_id: str
    score: FiniteFloat = Field(gt=0.0, le=1.0)
    shared_artist_count: int = Field(ge=1)


class GenreNeighborList(FrozenModel):
    """A deterministic nearest neighbor list for one genre."""

    genre_id: str
    neighbor_ids: tuple[str, ...]


class SimilarityRunResult(FrozenModel):
    """Artist overlap output for one explicit parameter set."""

    parameters: SimilarityParameters
    genre_count: int = Field(ge=1)
    candidate_pair_count: int = Field(ge=0)
    pair_visit_count: int = Field(ge=0)
    retained_edge_count: int = Field(ge=0)
    edges: tuple[GenreSimilarityEdge, ...]
    neighbors: tuple[GenreNeighborList, ...]


class AxisCorrelationResult(FrozenModel):
    """Pearson correlations between candidate and historical axes."""

    candidate_x_historical_x: FiniteFloat | None
    candidate_x_historical_y: FiniteFloat | None
    candidate_y_historical_x: FiniteFloat | None
    candidate_y_historical_y: FiniteFloat | None


class AlignmentResult(FrozenModel):
    """Best orientation preserving similarity alignment to historical points."""

    common_genre_count: int = Field(ge=2)
    scale: FiniteFloat = Field(gt=0.0)
    rotation_radians: FiniteFloat
    translation_x: FiniteFloat
    translation_y: FiniteFloat
    root_mean_square_error: FiniteFloat = Field(ge=0.0)
    normalized_root_mean_square_error: FiniteFloat = Field(ge=0.0)
    axis_correlations_before_alignment: AxisCorrelationResult
    axis_correlations_after_alignment: AxisCorrelationResult


class NeighborhoodPreservationResult(FrozenModel):
    """Mean top k recall against observed or coordinate derived neighbors."""

    reference_kind: Literal["observed", "historical_coordinate_knn"]
    neighbor_count: int = Field(ge=1, le=128)
    evaluated_genre_count: int = Field(ge=0)
    mean_recall: FiniteFloat = Field(ge=0.0, le=1.0)


class ExperimentRunResult(FrozenModel):
    """One similarity run and any historical comparisons it supports."""

    run_index: int = Field(ge=1)
    similarity: SimilarityRunResult
    alignment: AlignmentResult | None
    neighborhood_preservation: NeighborhoodPreservationResult | None


class ReconstructionExperimentResult(FrozenModel):
    """Deterministic results that do not claim exact historical recovery."""

    experiment_key: str
    harness_revision: Literal["reconstruction-v1"]
    claims: tuple[HistoricalClaim, ...]
    membership_artifact: VersionedInput
    historical_artifact: VersionedInput | None
    candidate_artifact: VersionedInput | None
    evaluation_neighbor_count: int = Field(ge=1, le=128)
    exact_historical_recovery_claimed: Literal[False] = False
    interpretation: Literal["candidate approximations only"] = "candidate approximations only"
    runs: tuple[ExperimentRunResult, ...] = Field(min_length=1, max_length=MAX_GRID_RUNS)


def expand_parameter_grid(grid: ParameterGrid) -> tuple[SimilarityParameters, ...]:
    """Expand settings in stable enum, neighbor count, and support order."""
    return tuple(
        SimilarityParameters(
            metric=metric,
            max_neighbors=neighbor_count,
            min_shared_artists=minimum_shared,
            max_candidate_pairs=grid.max_candidate_pairs,
            max_pair_visits=grid.max_pair_visits,
        )
        for metric, neighbor_count, minimum_shared in product(
            grid.metrics, grid.max_neighbors, grid.min_shared_artists
        )
    )


def build_artist_overlap_similarity(
    edges: tuple[GenreArtistEdge, ...], parameters: SimilarityParameters
) -> SimilarityRunResult:
    """Build a sparse genre graph from weighted direct artist overlap."""
    vectors: dict[str, dict[str, float]] = defaultdict(dict)
    artist_genres: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        vectors[edge.genre_id][edge.artist_id] = float(edge.weight)
        artist_genres[edge.artist_id].append(edge.genre_id)

    shared_counts, pair_visit_count = _count_shared_artist_pairs(artist_genres, parameters)
    vector_stats = {
        genre_id: _GenreVector(
            weights=vector,
            weight_sum=sum(vector.values()),
            norm=math.sqrt(sum(value * value for value in vector.values())),
        )
        for genre_id, vector in vectors.items()
    }

    scored_edges: list[GenreSimilarityEdge] = []
    for (source_id, target_id), shared_count in sorted(shared_counts.items()):
        if shared_count < parameters.min_shared_artists:
            continue
        score = _vector_similarity(
            vector_stats[source_id],
            vector_stats[target_id],
            parameters.metric,
        )
        if score > 0.0:
            scored_edges.append(
                GenreSimilarityEdge(
                    source_genre_id=source_id,
                    target_genre_id=target_id,
                    score=score,
                    shared_artist_count=shared_count,
                )
            )

    ranked: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for edge in scored_edges:
        ranked[edge.source_genre_id].append((float(edge.score), edge.target_genre_id))
        ranked[edge.target_genre_id].append((float(edge.score), edge.source_genre_id))
    neighbors = tuple(
        GenreNeighborList(
            genre_id=genre_id,
            neighbor_ids=tuple(
                neighbor_id
                for _, neighbor_id in sorted(
                    ranked.get(genre_id, ()), key=lambda item: (-item[0], item[1])
                )[: parameters.max_neighbors]
            ),
        )
        for genre_id in sorted(vectors)
    )
    return SimilarityRunResult(
        parameters=parameters,
        genre_count=len(vectors),
        candidate_pair_count=len(shared_counts),
        pair_visit_count=pair_visit_count,
        retained_edge_count=len(scored_edges),
        edges=tuple(scored_edges),
        neighbors=neighbors,
    )


def align_to_historical_points(
    candidate_points: tuple[ReconstructionPoint, ...],
    historical_points: tuple[HistoricalGenrePoint, ...],
) -> AlignmentResult:
    """Fit and score an orientation preserving two dimensional Procrustes transform."""
    candidate_by_id = {point.genre_id: point for point in candidate_points}
    historical_by_id = {point.genre_id: point for point in historical_points}
    common_ids = sorted(candidate_by_id.keys() & historical_by_id.keys())
    if len(common_ids) < MIN_ALIGNMENT_POINTS:
        raise ValueError("alignment needs at least two genres present in both point sets")
    candidate_xy = [
        (float(candidate_by_id[genre_id].x), float(candidate_by_id[genre_id].y))
        for genre_id in common_ids
    ]
    historical_xy = [
        (float(historical_by_id[genre_id].x), float(historical_by_id[genre_id].y))
        for genre_id in common_ids
    ]
    candidate_centered, candidate_mean = _center(candidate_xy)
    historical_centered, historical_mean = _center(historical_xy)
    candidate_energy = sum(x * x + y * y for x, y in candidate_centered)
    historical_energy = sum(x * x + y * y for x, y in historical_centered)
    if candidate_energy == 0.0 or historical_energy == 0.0:
        raise ValueError("alignment point sets must each have nonzero spatial variance")
    dot = sum(
        candidate_x * historical_x + candidate_y * historical_y
        for (candidate_x, candidate_y), (historical_x, historical_y) in zip(
            candidate_centered, historical_centered, strict=True
        )
    )
    cross = sum(
        candidate_x * historical_y - candidate_y * historical_x
        for (candidate_x, candidate_y), (historical_x, historical_y) in zip(
            candidate_centered, historical_centered, strict=True
        )
    )
    rotation_norm = math.hypot(dot, cross)
    if rotation_norm == 0.0:
        raise ValueError("alignment has no identifiable orientation preserving rotation")
    cosine = dot / rotation_norm
    sine = cross / rotation_norm
    scale = rotation_norm / candidate_energy
    translation_x = historical_mean[0] - scale * (
        cosine * candidate_mean[0] - sine * candidate_mean[1]
    )
    translation_y = historical_mean[1] - scale * (
        sine * candidate_mean[0] + cosine * candidate_mean[1]
    )
    aligned = [
        (
            scale * (cosine * x - sine * y) + translation_x,
            scale * (sine * x + cosine * y) + translation_y,
        )
        for x, y in candidate_xy
    ]
    squared_error = sum(
        (aligned_x - historical_x) ** 2 + (aligned_y - historical_y) ** 2
        for (aligned_x, aligned_y), (historical_x, historical_y) in zip(
            aligned, historical_xy, strict=True
        )
    )
    root_mean_square_error = math.sqrt(squared_error / len(common_ids))
    historical_rms_radius = math.sqrt(historical_energy / len(common_ids))
    return AlignmentResult(
        common_genre_count=len(common_ids),
        scale=scale,
        rotation_radians=math.atan2(sine, cosine),
        translation_x=translation_x,
        translation_y=translation_y,
        root_mean_square_error=root_mean_square_error,
        normalized_root_mean_square_error=root_mean_square_error / historical_rms_radius,
        axis_correlations_before_alignment=_axis_correlations(candidate_xy, historical_xy),
        axis_correlations_after_alignment=_axis_correlations(aligned, historical_xy),
    )


def evaluate_neighborhood_preservation(
    generated_neighbors: tuple[GenreNeighborList, ...],
    historical_neighbors: tuple[HistoricalNeighborList, ...],
    historical_points: tuple[HistoricalGenrePoint, ...],
    neighbor_count: int,
) -> NeighborhoodPreservationResult | None:
    """Measure mean top k recall against observed neighbors or historical coordinate kNN."""
    generated_by_id = {item.genre_id: item.neighbor_ids for item in generated_neighbors}
    if historical_neighbors:
        reference_kind: Literal["observed", "historical_coordinate_knn"] = "observed"
        reference_by_id = {item.genre_id: item.neighbor_ids for item in historical_neighbors}
    elif len(historical_points) > 1:
        if len(historical_points) > MAX_COORDINATE_KNN_POINTS:
            raise ValueError(
                f"coordinate neighbor fallback exceeds {MAX_COORDINATE_KNN_POINTS} points"
            )
        reference_kind = "historical_coordinate_knn"
        reference_by_id = _coordinate_neighbors(historical_points, neighbor_count)
    else:
        return None
    recalls: list[float] = []
    for genre_id in sorted(generated_by_id.keys() & reference_by_id.keys()):
        expected = tuple(reference_by_id[genre_id][:neighbor_count])
        if not expected:
            continue
        actual = set(generated_by_id[genre_id][:neighbor_count])
        recalls.append(len(actual.intersection(expected)) / len(expected))
    return NeighborhoodPreservationResult(
        reference_kind=reference_kind,
        neighbor_count=neighbor_count,
        evaluated_genre_count=len(recalls),
        mean_recall=sum(recalls) / len(recalls) if recalls else 0.0,
    )


def run_reconstruction_experiment(
    manifest: ReconstructionExperimentManifest,
) -> ReconstructionExperimentResult:
    """Run every deterministic baseline in a versioned experiment manifest."""
    results: list[ExperimentRunResult] = []
    alignment = None
    if manifest.candidate_points and manifest.inputs.historical_points:
        alignment = align_to_historical_points(
            manifest.candidate_points, manifest.inputs.historical_points
        )
    for run_index, parameters in enumerate(expand_parameter_grid(manifest.grid), start=1):
        similarity = build_artist_overlap_similarity(manifest.inputs.membership_edges, parameters)
        preservation = evaluate_neighborhood_preservation(
            similarity.neighbors,
            manifest.inputs.historical_neighbors,
            manifest.inputs.historical_points,
            manifest.evaluation_neighbor_count,
        )
        results.append(
            ExperimentRunResult(
                run_index=run_index,
                similarity=similarity,
                alignment=alignment,
                neighborhood_preservation=preservation,
            )
        )
    return ReconstructionExperimentResult(
        experiment_key=manifest.experiment_key,
        harness_revision=manifest.harness_revision,
        claims=manifest.claims,
        membership_artifact=manifest.inputs.membership_artifact,
        historical_artifact=manifest.inputs.historical_artifact,
        candidate_artifact=manifest.candidate_artifact,
        evaluation_neighbor_count=manifest.evaluation_neighbor_count,
        runs=tuple(results),
    )


def _require_unique_genre_ids(genre_ids: list[str], label: str) -> None:
    if len(set(genre_ids)) != len(genre_ids):
        raise ValueError(f"{label} genre IDs must be unique")


def _require_unique_evidence_refs(evidence_refs: tuple[EvidenceRef, ...]) -> None:
    if len(set(evidence_refs)) != len(evidence_refs):
        raise ValueError("evidence references must be unique")


def _count_shared_artist_pairs(
    artist_genres: dict[str, list[str]], parameters: SimilarityParameters
) -> tuple[dict[tuple[str, str], int], int]:
    shared_counts: dict[tuple[str, str], int] = defaultdict(int)
    pair_visit_count = 0
    for genres in artist_genres.values():
        ordered_genres = sorted(genres)
        for source_index, source_genre_id in enumerate(ordered_genres):
            for target_genre_id in ordered_genres[source_index + 1 :]:
                pair_visit_count += 1
                if pair_visit_count > parameters.max_pair_visits:
                    raise ValueError("artist overlap exceeds max_pair_visits")
                pair = (source_genre_id, target_genre_id)
                if (
                    pair not in shared_counts
                    and len(shared_counts) >= parameters.max_candidate_pairs
                ):
                    raise ValueError("artist overlap exceeds max_candidate_pairs")
                shared_counts[pair] += 1
    return shared_counts, pair_visit_count


def _vector_similarity(
    source: _GenreVector,
    target: _GenreVector,
    metric: SimilarityMetric,
) -> float:
    shared = source.weights.keys() & target.weights.keys()
    if metric is SimilarityMetric.WEIGHTED_JACCARD:
        intersection = sum(min(source.weights[key], target.weights[key]) for key in shared)
        union = source.weight_sum + target.weight_sum - intersection
        score = intersection / union if union else 0.0
    else:
        dot = sum(source.weights[key] * target.weights[key] for key in shared)
        score = dot / (source.norm * target.norm) if source.norm and target.norm else 0.0
    # Floating point accumulation can put a mathematically bounded score just
    # outside [0, 1], which would violate the typed edge contract.
    return min(1.0, max(0.0, score))


def _center(
    points: list[tuple[float, float]],
) -> tuple[list[tuple[float, float]], tuple[float, float]]:
    mean_x = sum(point[0] for point in points) / len(points)
    mean_y = sum(point[1] for point in points) / len(points)
    return ([(x - mean_x, y - mean_y) for x, y in points], (mean_x, mean_y))


def _axis_correlations(
    candidate: list[tuple[float, float]], historical: list[tuple[float, float]]
) -> AxisCorrelationResult:
    candidate_x = [point[0] for point in candidate]
    candidate_y = [point[1] for point in candidate]
    historical_x = [point[0] for point in historical]
    historical_y = [point[1] for point in historical]
    return AxisCorrelationResult(
        candidate_x_historical_x=_pearson(candidate_x, historical_x),
        candidate_x_historical_y=_pearson(candidate_x, historical_y),
        candidate_y_historical_x=_pearson(candidate_y, historical_x),
        candidate_y_historical_y=_pearson(candidate_y, historical_y),
    )


def _pearson(source: list[float], target: list[float]) -> float | None:
    source_mean = sum(source) / len(source)
    target_mean = sum(target) / len(target)
    source_centered = [value - source_mean for value in source]
    target_centered = [value - target_mean for value in target]
    source_sum_squares = sum(value * value for value in source_centered)
    target_sum_squares = sum(value * value for value in target_centered)
    denominator = math.sqrt(source_sum_squares * target_sum_squares)
    if denominator == 0.0:
        return None
    return (
        sum(
            source_value * target_value
            for source_value, target_value in zip(source_centered, target_centered, strict=True)
        )
        / denominator
    )


def _coordinate_neighbors(
    points: tuple[HistoricalGenrePoint, ...], neighbor_count: int
) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for source in points:
        distances = sorted(
            (
                (
                    (float(source.x) - float(target.x)) ** 2
                    + (float(source.y) - float(target.y)) ** 2,
                    target.genre_id,
                )
                for target in points
                if target.genre_id != source.genre_id
            ),
            key=lambda item: (item[0], item[1]),
        )
        result[source.genre_id] = tuple(genre_id for _, genre_id in distances[:neighbor_count])
    return result
