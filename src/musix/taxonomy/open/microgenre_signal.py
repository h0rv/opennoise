"""Source-neutral, review-only microgenre signal checkpoint.

The checkpoint accepts a small, typed open-evidence graph rather than a
source-specific database.  It evaluates deterministic *open-edge* holdouts
and combines only three transparent views: artist/genre weighted overlap,
positive PMI between genre memberships, and regional/era metadata overlap.
It is intentionally not a taxonomy publisher: every emitted edge is a review
candidate and every unscored edge is recorded as an abstention.

Historical Every Noise data are excluded at the contract boundary.  Its names
may be supplied as immutable vocabulary, but coordinates, memberships, and
neighbors have no fields here and any historical source reference is rejected.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, model_validator

from musix.models import FrozenModel

if TYPE_CHECKING:
    from pathlib import Path

_REVISION: Final = "microgenre-signal-checkpoint-v1"
_SETTINGS_REVISION: Final = "microgenre-signal-settings-v1"
_SHA: Final = r"^[0-9a-f]{64}$"
_HISTORICAL_TOKENS: Final = (
    "everynoise",
    "every_noise",
    "every noise",
    "historical",
    "spotify",
)

type NodeKind = Literal["genre", "artist"]
type GenreLevel = Literal["umbrella", "genre", "subgenre", "microgenre"]
type SignalRelation = Literal["membership", "similarity", "hierarchy", "lineage"]
type CandidateStatus = Literal["heldout_open_edge", "unconfirmed_open_candidate"]
type AbstentionReason = Literal["below_threshold", "no_train_signal", "cycle_prevented"]


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _split(identifier: str, settings: MicrogenreSignalSettings) -> bool:
    """Select a stable held-out edge without consulting its value or source row."""
    value = int(hashlib.sha256(f"{settings.split_seed}:{identifier}".encode()).hexdigest()[:16], 16)
    return value / (2**64) < settings.heldout_fraction


def _weighted_jaccard(left: dict[str, float], right: dict[str, float]) -> float:
    keys = set(left) | set(right)
    denominator = sum(max(left.get(key, 0.0), right.get(key, 0.0)) for key in keys)
    if denominator == 0.0:
        return 0.0
    return sum(min(left.get(key, 0.0), right.get(key, 0.0)) for key in keys) / denominator


def _set_jaccard(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    left_values, right_values = set(left), set(right)
    union = left_values | right_values
    return len(left_values & right_values) / len(union) if union else 0.0


def _label_overlap(left: str, right: str) -> float:
    return _set_jaccard(tuple(left.casefold().split()), tuple(right.casefold().split()))


class OpenEvidenceRef(FrozenModel):
    """One public, independently reviewable source row supporting an input edge."""

    source_id: str = Field(min_length=1, max_length=120)
    record_id: str = Field(min_length=1, max_length=500)
    weight: float = Field(default=1.0, gt=0.0, le=1_000.0)

    @model_validator(mode="after")
    def _not_historical(self) -> OpenEvidenceRef:
        source = self.source_id.casefold()
        if any(token in source for token in _HISTORICAL_TOKENS):
            raise ValueError("historical and Spotify sources are prohibited in construction")
        return self


class OpenSignalNode(FrozenModel):
    """A source-neutral artist or granular genre label with open metadata facets."""

    node_id: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=500)
    kind: NodeKind
    # Evaluation-only target stratum; construction deliberately never reads it.
    evaluation_level: GenreLevel | None = None
    regions: tuple[str, ...] = Field(default=(), max_length=16)
    eras: tuple[str, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def _evaluation_level_matches_kind(self) -> OpenSignalNode:
        if self.kind == "artist" and self.evaluation_level is not None:
            raise ValueError("artist nodes cannot declare an evaluation-only genre level")
        return self


class OpenSignalEdge(FrozenModel):
    """A positive open-evidence edge, never an inferred output edge."""

    edge_id: str = Field(min_length=1, max_length=200)
    relation: SignalRelation
    source_id: str = Field(min_length=1, max_length=200)
    target_id: str = Field(min_length=1, max_length=200)
    evidence: tuple[OpenEvidenceRef, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def _non_self(self) -> OpenSignalEdge:
        if self.source_id == self.target_id:
            raise ValueError("open evidence edges cannot be self edges")
        if self.relation == "similarity" and self.source_id > self.target_id:
            raise ValueError("similarity edges must use canonical endpoint order")
        return self

    @property
    def weight(self) -> float:
        """Collapse multiple independent refs into one bounded positive weight."""
        return sum(reference.weight for reference in self.evidence)


class SourceNeutralMicrogenreInput(FrozenModel):
    """Sealed source-neutral graph input for one checkpoint run."""

    revision: Literal["source-neutral-microgenre-input-v1"] = "source-neutral-microgenre-input-v1"
    immutable_legacy_names: tuple[str, ...] = Field(default=(), max_length=10_000)
    legacy_names_only: Literal[True] = True
    nodes: tuple[OpenSignalNode, ...] = Field(min_length=1, max_length=100_000)
    edges: tuple[OpenSignalEdge, ...] = Field(min_length=1, max_length=1_000_000)
    historical_inputs_read: Literal[False] = False
    input_sha256: str = Field(pattern=_SHA)

    @model_validator(mode="after")
    def _valid_graph(self) -> SourceNeutralMicrogenreInput:  # noqa: C901
        nodes = {node.node_id: node for node in self.nodes}
        if len(nodes) != len(self.nodes):
            raise ValueError("node IDs must be unique")
        if len({edge.edge_id for edge in self.edges}) != len(self.edges):
            raise ValueError("edge IDs must be unique")
        if len(set(self.immutable_legacy_names)) != len(self.immutable_legacy_names):
            raise ValueError("immutable legacy names must be unique")
        for edge in self.edges:
            source, target = nodes.get(edge.source_id), nodes.get(edge.target_id)
            if source is None or target is None:
                raise ValueError(f"edge {edge.edge_id} references an unknown node")
            if edge.relation == "membership" and (source.kind, target.kind) != ("genre", "artist"):
                raise ValueError("membership must point from genre to artist")
            if edge.relation == "similarity" and (source.kind, target.kind) != ("artist", "artist"):
                raise ValueError("similarity must connect artists")
            if edge.relation in {"hierarchy", "lineage"} and (
                source.kind != "genre" or target.kind != "genre"
            ):
                raise ValueError("hierarchy and lineage must connect genres")
        hierarchy: dict[str, set[str]] = defaultdict(set)
        for edge in self.edges:
            if edge.relation == "hierarchy":
                if _would_cycle(hierarchy, edge.source_id, edge.target_id):
                    raise ValueError("open hierarchy evidence must be acyclic")
                hierarchy[edge.source_id].add(edge.target_id)
        if self.input_sha256 != source_neutral_input_sha256(self):
            raise ValueError("source-neutral input hash does not replay")
        return self


class MicrogenreSignalSettings(FrozenModel):
    """Small deterministic controls for the transparent multi-view baseline."""

    revision: Literal["microgenre-signal-settings-v1"] = _SETTINGS_REVISION
    split_seed: int = Field(default=20260913, ge=0)
    heldout_fraction: float = Field(default=0.25, gt=0.0, lt=0.9)
    score_threshold: float = Field(default=0.35, ge=0.0, le=1.0)
    evaluation_k: int = Field(default=10, ge=1, le=100)
    max_generated_candidates_per_relation: int = Field(default=500, ge=0, le=10_000)


class MultiViewScore(FrozenModel):
    """Inspectable source-neutral feature values for a proposed relation."""

    weighted_overlap: float = Field(ge=0.0, le=1.0)
    ppmi_association: float = Field(ge=0.0, le=1.0)
    propagation_support: float = Field(ge=0.0, le=1.0)
    regional_era_overlap: float = Field(ge=0.0, le=1.0)


class MicrogenreSignalPrediction(FrozenModel):
    """A review-only reconstruction candidate with no membership promotion semantics."""

    relation: SignalRelation
    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)
    views: MultiViewScore
    evaluation_status: CandidateStatus
    disposition: Literal["review_candidate"] = "review_candidate"


class MicrogenreSignalAbstention(FrozenModel):
    """A candidate pair deliberately not emitted as a relation claim."""

    relation: SignalRelation
    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)
    reason: AbstentionReason
    evaluation_status: CandidateStatus


class HeldoutOpenEdgeMetrics(FrozenModel):
    """Positive-only evaluation of one relation against a frozen open-edge split."""

    relation: SignalRelation
    open_edge_count: int = Field(ge=0)
    heldout_open_edge_count: int = Field(ge=0)
    scoreable_heldout_edge_count: int = Field(ge=0)
    emitted_candidate_count: int = Field(ge=0)
    recovered_heldout_edge_count: int = Field(ge=0)
    abstained_heldout_edge_count: int = Field(ge=0)
    unconfirmed_emitted_candidate_count: int = Field(ge=0)
    heldout_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    heldout_recall: float | None = Field(default=None, ge=0.0, le=1.0)
    heldout_positive_hit_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    heldout_positive_hit_rate_at_k: float | None = Field(default=None, ge=0.0, le=1.0)
    heldout_recall_at_k: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _accounting(self) -> HeldoutOpenEdgeMetrics:
        if (
            self.recovered_heldout_edge_count + self.abstained_heldout_edge_count
            != self.heldout_open_edge_count
        ):
            raise ValueError("held-out recovery and abstention must account for every open edge")
        if self.emitted_candidate_count != (
            self.recovered_heldout_edge_count + self.unconfirmed_emitted_candidate_count
        ):
            raise ValueError("emitted candidate accounting does not replay")
        return self


class MicrogenreSignalCoverage(FrozenModel):
    """Full graph, candidate, and overlapping-hierarchy coverage accounting."""

    node_count: int = Field(ge=1)
    immutable_legacy_name_count: int = Field(ge=0)
    open_edge_count: int = Field(ge=1)
    train_open_edge_count: int = Field(ge=0)
    heldout_open_edge_count: int = Field(ge=0)
    candidate_pair_count: int = Field(ge=0)
    emitted_candidate_count: int = Field(ge=0)
    abstained_candidate_count: int = Field(ge=0)
    overlapping_hierarchy_child_count: int = Field(ge=0)
    historical_inputs_read: Literal[False] = False
    historical_coordinates_read: Literal[False] = False
    historical_memberships_read: Literal[False] = False
    historical_neighbors_read: Literal[False] = False

    @model_validator(mode="after")
    def _candidate_accounting(self) -> MicrogenreSignalCoverage:
        if self.train_open_edge_count + self.heldout_open_edge_count != self.open_edge_count:
            raise ValueError("train and held-out edges must account for open input edges")
        if (
            self.emitted_candidate_count + self.abstained_candidate_count
            != self.candidate_pair_count
        ):
            raise ValueError("predictions and abstentions must account for candidate pairs")
        return self


class MicrogenreSignalArtifact(FrozenModel):
    """Replayable review layer; not a map, taxonomy, or historical reconstruction."""

    revision: Literal["microgenre-signal-checkpoint-v1"] = _REVISION
    input_sha256: str = Field(pattern=_SHA)
    settings: MicrogenreSignalSettings
    settings_sha256: str = Field(pattern=_SHA)
    relation_metrics: tuple[HeldoutOpenEdgeMetrics, ...] = Field(min_length=4, max_length=4)
    predictions: tuple[MicrogenreSignalPrediction, ...]
    abstentions: tuple[MicrogenreSignalAbstention, ...]
    coverage: MicrogenreSignalCoverage
    historical_inputs_read: Literal[False] = False
    output_sha256: str = Field(pattern=_SHA)

    @model_validator(mode="after")
    def _complete(self) -> MicrogenreSignalArtifact:
        if {metric.relation for metric in self.relation_metrics} != {
            "membership",
            "similarity",
            "hierarchy",
            "lineage",
        }:
            raise ValueError("artifact must account for all four relation views")
        if len(self.predictions) != self.coverage.emitted_candidate_count:
            raise ValueError("prediction count does not match coverage")
        if len(self.abstentions) != self.coverage.abstained_candidate_count:
            raise ValueError("abstention count does not match coverage")
        return self


def source_neutral_input_sha256(value: SourceNeutralMicrogenreInput) -> str:
    """Hash source data excluding the self-referential input fingerprint."""
    return _sha(value.model_dump(mode="json", exclude={"input_sha256"}))


def microgenre_signal_settings_sha256(settings: MicrogenreSignalSettings) -> str:
    """Hash all baseline controls, including deterministic split controls."""
    return _sha(settings.model_dump(mode="json"))


def microgenre_signal_artifact_sha256(artifact: MicrogenreSignalArtifact) -> str:
    """Hash logical output fields excluding the self-referential output hash."""
    return _sha(artifact.model_dump(mode="json", exclude={"output_sha256"}))


def load_source_neutral_microgenre_input(path: Path) -> SourceNeutralMicrogenreInput:
    """Load one sealed generic evidence graph without any database dependency."""
    return SourceNeutralMicrogenreInput.model_validate_json(path.read_text(encoding="utf-8"))


def _edge_key(relation: SignalRelation, source_id: str, target_id: str) -> tuple[str, str, str]:
    return relation, source_id, target_id


def _candidate_pairs(
    graph: SourceNeutralMicrogenreInput,
    relation: SignalRelation,
    heldout: tuple[OpenSignalEdge, ...],
    settings: MicrogenreSignalSettings,
) -> tuple[tuple[str, str, CandidateStatus], ...]:
    genres = tuple(sorted(node.node_id for node in graph.nodes if node.kind == "genre"))
    artists = tuple(sorted(node.node_id for node in graph.nodes if node.kind == "artist"))
    if relation == "membership":
        universe = ((genre, artist) for genre in genres for artist in artists)
    elif relation == "similarity":
        universe = combinations(artists, 2)
    elif relation == "hierarchy":
        # Granularity is optional source metadata, never a construction feature.
        # Score all directed genre pairs and keep the emitted review layer acyclic.
        universe = ((parent, child) for parent in genres for child in genres if parent != child)
    else:
        universe = ((source, target) for source in genres for target in genres if source != target)
    known = {_edge_key(edge.relation, edge.source_id, edge.target_id) for edge in graph.edges}
    heldout_pairs = {(edge.source_id, edge.target_id) for edge in heldout}
    unknown = [
        (source, target)
        for source, target in universe
        if _edge_key(relation, source, target) not in known
        and (source, target) not in heldout_pairs
    ]
    chosen_unknown = sorted(
        unknown,
        key=lambda pair: hashlib.sha256(
            f"{settings.split_seed}:{relation}:{pair[0]}:{pair[1]}".encode()
        ).hexdigest(),
    )[: settings.max_generated_candidates_per_relation]
    return tuple(
        sorted(
            [(edge.source_id, edge.target_id, "heldout_open_edge") for edge in heldout]
            + [(source, target, "unconfirmed_open_candidate") for source, target in chosen_unknown],
            key=lambda row: (row[0], row[1], row[2]),
        )
    )


def _training_memberships(
    edges: tuple[OpenSignalEdge, ...],
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    genre_artists: dict[str, dict[str, float]] = defaultdict(dict)
    artist_genres: dict[str, dict[str, float]] = defaultdict(dict)
    for edge in edges:
        if edge.relation == "membership":
            genre_artists[edge.source_id][edge.target_id] = edge.weight
            artist_genres[edge.target_id][edge.source_id] = edge.weight
    return genre_artists, artist_genres


def _ppmi(genre_artists: dict[str, dict[str, float]]) -> dict[tuple[str, str], float]:
    marginals = {genre: sum(artists.values()) for genre, artists in genre_artists.items()}
    total = sum(marginals.values())
    values: dict[tuple[str, str], float] = {}
    if total == 0.0:
        return values
    for left, right in combinations(sorted(genre_artists), 2):
        shared = sum(
            min(genre_artists[left][artist], genre_artists[right][artist])
            for artist in set(genre_artists[left]) & set(genre_artists[right])
        )
        if shared:
            raw = math.log((shared * total) / (marginals[left] * marginals[right]))
            values[left, right] = max(0.0, raw)
    scale = max(values.values(), default=0.0)
    return {key: value / scale if scale else 0.0 for key, value in values.items()}


def _membership_score(  # noqa: PLR0913, PLR0917
    genre: str,
    artist: str,
    genre_artists: dict[str, dict[str, float]],
    artist_genres: dict[str, dict[str, float]],
    ppmi: dict[tuple[str, str], float],
    similarities: dict[str, dict[str, float]],
) -> MultiViewScore:
    known_genres = artist_genres.get(artist, {})
    ppmi_support = max(
        (ppmi.get(tuple(sorted((genre, other))), 0.0) for other in known_genres if other != genre),
        default=0.0,
    )
    neighbors = similarities.get(artist, {})
    denominator = sum(neighbors.values())
    propagation = (
        sum(
            weight * genre_artists.get(genre, {}).get(neighbor, 0.0)
            for neighbor, weight in neighbors.items()
        )
        / denominator
        if denominator
        else 0.0
    )
    propagation = min(1.0, propagation)
    overlap = _weighted_jaccard(known_genres, {genre: 1.0})
    return MultiViewScore(
        weighted_overlap=overlap,
        ppmi_association=ppmi_support,
        propagation_support=propagation,
        regional_era_overlap=0.0,
    )


def _similarity_score(
    left: str, right: str, artist_genres: dict[str, dict[str, float]]
) -> MultiViewScore:
    return MultiViewScore(
        weighted_overlap=_weighted_jaccard(
            artist_genres.get(left, {}), artist_genres.get(right, {})
        ),
        ppmi_association=0.0,
        propagation_support=0.0,
        regional_era_overlap=0.0,
    )


def _genre_score(
    relation: SignalRelation,
    source: OpenSignalNode,
    target: OpenSignalNode,
    genre_artists: dict[str, dict[str, float]],
) -> MultiViewScore:
    membership_overlap = _weighted_jaccard(
        genre_artists.get(source.node_id, {}), genre_artists.get(target.node_id, {})
    )
    regional_era = 0.5 * _set_jaccard(source.regions, target.regions) + 0.5 * _set_jaccard(
        source.eras, target.eras
    )
    if relation == "hierarchy":
        parent, child = genre_artists.get(source.node_id, {}), genre_artists.get(target.node_id, {})
        containment = (
            sum(min(parent.get(artist, 0.0), weight) for artist, weight in child.items())
            / sum(child.values())
            if child
            else 0.0
        )
        return MultiViewScore(
            weighted_overlap=containment,
            ppmi_association=_label_overlap(source.label, target.label),
            propagation_support=membership_overlap,
            regional_era_overlap=regional_era,
        )
    return MultiViewScore(
        weighted_overlap=membership_overlap,
        ppmi_association=0.0,
        propagation_support=0.0,
        regional_era_overlap=regional_era,
    )


def _combined_score(relation: SignalRelation, views: MultiViewScore) -> float:
    if relation == "membership":
        return (
            0.15 * views.weighted_overlap
            + 0.45 * views.ppmi_association
            + 0.4 * views.propagation_support
        )
    if relation == "hierarchy":
        return (
            0.45 * views.weighted_overlap
            + 0.2 * views.ppmi_association
            + 0.2 * views.propagation_support
            + 0.15 * views.regional_era_overlap
        )
    if relation == "lineage":
        return 0.55 * views.weighted_overlap + 0.45 * views.regional_era_overlap
    return views.weighted_overlap


def _would_cycle(parents: dict[str, set[str]], source_id: str, target_id: str) -> bool:
    """Return whether adding source -> target would introduce a directed cycle."""
    pending = [target_id]
    visited: set[str] = set()
    while pending:
        current = pending.pop()
        if current == source_id:
            return True
        if current not in visited:
            visited.add(current)
            pending.extend(parents.get(current, ()))
    return False


def build_microgenre_signal_checkpoint(  # noqa: C901, PLR0912
    graph: SourceNeutralMicrogenreInput,
    settings: MicrogenreSignalSettings | None = None,
) -> MicrogenreSignalArtifact:
    """Evaluate a source-neutral graph with no historical input or promotion path."""
    # Re-validate before every build, including callers that constructed models in memory.
    graph = SourceNeutralMicrogenreInput.model_validate_json(graph.model_dump_json())
    resolved = settings or MicrogenreSignalSettings()
    train_edges = tuple(edge for edge in graph.edges if not _split(edge.edge_id, resolved))
    heldout_by_relation: dict[SignalRelation, tuple[OpenSignalEdge, ...]] = {
        relation: tuple(
            edge
            for edge in graph.edges
            if edge.relation == relation and _split(edge.edge_id, resolved)
        )
        for relation in ("membership", "similarity", "hierarchy", "lineage")
    }
    nodes = {node.node_id: node for node in graph.nodes}
    genre_artists, artist_genres = _training_memberships(train_edges)
    ppmi = _ppmi(genre_artists)
    similarities: dict[str, dict[str, float]] = defaultdict(dict)
    for edge in train_edges:
        if edge.relation == "similarity":
            similarities[edge.source_id][edge.target_id] = edge.weight
            similarities[edge.target_id][edge.source_id] = edge.weight

    predictions: list[MicrogenreSignalPrediction] = []
    abstentions: list[MicrogenreSignalAbstention] = []
    metrics: list[HeldoutOpenEdgeMetrics] = []
    accepted_hierarchy: dict[str, set[str]] = defaultdict(set)
    for relation in ("membership", "similarity", "hierarchy", "lineage"):
        candidates = _candidate_pairs(graph, relation, heldout_by_relation[relation], resolved)
        emitted = recovered = abstained_heldout = unconfirmed = scoreable = 0
        scored: list[tuple[float, str, str, CandidateStatus]] = []
        for source_id, target_id, status in candidates:
            if relation == "membership":
                views = _membership_score(
                    source_id, target_id, genre_artists, artist_genres, ppmi, similarities
                )
            elif relation == "similarity":
                views = _similarity_score(source_id, target_id, artist_genres)
            else:
                views = _genre_score(relation, nodes[source_id], nodes[target_id], genre_artists)
            score = _combined_score(relation, views)
            scored.append((score, source_id, target_id, status))
            scoreable += status == "heldout_open_edge" and score > 0.0
            cycle_prevented = relation == "hierarchy" and _would_cycle(
                accepted_hierarchy, source_id, target_id
            )
            if score >= resolved.score_threshold and not cycle_prevented:
                predictions.append(
                    MicrogenreSignalPrediction(
                        relation=relation,
                        source_id=source_id,
                        target_id=target_id,
                        score=score,
                        views=views,
                        evaluation_status=status,
                    )
                )
                emitted += 1
                if status == "heldout_open_edge":
                    recovered += 1
                else:
                    unconfirmed += 1
                if relation == "hierarchy":
                    accepted_hierarchy[source_id].add(target_id)
            else:
                abstentions.append(
                    MicrogenreSignalAbstention(
                        relation=relation,
                        source_id=source_id,
                        target_id=target_id,
                        score=score,
                        reason=(
                            "cycle_prevented"
                            if cycle_prevented
                            else "no_train_signal"
                            if score == 0.0
                            else "below_threshold"
                        ),
                        evaluation_status=status,
                    )
                )
                abstained_heldout += status == "heldout_open_edge"
        heldout_count = len(heldout_by_relation[relation])
        top_k = sorted(scored, key=lambda row: (-row[0], row[1], row[2]))[: resolved.evaluation_k]
        top_k_confirmed = sum(status == "heldout_open_edge" for _, _, _, status in top_k)
        metrics.append(
            HeldoutOpenEdgeMetrics(
                relation=relation,
                open_edge_count=sum(edge.relation == relation for edge in graph.edges),
                heldout_open_edge_count=heldout_count,
                scoreable_heldout_edge_count=scoreable,
                emitted_candidate_count=emitted,
                recovered_heldout_edge_count=recovered,
                abstained_heldout_edge_count=abstained_heldout,
                unconfirmed_emitted_candidate_count=unconfirmed,
                heldout_coverage=scoreable / heldout_count if heldout_count else None,
                heldout_recall=recovered / heldout_count if heldout_count else None,
                heldout_positive_hit_rate=recovered / emitted if emitted else None,
                heldout_positive_hit_rate_at_k=top_k_confirmed / len(top_k) if top_k else None,
                heldout_recall_at_k=top_k_confirmed / heldout_count if heldout_count else None,
            )
        )
    hierarchy_parents: dict[str, set[str]] = defaultdict(set)
    for prediction in predictions:
        if prediction.relation == "hierarchy":
            hierarchy_parents[prediction.target_id].add(prediction.source_id)
    coverage = MicrogenreSignalCoverage(
        node_count=len(graph.nodes),
        immutable_legacy_name_count=len(graph.immutable_legacy_names),
        open_edge_count=len(graph.edges),
        train_open_edge_count=len(train_edges),
        heldout_open_edge_count=len(graph.edges) - len(train_edges),
        candidate_pair_count=len(predictions) + len(abstentions),
        emitted_candidate_count=len(predictions),
        abstained_candidate_count=len(abstentions),
        overlapping_hierarchy_child_count=sum(
            len(parents) > 1 for parents in hierarchy_parents.values()
        ),
    )
    preliminary = MicrogenreSignalArtifact(
        input_sha256=graph.input_sha256,
        settings=resolved,
        settings_sha256=microgenre_signal_settings_sha256(resolved),
        relation_metrics=tuple(metrics),
        predictions=tuple(predictions),
        abstentions=tuple(abstentions),
        coverage=coverage,
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(
        update={"output_sha256": microgenre_signal_artifact_sha256(preliminary)}
    )


def verify_microgenre_signal_checkpoint(artifact: MicrogenreSignalArtifact) -> None:
    """Fail closed when settings or logical output has changed after construction."""
    if artifact.settings_sha256 != microgenre_signal_settings_sha256(artifact.settings):
        raise ValueError("microgenre signal settings hash does not replay")
    if artifact.output_sha256 != microgenre_signal_artifact_sha256(artifact):
        raise ValueError("microgenre signal artifact hash does not replay")
