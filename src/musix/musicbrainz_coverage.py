"""Evaluate MusicBrainz artist-genre coverage against Every Noise names only.

This module deliberately treats the Every Noise catalog as a vocabulary seed.  It
does not read its coordinates, historical memberships, or any other display
observations.  MusicBrainz evidence remains source-qualified and positive-only.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import unicodedata
from collections import Counter
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict, Field

from musix.reconstruction import (
    GenreArtistEdge,
    ReconstructionInputs,
    SimilarityMetric,
    SimilarityParameters,
    SimilarityRunResult,
    VersionedInput,
    build_artist_overlap_similarity,
)

if TYPE_CHECKING:
    from pathlib import Path

WHITESPACE: Final[re.Pattern[str]] = re.compile(r"\s+")
NON_ALNUM: Final[re.Pattern[str]] = re.compile(r"[^\w]+", re.UNICODE)


class CoverageMatch(BaseModel):
    """One seed name matched to one or more imported MusicBrainz genre IDs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    seed_name: str = Field(min_length=1)
    match_kind: str = Field(pattern=r"^(exact|normalized)$")
    musicbrainz_genre_ids: tuple[str, ...] = Field(min_length=1)
    positive_artist_count: int = Field(ge=0)
    positive_evidence_count: int = Field(ge=0)


class CoverageReport(BaseModel):
    """Typed, deterministic coverage report and its reproducibility metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_revision: str = "musicbrainz-coverage-v1"
    research_database: str
    seed_database: str
    source_key: str
    seed_name_count: int = Field(ge=0)
    imported_genre_count: int = Field(ge=0)
    imported_genre_alias_count: int = Field(ge=0)
    imported_name_count: int = Field(ge=0)
    imported_positive_genre_count: int = Field(ge=0)
    imported_positive_artist_count: int = Field(ge=0)
    imported_positive_evidence_count: int = Field(ge=0)
    imported_positive_weight_sum: float = Field(ge=0)
    imported_positive_weight_distribution: dict[str, int]
    exact_match_count: int = Field(ge=0)
    normalized_match_count: int = Field(ge=0)
    exact_positive_match_count: int = Field(ge=0)
    normalized_positive_match_count: int = Field(ge=0)
    distinct_matched_genre_count: int = Field(ge=0)
    distinct_positive_artist_count: int = Field(ge=0)
    positive_evidence_count: int = Field(ge=0)
    positive_weight_sum: float = Field(ge=0)
    positive_weight_distribution: dict[str, int]
    normalized_rule: str
    matches: tuple[CoverageMatch, ...]
    unmatched_seed_names: tuple[str, ...]
    runtime_seconds: float = Field(ge=0)


class ReconstructionArtifactReport(BaseModel):
    """Hashes and graph metrics for an optional source-only baseline artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_revision: str = "musicbrainz-reconstruction-inputs-v1"
    inputs_path: str
    inputs_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed_matched_genre_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    artist_count: int = Field(ge=0)
    weighted_jaccard_neighbor_count: int = Field(ge=0)
    weighted_cosine_neighbor_count: int = Field(ge=0)
    weighted_jaccard_pair_visits: int = Field(ge=0)
    weighted_cosine_pair_visits: int = Field(ge=0)


class BaselineRun(BaseModel):
    """One deterministic source-only overlap baseline summary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: SimilarityMetric
    genre_count: int = Field(ge=1)
    candidate_pair_count: int = Field(ge=0)
    pair_visit_count: int = Field(ge=0)
    retained_edge_count: int = Field(ge=0)
    neighbor_count: int = Field(ge=0)


class BaselineReport(BaseModel):
    """Deterministic summary of source-only overlap baselines."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    runs: tuple[BaselineRun, ...] = Field(min_length=1, max_length=2)


def normalize_label(value: str) -> str:
    """Normalize labels for conservative case, accent, punctuation, and space matching."""
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    words = NON_ALNUM.sub(" ", unicodedata.normalize("NFKC", without_marks))
    return WHITESPACE.sub(" ", words).strip()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_seed_names(connection: sqlite3.Connection) -> tuple[str, ...]:
    rows = connection.execute(
        "SELECT name FROM genres WHERE entity_kind = 'genre' ORDER BY id"
    ).fetchall()
    names = tuple(str(row[0]) for row in rows)
    if len(names) != len(set(names)):
        raise ValueError("seed genre names must be unique")
    return names


