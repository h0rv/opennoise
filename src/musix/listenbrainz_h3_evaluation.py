"""Positive-only H3 evaluation of sealed ListenBrainz review candidates.

This module is intentionally downstream of the sealed v5 frontier.  It never
writes candidates back to the frontier and H3 is not an input to construction.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import ijson
from pydantic import BaseModel, ConfigDict, Field, model_validator

from musix.evidence.evidence_frontier import AllSeedEvidenceFrontierArtifact, EvidenceFrontierReceipt
from musix.taxonomy.genre_seed_universe import normalize_label
from musix.listenbrainz_propagation import ListenBrainzPropagationReceipt
from musix.models import FrozenModel
from musix.spotify_bridge_artifact import (
    iter_accepted_spotify_to_musicbrainz,
    load_receipted_musicbrainz_spotify_bridge,
)
from musix.storage import ObjectKey, ObjectStore, ObjectWrite

_SHA256: Final = r"^[0-9a-f]{64}$"
_ARTIST_PREFIX: Final = "musicbrainz:artist:"
_RETRIEVAL_K: Final = 50


@dataclass(frozen=True, slots=True)
class ListenBrainzH3EvaluationInputs:
    """Explicit local custody paths for an evaluation that cannot affect construction."""

    frontier_path: Path
    frontier_receipt_path: Path
    propagation_path: Path
    propagation_receipt_path: Path
    bridge_path: Path
    bridge_receipt_path: Path
    bridge_receipt_sha256: str
    historical_database_path: Path


class ListenBrainzH3EvaluationSettings(FrozenModel):
    """Fixed positive-only bounds for a laptop-safe evaluation pass."""

    revision: Literal["listenbrainz-h3-evaluation-settings-v1"] = (
        "listenbrainz-h3-evaluation-settings-v1"
    )
    retrieval_k: Literal[50] = 50
    maximum_candidate_rows: int = Field(default=100_000, ge=1, le=250_000)
    maximum_h3_observations: int = Field(default=350_000, ge=1, le=500_000)
    h3_used_for_construction: Literal[False] = False
    positive_only: Literal[True] = True


class ListenBrainzH3EvaluationCoverage(FrozenModel):
    """Account for candidate availability and H3 resolution without negative inference."""

    h3_observation_count: int = Field(ge=0)
    h3_mapped_positive_count: int = Field(ge=0)
    h3_unique_mapped_positive_count: int = Field(ge=0)
    h3_unmapped_genre_observation_count: int = Field(ge=0)
    h3_unbridged_artist_observation_count: int = Field(ge=0)
    h3_conflicted_artist_observation_count: int = Field(ge=0)
    h3_positive_genre_count: int = Field(ge=0)
    candidate_genre_count: int = Field(ge=0)
    candidate_genre_with_h3_positive_count: int = Field(ge=0)
    abstained_h3_positive_genre_count: int = Field(ge=0)
    evaluated_positive_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _account_for_h3_rows(self) -> ListenBrainzH3EvaluationCoverage:
        if self.h3_observation_count != (
            self.h3_mapped_positive_count
            + self.h3_unmapped_genre_observation_count
            + self.h3_unbridged_artist_observation_count
            + self.h3_conflicted_artist_observation_count
        ):
            raise ValueError("H3 evaluation resolution paths do not account for observations")
        if self.h3_unique_mapped_positive_count > self.h3_mapped_positive_count:
            raise ValueError("unique H3 positives exceed mapped H3 observations")
        if self.h3_positive_genre_count != (
            self.candidate_genre_with_h3_positive_count + self.abstained_h3_positive_genre_count
        ):
            raise ValueError("candidate coverage and abstention must partition H3-positive genres")
        return self


class ListenBrainzH3EvaluationMetrics(FrozenModel):
    """Unranked H3 positives evaluated against the top-50 review retrieval only."""

    retrieval_k: Literal[50] = 50
    hit_count_at_50: int = Field(ge=0)
    candidate_available_positive_count: int = Field(ge=0)
    all_mapped_unique_positive_count: int = Field(ge=0)
    predicted_candidate_count_at_50: int = Field(ge=0)
    candidate_available_recall_at_50: float | None = Field(default=None, ge=0.0, le=1.0)
    global_recall_at_50: float | None = Field(default=None, ge=0.0, le=1.0)
    precision_at_50: None = None
    precision_unavailable_reason: Literal["positive_only_h3_absences_are_unknown"] = (
        "positive_only_h3_absences_are_unknown"
    )

    @model_validator(mode="after")
    def _require_metric_denominators(self) -> ListenBrainzH3EvaluationMetrics:
        if self.hit_count_at_50 > self.candidate_available_positive_count:
            raise ValueError("H3 hits exceed candidate-available positive denominator")
        if self.candidate_available_positive_count > self.all_mapped_unique_positive_count:
            raise ValueError("candidate-available positives exceed all mapped positives")
        if self.hit_count_at_50 > self.predicted_candidate_count_at_50:
            raise ValueError("H3 hits exceed top-50 prediction denominator")
        return self


class ListenBrainzH3EvaluationArtifact(FrozenModel):
    """Sealed evaluation result; no field can be reused as a construction input."""

    revision: Literal["listenbrainz-h3-evaluation-v1"] = "listenbrainz-h3-evaluation-v1"
    frontier_v5_output_sha256: str = Field(pattern=_SHA256)
    frontier_v5_file_sha256: str = Field(pattern=_SHA256)
    listenbrainz_propagation_output_sha256: str = Field(pattern=_SHA256)
    listenbrainz_propagation_file_sha256: str = Field(pattern=_SHA256)
    bridge_output_sha256: str = Field(pattern=_SHA256)
    historical_database_sha256: str = Field(pattern=_SHA256)
    settings: ListenBrainzH3EvaluationSettings
    coverage: ListenBrainzH3EvaluationCoverage
    metrics: ListenBrainzH3EvaluationMetrics
    h3_used_for_construction: Literal[False] = False
    output_sha256: str = Field(pattern=_SHA256)


class ListenBrainzH3EvaluationReceipt(FrozenModel):
    """Immutable custody receipt for the evaluation-only artifact."""

    revision: Literal["listenbrainz-h3-evaluation-publication-v1"] = (
        "listenbrainz-h3-evaluation-publication-v1"
    )
    artifact: ObjectWrite
    artifact_sha256: str = Field(pattern=_SHA256)
    logical_output_sha256: str = Field(pattern=_SHA256)
    h3_used_for_construction: Literal[False] = False


class _CandidateBoundary(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    artist_id: str = Field(min_length=1)
    genre_id: str = Field(min_length=1)
    genre_rank: int = Field(ge=1)


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1_048_576):
            digest.update(chunk)
    return digest.hexdigest()


def _load_candidates(path: Path, *, maximum_rows: int) -> tuple[dict[str, tuple[str, ...]], int]:
    """Stream only top-50 artist IDs per legacy seed from the sealed review artifact."""
    rows = 0
    by_seed: dict[str, list[tuple[int, str]]] = defaultdict(list)
    with path.open("rb") as stream:
        for raw in ijson.items(stream, "candidates.item", use_float=True):
            candidate = _CandidateBoundary.model_validate(raw)
            rows += 1
            if rows > maximum_rows:
                raise ValueError("ListenBrainz candidate rows exceed evaluation bound")
            if not candidate.genre_id.startswith("legacy:"):
                raise ValueError("ListenBrainz candidate is outside stable seed namespace")
            if not candidate.artist_id.startswith(_ARTIST_PREFIX):
                raise ValueError("ListenBrainz candidate lacks a MusicBrainz artist ID")
            if candidate.genre_rank <= _RETRIEVAL_K:
                by_seed[candidate.genre_id.removeprefix("legacy:")].append(
                    (candidate.genre_rank, candidate.artist_id.removeprefix(_ARTIST_PREFIX))
                )
    return {
        seed: tuple(artist for _rank, artist in sorted(values))
        for seed, values in sorted(by_seed.items())
    }, rows


def _load_h3_positives(
    database_path: Path,
    *,
    seed_by_name: dict[str, str],
    spotify_to_mbid: dict[str, str],
    conflicted_spotify_ids: frozenset[str],
    maximum_observations: int,
) -> tuple[dict[str, set[str]], dict[str, int]]:
    """Read bridge-resolved H3 positives from SQLite without creating inferred negatives."""
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
    with closing(
        sqlite3.connect(f"file:{database_path.resolve()}?mode=ro", uri=True)
    ) as connection:
        for genre_name, spotify_id in connection.execute(query):
            counters["h3_observation_count"] += 1
            if counters["h3_observation_count"] > maximum_observations:
                raise ValueError("H3 observations exceed evaluation bound")
            seed = seed_by_name.get(normalize_label(str(genre_name)))
            if seed is None:
                counters["h3_unmapped_genre_observation_count"] += 1
                continue
            mbid = spotify_to_mbid.get(str(spotify_id))
            if mbid is None:
                if str(spotify_id) in conflicted_spotify_ids:
                    counters["h3_conflicted_artist_observation_count"] += 1
                else:
                    counters["h3_unbridged_artist_observation_count"] += 1
                continue
            positives[seed].add(mbid)
            counters["h3_mapped_positive_count"] += 1
    return dict(positives), counters


def evaluate_listenbrainz_propagation_h3(
    inputs: ListenBrainzH3EvaluationInputs,
    settings: ListenBrainzH3EvaluationSettings | None = None,
) -> ListenBrainzH3EvaluationArtifact:
    """Evaluate sealed top-50 review candidates against bridge-resolved H3 positives."""
    resolved = settings or ListenBrainzH3EvaluationSettings()
    frontier_receipt = EvidenceFrontierReceipt.model_validate_json(
        inputs.frontier_receipt_path.read_bytes()
    )
    frontier_file_sha256 = _file_sha256(inputs.frontier_path)
    if frontier_file_sha256 != frontier_receipt.artifact_sha256:
        raise ValueError("v5 frontier byte hash does not match its receipt")
    frontier = AllSeedEvidenceFrontierArtifact.model_validate_json(
        inputs.frontier_path.read_bytes()
    )
    if frontier.output_sha256 != frontier_receipt.logical_output_sha256:
        raise ValueError("v5 frontier logical hash does not match its receipt")
    if frontier.historical_memberships_read:
        raise ValueError("H3 evaluator requires a construction-sealed v5 frontier")
    propagation_receipt = ListenBrainzPropagationReceipt.model_validate_json(
        inputs.propagation_receipt_path.read_bytes()
    )
    if _file_sha256(inputs.propagation_path) != propagation_receipt.artifact_sha256:
        raise ValueError("ListenBrainz propagation byte hash does not match its receipt")
    if (
        frontier.listenbrainz_propagation_output_sha256 != propagation_receipt.logical_output_sha256
        or frontier.listenbrainz_propagation_file_sha256 != propagation_receipt.artifact_sha256
    ):
        raise ValueError("v5 frontier does not bind the supplied ListenBrainz artifact")
    candidates, _candidate_rows = _load_candidates(
        inputs.propagation_path, maximum_rows=resolved.maximum_candidate_rows
    )
    bridge = load_receipted_musicbrainz_spotify_bridge(
        inputs.bridge_path, inputs.bridge_receipt_path, inputs.bridge_receipt_sha256
    )
    try:
        spotify_to_mbid = dict(iter_accepted_spotify_to_musicbrainz(bridge))
        conflicted = frozenset(
            spotify_id
            for conflict in bridge.conflicts
            for spotify_id in conflict.spotify_artist_ids
        )
        seed_by_name = {normalize_label(row.seed_name): row.source_item_id for row in frontier.rows}
        positives, counters = _load_h3_positives(
            inputs.historical_database_path,
            seed_by_name=seed_by_name,
            spotify_to_mbid=spotify_to_mbid,
            conflicted_spotify_ids=conflicted,
            maximum_observations=resolved.maximum_h3_observations,
        )
    finally:
        bridge.close()
    if _file_sha256(inputs.historical_database_path) != bridge.header.historical_database_sha256:
        raise ValueError("H3 database changed or does not match bridge custody")
    h3_genres = set(positives)
    candidate_h3_genres = h3_genres & set(candidates)
    hits = sum(len(set(candidates[seed]) & positives[seed]) for seed in sorted(candidate_h3_genres))
    evaluated_positives = sum(len(positives[seed]) for seed in candidate_h3_genres)
    all_mapped_unique_positives = sum(len(values) for values in positives.values())
    predicted_candidates = sum(len(candidates[seed]) for seed in candidate_h3_genres)
    recall = hits / evaluated_positives if evaluated_positives else None
    global_recall = hits / all_mapped_unique_positives if all_mapped_unique_positives else None
    coverage = ListenBrainzH3EvaluationCoverage(
        **counters,
        h3_unique_mapped_positive_count=all_mapped_unique_positives,
        h3_positive_genre_count=len(h3_genres),
        candidate_genre_count=len(candidates),
        candidate_genre_with_h3_positive_count=len(candidate_h3_genres),
        abstained_h3_positive_genre_count=len(h3_genres - set(candidates)),
        evaluated_positive_count=evaluated_positives,
    )
    preliminary = ListenBrainzH3EvaluationArtifact(
        frontier_v5_output_sha256=frontier.output_sha256,
        frontier_v5_file_sha256=frontier_file_sha256,
        listenbrainz_propagation_output_sha256=propagation_receipt.logical_output_sha256,
        listenbrainz_propagation_file_sha256=propagation_receipt.artifact_sha256,
        bridge_output_sha256=bridge.header.output_sha256,
        historical_database_sha256=bridge.header.historical_database_sha256,
        settings=resolved,
        coverage=coverage,
        metrics=ListenBrainzH3EvaluationMetrics(
            hit_count_at_50=hits,
            candidate_available_positive_count=evaluated_positives,
            all_mapped_unique_positive_count=all_mapped_unique_positives,
            predicted_candidate_count_at_50=predicted_candidates,
            candidate_available_recall_at_50=recall,
            global_recall_at_50=global_recall,
        ),
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(
        update={
            "output_sha256": _sha(preliminary.model_dump(mode="json", exclude={"output_sha256"}))
        }
    )


def publish_listenbrainz_h3_evaluation(
    artifact: ListenBrainzH3EvaluationArtifact, *, output_path: Path, store: ObjectStore
) -> ListenBrainzH3EvaluationReceipt:
    """Publish the compact, evaluation-only report under a content-addressed key."""
    if artifact.output_sha256 != _sha(artifact.model_dump(mode="json", exclude={"output_sha256"})):
        raise ValueError("ListenBrainz H3 evaluation hash does not replay")
    payload = (artifact.model_dump_json(indent=2) + "\n").encode()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(prefix=f".{output_path.name}.", dir=output_path.parent)
    temporary = Path(raw_path)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(output_path)
    finally:
        temporary.unlink(missing_ok=True)
    artifact_sha256 = hashlib.sha256(payload).hexdigest()
    write = store.push(
        output_path,
        ObjectKey(
            value=f"listenbrainz-h3-evaluation/{artifact.output_sha256}/{artifact_sha256}.json"
        ),
    )
    if write.sha256 != artifact_sha256:
        raise ValueError("object store changed ListenBrainz H3 evaluation bytes")
    return ListenBrainzH3EvaluationReceipt(
        artifact=write,
        artifact_sha256=artifact_sha256,
        logical_output_sha256=artifact.output_sha256,
    )
