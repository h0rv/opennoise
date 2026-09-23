"""Offline, aggregate-only evaluation of qualified ListenBrainz co-listens.

This module intentionally emits aggregate evaluation metrics only.  It does
not provide a neighbor lookup, retain ranked artist results, or make a
serving/API claim from the qualified aggregate source.
"""

from __future__ import annotations

import math
import sqlite3
import uuid
from collections import defaultdict
from collections.abc import Callable
from contextlib import closing
from typing import TYPE_CHECKING, Literal

from pydantic import Field, FiniteFloat

from opennoise.models import FrozenModel
from opennoise.types import (
    Sha256,  # noqa: TC001  # Pydantic resolves the alias at model definition.
)

if TYPE_CHECKING:
    from pathlib import Path

_REVISION = "listenbrainz-offline-co-listen-evaluation-v1"
_TRAIN_WINDOW_COUNT = 4
_RANKS = (10, 25)

type RankingMethod = Literal[
    "direct_genre_idf_weighted_jaccard",
    "train_common_neighbor_cosine",
    "train_degree_popularity",
]
type ScoreFunction = Callable[[str], dict[str, float]]


class ListenBrainzOfflineExperimentSettings(FrozenModel):
    """Fixed, time-ordered settings for the local aggregate experiment."""

    revision: Literal["listenbrainz-offline-co-listen-evaluation-settings-v1"] = (
        "listenbrainz-offline-co-listen-evaluation-settings-v1"
    )
    train_window_count: Literal[4] = _TRAIN_WINDOW_COUNT
    ranks: tuple[int, ...] = _RANKS
    evaluation_window_order: Literal["chronological", "reverse_chronological"] = "chronological"


class RankingMetrics(FrozenModel):
    """Aggregate retrieval metrics for novel held-out co-listen pairs."""

    method: RankingMethod
    query_count: int = Field(ge=0)
    reference_pair_count: int = Field(ge=0)
    scored_query_count: int = Field(ge=0)
    scored_reference_pair_count: int = Field(ge=0)
    hit_query_count_at_10: int = Field(ge=0)
    hit_rate_at_10: FiniteFloat = Field(ge=0.0, le=1.0)
    recall_at_10: FiniteFloat = Field(ge=0.0, le=1.0)
    hit_query_count_at_25: int = Field(ge=0)
    hit_rate_at_25: FiniteFloat = Field(ge=0.0, le=1.0)
    recall_at_25: FiniteFloat = Field(ge=0.0, le=1.0)


class ListenBrainzOfflineExperimentArtifact(FrozenModel):
    """Receipt-bound aggregate evaluation, not a serveable similarity model."""

    revision: Literal["listenbrainz-offline-co-listen-evaluation-v1"] = _REVISION
    source_kind: Literal["qualified_daily_aggregate"] = "qualified_daily_aggregate"
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    source_listenbrainz_database_sha256: Sha256
    source_public_database_sha256: Sha256
    settings: ListenBrainzOfflineExperimentSettings
    public_artist_crosswalk_count: int = Field(ge=0)
    source_window_count: int = Field(ge=0)
    train_window_count: int = Field(ge=0)
    heldout_window_count: int = Field(ge=0)
    train_pair_count: int = Field(ge=0)
    heldout_pair_count: int = Field(ge=0)
    novel_heldout_pair_count: int = Field(ge=0)
    novel_heldout_query_count: int = Field(ge=0)
    train_candidate_cohort_count: int = Field(ge=0)
    common_scored_query_count: int = Field(ge=0)
    common_scored_reference_pair_count: int = Field(ge=0)
    aggregate_support_definition: Literal["distinct_daily_windows"] = "distinct_daily_windows"
    direct_genre_side_information: Literal["fixed_transductive_snapshot"] = (
        "fixed_transductive_snapshot"
    )
    metrics: tuple[RankingMetrics, ...] = Field(min_length=3, max_length=3)
    common_scored_metrics: tuple[RankingMetrics, ...] = Field(min_length=3, max_length=3)


