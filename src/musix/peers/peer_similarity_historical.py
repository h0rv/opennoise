"""Compatibility-only validation for derived genre peer candidates.

The historical Every Noise snapshot is an evaluation reference only.  This
module reads it after construction, turns its artist memberships into a
deterministic overlap graph, and compares top-k neighborhoods with the public
candidate graph.  It never returns historical rows as model inputs.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from contextlib import closing
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from musix.common import sha256_file, sha256_json
from musix.models import FrozenModel
from musix.models.modeling import PublicModelInput
from musix.peers.peer_similarity import (
    GenrePeerSimilarityArtifact,
    PeerSimilaritySettings,
    evaluate_peer_similarity_gate,
    peer_similarity_output_sha256,
)
from musix.storage import ObjectKey, ObjectStore, ObjectWrite
from musix.taxonomy.genre_seed_universe import normalize_label
from musix.types import Sha256  # noqa: TC001

if TYPE_CHECKING:
    from pathlib import Path

_REVISION = "genre-peer-similarity-historical-evaluation-v1"
_MAX_K = 100

type NullBaselineKind = Literal["uniform_without_replacement"]


class HistoricalPeerSettings(FrozenModel):
    """Bound evaluation settings; none are construction settings."""

    revision: Literal["genre-peer-similarity-historical-evaluation-v1"] = _REVISION
    k: int = Field(default=25, gt=0, le=_MAX_K)
    minimum_shared_artists: int = Field(default=1, gt=0, le=1_000_000)
    null_baseline: NullBaselineKind = "uniform_without_replacement"


class HistoricalPeerGenreResult(FrozenModel):
    """Top-k overlap measurements for one name-matched genre."""

    genre_id: str = Field(min_length=1, max_length=200)
    genre_name: str = Field(min_length=1, max_length=500)
    historical_artist_count: int = Field(ge=0)
    candidate_neighbor_count: int = Field(ge=0)
    historical_neighbor_count: int = Field(ge=0)
    comparable_neighbor_universe_count: int = Field(ge=0)
    overlap_count: int = Field(ge=0)
    candidate_precision_at_k: float | None = Field(default=None, ge=0.0, le=1.0)
    candidate_recall_at_k: float | None = Field(default=None, ge=0.0, le=1.0)
    null_expected_overlap: float = Field(ge=0.0)
    null_precision_at_k: float | None = Field(default=None, ge=0.0, le=1.0)
    null_recall_at_k: float | None = Field(default=None, ge=0.0, le=1.0)


class HistoricalPeerEvaluationReport(FrozenModel):
    """Content-addressed report with explicit historical isolation flags."""

    revision: Literal["genre-peer-similarity-historical-evaluation-v1"] = _REVISION
    report_sha256: Sha256
    candidate_file_sha256: Sha256
    candidate_output_sha256: Sha256
    candidate_input_sha256: Sha256
    public_input_sha256: Sha256
    public_database_sha256: Sha256
    historical_database_sha256: Sha256
    historical_inputs_used_for_construction: Literal[False] = False
    historical_data_used_for_scoring: Literal[True] = True
    absence_is_negative: Literal[False] = False
    candidate_gate_passed: Literal[True] = True
    construction_excluded_historical_data: Literal[True] = True
    settings_sha256: Sha256
    k: int = Field(gt=0, le=_MAX_K)
    public_genre_count: int = Field(ge=0)
    historical_genre_count: int = Field(ge=0)
    matched_genre_count: int = Field(ge=0)
    ambiguous_genre_name_count: int = Field(ge=0)
    historical_source_membership_count: int = Field(ge=0)
    mapped_historical_artist_membership_count: int = Field(ge=0)
    strict_artist_name_crosswalk_count: int = Field(ge=0)
    ambiguous_artist_name_count: int = Field(ge=0)
    candidate_edge_count: int = Field(ge=0)
    historical_edge_count: int = Field(ge=0)
    matched_historical_edge_count: int = Field(ge=0)
    historical_edge_count_scope: Literal["all_historical_genres"] = "all_historical_genres"
    candidate_directed_neighbor_count: int = Field(ge=0)
    historical_directed_neighbor_count: int = Field(ge=0)
    candidate_mutual_neighbor_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    historical_mutual_neighbor_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    candidate_historical_mutual_edge_overlap: int = Field(ge=0)
    micro_overlap_count: int = Field(ge=0)
    micro_candidate_precision_at_k: float | None = Field(default=None, ge=0.0, le=1.0)
    micro_candidate_recall_at_k: float | None = Field(default=None, ge=0.0, le=1.0)
    macro_candidate_precision_at_k: float | None = Field(default=None, ge=0.0, le=1.0)
    macro_candidate_recall_at_k: float | None = Field(default=None, ge=0.0, le=1.0)
    micro_null_expected_overlap: float = Field(ge=0.0)
    micro_null_precision_at_k: float | None = Field(default=None, ge=0.0, le=1.0)
    micro_null_recall_at_k: float | None = Field(default=None, ge=0.0, le=1.0)
    null_baseline: NullBaselineKind
    per_genre: tuple[HistoricalPeerGenreResult, ...]


class HistoricalPeerPublicationReceipt(FrozenModel):
    """Receipt binding one verified report to immutable ObjectStore custody."""

    revision: Literal["genre-peer-similarity-historical-publication-v1"] = (
        "genre-peer-similarity-historical-publication-v1"
    )
    report: ObjectWrite
    report_sha256: Sha256
    candidate_output_sha256: Sha256
    historical_database_sha256: Sha256
    historical_inputs_used_for_construction: Literal[False] = False
    content_policy: Literal["metadata_only_no_audio"] = "metadata_only_no_audio"


def _sealed_candidate_output_sha256(candidate_path: Path) -> Sha256:
    """Recompute the hash from the candidate's serialized JSON shape.

    The v3 bridge artifact was sealed before strict Pydantic parsing.  JSON
    arrays are equivalent to the tuple fields in the model, but Pydantic's
    model dump can normalize numeric values while parsing.  Evaluation must
    verify the bytes' own content hash first, then may use the normalized
    model only for the structural gate.
    """
    payload = json.loads(candidate_path.read_bytes())
    if not isinstance(payload, dict):
        raise TypeError("candidate output must be a JSON object")
    stored = payload.get("output_sha256")
    if not isinstance(stored, str):
        raise TypeError("candidate output hash is missing")
    without_hash = {key: value for key, value in payload.items() if key != "output_sha256"}
    recomputed = sha256_json(without_hash)
    if stored != recomputed:
        raise ValueError("candidate serialized output hash does not replay")
    return recomputed


def historical_peer_report_sha256(report: HistoricalPeerEvaluationReport) -> Sha256:
    """Recompute the report hash without trusting its stored value."""
    return sha256_json(report.model_dump(mode="json", exclude={"report_sha256"}))


def _strict_artist_name_crosswalk(
    connection: sqlite3.Connection,
) -> tuple[dict[str, str], int]:
    """Return only names mapping to exactly one preferred English artist ID."""
    ids_by_name: dict[str, set[str]] = defaultdict(set)
    for row in connection.execute(
        """
        SELECT identifier.normalized_value, names.name
          FROM entity_identifiers AS identifier
          JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
          JOIN entity_names AS names ON names.entity_id = identifier.entity_id
         WHERE type.type_key = 'musicbrainz_artist_id'
           AND names.name_kind = 'primary'
           AND names.is_preferred = 1
           AND names.language_tag = 'en'
        """
    ):
        ids_by_name[normalize_label(str(row[1]))].add(str(row[0]))
    ambiguous = sum(len(ids) > 1 for ids in ids_by_name.values())
    return (
        {name: next(iter(ids)) for name, ids in ids_by_name.items() if len(ids) == 1},
        ambiguous,
    )


def _historical_sets(
    connection: sqlite3.Connection,
    crosswalk: dict[str, str],
) -> tuple[dict[str, set[str]], int, int]:
    """Read H3 artist sets, mapping only unambiguous public artist names."""
    names_by_genre: dict[str, list[str]] = defaultdict(list)
    source_count = 0
    for row in connection.execute(
        """
        SELECT genres.name, observations.source_artist_name
          FROM historical_genre_artist_observations AS observations
          JOIN genres ON genres.id = observations.genre_id
         ORDER BY genres.name, COALESCE(observations.source_local_rank, 100000), observations.id
        """
    ):
        source_count += 1
        names_by_genre[normalize_label(str(row[0]))].append(str(row[1]))
    by_genre: dict[str, set[str]] = {}
    mapped_count = 0
    for genre_name, names in names_by_genre.items():
        artists = {
            crosswalk[normalized]
            for name in names
            if (normalized := normalize_label(name)) in crosswalk
        }
        mapped_count += len(artists)
        by_genre[genre_name] = artists
    return by_genre, source_count, mapped_count


def _historical_neighbors(
    artist_sets: dict[str, set[str]],
    *,
    minimum_shared_artists: int,
    k: int,
) -> tuple[dict[str, tuple[str, ...]], dict[tuple[str, str], int]]:
    """Build a sparse, symmetric historical overlap graph without dense O(G²)."""
    genres_by_artist: dict[str, list[str]] = defaultdict(list)
    for genre, artists in sorted(artist_sets.items()):
        for artist in sorted(artists):
            genres_by_artist[artist].append(genre)
    shared: dict[tuple[str, str], int] = defaultdict(int)
    for genres in genres_by_artist.values():
        ordered = sorted(genres)
        for index, left in enumerate(ordered):
            for right in ordered[index + 1 :]:
                shared[(left, right)] += 1
    ranked: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for (left, right), count in sorted(shared.items()):
        if count >= minimum_shared_artists:
            ranked[left].append((right, count))
            ranked[right].append((left, count))
    neighbors = {
        genre: tuple(
            target for target, _ in sorted(values, key=lambda item: (-item[1], item[0]))[:k]
        )
        for genre, values in ranked.items()
    }
    return neighbors, dict(shared)


def _candidate_neighbors(
    artifact: GenrePeerSimilarityArtifact,
    *,
    genre_ids: set[str],
    k: int,
) -> tuple[dict[str, tuple[str, ...]], dict[tuple[str, str], float]]:
    """Build directed top-k candidates from canonical stored pairs."""
    ranked: dict[str, list[tuple[str, float]]] = defaultdict(list)
    pair_scores: dict[tuple[str, str], float] = {}
    for candidate in artifact.candidates:
        if candidate.source_genre_id not in genre_ids or candidate.target_genre_id not in genre_ids:
            continue
        pair = (candidate.source_genre_id, candidate.target_genre_id)
        pair_scores[pair] = candidate.score
        ranked[candidate.source_genre_id].append((candidate.target_genre_id, candidate.score))
        ranked[candidate.target_genre_id].append((candidate.source_genre_id, candidate.score))
    neighbors = {
        genre: tuple(
            target for target, _ in sorted(values, key=lambda item: (-item[1], item[0]))[:k]
        )
        for genre, values in ranked.items()
    }
    return neighbors, pair_scores


def _mutual_fraction(neighbors: dict[str, tuple[str, ...]]) -> float | None:
    directed = {(source, target) for source, targets in neighbors.items() for target in targets}
    if not directed:
        return None
    mutual = sum((target, source) in directed for source, target in directed)
    return mutual / len(directed)


def evaluate_peer_similarity_historical(  # noqa: C901, PLR0912, PLR0913, PLR0915
    candidate_path: Path,
    public_input_path: Path,
    public_database_path: Path,
    historical_database_path: Path,
    *,
    candidate_settings: PeerSimilaritySettings,
    settings: HistoricalPeerSettings | None = None,
) -> HistoricalPeerEvaluationReport:
    """Compare public candidates to H3 overlap neighbors after construction."""
    resolved = settings or HistoricalPeerSettings()
    candidate_file_hash = sha256_file(candidate_path)[0]
    public_input_hash = sha256_file(public_input_path)[0]
    public_hash = sha256_file(public_database_path)[0]
    historical_hash = sha256_file(historical_database_path)[0]
    candidate_bytes_hash = _sealed_candidate_output_sha256(candidate_path)
    candidate = GenrePeerSimilarityArtifact.model_validate_json(candidate_path.read_bytes())
    public_input = PublicModelInput.model_validate_json(public_input_path.read_bytes())
    if candidate.input_sha256 != sha256_json(public_input.model_dump(mode="json")):
        raise ValueError("candidate input hash does not match public model input")
    normalized_output_hash = peer_similarity_output_sha256(candidate)
    if candidate_bytes_hash != candidate.output_sha256:
        raise ValueError("candidate parsed output hash disagrees with sealed JSON hash")
    gate_candidate = candidate
    if normalized_output_hash != candidate.output_sha256:
        gate_candidate = candidate.model_copy(update={"output_sha256": normalized_output_hash})
    gate = evaluate_peer_similarity_gate(gate_candidate, public_input, candidate_settings)
    if not gate.passed:
        raise ValueError("candidate peer gate failed: " + "; ".join(gate.failures))
    if sha256_file(candidate_path)[0] != candidate_file_hash:
        raise ValueError("candidate file changed while evaluating")
    if sha256_file(public_input_path)[0] != public_input_hash:
        raise ValueError("public input changed while evaluating")
    with closing(
        sqlite3.connect(f"file:{public_database_path.resolve()}?mode=ro", uri=True)
    ) as public:
        public.row_factory = sqlite3.Row
        crosswalk, ambiguous_artists = _strict_artist_name_crosswalk(public)
    if sha256_file(public_database_path)[0] != public_hash:
        raise ValueError("public database changed while evaluating")
    with closing(
        sqlite3.connect(f"file:{historical_database_path.resolve()}?mode=ro", uri=True)
    ) as historical:
        historical.row_factory = sqlite3.Row
        historical_sets, source_memberships, mapped_memberships = _historical_sets(
            historical, crosswalk
        )
    if sha256_file(historical_database_path)[0] != historical_hash:
        raise ValueError("historical database changed while evaluating")

    public_genres_by_name: dict[str, list[str]] = defaultdict(list)
    public_names = {item.genre_id: item.name for item in public_input.genres}
    if any(
        item.name == item.genre_id
        and any(ref.startswith("reconstruction:genre:") for ref in item.evidence_refs)
        for item in public_input.genres
    ):
        raise ValueError(
            "historical evaluation requires explicit seed names; reconstruction IDs are not names"
        )
    for item in public_input.genres:
        public_genres_by_name[normalize_label(item.name)].append(item.genre_id)
    matched: dict[str, str] = {}
    ambiguous_genres = 0
    for name in sorted(historical_sets):
        ids = public_genres_by_name.get(name, [])
        if len(ids) == 1:
            matched[name] = ids[0]
        elif len(ids) > 1:
            ambiguous_genres += 1
    matched_historical_sets = {
        matched[name]: artists for name, artists in historical_sets.items() if name in matched
    }
    historical_neighbors_by_name, historical_pairs = _historical_neighbors(
        historical_sets,
        minimum_shared_artists=resolved.minimum_shared_artists,
        k=resolved.k,
    )
    historical_neighbors = {
        matched[name]: tuple(matched[target] for target in targets if target in matched)
        for name, targets in historical_neighbors_by_name.items()
        if name in matched
    }
    matched_ids = set(matched.values())
    candidate_neighbors, candidate_pairs = _candidate_neighbors(
        candidate, genre_ids=matched_ids, k=resolved.k
    )
    comparable_count = max(len(matched_ids) - 1, 0)
    per_genre: list[HistoricalPeerGenreResult] = []
    overlap_total = candidate_total = historical_total = 0
    null_overlap_total = 0.0
    candidate_historical_mutual_overlap = 0
    historical_edge_count = sum(
        count >= resolved.minimum_shared_artists
        for count in historical_pairs.values()
        if count >= resolved.minimum_shared_artists
    )
    matched_names = set(matched)
    matched_historical_edge_count = sum(
        count >= resolved.minimum_shared_artists
        and left in matched_names
        and right in matched_names
        for (left, right), count in historical_pairs.items()
    )
    for genre_id in sorted(matched_historical_sets):
        candidate_targets = set(candidate_neighbors.get(genre_id, ()))
        historical_targets = set(historical_neighbors.get(genre_id, ()))
        overlap = len(candidate_targets & historical_targets)
        candidate_count = len(candidate_targets)
        historical_count = len(historical_targets)
        null_expected = (
            candidate_count * historical_count / comparable_count if comparable_count else 0.0
        )
        candidate_total += candidate_count
        historical_total += historical_count
        overlap_total += overlap
        null_overlap_total += null_expected
        for target in candidate_targets:
            if genre_id in candidate_neighbors.get(target, ()) and target in historical_targets:
                candidate_historical_mutual_overlap += 1
        per_genre.append(
            HistoricalPeerGenreResult(
                genre_id=genre_id,
                genre_name=public_names[genre_id],
                historical_artist_count=len(matched_historical_sets[genre_id]),
                candidate_neighbor_count=candidate_count,
                historical_neighbor_count=historical_count,
                comparable_neighbor_universe_count=comparable_count,
                overlap_count=overlap,
                candidate_precision_at_k=overlap / candidate_count if candidate_count else None,
                candidate_recall_at_k=overlap / historical_count if historical_count else None,
                null_expected_overlap=null_expected,
                null_precision_at_k=(null_expected / candidate_count if candidate_count else None),
                null_recall_at_k=(null_expected / historical_count if historical_count else None),
            )
        )
    candidate_edge_count = len(candidate_pairs)
    settings_hash = sha256_json(resolved.model_dump(mode="json"))
    report = HistoricalPeerEvaluationReport(
        report_sha256="0" * 64,
        candidate_file_sha256=candidate_file_hash,
        candidate_output_sha256=candidate.output_sha256,
        candidate_input_sha256=candidate.input_sha256,
        public_input_sha256=public_input_hash,
        public_database_sha256=public_hash,
        historical_database_sha256=historical_hash,
        settings_sha256=settings_hash,
        k=resolved.k,
        public_genre_count=len(public_input.genres),
        historical_genre_count=len(historical_sets),
        matched_genre_count=len(matched_historical_sets),
        ambiguous_genre_name_count=ambiguous_genres,
        historical_source_membership_count=source_memberships,
        mapped_historical_artist_membership_count=mapped_memberships,
        strict_artist_name_crosswalk_count=len(crosswalk),
        ambiguous_artist_name_count=ambiguous_artists,
        candidate_edge_count=candidate_edge_count,
        historical_edge_count=historical_edge_count,
        matched_historical_edge_count=matched_historical_edge_count,
        candidate_directed_neighbor_count=sum(map(len, candidate_neighbors.values())),
        historical_directed_neighbor_count=sum(map(len, historical_neighbors.values())),
        candidate_mutual_neighbor_fraction=_mutual_fraction(candidate_neighbors),
        historical_mutual_neighbor_fraction=_mutual_fraction(historical_neighbors),
        candidate_historical_mutual_edge_overlap=candidate_historical_mutual_overlap,
        micro_overlap_count=overlap_total,
        micro_candidate_precision_at_k=overlap_total / candidate_total if candidate_total else None,
        micro_candidate_recall_at_k=overlap_total / historical_total if historical_total else None,
        macro_candidate_precision_at_k=(
            sum(
                item.candidate_precision_at_k
                for item in per_genre
                if item.candidate_precision_at_k is not None
            )
            / sum(item.candidate_precision_at_k is not None for item in per_genre)
            if any(item.candidate_precision_at_k is not None for item in per_genre)
            else None
        ),
        macro_candidate_recall_at_k=(
            sum(
                item.candidate_recall_at_k
                for item in per_genre
                if item.candidate_recall_at_k is not None
            )
            / sum(item.candidate_recall_at_k is not None for item in per_genre)
            if any(item.candidate_recall_at_k is not None for item in per_genre)
            else None
        ),
        micro_null_expected_overlap=null_overlap_total,
        micro_null_precision_at_k=null_overlap_total / candidate_total if candidate_total else None,
        micro_null_recall_at_k=null_overlap_total / historical_total if historical_total else None,
        null_baseline=resolved.null_baseline,
        per_genre=tuple(per_genre),
    )
    return report.model_copy(update={"report_sha256": historical_peer_report_sha256(report)})


def verify_historical_peer_report(report: HistoricalPeerEvaluationReport) -> None:
    """Fail closed if a persisted evaluation report was altered."""
    if historical_peer_report_sha256(report) != report.report_sha256:
        raise ValueError("historical peer evaluation report hash does not replay")


def publish_historical_peer_evaluation(
    report_path: Path,
    report: HistoricalPeerEvaluationReport,
    store: ObjectStore,
) -> HistoricalPeerPublicationReceipt:
    """Persist one exact evaluation report through the generic object store."""
    file_hash = sha256_file(report_path)[0]
    persisted = HistoricalPeerEvaluationReport.model_validate_json(report_path.read_bytes())
    if persisted != report:
        raise ValueError("evaluation report file does not match the supplied report")
    verify_historical_peer_report(persisted)
    stored = store.push(
        report_path,
        ObjectKey(value=(f"evaluation/genre-peer-similarity-historical/sha256/{file_hash}.json")),
    )
    if stored.sha256 != file_hash:
        raise ValueError("object store changed historical evaluation report bytes")
    return HistoricalPeerPublicationReceipt(
        report=stored,
        report_sha256=file_hash,
        candidate_output_sha256=report.candidate_output_sha256,
        historical_database_sha256=report.historical_database_sha256,
    )
