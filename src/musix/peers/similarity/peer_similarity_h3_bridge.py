"""Evaluate sealed peer candidates against bridge-resolved H3 positives only."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from contextlib import closing
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from musix.models import FrozenModel
from musix.models.modeling import PublicModelInput
from musix.peers.similarity.peer_similarity import (
    GenrePeerSimilarityArtifact,
    PeerSimilaritySettings,
    evaluate_peer_similarity_gate,
)
from musix.peers.similarity.peer_similarity_historical import _candidate_neighbors
from musix.spotify_bridge_artifact import (
    iter_accepted_spotify_to_musicbrainz,
    load_receipted_musicbrainz_spotify_bridge,
)
from musix.taxonomy.seeds.genre_seed_universe import normalize_label
from musix.types import Sha256  # noqa: TC001

if TYPE_CHECKING:
    from pathlib import Path

_MAX_OBSERVATIONS = 350_000


class BridgePeerEvaluationSettings(FrozenModel):
    """Fixed bounds for a bridge-resolved positive-only peer evaluation."""

    revision: Literal["genre-peer-h3-bridge-evaluation-settings-v1"] = (
        "genre-peer-h3-bridge-evaluation-settings-v1"
    )
    k: Literal[25] = 25
    minimum_shared_artists: Literal[1] = 1
    maximum_h3_observations: int = Field(default=_MAX_OBSERVATIONS, ge=1, le=500_000)
    historical_inputs_used_for_construction: Literal[False] = False
    positive_only: Literal[True] = True


class BridgePeerEvaluationCoverage(FrozenModel):
    """Account for every H3 observation without treating absence as negative."""

    h3_observation_count: int = Field(ge=0)
    h3_mapped_positive_count: int = Field(ge=0)
    h3_unique_mapped_positive_count: int = Field(ge=0)
    h3_unique_mapped_artist_count: int = Field(ge=0)
    h3_unmapped_genre_observation_count: int = Field(ge=0)
    h3_unbridged_artist_observation_count: int = Field(ge=0)
    h3_conflicted_artist_observation_count: int = Field(ge=0)
    h3_positive_genre_count: int = Field(ge=0)
    candidate_genre_with_h3_positive_count: int = Field(ge=0)


class BridgePeerEvaluationMetrics(FrozenModel):
    """Top-k overlap against unranked, bridge-resolved H3 positives."""

    micro_overlap_count: int = Field(ge=0)
    historical_neighbor_reference_count: int = Field(ge=0)
    evaluated_genre_count: int = Field(ge=0)
    candidate_available_reference_count: int = Field(ge=0)
    candidate_available_evaluated_genre_count: int = Field(ge=0)
    micro_recall_at_25: float | None = Field(default=None, ge=0.0, le=1.0)
    macro_recall_at_25: float | None = Field(default=None, ge=0.0, le=1.0)
    conditional_micro_recall_at_25: float | None = Field(default=None, ge=0.0, le=1.0)
    precision_at_25: None = None
    precision_unavailable_reason: Literal["positive_only_h3_absences_are_unknown"] = (
        "positive_only_h3_absences_are_unknown"
    )


class BridgePeerEvaluationReport(FrozenModel):
    """A sealed H3-only evaluation report that cannot become construction input."""

    revision: Literal["genre-peer-h3-bridge-evaluation-v1"] = "genre-peer-h3-bridge-evaluation-v1"
    candidate_output_sha256: Sha256
    candidate_input_sha256: Sha256
    bridge_output_sha256: Sha256
    historical_database_sha256: Sha256
    settings: BridgePeerEvaluationSettings
    coverage: BridgePeerEvaluationCoverage
    metrics: BridgePeerEvaluationMetrics
    historical_inputs_used_for_construction: Literal[False] = False
    absence_is_negative: Literal[False] = False
    output_sha256: Sha256


def _sha(value: object) -> Sha256:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def report_sha256(report: BridgePeerEvaluationReport) -> Sha256:
    """Return the logical hash for one evaluation-only report."""
    return _sha(report.model_dump(mode="json", exclude={"output_sha256"}))


def _file_sha(path: Path) -> Sha256:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1_048_576):
            digest.update(chunk)
    return digest.hexdigest()


def _load_positives(
    database: Path,
    *,
    seed_by_name: dict[str, str],
    spotify_to_mbid: dict[str, str],
    conflicted: frozenset[str],
    maximum_observations: int,
) -> tuple[dict[str, set[str]], dict[str, int]]:
    """Read only direct H3 page members through exact accepted bridge IDs."""
    counters = dict.fromkeys(
        (
            "h3_observation_count",
            "h3_mapped_positive_count",
            "h3_unmapped_genre_observation_count",
            "h3_unbridged_artist_observation_count",
            "h3_conflicted_artist_observation_count",
        ),
        0,
    )
    positives: dict[str, set[str]] = defaultdict(set)
    query = """
        SELECT genre.name, observation.source_artist_id
          FROM historical_genre_artist_observations AS observation
          JOIN genres AS genre ON genre.id = observation.genre_id
         WHERE observation.observation_role = 'genre_page_member'
           AND observation.source_artist_id IS NOT NULL
         ORDER BY genre.name COLLATE NOCASE, observation.source_artist_id
    """
    with closing(sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)) as connection:
        for genre_name, spotify_id in connection.execute(query):
            counters["h3_observation_count"] += 1
            if counters["h3_observation_count"] > maximum_observations:
                raise ValueError("H3 observations exceed evaluation bound")
            seed = seed_by_name.get(normalize_label(str(genre_name)))
            if seed is None:
                counters["h3_unmapped_genre_observation_count"] += 1
            elif (mbid := spotify_to_mbid.get(str(spotify_id))) is not None:
                positives[seed].add(mbid)
                counters["h3_mapped_positive_count"] += 1
            elif str(spotify_id) in conflicted:
                counters["h3_conflicted_artist_observation_count"] += 1
            else:
                counters["h3_unbridged_artist_observation_count"] += 1
    return dict(positives), counters


def _historical_jaccard_neighbors(
    positives: dict[str, set[str]], *, k: int
) -> dict[str, tuple[str, ...]]:
    """Rank sparse H3 genre overlap by binary Jaccard with stable ID ties."""
    genres_by_artist: dict[str, list[str]] = defaultdict(list)
    for genre, artists in sorted(positives.items()):
        for artist in sorted(artists):
            genres_by_artist[artist].append(genre)
    shared: dict[tuple[str, str], int] = defaultdict(int)
    for genres in genres_by_artist.values():
        ordered = sorted(genres)
        for index, left in enumerate(ordered):
            for right in ordered[index + 1 :]:
                shared[(left, right)] += 1
    ranked: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for (left, right), count in shared.items():
        score = count / (len(positives[left]) + len(positives[right]) - count)
        ranked[left].append((right, score))
        ranked[right].append((left, score))
    return {
        genre: tuple(target for target, _ in sorted(values, key=lambda row: (-row[1], row[0]))[:k])
        for genre, values in ranked.items()
    }


def evaluate_peer_similarity_h3_bridge(  # noqa: PLR0913
    *,
    candidate_path: Path,
    public_input_path: Path,
    bridge_path: Path,
    bridge_receipt_path: Path,
    bridge_receipt_sha256: Sha256,
    historical_database_path: Path,
    settings: BridgePeerEvaluationSettings | None = None,
) -> BridgePeerEvaluationReport:
    """Compare a sealed peer graph with exact bridge-resolved H3 positives."""
    resolved = settings or BridgePeerEvaluationSettings()
    candidate = GenrePeerSimilarityArtifact.model_validate_json(candidate_path.read_bytes())
    public_input = PublicModelInput.model_validate_json(public_input_path.read_bytes())
    if candidate.input_sha256 != _sha(public_input.model_dump(mode="json")):
        raise ValueError("candidate input hash does not match public model input")
    gate = evaluate_peer_similarity_gate(candidate, public_input, PeerSimilaritySettings())
    if not gate.passed:
        raise ValueError("candidate peer gate failed")
    names: dict[str, list[str]] = defaultdict(list)
    for genre in public_input.genres:
        names[normalize_label(genre.name)].append(genre.genre_id)
    seed_by_name = {name: values[0] for name, values in names.items() if len(values) == 1}
    bridge = load_receipted_musicbrainz_spotify_bridge(
        bridge_path, bridge_receipt_path, bridge_receipt_sha256
    )
    try:
        accepted = dict(iter_accepted_spotify_to_musicbrainz(bridge))
        conflicted = frozenset(
            spotify_id
            for conflict in bridge.conflicts
            for spotify_id in conflict.spotify_artist_ids
        )
        positives, counters = _load_positives(
            historical_database_path,
            seed_by_name=seed_by_name,
            spotify_to_mbid=accepted,
            conflicted=conflicted,
            maximum_observations=resolved.maximum_h3_observations,
        )
    finally:
        bridge.close()
    if _file_sha(historical_database_path) != bridge.header.historical_database_sha256:
        raise ValueError("H3 database does not match bridge custody")
    historical_neighbors = _historical_jaccard_neighbors(positives, k=resolved.k)
    candidate_neighbors, _candidate_pairs = _candidate_neighbors(
        candidate, genre_ids=set(positives), k=resolved.k
    )
    overlap = 0
    positive_count = 0
    conditional_overlap = 0
    conditional_reference_count = 0
    conditional_genres = 0
    recalls: list[float] = []
    for seed in positives:
        targets = set(candidate_neighbors.get(seed, ()))
        reference = set(historical_neighbors.get(seed, ()))
        if not reference:
            continue
        hits = len(targets & reference)
        overlap += hits
        positive_count += len(reference)
        recalls.append(hits / len(reference))
        if targets:
            conditional_overlap += hits
            conditional_reference_count += len(reference)
            conditional_genres += 1
    coverage = BridgePeerEvaluationCoverage(
        **counters,
        h3_unique_mapped_positive_count=sum(len(rows) for rows in positives.values()),
        h3_unique_mapped_artist_count=len(set().union(*positives.values())) if positives else 0,
        h3_positive_genre_count=len(positives),
        candidate_genre_with_h3_positive_count=len(set(positives) & set(candidate_neighbors)),
    )
    preliminary = BridgePeerEvaluationReport(
        candidate_output_sha256=candidate.output_sha256,
        candidate_input_sha256=candidate.input_sha256,
        bridge_output_sha256=bridge.header.output_sha256,
        historical_database_sha256=bridge.header.historical_database_sha256,
        settings=resolved,
        coverage=coverage,
        metrics=BridgePeerEvaluationMetrics(
            micro_overlap_count=overlap,
            historical_neighbor_reference_count=positive_count,
            evaluated_genre_count=len(recalls),
            candidate_available_reference_count=conditional_reference_count,
            candidate_available_evaluated_genre_count=conditional_genres,
            micro_recall_at_25=overlap / positive_count if positive_count else None,
            macro_recall_at_25=sum(recalls) / len(recalls) if recalls else None,
            conditional_micro_recall_at_25=(
                conditional_overlap / conditional_reference_count
                if conditional_reference_count
                else None
            ),
        ),
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(update={"output_sha256": report_sha256(preliminary)})
