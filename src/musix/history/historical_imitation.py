"""Bridge-aware, positive-only historical membership imitation.

This is deliberately two models under one sealed evaluation contract:

* the open-only baseline builds genre vectors only from public MusicBrainz
  direct evidence and open tag features;
* the historical imitation model builds vectors from H3 positives after a
  deterministic whole-genre cold split and separate per-edge holdout.

H3 absence never becomes a negative label.  H3 supplies unranked positive
observations only, so NDCG uses binary relevance and its ideal ordering rather
than inventing an unavailable historical rank.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import tempfile
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, model_validator

from musix.ingest.musicbrainz.seed_targets import (
    MusicBrainzSeedTargetArtifact,
    verify_seed_target_artifact,
)
from musix.ingest.spotify.artifact import (
    LoadedSpotifyBridgeArtifact,
    iter_accepted_spotify_to_musicbrainz,
)
from musix.models import FrozenModel
from musix.storage import ObjectKey, ObjectStore, ObjectWrite
from musix.taxonomy.seeds.universe import normalize_label

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

from musix.taxonomy.open.tag_feature_matrix import (
    OpenTagFeatureMatrixReader,
    verify_open_tag_feature_matrix,
)

_REVISION: Final = "historical-imitation-v1"
_SHA256: Final = r"^[0-9a-f]{64}$"

type EvaluationPartition = Literal["open_only", "edge_holdout", "cold_labels"]


class HistoricalImitationError(ValueError):
    """Report invalid input custody, H3 shape, or positive-only evaluation state."""


class HistoricalImitationSettings(FrozenModel):
    """Explicit split and retrieval controls for one reproducible evaluation."""

    revision: Literal["historical-imitation-settings-v1"] = "historical-imitation-settings-v1"
    split_seed: int = Field(default=20260906, ge=0)
    cold_label_fraction: float = Field(default=0.2, ge=0.05, lt=0.95)
    edge_holdout_fraction: float = Field(default=0.2, ge=0.05, lt=0.95)
    retrieval_k: int = Field(default=50, ge=1, le=50)
    minimum_train_edges_per_label: int = Field(default=1, ge=1, le=25)
    max_historical_observations: int = Field(default=350_000, gt=0, le=500_000)
    # The sealed full seed artifact has 815,723 direct observations. Keep the
    # default just above that reproducible corpus and retain a one-million
    # observation hard guardrail for laptop-scale runs.
    max_open_evidence_rows: int = Field(default=850_000, gt=0, le=1_000_000)
    max_feature_artists: int = Field(default=125_000, gt=0, le=125_000)
    max_feature_rows: int = Field(default=300_000, gt=0, le=500_000)
    max_scored_candidates_per_genre: int = Field(default=125_000, gt=0, le=125_000)
    open_direct_evidence_semantics: Literal["binary_distinct_membership"] = (
        "binary_distinct_membership"
    )


class H3CustodyInput(FrozenModel):
    """H3 database plus an optional local directory for its verified snapshot."""

    database_path: Path
    snapshot_work_directory: Path | None = None


class HistoricalImitationCoverage(FrozenModel):
    """Complete mapping, split, and feature accounting for one run."""

    seed_count: int = Field(gt=0)
    historical_observation_count: int = Field(ge=0)
    historical_mapped_observation_count: int = Field(ge=0)
    historical_duplicate_mbid_observation_count: int = Field(ge=0)
    historical_unmapped_genre_observation_count: int = Field(ge=0)
    historical_unbridged_artist_observation_count: int = Field(ge=0)
    historical_conflicted_artist_observation_count: int = Field(ge=0)
    unique_bridged_artist_count: int = Field(ge=0)
    feature_artist_count: int = Field(ge=0)
    feature_row_count: int = Field(ge=0)
    open_direct_positive_count: int = Field(ge=0)
    cold_label_count: int = Field(ge=0)
    edge_train_positive_count: int = Field(ge=0)
    edge_holdout_positive_count: int = Field(ge=0)
    resource_profile: Literal["laptop_bounded_v1"] = "laptop_bounded_v1"

    @model_validator(mode="after")
    def _split_is_accounted(self) -> HistoricalImitationCoverage:
        if self.historical_mapped_observation_count > self.historical_observation_count:
            raise ValueError("mapped historical positives exceed historical observations")
        return self


class PositiveOnlyMetrics(FrozenModel):
    """Unranked-positive retrieval metrics with every abstention stated explicitly."""

    partition: EvaluationPartition
    positive_count: int = Field(ge=0)
    genre_count: int = Field(ge=0)
    predicted_genre_count: int = Field(ge=0)
    abstained_genre_count: int = Field(ge=0)
    feature_unavailable_positive_count: int = Field(ge=0)
    hit_count_at_k: int = Field(ge=0)
    micro_recall_at_k: float | None = Field(default=None, ge=0.0, le=1.0)
    macro_recall_at_k: float | None = Field(default=None, ge=0.0, le=1.0)
    micro_mrr: float | None = Field(default=None, ge=0.0, le=1.0)
    macro_mrr: float | None = Field(default=None, ge=0.0, le=1.0)
    micro_ndcg_at_k: float | None = Field(default=None, ge=0.0, le=1.0)
    macro_ndcg_at_k: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _genre_accounting(self) -> PositiveOnlyMetrics:
        if self.predicted_genre_count + self.abstained_genre_count != self.genre_count:
            raise ValueError("positive-only metrics must account for every genre")
        if self.hit_count_at_k > self.positive_count:
            raise ValueError("positive-only hits exceed positives")
        return self


class HistoricalImitationArtifact(FrozenModel):
    """Hash-bound output with isolated open and H3-trained benchmark results."""

    revision: Literal["historical-imitation-v1"] = _REVISION
    source_seed_target_output_sha256: str = Field(pattern=_SHA256)
    feature_matrix_output_sha256: str = Field(pattern=_SHA256)
    open_only_feature_index_sha256: str = Field(pattern=_SHA256)
    historical_feature_index_sha256: str = Field(pattern=_SHA256)
    bridge_output_sha256: str = Field(pattern=_SHA256)
    historical_database_sha256: str = Field(pattern=_SHA256)
    settings: HistoricalImitationSettings
    settings_sha256: str = Field(pattern=_SHA256)
    coverage: HistoricalImitationCoverage
    open_only_baseline: PositiveOnlyMetrics
    historical_edge_holdout: PositiveOnlyMetrics
    historical_cold_labels: PositiveOnlyMetrics
    historical_inputs_read: Literal[True] = True
    open_only_baseline_historical_evaluation_labels_read: Literal[True] = True
    open_only_baseline_historical_training_used: Literal[False] = False
    open_only_baseline_historical_features_used: Literal[False] = False
    open_only_baseline_historical_candidate_eligibility_used: Literal[False] = False
    h3_absence_treated_as_negative: Literal[False] = False
    h3_membership_rank_used: Literal[False] = False
    open_direct_positive_weight_used: Literal[False] = False
    output_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _accounting(self) -> HistoricalImitationArtifact:
        coverage = self.coverage
        if (
            coverage.historical_mapped_observation_count
            + coverage.historical_unmapped_genre_observation_count
            + coverage.historical_unbridged_artist_observation_count
            + coverage.historical_conflicted_artist_observation_count
            != coverage.historical_observation_count
        ):
            raise ValueError("historical observation resolution paths do not account for all rows")
        if coverage.cold_label_count != self.historical_cold_labels.genre_count:
            raise ValueError("cold label coverage does not match cold evaluation genres")
        if coverage.edge_holdout_positive_count != self.historical_edge_holdout.positive_count:
            raise ValueError("edge holdout coverage does not match edge evaluation positives")
        return self


class HistoricalImitationPublicationReceipt(FrozenModel):
    """Immutable publication receipt binding the benchmark to every input hash."""

    revision: Literal["historical-imitation-publication-v1"] = "historical-imitation-publication-v1"
    artifact: ObjectWrite
    artifact_sha256: str = Field(pattern=_SHA256)
    logical_output_sha256: str = Field(pattern=_SHA256)
    source_seed_target_output_sha256: str = Field(pattern=_SHA256)
    feature_matrix_output_sha256: str = Field(pattern=_SHA256)
    bridge_output_sha256: str = Field(pattern=_SHA256)
    historical_database_sha256: str = Field(pattern=_SHA256)
    content_policy: Literal["metadata_only_no_audio"] = "metadata_only_no_audio"


@dataclass(frozen=True, slots=True)
class _FeatureIndex:
    vectors: Mapping[str, Mapping[str, float]]
    inverted: Mapping[str, tuple[tuple[str, float], ...]]


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1_048_576):
            digest.update(block)
    return digest.hexdigest()


def _snapshot_sealed_database(
    source: Path, destination_directory: Path, expected_sha256: str
) -> Path:
    """Copy one H3 SQLite file while hashing it, rejecting a changing source."""
    destination = destination_directory / "historical.sqlite"
    digest = hashlib.sha256()
    with source.open("rb") as input_stream, destination.open("xb") as output_stream:
        while block := input_stream.read(1_048_576):
            digest.update(block)
            output_stream.write(block)
        output_stream.flush()
        os.fsync(output_stream.fileno())
    if digest.hexdigest() != expected_sha256:
        destination.unlink(missing_ok=True)
        raise HistoricalImitationError(
            "historical database changed before immutable snapshot completed"
        )
    return destination


def historical_imitation_settings_sha256(settings: HistoricalImitationSettings) -> str:
    """Hash all split and bounded-retrieval settings."""
    return hashlib.sha256(_canonical(settings.model_dump(mode="json"))).hexdigest()


def historical_imitation_artifact_sha256(artifact: HistoricalImitationArtifact) -> str:
    """Hash output fields excluding their self-referential hash."""
    return hashlib.sha256(
        _canonical(artifact.model_dump(mode="json", exclude={"output_sha256"}))
    ).hexdigest()


def _hash_unit(seed: int, *parts: str) -> float:
    digest = hashlib.sha256(f"{seed}\0".encode() + "\0".join(parts).encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def _unique_seed_names(source: MusicBrainzSeedTargetArtifact) -> dict[str, str]:
    by_name: dict[str, list[str]] = defaultdict(list)
    for row in source.coverage:
        by_name[normalize_label(row.seed_name)].append(row.seed_source_item_id)
    return {name: ids[0] for name, ids in by_name.items() if len(ids) == 1}


def _load_historical_positives(
    database_path: Path,
    bridge: LoadedSpotifyBridgeArtifact,
    seed_by_name: Mapping[str, str],
    settings: HistoricalImitationSettings,
) -> tuple[dict[str, set[str]], dict[str, int]]:
    """Join H3 positives to accepted bridge identities without negative inference."""
    accepted = dict(iter_accepted_spotify_to_musicbrainz(bridge))
    conflicted = {
        spotify_id for conflict in bridge.conflicts for spotify_id in conflict.spotify_artist_ids
    }
    counters = dict.fromkeys(
        (
            "historical_observation_count",
            "historical_mapped_observation_count",
            "historical_duplicate_mbid_observation_count",
            "historical_unmapped_genre_observation_count",
            "historical_unbridged_artist_observation_count",
            "historical_conflicted_artist_observation_count",
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
    try:
        with closing(
            sqlite3.connect(f"file:{database_path.resolve()}?mode=ro", uri=True)
        ) as connection:
            for genre_name, spotify_id in connection.execute(query):
                counters["historical_observation_count"] += 1
                if counters["historical_observation_count"] > settings.max_historical_observations:
                    raise HistoricalImitationError(
                        "historical observations exceed configured bound"
                    )
                genre_id = seed_by_name.get(normalize_label(str(genre_name)))
                if genre_id is None:
                    counters["historical_unmapped_genre_observation_count"] += 1
                    continue
                mbid = accepted.get(str(spotify_id))
                if mbid is None:
                    if str(spotify_id) in conflicted:
                        counters["historical_conflicted_artist_observation_count"] += 1
                    else:
                        counters["historical_unbridged_artist_observation_count"] += 1
                    continue
                before = len(positives[genre_id])
                positives[genre_id].add(mbid)
                counters["historical_mapped_observation_count"] += 1
                counters["historical_duplicate_mbid_observation_count"] += (
                    len(positives[genre_id]) == before
                )
    except sqlite3.Error as error:
        raise HistoricalImitationError(
            "historical database lacks H3 observation and genre tables"
        ) from error
    return dict(positives), counters


def _load_open_positives(
    source: MusicBrainzSeedTargetArtifact, settings: HistoricalImitationSettings
) -> dict[str, set[str]]:
    positives: dict[str, set[str]] = defaultdict(set)
    for count, row in enumerate(source.evidence, start=1):
        if count > settings.max_open_evidence_rows:
            raise HistoricalImitationError("open direct evidence exceeds configured bound")
        positives[row.seed_source_item_id].add(row.artist_id)
    return dict(positives)


def _load_raw_features(
    reader: OpenTagFeatureMatrixReader,
    artists: Iterable[str] | None,
    settings: HistoricalImitationSettings,
) -> tuple[dict[str, dict[str, float]], int]:
    """Read the bounded sparse rows needed by this run."""
    requested = tuple(sorted(set(artists))) if artists is not None else None
    if requested is not None and len(requested) > settings.max_feature_artists:
        raise HistoricalImitationError("feature artist request exceeds configured bound")
    raw: dict[str, dict[str, float]] = defaultdict(dict)
    rows = 0
    feature_rows = (
        reader.iter_features_for_artists(requested)
        if requested is not None
        else reader.iter_all_features()
    )
    for feature in feature_rows:
        rows += 1
        if rows > settings.max_feature_rows:
            raise HistoricalImitationError("feature rows exceed configured bound")
        raw[feature.artist_id][feature.tag_identity] = float(feature.tag_count)
    return raw, rows


def _normalize_feature_index(raw: Mapping[str, Mapping[str, float]]) -> _FeatureIndex:
    """Transform trusted sparse counts to normalized TF-IDF retrieval vectors."""
    document_frequency = defaultdict(int)
    for vector in raw.values():
        for tag in vector:
            document_frequency[tag] += 1
    total = len(raw)
    vectors: dict[str, dict[str, float]] = {}
    inverted_build: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for artist_id, vector in sorted(raw.items()):
        weighted = {
            tag: math.log1p(value) * (math.log((1 + total) / (1 + document_frequency[tag])) + 1)
            for tag, value in vector.items()
        }
        norm = math.sqrt(sum(value * value for value in weighted.values()))
        if norm == 0.0:
            continue
        normalized = {tag: value / norm for tag, value in weighted.items()}
        vectors[artist_id] = normalized
        for tag, value in normalized.items():
            inverted_build[tag].append((artist_id, value))
    return _FeatureIndex(
        vectors=vectors,
        inverted={tag: tuple(items) for tag, items in inverted_build.items()},
    )


def _build_feature_index(
    reader: OpenTagFeatureMatrixReader,
    artists: Iterable[str] | None,
    settings: HistoricalImitationSettings,
) -> tuple[_FeatureIndex, int, int]:
    """Build bounded TF-IDF sparse maps from the persisted open feature matrix."""
    raw, rows = _load_raw_features(reader, artists, settings)
    return _normalize_feature_index(raw), len(raw), rows


def _feature_index_sha256(index: _FeatureIndex) -> str:
    """Bind a deterministic feature universe and its exact TF-IDF weights."""
    return hashlib.sha256(
        _canonical(
            {
                artist: dict(sorted(vector.items()))
                for artist, vector in sorted(index.vectors.items())
            }
        )
    ).hexdigest()


def _prototype(artists: Iterable[str], features: _FeatureIndex) -> dict[str, float]:
    values: dict[str, float] = defaultdict(float)
    count = 0
    for artist in artists:
        vector = features.vectors.get(artist)
        if vector is None:
            continue
        count += 1
        for tag, value in vector.items():
            values[tag] += value
    if count == 0:
        return {}
    norm = math.sqrt(sum(value * value for value in values.values()))
    return {tag: value / norm for tag, value in values.items()} if norm else {}


def _top_k(
    prototype: Mapping[str, float], features: _FeatureIndex, settings: HistoricalImitationSettings
) -> tuple[str, ...]:
    scores: dict[str, float] = defaultdict(float)
    for tag, prototype_value in prototype.items():
        for artist_id, feature_value in features.inverted.get(tag, ()):
            scores[artist_id] += prototype_value * feature_value
            if len(scores) > settings.max_scored_candidates_per_genre:
                raise HistoricalImitationError("genre retrieval exceeds laptop candidate bound")
    return tuple(
        artist
        for artist, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))[
            : settings.retrieval_k
        ]
        if score > 0.0
    )


def _evaluate(
    partition: EvaluationPartition,
    targets: Mapping[str, set[str]],
    training: Mapping[str, set[str]],
    features: _FeatureIndex,
    settings: HistoricalImitationSettings,
) -> PositiveOnlyMetrics:
    """Evaluate binary positive sets; every label without a vector abstains."""
    genre_count = len(targets)
    positive_count = sum(len(items) for items in targets.values())
    predicted = abstained = unavailable = hits = 0
    macro_recall: list[float] = []
    macro_mrr: list[float] = []
    macro_ndcg: list[float] = []
    weighted_reciprocal_sum = weighted_ndcg_sum = 0.0
    for genre, positives in sorted(targets.items()):
        prototype = _prototype(training.get(genre, ()), features)
        prediction = _top_k(prototype, features, settings)
        if not prediction:
            abstained += 1
            unavailable += len(positives)
            continue
        predicted += 1
        ranks = [index + 1 for index, artist in enumerate(prediction) if artist in positives]
        hit_count = len(ranks)
        hits += hit_count
        recall = hit_count / len(positives)
        reciprocal = 1.0 / min(ranks) if ranks else 0.0
        dcg = sum(1.0 / math.log2(rank + 1) for rank in ranks)
        ideal = sum(
            1.0 / math.log2(rank + 1)
            for rank in range(1, min(len(positives), settings.retrieval_k) + 1)
        )
        ndcg = dcg / ideal if ideal else 0.0
        macro_recall.append(recall)
        macro_mrr.append(reciprocal)
        macro_ndcg.append(ndcg)
        weighted_reciprocal_sum += reciprocal * len(positives)
        weighted_ndcg_sum += ndcg * len(positives)
    return PositiveOnlyMetrics(
        partition=partition,
        positive_count=positive_count,
        genre_count=genre_count,
        predicted_genre_count=predicted,
        abstained_genre_count=abstained,
        feature_unavailable_positive_count=unavailable,
        hit_count_at_k=hits,
        micro_recall_at_k=hits / positive_count if positive_count else None,
        macro_recall_at_k=sum(macro_recall) / genre_count if genre_count else None,
        micro_mrr=weighted_reciprocal_sum / positive_count if positive_count else None,
        macro_mrr=sum(macro_mrr) / genre_count if genre_count else None,
        micro_ndcg_at_k=weighted_ndcg_sum / positive_count if positive_count else None,
        macro_ndcg_at_k=sum(macro_ndcg) / genre_count if genre_count else None,
    )


def _split_historical(
    positives: Mapping[str, set[str]], settings: HistoricalImitationSettings
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, set[str]], int]:
    """Create label-cold and edge-holdout targets while retaining train positives."""
    training: dict[str, set[str]] = {}
    holdout: dict[str, set[str]] = {}
    cold: dict[str, set[str]] = {}
    for genre, artists in sorted(positives.items()):
        if _hash_unit(settings.split_seed, "cold", genre) < settings.cold_label_fraction:
            cold[genre] = set(artists)
            continue
        ordered = sorted(artists)
        selected = {
            artist
            for artist in ordered
            if _hash_unit(settings.split_seed, "edge", genre, artist)
            < settings.edge_holdout_fraction
        }
        maximum_holdout = max(0, len(ordered) - settings.minimum_train_edges_per_label)
        if len(selected) > maximum_holdout:
            selected = set(sorted(selected)[:maximum_holdout])
        training[genre] = set(ordered) - selected
        if selected:
            holdout[genre] = selected
    return training, holdout, cold, len(cold)


def build_historical_imitation(
    source: MusicBrainzSeedTargetArtifact,
    bridge: LoadedSpotifyBridgeArtifact,
    features: OpenTagFeatureMatrixReader,
    h3_input: H3CustodyInput,
    settings: HistoricalImitationSettings | None = None,
) -> HistoricalImitationArtifact:
    """Train/evaluate H3 imitation while retaining an isolated open-only baseline."""
    verify_seed_target_artifact(source)
    resolved = settings or HistoricalImitationSettings()
    if features.artifact.source_seed_target_output_sha256 != source.output_sha256:
        raise HistoricalImitationError(
            "feature matrix source hash does not match seed target artifact"
        )
    # Both feature universes are the full persisted source-only matrix. H3 can
    # affect labels and evaluation, but never candidate eligibility or IDF.
    open_positives = _load_open_positives(source, resolved)
    open_feature_index, _open_feature_artists, _open_feature_rows = _build_feature_index(
        features,
        None,
        resolved,
    )
    if h3_input.snapshot_work_directory is not None:
        h3_input.snapshot_work_directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="musix-h3-snapshot-",
        dir=h3_input.snapshot_work_directory,
    ) as directory:
        snapshot = _snapshot_sealed_database(
            h3_input.database_path,
            Path(directory),
            bridge.header.historical_database_sha256,
        )
        historical, counters = _load_historical_positives(
            snapshot, bridge, _unique_seed_names(source), resolved
        )
    training, holdout, cold, cold_count = _split_historical(historical, resolved)
    feature_index, feature_artist_count, feature_row_count = _build_feature_index(
        features,
        None,
        resolved,
    )
    open_baseline = _evaluate("open_only", historical, open_positives, open_feature_index, resolved)
    edge_metrics = _evaluate("edge_holdout", holdout, training, feature_index, resolved)
    cold_metrics = _evaluate("cold_labels", cold, {}, feature_index, resolved)
    coverage = HistoricalImitationCoverage.model_validate(
        {
            **counters,
            "seed_count": source.seed_count,
            "unique_bridged_artist_count": len(set().union(*historical.values()))
            if historical
            else 0,
            "feature_artist_count": feature_artist_count,
            "feature_row_count": feature_row_count,
            "open_direct_positive_count": sum(len(items) for items in open_positives.values()),
            "cold_label_count": cold_count,
            "edge_train_positive_count": sum(len(items) for items in training.values()),
            "edge_holdout_positive_count": sum(len(items) for items in holdout.values()),
        }
    )
    provisional = HistoricalImitationArtifact(
        source_seed_target_output_sha256=source.output_sha256,
        feature_matrix_output_sha256=features.artifact.output_sha256,
        open_only_feature_index_sha256=_feature_index_sha256(open_feature_index),
        historical_feature_index_sha256=_feature_index_sha256(feature_index),
        bridge_output_sha256=bridge.header.output_sha256,
        historical_database_sha256=bridge.header.historical_database_sha256,
        settings=resolved,
        settings_sha256=historical_imitation_settings_sha256(resolved),
        coverage=coverage,
        open_only_baseline=open_baseline,
        historical_edge_holdout=edge_metrics,
        historical_cold_labels=cold_metrics,
        output_sha256="0" * 64,
    )
    # Stream-backed sources and SQLite matrices are reverified after all
    # passes, so a mutation between input validation and model construction
    # cannot be silently bound into the result.
    verify_seed_target_artifact(source)
    verify_open_tag_feature_matrix(features.artifact, features.matrix_path)
    return provisional.model_copy(
        update={"output_sha256": historical_imitation_artifact_sha256(provisional)}
    )


def verify_historical_imitation(artifact: HistoricalImitationArtifact) -> None:
    """Fail closed on hash or a claim that violates positive-only semantics."""
    if artifact.settings_sha256 != historical_imitation_settings_sha256(artifact.settings):
        raise HistoricalImitationError("historical imitation settings hash does not replay")
    if artifact.output_sha256 != historical_imitation_artifact_sha256(artifact):
        raise HistoricalImitationError("historical imitation output hash does not replay")


def write_historical_imitation(artifact: HistoricalImitationArtifact, path: Path) -> str:
    """Atomically write one verified compact benchmark artifact."""
    verify_historical_imitation(artifact)
    payload = _canonical(artifact.model_dump(mode="json")) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return hashlib.sha256(payload).hexdigest()


def publish_historical_imitation(
    artifact: HistoricalImitationArtifact, *, output_path: Path, store: ObjectStore
) -> HistoricalImitationPublicationReceipt:
    """Write and publish one verified benchmark under an immutable object key."""
    artifact_sha256 = write_historical_imitation(artifact, output_path)
    stored = store.push(
        output_path,
        ObjectKey(value=f"historical-imitation/sha256/{artifact_sha256}.json"),
    )
    if stored.sha256 != artifact_sha256:
        raise HistoricalImitationError("object store changed historical imitation artifact bytes")
    return HistoricalImitationPublicationReceipt(
        artifact=stored,
        artifact_sha256=artifact_sha256,
        logical_output_sha256=artifact.output_sha256,
        source_seed_target_output_sha256=artifact.source_seed_target_output_sha256,
        feature_matrix_output_sha256=artifact.feature_matrix_output_sha256,
        bridge_output_sha256=artifact.bridge_output_sha256,
        historical_database_sha256=artifact.historical_database_sha256,
    )