def evaluate_listenbrainz_offline_experiment(
    *,
    listenbrainz_path: Path,
    public_database_path: Path,
    listenbrainz_database_sha256: str,
    public_database_sha256: str,
    settings: ListenBrainzOfflineExperimentSettings | None = None,
) -> ListenBrainzOfflineExperimentArtifact:
    """Evaluate novel held-out aggregate pairs against train-only rankings.

    The ``reverse_chronological`` setting is a sensitivity arm, not a future-prediction
    claim: it reverses the same seven fixed daily windows before splitting.
    It permits a bounded check that the retrieval comparison is not dependent
    on only one chronological partition.  It never changes the source rows,
    their distinct-user privacy floor, or the aggregate-only boundary.
    """
    resolved_settings = settings or ListenBrainzOfflineExperimentSettings()
    crosswalk, genre_sets = _load_public_artist_inputs(public_database_path)
    windows = _load_public_co_listen_windows(listenbrainz_path, crosswalk)
    if resolved_settings.evaluation_window_order == "reverse_chronological":
        windows = tuple(reversed(windows))
    if len(windows) <= resolved_settings.train_window_count:
        raise ValueError("co-listen source needs at least one held-out window")
    train_windows = windows[: resolved_settings.train_window_count]
    heldout_windows = windows[resolved_settings.train_window_count :]
    train_pair_support = _pair_window_support(train_windows)
    train_pairs = set(train_pair_support)
    heldout_pairs = _pairs(heldout_windows)
    novel_heldout_pairs = heldout_pairs - train_pairs
    reference_by_artist = _references_by_artist(novel_heldout_pairs)
    train_adjacency = _adjacency(train_pair_support)
    candidate_cohort = frozenset(train_adjacency)
    rankers: tuple[tuple[RankingMethod, ScoreFunction], ...] = (
        (
            "direct_genre_idf_weighted_jaccard",
            _direct_genre_jaccard_scores(genre_sets, candidate_cohort),
        ),
        (
            "train_common_neighbor_cosine",
            _common_neighbor_cosine_scores(train_adjacency, candidate_cohort),
        ),
        ("train_degree_popularity", _degree_popularity_scores(train_adjacency, candidate_cohort)),
    )
    rankings = {
        method: _ranked_candidates(reference_by_artist, train_pairs, score)
        for method, score in rankers
    }
    metrics = tuple(
        _metrics_from_rankings(method, rankings[method], reference_by_artist)
        for method, _ in rankers
    )
    common_query_ids = frozenset.intersection(
        *(
            frozenset(artist_id for artist_id, ranking in rankings[method].items() if ranking)
            for method, _ in rankers
        )
    )
    common_references = {
        artist_id: references
        for artist_id, references in reference_by_artist.items()
        if artist_id in common_query_ids
    }
    common_scored_metrics = tuple(
        _metrics_from_rankings(method, rankings[method], common_references) for method, _ in rankers
    )
    return ListenBrainzOfflineExperimentArtifact(
        source_listenbrainz_database_sha256=listenbrainz_database_sha256,
        source_public_database_sha256=public_database_sha256,
        settings=resolved_settings,
        public_artist_crosswalk_count=len(crosswalk),
        source_window_count=len(windows),
        train_window_count=len(train_windows),
        heldout_window_count=len(heldout_windows),
        train_pair_count=len(train_pairs),
        heldout_pair_count=len(heldout_pairs),
        novel_heldout_pair_count=len(novel_heldout_pairs),
        novel_heldout_query_count=len(reference_by_artist),
        train_candidate_cohort_count=len(candidate_cohort),
        common_scored_query_count=len(common_references),
        common_scored_reference_pair_count=sum(
            len(values) for values in common_references.values()
        ),
        metrics=metrics,
        common_scored_metrics=common_scored_metrics,
    )