def _read_imported_genres(
    connection: sqlite3.Connection,
    source_key: str,
) -> tuple[tuple[str, str, str], ...]:
    """Return (genre ID, name, name kind), including only source-qualified genres."""
    rows = connection.execute(
        """
        SELECT DISTINCT identifiers.normalized_value, names.name, names.name_kind
        FROM genres AS genres
        JOIN catalog_entities AS entities ON entities.id = genres.id
        JOIN (
            SELECT entity_id, normalized_value
            FROM entity_identifiers
            WHERE identifier_type_id = (
                SELECT id FROM identifier_types WHERE type_key = 'musicbrainz_genre_id'
            )
            GROUP BY entity_id, normalized_value
        ) AS identifiers ON identifiers.entity_id = entities.id
        JOIN entity_names AS names ON names.entity_id = entities.id
        JOIN artist_genre_evidence AS evidence ON evidence.genre_id = genres.id
        WHERE evidence.source_key = ?
        ORDER BY identifiers.normalized_value, names.name_kind, names.name
        """,
        (source_key,),
    ).fetchall()
    # Older projections store the genre name only on genres, not entity_names.
    fallback = connection.execute(
        """
        SELECT DISTINCT identifiers.normalized_value, genres.name, 'primary'
        FROM genres
        JOIN (
            SELECT entity_id, normalized_value
            FROM entity_identifiers
            WHERE identifier_type_id = (
                SELECT id FROM identifier_types WHERE type_key = 'musicbrainz_genre_id'
            )
            GROUP BY entity_id, normalized_value
        ) AS identifiers ON identifiers.entity_id = genres.id
        JOIN artist_genre_evidence AS evidence ON evidence.genre_id = genres.id
        WHERE evidence.source_key = ?
        ORDER BY identifiers.normalized_value, genres.name
        """,
        (source_key,),
    ).fetchall()
    values = {(str(row[0]), str(row[1]), str(row[2])) for row in rows}
    values.update((str(row[0]), str(row[1]), str(row[2])) for row in fallback)
    return tuple(sorted(values))


def _positive_evidence(
    connection: sqlite3.Connection,
    source_key: str,
) -> dict[str, tuple[int, int, float, tuple[tuple[str, str], ...]]]:
    """Index genre UUID to artists, row count, total count, and evidence references."""
    rows = connection.execute(
        """
        SELECT genre_identifiers.normalized_value,
               artist_identifiers.normalized_value,
               evidence.evidence_value,
               evidence.id
        FROM artist_genre_evidence AS evidence
        JOIN genres AS genres ON genres.id = evidence.genre_id
        JOIN (
            SELECT entity_id, normalized_value
            FROM entity_identifiers
            WHERE identifier_type_id = (
                SELECT id FROM identifier_types WHERE type_key = 'musicbrainz_genre_id'
            )
            GROUP BY entity_id, normalized_value
        ) AS genre_identifiers ON genre_identifiers.entity_id = genres.id
        JOIN artists AS artists ON artists.id = evidence.artist_id
        JOIN (
            SELECT entity_id, normalized_value
            FROM entity_identifiers
            WHERE identifier_type_id = (
                SELECT id FROM identifier_types WHERE type_key = 'source_id'
            )
            GROUP BY entity_id, normalized_value
        ) AS artist_identifiers ON artist_identifiers.entity_id = artists.id
        WHERE evidence.source_key = ? AND evidence.evidence_value > 0
        ORDER BY genre_identifiers.normalized_value,
                 artist_identifiers.normalized_value, evidence.id
        """,
        (source_key,),
    ).fetchall()
    grouped: dict[str, list[tuple[str, float, str]]] = {}
    for genre_id, artist_id, weight, evidence_id in rows:
        grouped.setdefault(str(genre_id), []).append(
            (str(artist_id), float(weight), str(evidence_id))
        )
    return {
        genre_id: (
            len({artist_id for artist_id, _, _ in values}),
            len(values),
            sum(weight for _, weight, _ in values),
            tuple((artist_id, evidence_id) for artist_id, _, evidence_id in values),
        )
        for genre_id, values in grouped.items()
    }


