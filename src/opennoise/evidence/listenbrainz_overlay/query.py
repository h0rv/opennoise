"""Bounded read-only queries for certified ListenBrainz sidecars."""

from __future__ import annotations

import json
from contextlib import closing
from dataclasses import dataclass
from typing import Final

from opennoise.common import canonical_json, connect_readonly
from opennoise.ingest.listenbrainz.propagation import PropagationPath

from .contracts import (
    CertifiedCoListenOverlaySources,
    CertifiedDerivedReviewOverlaySources,
    ListenBrainzOverlayError,
)

_MAX_QUERY_LIMIT: Final = 1_000


@dataclass(frozen=True, slots=True)
class DerivedReviewCandidate:
    """One derived review candidate with its original propagation paths intact."""

    artist_mbid: str
    artist_source_id: str
    stable_seed_id: str
    legacy_seed_id: str
    score: float
    genre_rank: int
    paths: tuple[PropagationPath, ...]
    propagation_provenance_ref: str


@dataclass(frozen=True, slots=True)
class DerivedReviewCandidatePage:
    """A bounded seed page with complete matching-population accounting."""

    total_candidate_count: int
    returned_candidate_count: int
    candidates: tuple[DerivedReviewCandidate, ...]


@dataclass(frozen=True, slots=True)
class CoListenRelation:
    """One canonical-undirected aggregate relation seen from a requested artist."""

    artist_mbid: str
    neighbor_artist_mbid: str
    window_start: int
    window_end: int
    distinct_user_count: int
    evidence_fingerprint: str
    source_binding: str
    source_provenance_ref: str


@dataclass(frozen=True, slots=True)
class CoListenRelationPage:
    """A bounded artist page with all privacy-qualified graph-overlapping evidence."""

    total_relation_count: int
    returned_relation_count: int
    relations: tuple[CoListenRelation, ...]


def derived_reviews_for_seed(
    certified: CertifiedDerivedReviewOverlaySources,
    stable_seed_id: str,
    *,
    limit: int = 100,
) -> DerivedReviewCandidatePage:
    """Return review-only candidates for one exact stable seed after startup certification."""
    if not certified.is_valid():
        raise ListenBrainzOverlayError("derived-review sources are not startup-certified")
    _require_limit(limit)
    with closing(connect_readonly(certified.sources.database)) as database:
        database.execute("PRAGMA query_only = ON")
        rows = database.execute(
            """SELECT artist_mbid, artist_source_id, stable_seed_id, legacy_seed_id, score,
                      genre_rank, paths_json, propagation_provenance_ref, count(*) OVER ()
                 FROM review_candidate
                WHERE stable_seed_id = ?
             ORDER BY genre_rank, artist_mbid
                LIMIT ?""",
            (stable_seed_id, limit),
        ).fetchall()
    candidates = tuple(_review_candidate_from_row(row[:8]) for row in rows)
    return DerivedReviewCandidatePage(
        total_candidate_count=0 if not rows else int(rows[0][8]),
        returned_candidate_count=len(candidates),
        candidates=candidates,
    )


def colistens_for_artist(
    certified: CertifiedCoListenOverlaySources,
    artist_mbid: str,
    *,
    limit: int = 100,
) -> CoListenRelationPage:
    """Return privacy-qualified aggregate co-listens for an exact graph artist ID."""
    if not certified.is_valid():
        raise ListenBrainzOverlayError("co-listen sources are not startup-certified")
    _require_limit(limit)
    with closing(connect_readonly(certified.sources.database)) as database:
        database.execute("PRAGMA query_only = ON")
        rows = database.execute(
            """WITH scoped AS (
                   SELECT CASE
                              WHEN left_artist_mbid = ? THEN right_artist_mbid
                              ELSE left_artist_mbid
                          END AS neighbor_artist_mbid,
                          window_start, window_end, distinct_user_count, evidence_fingerprint,
                          source_binding, source_provenance_ref
                     FROM colisten_relation
                    WHERE left_artist_mbid = ? OR right_artist_mbid = ?
                 )
                 SELECT neighbor_artist_mbid, window_start, window_end, distinct_user_count,
                        evidence_fingerprint, source_binding, source_provenance_ref,
                        count(*) OVER ()
                   FROM scoped
               ORDER BY distinct_user_count DESC, window_start DESC, neighbor_artist_mbid,
                        evidence_fingerprint
                  LIMIT ?""",
            (artist_mbid, artist_mbid, artist_mbid, limit),
        ).fetchall()
    relations = tuple(
        CoListenRelation(
            artist_mbid=artist_mbid,
            neighbor_artist_mbid=str(row[0]),
            window_start=int(row[1]),
            window_end=int(row[2]),
            distinct_user_count=int(row[3]),
            evidence_fingerprint=str(row[4]),
            source_binding=str(row[5]),
            source_provenance_ref=str(row[6]),
        )
        for row in rows
    )
    return CoListenRelationPage(
        total_relation_count=0 if not rows else int(rows[0][7]),
        returned_relation_count=len(relations),
        relations=relations,
    )


def _review_candidate_from_row(row: tuple[object, ...]) -> DerivedReviewCandidate:
    try:
        raw_paths = json.loads(str(row[6]))
    except json.JSONDecodeError as error:
        raise ListenBrainzOverlayError("review candidate paths are malformed") from error
    if not isinstance(raw_paths, list):
        raise ListenBrainzOverlayError("review candidate paths are malformed")
    try:
        paths = tuple(PropagationPath.model_validate_json(canonical_json(item)) for item in raw_paths)
    except ValueError as error:
        raise ListenBrainzOverlayError("review candidate paths are invalid") from error
    if not paths:
        raise ListenBrainzOverlayError("review candidate lacks propagation paths")
    return DerivedReviewCandidate(
        artist_mbid=str(row[0]),
        artist_source_id=str(row[1]),
        stable_seed_id=str(row[2]),
        legacy_seed_id=str(row[3]),
        score=_as_float(row[4]),
        genre_rank=_as_int(row[5]),
        paths=paths,
        propagation_provenance_ref=str(row[7]),
    )


def _require_limit(limit: int) -> None:
    if not 1 <= limit <= _MAX_QUERY_LIMIT:
        raise ListenBrainzOverlayError(f"query limit must be between 1 and {_MAX_QUERY_LIMIT}")


def _as_float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ListenBrainzOverlayError("review candidate score is malformed")
    return float(value)


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ListenBrainzOverlayError("review candidate rank is malformed")
    return value
