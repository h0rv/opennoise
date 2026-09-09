"""Compatibility-only evaluation of a public membership candidate against H3."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from contextlib import closing
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from musix.common import sha256_file
from musix.genre_seed_universe import normalize_label
from musix.public_artist_membership import (
    ApprovedPublicMembershipInput,
    PublicArtistMembershipCandidateArtifact,
    StrictFrozenModel,
    canonical_sha256,
    verify_public_artist_membership_candidate,
)

if TYPE_CHECKING:
    from pathlib import Path

from musix.types import Sha256  # noqa: TC001


class HistoricalGenreEvaluation(StrictFrozenModel):
    """One matched H3 genre's positives-only top-k measurement."""

    genre_name: str
    genre_id: str
    historical_positive_top_k_count: int = Field(ge=0)
    candidate_overlap_count: int = Field(ge=0)
    candidate_prediction_count: int = Field(ge=0)


class HistoricalMembershipEvaluationReport(StrictFrozenModel):
    """Strict, compatibility-only positive-overlap evaluation output."""

    revision: Literal["public-artist-membership-historical-evaluation-v1"] = (
        "public-artist-membership-historical-evaluation-v1"
    )
    candidate_file_sha256: Sha256
    candidate_output_sha256: Sha256
    candidate_input_sha256: Sha256
    approved_input_file_sha256: Sha256
    approved_input_sha256: Sha256
    public_database_sha256: Sha256
    historical_database_sha256: Sha256
    historical_inputs_used_for_construction: Literal[False] = False
    independent_public_gold: Literal[False] = False
    absence_is_negative: Literal[False] = False
    historical_source_membership_count: int = Field(ge=0)
    historical_source_genre_count: int = Field(ge=0)
    strict_normalized_artist_name_crosswalk_count: int = Field(ge=0)
    strict_normalized_artist_id_crosswalk_count: int = Field(ge=0)
    k: int = Field(gt=0)
    matched_genre_count: int = Field(ge=0)
    mapped_historical_positive_count: int = Field(ge=0)
    candidate_overlap_count: int = Field(ge=0)
    candidate_prediction_count: int = Field(ge=0)
    micro_recall_at_k: float | None = Field(default=None, ge=0.0, le=1.0)
    per_genre: tuple[HistoricalGenreEvaluation, ...]


def _strict_name_map(
    connection: sqlite3.Connection,
) -> dict[str, str]:
    """Map unique preferred English primary names across every public artist ID."""
    names: dict[str, set[str]] = defaultdict(set)
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
        names[normalize_label(str(row[1]))].add(str(row[0]))
    return {name: next(iter(ids)) for name, ids in names.items() if len(ids) == 1}