def _load_public_artist_inputs(path: Path) -> tuple[set[str], dict[str, frozenset[int]]]:
    with closing(_read_only(path)) as connection:
        crosswalk = {
            f"musicbrainz:artist:{artist_mbid}"
            for (artist_mbid,) in connection.execute(
                """SELECT identifier.value
                   FROM artists
                   JOIN entity_identifiers AS identifier ON identifier.entity_id = artists.id
                   JOIN identifier_types AS identifier_type
                     ON identifier_type.id = identifier.identifier_type_id
                   WHERE identifier_type.type_key = 'musicbrainz_artist_id'
                   ORDER BY identifier.value"""
            )
        }
        evidence_rows = connection.execute(
            """SELECT identifier.value, evidence.genre_id
               FROM displayable_artist_genre_evidence AS evidence
               JOIN entity_identifiers AS identifier ON identifier.entity_id = evidence.artist_id
               JOIN identifier_types AS identifier_type
                 ON identifier_type.id = identifier.identifier_type_id
               WHERE evidence.evidence_kind = 'direct_source_claim'
                 AND identifier_type.type_key = 'musicbrainz_artist_id'
               ORDER BY identifier.value, evidence.genre_id"""
        )
        mutable_genres: dict[str, set[int]] = defaultdict(set)
        for artist_mbid, genre_id in evidence_rows:
            mutable_genres[f"musicbrainz:artist:{artist_mbid}"].add(genre_id)
    return crosswalk, {key: frozenset(value) for key, value in mutable_genres.items()}


def _load_public_co_listen_windows(
    path: Path, crosswalk: set[str]
) -> tuple[frozenset[tuple[str, str]], ...]:
    with closing(_read_only(path)) as connection:
        rows = connection.execute(
            """SELECT window_start, left_artist_source_id, right_artist_source_id
               FROM artist_co_listen_evidence
               ORDER BY window_start, left_artist_source_id, right_artist_source_id"""
        )
        pairs_by_window: dict[int, set[tuple[str, str]]] = defaultdict(set)
        for window_start, left, right in rows:
            if not (_is_musicbrainz_artist_id(left) and _is_musicbrainz_artist_id(right)):
                raise ValueError(
                    "co-listen source pairs must contain canonical MusicBrainz artist IDs"
                )
            if left >= right:
                raise ValueError("co-listen source pairs must use ascending distinct artist IDs")
            if left in crosswalk and right in crosswalk:
                pairs_by_window[window_start].add((left, right))
    return tuple(frozenset(pairs_by_window[value]) for value in sorted(pairs_by_window))