def _positive_weights(
    connection: sqlite3.Connection,
    source_key: str,
) -> dict[str, float]:
    """Return positive evidence weights keyed by their stable database row ID."""
    rows = connection.execute(
        """
        SELECT id, evidence_value
        FROM artist_genre_evidence
        WHERE source_key = ? AND evidence_value > 0
        ORDER BY id
        """,
        (source_key,),
    ).fetchall()
    return {str(row[0]): float(row[1]) for row in rows}


def evaluate_coverage(
    research_database: Path,
    seed_database: Path,
    *,
    source_key: str = "musicbrainz_json_artist_research_20260829",
) -> CoverageReport:
    """Compare imported genre labels and direct positive evidence to seed names."""
    started = time.monotonic()
    with (
        sqlite3.connect(seed_database) as seed_connection,
        sqlite3.connect(research_database) as research_connection,
    ):
        seed_names = _read_seed_names(seed_connection)
        imported = _read_imported_genres(research_connection, source_key)
        evidence = _positive_evidence(research_connection, source_key)
        weights = _positive_weights(research_connection, source_key)
    imported_positive_genres = set(evidence)
    imported_positive_artists = {
        artist_id for _, _, _, refs in evidence.values() for artist_id, _ in refs
    }
    imported_positive_distribution: Counter[str] = Counter()
    for weight in weights.values():
        imported_positive_distribution[str(int(weight) if weight.is_integer() else weight)] += 1
    by_exact: dict[str, set[str]] = {}
    by_normalized: dict[str, set[str]] = {}
    alias_count = 0
    for genre_id, name, name_kind in imported:
        by_exact.setdefault(name, set()).add(genre_id)
        by_normalized.setdefault(normalize_label(name), set()).add(genre_id)
        alias_count += int(name_kind == "alias")

    matches: list[CoverageMatch] = []
    unmatched: list[str] = []
    exact_positive = normalized_positive = 0
    all_genres: set[str] = set()
    all_artists: set[str] = set()
    total_evidence = 0
    total_weight = 0.0
    distribution: Counter[str] = Counter()
    for seed_name in seed_names:
        exact_ids = tuple(sorted(by_exact.get(seed_name, ())))
        match_kind = "exact" if exact_ids else "normalized"
        genre_ids = exact_ids or tuple(sorted(by_normalized.get(normalize_label(seed_name), ())))
        if not genre_ids:
            unmatched.append(seed_name)
            continue
        genre_evidence = [evidence.get(genre_id, (0, 0, 0.0, ())) for genre_id in genre_ids]
        artists = {artist_id for _, _, _, refs in genre_evidence for artist_id, _ in refs}
        evidence_count = sum(item[1] for item in genre_evidence)
        matches.append(
            CoverageMatch(
                seed_name=seed_name,
                match_kind=match_kind,
                musicbrainz_genre_ids=genre_ids,
                positive_artist_count=len(artists),
                positive_evidence_count=evidence_count,
            )
        )
        exact_positive += int(bool(exact_ids and artists))
        normalized_positive += int(bool(artists))
        all_genres.update(genre_ids)
        all_artists.update(artists)
        total_evidence += evidence_count
        total_weight += sum(item[2] for item in genre_evidence)
        for _, _, _, refs in genre_evidence:
            for _, evidence_id in refs:
                weight = weights[evidence_id]
                distribution[str(int(weight) if float(weight).is_integer() else weight)] += 1
    return CoverageReport(
        research_database=str(research_database),
        seed_database=str(seed_database),
        source_key=source_key,
        seed_name_count=len(seed_names),
        imported_genre_count=len({genre_id for genre_id, _, _ in imported}),
        imported_genre_alias_count=alias_count,
        imported_name_count=len(imported),
        imported_positive_genre_count=len(imported_positive_genres),
        imported_positive_artist_count=len(imported_positive_artists),
        imported_positive_evidence_count=len(weights),
        imported_positive_weight_sum=sum(weights.values()),
        imported_positive_weight_distribution=dict(sorted(imported_positive_distribution.items())),
        exact_match_count=sum(match.match_kind == "exact" for match in matches),
        normalized_match_count=len(matches),
        exact_positive_match_count=exact_positive,
        normalized_positive_match_count=normalized_positive,
        distinct_matched_genre_count=len(all_genres),
        distinct_positive_artist_count=len(all_artists),
        positive_evidence_count=total_evidence,
        positive_weight_sum=total_weight,
        positive_weight_distribution=dict(sorted(distribution.items())),
        normalized_rule=(
            "NFKD, casefold, remove combining marks, punctuation to spaces, collapse spaces"
        ),
        matches=tuple(matches),
        unmatched_seed_names=tuple(unmatched),
        runtime_seconds=time.monotonic() - started,
    )


