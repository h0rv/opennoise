"""Build a sealed, local-only MusicBrainz name-seed research graph.

The builder accepts direct MusicBrainz artist--genre evidence plus Every Noise
*names* as vocabulary seeds.  It deliberately rejects reconstruction inputs
that contain historical coordinates, historical memberships, or historical
neighbors.  Historical artifacts are readable only by ``evaluate_sealed_graph``
after a completed graph's bytes and declared hash agree.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, FiniteFloat, model_validator

from musix.evidence.reconstruction import ReconstructionInputs
from musix.ingest.musicbrainz.coverage import CoverageMatch, normalize_label
from musix.models import FrozenModel

if TYPE_CHECKING:
    from pathlib import Path

_REVISION: Final = "musicbrainz-name-seed-research-graph-v1"
_POLICY: Final = "CC-BY-NC-SA-3.0-local-research"
_MAX_NEIGHBORS: Final = 64
_MINIMUM_RMS: Final = 1e-12


class ResearchGraphBuildConfig(FrozenModel):
    """Bounded, explicit parameters for the graph and graph-only landscape."""

    expected_genre_count: int = Field(default=724, ge=1, le=10_000)
    max_neighbors: int = Field(default=12, ge=1, le=_MAX_NEIGHBORS)
    max_candidate_pairs: int = Field(default=250_000, ge=1, le=500_000)
    max_pair_visits: int = Field(default=2_000_000, ge=1, le=5_000_000)
    landscape_iterations: int = Field(default=80, ge=1, le=500)
    landscape_neighbor_limit: int = Field(default=12, ge=1, le=_MAX_NEIGHBORS)


class _SeedCoverageInput(FrozenModel):
    """The stable subset of the versioned coverage report needed by this builder."""

    source_key: str = Field(min_length=1, max_length=300)
    matches: tuple[CoverageMatch, ...] = Field(min_length=1, max_length=10_000)


class ResearchGraphInput(FrozenModel):
    """Hashed inputs and policy declaration for the local graph."""

    coverage_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reconstruction_inputs_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    research_database_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    membership_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    membership_artifact_key: str = Field(min_length=1, max_length=200)
    membership_artifact_revision: str = Field(min_length=1, max_length=200)
    source_policy: Literal["CC-BY-NC-SA-3.0-local-research"] = _POLICY
    name_seeds_only: Literal[True] = True
    historical_coordinates_excluded: Literal[True] = True
    historical_artist_assignments_excluded: Literal[True] = True
    historical_neighbors_excluded: Literal[True] = True
    audio_or_music_files_excluded: Literal[True] = True


class ResearchGenre(FrozenModel):
    """One MusicBrainz genre matched from a legacy name seed."""

    genre_id: str = Field(min_length=1, max_length=200)
    seed_name: str = Field(min_length=1, max_length=500)
    match_kind: Literal["exact", "normalized"]


class ResearchMembership(FrozenModel):
    """Direct positive source evidence, without historical artist assignments."""

    genre_id: str = Field(min_length=1, max_length=200)
    artist_id: str = Field(min_length=1, max_length=200)
    weight: FiniteFloat = Field(gt=0.0)
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=32)


class ResearchSimilarity(FrozenModel):
    """Both source-derived similarity measures for one undirected pair."""

    source_genre_id: str
    target_genre_id: str
    weighted_jaccard: FiniteFloat = Field(gt=0.0, le=1.0)
    weighted_cosine: FiniteFloat = Field(gt=0.0, le=1.0)
    shared_artist_count: int = Field(ge=1)


class ResearchNeighbor(FrozenModel):
    """A bounded ranking that retains both direct-overlap scores."""

    genre_id: str
    neighbor_genre_id: str
    rank: int = Field(ge=1, le=_MAX_NEIGHBORS)
    weighted_jaccard: FiniteFloat = Field(gt=0.0, le=1.0)
    weighted_cosine: FiniteFloat = Field(gt=0.0, le=1.0)
    shared_artist_count: int = Field(ge=1)


class ResearchLandscapePoint(FrozenModel):
    """Coordinate from graph topology and stable name-derived initial seeds only."""

    genre_id: str
    x: FiniteFloat
    y: FiniteFloat


class ResearchGraphQuality(FrozenModel):
    """Counts and replay guardrails for a completed local research artifact."""

    genre_count: int = Field(ge=1)
    membership_count: int = Field(ge=1)
    artist_count: int = Field(ge=1)
    sqlite_validated_evidence_ref_count: int = Field(ge=1)
    similarity_count: int = Field(ge=0)
    neighbor_count: int = Field(ge=0)
    landscape_point_count: int = Field(ge=1)
    candidate_pair_count: int = Field(ge=0)
    pair_visit_count: int = Field(ge=0)
    deterministic_replay: Literal[True] = True
    exportable_public_model: Literal[False] = False


class MusicBrainzResearchGraph(FrozenModel):
    """Sealed output that remains unavailable to the exportable public model."""

    revision: Literal["musicbrainz-name-seed-research-graph-v1"] = _REVISION
    publication_scope: Literal["local_research_only"] = "local_research_only"
    inputs: ResearchGraphInput
    config: ResearchGraphBuildConfig
    genres: tuple[ResearchGenre, ...] = Field(min_length=1, max_length=10_000)
    memberships: tuple[ResearchMembership, ...] = Field(min_length=1, max_length=500_000)
    similarities: tuple[ResearchSimilarity, ...] = Field(max_length=500_000)
    neighbors: tuple[ResearchNeighbor, ...] = Field(max_length=640_000)
    landscape: tuple[ResearchLandscapePoint, ...] = Field(min_length=1, max_length=10_000)
    quality: ResearchGraphQuality
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _require_closed_local_graph(self) -> MusicBrainzResearchGraph:
        genre_ids = {genre.genre_id for genre in self.genres}
        if len(genre_ids) != len(self.genres):
            raise ValueError("research graph genre IDs must be unique")
        if {item.genre_id for item in self.landscape} != genre_ids:
            raise ValueError("research landscape must place each graph genre exactly once")
        if any(item.genre_id not in genre_ids for item in self.memberships):
            raise ValueError("research memberships must target retained graph genres")
        if self.quality.genre_count != len(self.genres):
            raise ValueError("research graph quality genre count must match genres")
        if self.quality.membership_count != len(self.memberships):
            raise ValueError("research graph quality membership count must match memberships")
        return self


class ResearchGraphGate(FrozenModel):
    """A fail-closed construction report, separate from historical evaluation."""

    graph_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    passed: Literal[True] = True
    construction_input_fields: tuple[str, ...]
    prohibited_historical_fields: tuple[str, ...]
    local_research_only: Literal[True] = True
    exportable_public_model: Literal[False] = False


class SealedTopologyEvaluation(FrozenModel):
    """Topology-only historical comparison performed after graph sealing."""

    revision: Literal["musicbrainz-name-seed-topology-evaluation-v1"] = (
        "musicbrainz-name-seed-topology-evaluation-v1"
    )
    sealed_graph_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    historical_benchmark_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    overlap_by_normalized_name_count: int = Field(ge=0)
    graph_genre_count: int = Field(ge=1)
    historical_node_count: int = Field(ge=1)
    evaluated_genre_count: int = Field(ge=0)
    neighbor_count: int = Field(ge=1, le=_MAX_NEIGHBORS)
    mean_topology_recall: FiniteFloat = Field(ge=0.0, le=1.0)
    construction_artifact_unchanged: Literal[True] = True
    historical_coordinates_read: Literal[False] = False
    historical_artist_assignments_read: Literal[False] = False
    evaluation_reads_only: tuple[Literal["node genre_id/name", "neighbor genre_id/rank"], ...]


@dataclass(frozen=True, slots=True)
class _Vector:
    weights: dict[str, float]
    weight_sum: float
    norm: float


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _artifact_hash_without_output(graph: MusicBrainzResearchGraph) -> str:
    payload = graph.model_dump(mode="json", exclude={"output_sha256"})
    return _sha256(_canonical_bytes(payload))


def _read_json(path: Path) -> tuple[object, str]:
    payload = path.read_bytes()
    return json.loads(payload), _sha256(payload)


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_construction_inputs(
    coverage_path: Path, reconstruction_inputs_path: Path
) -> tuple[_SeedCoverageInput, ReconstructionInputs, str, str]:
    coverage_raw, coverage_sha = _read_json(coverage_path)
    reconstruction_raw, reconstruction_sha = _read_json(reconstruction_inputs_path)
    del coverage_raw, reconstruction_raw
    coverage = _SeedCoverageInput.model_validate_json(coverage_path.read_text(encoding="utf-8"))
    reconstruction = ReconstructionInputs.model_validate_json(
        reconstruction_inputs_path.read_text(encoding="utf-8")
    )
    if (
        reconstruction.historical_artifact is not None
        or reconstruction.historical_points
        or reconstruction.historical_neighbors
    ):
        raise ValueError("construction inputs must not carry historical observations")
    return coverage, reconstruction, coverage_sha, reconstruction_sha


def _verify_direct_evidence_in_sqlite(
    database_path: Path,
    source_key: str,
    memberships: tuple[ResearchMembership, ...],
) -> tuple[str, int]:
    """Read only evidence IDs from SQLite; reject a detached reconstruction JSON."""
    expected = {
        reference.removeprefix("musicbrainz:artist_genre_evidence:")
        for membership in memberships
        for reference in membership.evidence_refs
    }
    if len(expected) != sum(len(item.evidence_refs) for item in memberships):
        raise ValueError("direct membership evidence references must be globally unique")
    with closing(sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)) as connection:
        found = {
            str(row[0])
            for row in connection.execute(
                "SELECT id FROM artist_genre_evidence WHERE source_key = ? AND evidence_value > 0",
                (source_key,),
            )
        }
    if not expected <= found:
        raise ValueError(
            "reconstruction evidence references are not present in the research SQLite"
        )
    return _sha256_path(database_path), len(expected)


def build_musicbrainz_research_graph(
    coverage_path: Path,
    reconstruction_inputs_path: Path,
    research_database_path: Path,
    *,
    config: ResearchGraphBuildConfig | None = None,
) -> MusicBrainzResearchGraph:
    """Build the graph from seed-name matches and direct MusicBrainz evidence only."""
    config = config or ResearchGraphBuildConfig()
    coverage, reconstruction, coverage_sha, reconstruction_sha = _load_construction_inputs(
        coverage_path, reconstruction_inputs_path
    )
    genres_by_id: dict[str, ResearchGenre] = {}
    for match in coverage.matches:
        if match.match_kind == "exact":
            match_kind: Literal["exact", "normalized"] = "exact"
        elif match.match_kind == "normalized":
            match_kind = "normalized"
        else:
            raise ValueError("coverage match kind must be exact or normalized")
        for raw_genre_id in match.musicbrainz_genre_ids:
            genre_id = f"musicbrainz:genre:{raw_genre_id}"
            candidate = ResearchGenre(
                genre_id=genre_id, seed_name=match.seed_name, match_kind=match_kind
            )
            existing = genres_by_id.setdefault(genre_id, candidate)
            if existing != candidate:
                raise ValueError("a MusicBrainz genre cannot resolve to multiple name seeds")
    genres = tuple(sorted(genres_by_id.values(), key=lambda item: item.genre_id))
    if len(genres) != config.expected_genre_count:
        raise ValueError(
            f"expected {config.expected_genre_count} matched genres, found {len(genres)}"
        )
    memberships = tuple(
        ResearchMembership(
            genre_id=edge.genre_id,
            artist_id=edge.artist_id,
            weight=float(edge.weight),
            evidence_refs=edge.evidence_refs,
        )
        for edge in reconstruction.membership_edges
        if edge.genre_id in genres_by_id
    )
    if not memberships:
        raise ValueError("matched name seeds have no positive direct MusicBrainz evidence")
    if len({(edge.genre_id, edge.artist_id) for edge in memberships}) != len(memberships):
        raise ValueError("construction memberships must be pre-aggregated by genre and artist")
    database_sha, sqlite_validated_evidence_ref_count = _verify_direct_evidence_in_sqlite(
        research_database_path, coverage.source_key, memberships
    )
    similarities, pair_visits = _similarities(memberships, config)
    neighbors = _neighbors(genres, similarities, config.max_neighbors)
    landscape = _landscape(genres, neighbors, config)
    preliminary = MusicBrainzResearchGraph(
        inputs=ResearchGraphInput(
            coverage_sha256=coverage_sha,
            reconstruction_inputs_sha256=reconstruction_sha,
            research_database_sha256=database_sha,
            membership_artifact_sha256=reconstruction.membership_artifact.content_sha256,
            membership_artifact_key=reconstruction.membership_artifact.artifact_key,
            membership_artifact_revision=reconstruction.membership_artifact.revision,
        ),
        config=config,
        genres=genres,
        memberships=memberships,
        similarities=similarities,
        neighbors=neighbors,
        landscape=landscape,
        quality=ResearchGraphQuality(
            genre_count=len(genres),
            membership_count=len(memberships),
            artist_count=len({edge.artist_id for edge in memberships}),
            sqlite_validated_evidence_ref_count=sqlite_validated_evidence_ref_count,
            similarity_count=len(similarities),
            neighbor_count=len(neighbors),
            landscape_point_count=len(landscape),
            candidate_pair_count=len(similarities),
            pair_visit_count=pair_visits,
        ),
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(
        update={"output_sha256": _artifact_hash_without_output(preliminary)}
    )


def _similarities(
    memberships: tuple[ResearchMembership, ...], config: ResearchGraphBuildConfig
) -> tuple[tuple[ResearchSimilarity, ...], int]:
    vectors: dict[str, dict[str, float]] = defaultdict(dict)
    by_artist: dict[str, list[str]] = defaultdict(list)
    for edge in memberships:
        vectors[edge.genre_id][edge.artist_id] = float(edge.weight)
        by_artist[edge.artist_id].append(edge.genre_id)
    pairs: set[tuple[str, str]] = set()
    visits = 0
    for artist_id in sorted(by_artist):
        genre_ids = sorted(by_artist[artist_id])
        for left_index, left in enumerate(genre_ids):
            for right in genre_ids[left_index + 1 :]:
                visits += 1
                if visits > config.max_pair_visits:
                    raise ValueError("direct-overlap pair visits exceed configured cap")
                if (left, right) not in pairs and len(pairs) >= config.max_candidate_pairs:
                    raise ValueError("direct-overlap candidate pairs exceed configured cap")
                pairs.add((left, right))
    prepared = {
        genre_id: _Vector(
            weights=weights,
            weight_sum=sum(weights.values()),
            norm=math.sqrt(sum(weight * weight for weight in weights.values())),
        )
        for genre_id, weights in vectors.items()
    }
    results: list[ResearchSimilarity] = []
    for source, target in sorted(pairs):
        source_vector, target_vector = prepared[source], prepared[target]
        shared = source_vector.weights.keys() & target_vector.weights.keys()
        intersection = sum(
            min(source_vector.weights[artist_id], target_vector.weights[artist_id])
            for artist_id in shared
        )
        union = source_vector.weight_sum + target_vector.weight_sum - intersection
        dot = sum(
            source_vector.weights[artist_id] * target_vector.weights[artist_id]
            for artist_id in shared
        )
        jaccard = intersection / union if union else 0.0
        cosine = dot / (source_vector.norm * target_vector.norm)
        if jaccard > 0.0 and cosine > 0.0:
            results.append(
                ResearchSimilarity(
                    source_genre_id=source,
                    target_genre_id=target,
                    weighted_jaccard=jaccard,
                    weighted_cosine=cosine,
                    shared_artist_count=len(shared),
                )
            )
    return tuple(results), visits


def _neighbors(
    genres: tuple[ResearchGenre, ...],
    similarities: tuple[ResearchSimilarity, ...],
    limit: int,
) -> tuple[ResearchNeighbor, ...]:
    ranked: dict[str, list[tuple[str, ResearchSimilarity]]] = defaultdict(list)
    for item in similarities:
        ranked[item.source_genre_id].append((item.target_genre_id, item))
        ranked[item.target_genre_id].append((item.source_genre_id, item))
    output: list[ResearchNeighbor] = []
    for genre in genres:
        choices = sorted(
            ranked.get(genre.genre_id, ()),
            key=lambda item: (
                -float(item[1].weighted_jaccard),
                -float(item[1].weighted_cosine),
                -item[1].shared_artist_count,
                item[0],
            ),
        )[:limit]
        output.extend(
            ResearchNeighbor(
                genre_id=genre.genre_id,
                neighbor_genre_id=neighbor_id,
                rank=rank,
                weighted_jaccard=item.weighted_jaccard,
                weighted_cosine=item.weighted_cosine,
                shared_artist_count=item.shared_artist_count,
            )
            for rank, (neighbor_id, item) in enumerate(choices, start=1)
        )
    return tuple(output)


def _unit_seed(genre: ResearchGenre, axis: str) -> float:
    digest = hashlib.sha256(f"{axis}\0{genre.genre_id}\0{genre.seed_name}".encode()).digest()
    return (int.from_bytes(digest[:8], "big") / ((1 << 64) - 1)) * 2.0 - 1.0


def _landscape(
    genres: tuple[ResearchGenre, ...],
    neighbors: tuple[ResearchNeighbor, ...],
    config: ResearchGraphBuildConfig,
) -> tuple[ResearchLandscapePoint, ...]:
    """Diffuse deterministic name seeds across direct-overlap graph topology.

    This intentionally has no input channel for historical positions, artist-page
    assignments, or historical neighbor lists.  It is a compact, reproducible
    topology landscape rather than an assertion about the legacy coordinate axes.
    """
    by_id = {genre.genre_id: genre for genre in genres}
    adjacency: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for item in neighbors:
        if item.rank <= config.landscape_neighbor_limit:
            adjacency[item.genre_id].append((item.neighbor_genre_id, float(item.weighted_jaccard)))
    points = {genre.genre_id: (_unit_seed(genre, "x"), _unit_seed(genre, "y")) for genre in genres}
    for _ in range(config.landscape_iterations):
        updated: dict[str, tuple[float, float]] = {}
        for genre_id in sorted(by_id):
            nearby = adjacency.get(genre_id, ())
            x, y = points[genre_id]
            total = sum(weight for _, weight in nearby)
            if total:
                average_x = sum(points[neighbor][0] * weight for neighbor, weight in nearby) / total
                average_y = sum(points[neighbor][1] * weight for neighbor, weight in nearby) / total
                updated[genre_id] = (0.8 * x + 0.2 * average_x, 0.8 * y + 0.2 * average_y)
            else:
                updated[genre_id] = (x, y)
        points = _normalize_landscape(updated)
    return tuple(
        ResearchLandscapePoint(genre_id=genre_id, x=points[genre_id][0], y=points[genre_id][1])
        for genre_id in sorted(points)
    )


def _normalize_landscape(points: dict[str, tuple[float, float]]) -> dict[str, tuple[float, float]]:
    mean_x = sum(x for x, _ in points.values()) / len(points)
    mean_y = sum(y for _, y in points.values()) / len(points)
    rms = math.sqrt(
        sum((x - mean_x) ** 2 + (y - mean_y) ** 2 for x, y in points.values()) / len(points)
    )
    scale = rms if rms > _MINIMUM_RMS else 1.0
    return {
        genre_id: ((x - mean_x) / scale, (y - mean_y) / scale)
        for genre_id, (x, y) in points.items()
    }


def write_research_graph(path: Path, graph: MusicBrainzResearchGraph) -> str:
    """Write stable human-readable JSON and return the byte hash."""
    if graph.output_sha256 != _artifact_hash_without_output(graph):
        raise ValueError("research graph logical output hash does not match its content")
    payload = graph.model_dump_json(indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    return _sha256(payload.encode())


def build_gate(graph: MusicBrainzResearchGraph) -> ResearchGraphGate:
    """Validate construction-only policy invariants before any benchmark is read."""
    if graph.output_sha256 != _artifact_hash_without_output(graph):
        raise ValueError("research graph logical output hash does not match its content")
    return ResearchGraphGate(
        graph_sha256=graph.output_sha256,
        construction_input_fields=(
            "coverage seed_name/match_kind/musicbrainz_genre_ids",
            "MusicBrainz direct artist-genre evidence",
            "bounded weighted Jaccard/cosine overlap",
            "genre_id and seed_name hash landscape initialization",
        ),
        prohibited_historical_fields=(
            "H2/H3 coordinates",
            "historical artist assignments",
            "historical neighbors",
        ),
    )


def evaluate_sealed_graph(  # noqa: C901, PLR0912
    graph_path: Path,
    historical_benchmark_path: Path,
    *,
    expected_graph_sha256: str,
    neighbor_count: int = 10,
) -> SealedTopologyEvaluation:
    """Compare name overlap and neighbor topology only after sealing the graph.

    The benchmark is deliberately decoded as plain JSON and only ``nodes``
    ``genre_id/name`` and ``neighbors`` ``genre_id/neighbor_genre_id/rank`` are
    selected.  Coordinates and historical artist assignments are never read.
    """
    if not 1 <= neighbor_count <= _MAX_NEIGHBORS:
        raise ValueError(f"neighbor count must be between 1 and {_MAX_NEIGHBORS}")
    graph_raw, graph_byte_sha = _read_json(graph_path)
    del graph_raw
    graph = MusicBrainzResearchGraph.model_validate_json(graph_path.read_text(encoding="utf-8"))
    if graph.output_sha256 != expected_graph_sha256:
        raise ValueError("expected graph hash does not match sealed graph declaration")
    if graph.output_sha256 != _artifact_hash_without_output(graph):
        raise ValueError("sealed graph declaration does not match logical graph content")
    if not graph_byte_sha:
        raise ValueError("sealed graph must have nonempty bytes")
    benchmark_raw, benchmark_sha = _read_json(historical_benchmark_path)
    if not isinstance(benchmark_raw, dict):
        raise TypeError("historical benchmark must be a JSON object")
    raw_nodes = benchmark_raw.get("nodes")
    raw_neighbors = benchmark_raw.get("neighbors")
    if not isinstance(raw_nodes, list) or not isinstance(raw_neighbors, list):
        raise TypeError("historical benchmark needs nodes and neighbors lists")
    historical_name_to_id: dict[str, str] = {}
    for raw in raw_nodes:
        if not isinstance(raw, dict):
            continue
        genre_id, name = raw.get("genre_id"), raw.get("name")
        if isinstance(genre_id, str) and isinstance(name, str):
            key = normalize_label(name)
            if key in historical_name_to_id:
                historical_name_to_id[key] = ""
            else:
                historical_name_to_id[key] = genre_id
    graph_to_historical = {
        genre.genre_id: historical_name_to_id.get(normalize_label(genre.seed_name), "")
        for genre in graph.genres
    }
    graph_to_historical = {key: value for key, value in graph_to_historical.items() if value}
    historical_to_graph = {
        historical: graph_id for graph_id, historical in graph_to_historical.items()
    }
    benchmark_neighbors: dict[str, list[str]] = defaultdict(list)
    for raw in raw_neighbors:
        if not isinstance(raw, dict):
            continue
        source, target, rank = raw.get("genre_id"), raw.get("neighbor_genre_id"), raw.get("rank")
        if (
            isinstance(source, str)
            and isinstance(target, str)
            and isinstance(rank, int)
            and rank <= neighbor_count
        ):
            benchmark_neighbors[source].append(target)
    generated_neighbors: dict[str, list[str]] = defaultdict(list)
    for item in graph.neighbors:
        if item.rank <= neighbor_count:
            generated_neighbors[item.genre_id].append(item.neighbor_genre_id)
    recalls: list[float] = []
    for graph_id, historical_id in sorted(graph_to_historical.items()):
        expected = {
            historical_to_graph[target]
            for target in benchmark_neighbors.get(historical_id, ())
            if target in historical_to_graph
        }
        if not expected:
            continue
        actual = set(generated_neighbors.get(graph_id, ()))
        recalls.append(len(actual & expected) / len(expected))
    return SealedTopologyEvaluation(
        sealed_graph_sha256=graph.output_sha256,
        historical_benchmark_sha256=benchmark_sha,
        overlap_by_normalized_name_count=len(graph_to_historical),
        graph_genre_count=len(graph.genres),
        historical_node_count=len(historical_name_to_id),
        evaluated_genre_count=len(recalls),
        neighbor_count=neighbor_count,
        mean_topology_recall=sum(recalls) / len(recalls) if recalls else 0.0,
        evaluation_reads_only=("node genre_id/name", "neighbor genre_id/rank"),
    )