def _pairs(windows: tuple[frozenset[tuple[str, str]], ...]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for window in windows:
        pairs.update(window)
    return pairs


def _pair_window_support(
    windows: tuple[frozenset[tuple[str, str]], ...],
) -> dict[tuple[str, str], int]:
    """Count distinct aggregate windows, never summed per-window user counts."""
    support: dict[tuple[str, str], int] = defaultdict(int)
    for window in windows:
        for pair in window:
            support[pair] += 1
    return dict(support)


def _references_by_artist(pairs: set[tuple[str, str]]) -> dict[str, frozenset[str]]:
    references: dict[str, set[str]] = defaultdict(set)
    for left, right in pairs:
        references[left].add(right)
        references[right].add(left)
    return {artist_id: frozenset(targets) for artist_id, targets in references.items()}


def _adjacency(pair_support: dict[tuple[str, str], int]) -> dict[str, dict[str, int]]:
    neighbors: dict[str, dict[str, int]] = defaultdict(dict)
    for (left, right), support in pair_support.items():
        neighbors[left][right] = support
        neighbors[right][left] = support
    return dict(neighbors)


def _direct_genre_jaccard_scores(
    genre_sets: dict[str, frozenset[int]], candidate_cohort: frozenset[str]
) -> ScoreFunction:
    """Prepare a fixed-side-information ranker over the declared train cohort."""
    document_frequency: dict[int, int] = defaultdict(int)
    by_genre: dict[int, set[str]] = defaultdict(set)
    for candidate_id in candidate_cohort:
        candidate_genres = genre_sets.get(candidate_id, frozenset())
        for genre_id in candidate_genres:
            document_frequency[genre_id] += 1
            by_genre[genre_id].add(candidate_id)
    artist_count = len(candidate_cohort)

    def weight(genre_id: int) -> float:
        return math.log((artist_count + 1) / (document_frequency[genre_id] + 1)) + 1.0

    def score(artist_id: str) -> dict[str, float]:
        genres = genre_sets.get(artist_id, frozenset())
        if not genres:
            return {}
        candidates = set().union(
            *(by_genre[genre_id] for genre_id in genres if genre_id in by_genre)
        )
        scores: dict[str, float] = {}
        for candidate_id in candidates - {artist_id}:
            candidate_genres = genre_sets[candidate_id]
            overlap = genres & candidate_genres
            numerator = sum(weight(genre_id) for genre_id in overlap)
            denominator = sum(weight(genre_id) for genre_id in genres | candidate_genres)
            if numerator and denominator:
                scores[candidate_id] = numerator / denominator
        return scores

    return score


def _common_neighbor_cosine_scores(
    adjacency: dict[str, dict[str, int]], candidate_cohort: frozenset[str]
) -> ScoreFunction:
    """Prepare train-only common-neighbor cosine scores over the fixed cohort."""

    def score(artist_id: str) -> dict[str, float]:
        neighbors = adjacency.get(artist_id, {})
        if not neighbors:
            return {}
        dot_products: dict[str, int] = defaultdict(int)
        for middle, source_weight in neighbors.items():
            for candidate_id, candidate_weight in adjacency.get(middle, {}).items():
                if candidate_id != artist_id and candidate_id in candidate_cohort:
                    dot_products[candidate_id] += source_weight * candidate_weight
        source_norm = math.sqrt(sum(weight * weight for weight in neighbors.values()))
        return {
            candidate_id: dot
            / (
                source_norm
                * math.sqrt(sum(weight * weight for weight in adjacency[candidate_id].values()))
            )
            for candidate_id, dot in dot_products.items()
        }

    return score


def _degree_popularity_scores(
    adjacency: dict[str, dict[str, int]], candidate_cohort: frozenset[str]
) -> ScoreFunction:
    """Prepare a train-only global-degree null ranker over the same cohort."""
    popularity = {
        candidate_id: float(sum(adjacency[candidate_id].values()))
        for candidate_id in candidate_cohort
    }

    def score(artist_id: str) -> dict[str, float]:
        return {
            candidate_id: value
            for candidate_id, value in popularity.items()
            if candidate_id != artist_id
        }

    return score


def _ranked_candidates(
    references_by_artist: dict[str, frozenset[str]],
    train_pairs: set[tuple[str, str]],
    score: ScoreFunction,
) -> dict[str, tuple[str, ...]]:
    rankings: dict[str, tuple[str, ...]] = {}
    for artist_id in references_by_artist:
        excluded = {
            right if left == artist_id else left
            for left, right in train_pairs
            if artist_id in (left, right)
        }
        rankings[artist_id] = tuple(
            candidate_id
            for candidate_id, _ in sorted(
                (
                    (candidate_id, value)
                    for candidate_id, value in score(artist_id).items()
                    if candidate_id not in excluded and candidate_id != artist_id
                ),
                key=lambda item: (-item[1], item[0]),
            )
        )
    return rankings


def _metrics_from_rankings(
    method: RankingMethod,
    rankings: dict[str, tuple[str, ...]],
    references_by_artist: dict[str, frozenset[str]],
) -> RankingMetrics:
    hits_by_rank = dict.fromkeys(_RANKS, 0)
    recovered_by_rank = dict.fromkeys(_RANKS, 0)
    scored_queries = 0
    scored_reference_pairs = 0
    for artist_id, references in references_by_artist.items():
        ranked = rankings[artist_id]
        if ranked:
            scored_queries += 1
            scored_reference_pairs += len(references)
        for rank in _RANKS:
            recovered = len(references & set(ranked[:rank]))
            recovered_by_rank[rank] += recovered
            hits_by_rank[rank] += int(recovered > 0)
    query_count = len(references_by_artist)
    reference_count = sum(len(values) for values in references_by_artist.values())
    return RankingMetrics(
        method=method,
        query_count=query_count,
        reference_pair_count=reference_count,
        scored_query_count=scored_queries,
        scored_reference_pair_count=scored_reference_pairs,
        hit_query_count_at_10=hits_by_rank[10],
        hit_rate_at_10=_ratio(hits_by_rank[10], query_count),
        recall_at_10=_ratio(recovered_by_rank[10], reference_count),
        hit_query_count_at_25=hits_by_rank[25],
        hit_rate_at_25=_ratio(hits_by_rank[25], query_count),
        recall_at_25=_ratio(recovered_by_rank[25], reference_count),
    )


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 12) if denominator else 0.0


def _read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)


def _is_musicbrainz_artist_id(value: str) -> bool:
    prefix = "musicbrainz:artist:"
    if not value.startswith(prefix):
        return False
    try:
        return str(uuid.UUID(value.removeprefix(prefix))) == value.removeprefix(prefix)
    except ValueError:
        return False