def evaluate_public_artist_membership_historical(  # noqa: C901
    candidate_path: Path,
    approved_input_path: Path,
    public_database_path: Path,
    historical_database_path: Path,
    k: int = 50,
) -> HistoricalMembershipEvaluationReport:
    """Evaluate top-k candidate predictions against H3 positives; never construct."""
    if k < 1:
        raise ValueError("k must be positive")
    candidate_file_hash = sha256_file(candidate_path)[0]
    candidate_bytes = candidate_path.read_bytes()
    approved_file_hash = sha256_file(approved_input_path)[0]
    approved_bytes = approved_input_path.read_bytes()
    candidate = PublicArtistMembershipCandidateArtifact.model_validate_json(candidate_bytes)
    verify_public_artist_membership_candidate(candidate)
    approved = ApprovedPublicMembershipInput.model_validate_json(approved_bytes)
    expected_input_sha = canonical_sha256(
        {
            "name_universe": candidate.name_universe.model_dump(mode="json"),
            "approved_public_input": approved.model_dump(mode="json"),
        }
    )
    if candidate.input_sha256 != expected_input_sha:
        raise ValueError("candidate input hash does not match its parsed construction inputs")
    if sha256_file(candidate_path)[0] != candidate_file_hash:
        raise ValueError("candidate file changed while evaluating")
    if sha256_file(approved_input_path)[0] != approved_file_hash:
        raise ValueError("approved input file changed while evaluating")
    public_hash = sha256_file(public_database_path)[0]
    with closing(
        sqlite3.connect(f"file:{public_database_path.resolve()}?mode=ro", uri=True)
    ) as public:
        public.row_factory = sqlite3.Row
        strict_name_map = _strict_name_map(public)
    if sha256_file(public_database_path)[0] != public_hash:
        raise ValueError("public database changed while evaluating")

    h3_hash = sha256_file(historical_database_path)[0]
    with closing(
        sqlite3.connect(f"file:{historical_database_path.resolve()}?mode=ro", uri=True)
    ) as historical:
        historical.row_factory = sqlite3.Row
        h3_by_genre: dict[str, list[str]] = defaultdict(list)
        for row in historical.execute(
            """
            SELECT genres.name, observations.source_artist_name
              FROM historical_genre_artist_observations AS observations
              JOIN genres ON genres.id = observations.genre_id
             ORDER BY genres.name, COALESCE(observations.source_local_rank, 100000), observations.id
            """
        ):
            h3_by_genre[normalize_label(str(row[0]))].append(str(row[1]))
    if sha256_file(historical_database_path)[0] != h3_hash:
        raise ValueError("historical database changed while evaluating")

    genre_ids: dict[str, list[str]] = defaultdict(list)
    for item in approved.public_model_input.genres:
        genre_ids[normalize_label(item.name)].append(item.genre_id)
    artist_ids = {
        item.artist_id.removeprefix("musicbrainz:artist:")
        for item in (*candidate.directly_observed_memberships, *candidate.propagated_candidates)
    }
    strict_crosswalk = {
        name: artist_id for name, artist_id in strict_name_map.items() if artist_id in artist_ids
    }
    scored_by_genre: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for item in (*candidate.directly_observed_memberships, *candidate.propagated_candidates):
        scored_by_genre[item.genre_id].append(
            (item.score, item.artist_id.removeprefix("musicbrainz:artist:"))
        )

    matched_genres = mapped_positive_count = overlap_count = prediction_count = 0
    per_genre: list[HistoricalGenreEvaluation] = []
    for genre_name, artists in sorted(h3_by_genre.items()):
        ids = genre_ids.get(genre_name, ())
        if len(ids) != 1:
            continue
        matched_genres += 1
        positives = {
            strict_crosswalk[normalize_label(name)]
            for name in artists[:k]
            if normalize_label(name) in strict_crosswalk
        }
        predictions = {
            artist_id
            for _, artist_id in sorted(
                scored_by_genre.get(ids[0], ()), key=lambda item: (-item[0], item[1])
            )[:k]
        }
        overlap = len(positives & predictions)
        mapped_positive_count += len(positives)
        overlap_count += overlap
        prediction_count += len(predictions)
        per_genre.append(
            HistoricalGenreEvaluation(
                genre_name=genre_name,
                genre_id=ids[0],
                historical_positive_top_k_count=len(positives),
                candidate_overlap_count=overlap,
                candidate_prediction_count=len(predictions),
            )
        )
    return HistoricalMembershipEvaluationReport(
        candidate_file_sha256=candidate_file_hash,
        candidate_output_sha256=candidate.output_sha256,
        candidate_input_sha256=candidate.input_sha256,
        approved_input_file_sha256=approved_file_hash,
        approved_input_sha256=approved.public_model_input_sha256,
        public_database_sha256=public_hash,
        historical_database_sha256=h3_hash,
        historical_source_membership_count=sum(map(len, h3_by_genre.values())),
        historical_source_genre_count=len(h3_by_genre),
        strict_normalized_artist_name_crosswalk_count=len(strict_crosswalk),
        strict_normalized_artist_id_crosswalk_count=len(set(strict_crosswalk.values())),
        k=k,
        matched_genre_count=matched_genres,
        mapped_historical_positive_count=mapped_positive_count,
        candidate_overlap_count=overlap_count,
        candidate_prediction_count=prediction_count,
        micro_recall_at_k=overlap_count / mapped_positive_count if mapped_positive_count else None,
        per_genre=tuple(per_genre),
    )