def build_reconstruction_inputs(
    research_database: Path,
    coverage: CoverageReport,
    *,
    source_key: str = "musicbrainz_json_artist_research_20260829",
) -> ReconstructionInputs:
    """Materialize unique source-only edges for matched seed names."""
    matched_ids = {
        genre_id for match in coverage.matches for genre_id in match.musicbrainz_genre_ids
    }
    with sqlite3.connect(research_database) as connection:
        rows = connection.execute(
            """
            SELECT genre_identifiers.normalized_value, artist_identifiers.normalized_value,
                   SUM(evidence.evidence_value), GROUP_CONCAT(evidence.id)
            FROM artist_genre_evidence AS evidence
            JOIN genres ON genres.id = evidence.genre_id
            JOIN (
                SELECT entity_id, normalized_value
                FROM entity_identifiers
                WHERE identifier_type_id = (
                    SELECT id FROM identifier_types WHERE type_key = 'musicbrainz_genre_id'
                )
                GROUP BY entity_id, normalized_value
            ) AS genre_identifiers ON genre_identifiers.entity_id = genres.id
            JOIN artists ON artists.id = evidence.artist_id
            JOIN (
                SELECT entity_id, normalized_value
                FROM entity_identifiers
                WHERE identifier_type_id = (
                    SELECT id FROM identifier_types WHERE type_key = 'source_id'
                )
                GROUP BY entity_id, normalized_value
            ) AS artist_identifiers ON artist_identifiers.entity_id = artists.id
            WHERE evidence.source_key = ? AND evidence.evidence_value > 0
            GROUP BY genre_identifiers.normalized_value, artist_identifiers.normalized_value
            ORDER BY genre_identifiers.normalized_value, artist_identifiers.normalized_value
            """,
            (source_key,),
        ).fetchall()
    edges = tuple(
        GenreArtistEdge(
            genre_id=f"musicbrainz:genre:{genre_id}",
            artist_id=f"musicbrainz:artist:{artist_id}",
            weight=float(weight),
            evidence_refs=tuple(
                f"musicbrainz:artist_genre_evidence:{item}" for item in str(refs).split(",")
            ),
        )
        for genre_id, artist_id, weight, refs in rows
        if str(genre_id) in matched_ids
    )
    canonical = json.dumps(
        {
            "membership_artifact": "musicbrainz-artist-genre-v3",
            "source_key": source_key,
            "edges": [edge.model_dump(mode="json") for edge in edges],
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return ReconstructionInputs(
        membership_artifact=VersionedInput(
            artifact_key="musicbrainz-artist-genre-v3",
            revision="2026-08-29:sha256-prefix-0:seed-name-matches",
            content_sha256=_sha256_bytes(canonical),
        ),
        membership_edges=edges,
    )


def run_source_baselines(inputs: ReconstructionInputs) -> tuple[SimilarityRunResult, ...]:
    """Run bounded weighted Jaccard and cosine baselines over source-only edges."""
    return tuple(
        build_artist_overlap_similarity(
            inputs.membership_edges,
            SimilarityParameters(metric=metric, max_neighbors=10),
        )
        for metric in (SimilarityMetric.WEIGHTED_JACCARD, SimilarityMetric.WEIGHTED_COSINE)
    )


def write_reconstruction_inputs(path: Path, inputs: ReconstructionInputs) -> str:
    """Write stable JSON and return its content hash."""
    payload = (inputs.model_dump_json(indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return _sha256_bytes(payload)
