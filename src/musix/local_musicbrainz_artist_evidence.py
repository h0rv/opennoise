"""Read direct MusicBrainz seed memberships from local research SQLite evidence.

This module deliberately has no public-store or HTTP dependency. It reads a
completed local research database and a verified all-seed reconciliation
sidecar, and it never treats release-group support or contextual tags as direct
artist membership.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from hashlib import sha256
from time import monotonic
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, FiniteFloat

from musix.genre_seed_universe import normalize_label
from musix.models import FrozenModel
from musix.musicbrainz_model_adapter import (
    MusicBrainzModelAdapterReport,
    verify_musicbrainz_model_adapter_report,
)
from musix.musicbrainz_release_group_evidence import (
    ReleaseGroupEvidenceArtifact,
    verify_release_group_evidence,
)
from musix.open_construction_store_v2 import _ALIASES_BY_NODE_ID

if TYPE_CHECKING:
    from pathlib import Path

    from musix.seed_reconciliation import (
        SeedReconciliationArtifact,
        SeedReconciliationDisposition,
    )

_MAX_RESULTS: Final = 100
_ARTIST_ROW_COLUMN_COUNT: Final = 3
_EXPECTED_DIRECT_COLUMNS: Final = frozenset({"genre_id", "artist_id", "facet", "evidence_ref"})

type DirectFacet = Literal["musicbrainz_genre", "musicbrainz_tag"]


class LocalMusicBrainzArtistEvidenceError(ValueError):
    """Raised when a local evidence database or stable seed query is invalid."""


@dataclass(frozen=True, slots=True)
class LocalMusicBrainzEvidenceSources:
    """The immutable inputs required for one local direct-membership query."""

    database: Path
    evidence_artifact: ReleaseGroupEvidenceArtifact
    reconciliation: SeedReconciliationArtifact
    adapter_report: MusicBrainzModelAdapterReport


class LocalResearchSeed(FrozenModel):
    """One preserved legacy seed identity from the reconciliation sidecar."""

    source_item_id: str = Field(min_length=1)
    source_external_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    disposition: str = Field(min_length=1)


class DirectArtistClaim(FrozenModel):
    """Direct artist membership grouped by stable MusicBrainz artist ID."""

    artist_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")
    facets: tuple[DirectFacet, ...] = Field(min_length=1, max_length=2)
    evidence_reference_count: int = Field(ge=1)


class LocalArtistEvidenceResponse(FrozenModel):
    """One bounded local-research result, never a public serving response."""

    scope: Literal["local_research_only"] = "local_research_only"
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    contextual_claims_available: Literal[False] = False
    release_group_support_included: Literal[False] = False
    verification_seconds: FiniteFloat = Field(ge=0.0)
    query_seconds: FiniteFloat = Field(ge=0.0)
    seed_universe_count: int = Field(ge=1)
    seed: LocalResearchSeed
    artists: tuple[DirectArtistClaim, ...] = Field(max_length=_MAX_RESULTS)
    total_direct_artist_count: int = Field(ge=0)
    remaining_direct_artist_count: int = Field(ge=0)


class LocalArtistSeedResponse(FrozenModel):
    """The direct stable-seed claims for one exact MusicBrainz artist ID."""

    scope: Literal["local_research_only"] = "local_research_only"
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    contextual_claims_available: Literal[False] = False
    release_group_support_included: Literal[False] = False
    verification_seconds: FiniteFloat = Field(ge=0.0)
    query_seconds: FiniteFloat = Field(ge=0.0)
    artist_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")
    seeds: tuple[LocalResearchSeed, ...] = Field(max_length=_MAX_RESULTS)
    total_direct_seed_count: int = Field(ge=0)
    remaining_direct_seed_count: int = Field(ge=0)


def resolve_seed_query(reconciliation: SeedReconciliationArtifact, query: str) -> LocalResearchSeed:
    """Resolve an exact stable ID or one reviewed display alias to a stable seed."""
    by_id = {row.source_item_id: row for row in reconciliation.dispositions}
    if row := by_id.get(query):
        return _seed(row)
    normalized_query = normalize_label(query)
    matches = [
        row
        for row in reconciliation.dispositions
        if normalized_query
        in _seed_search_terms(row.source_item_id, row.seed_name, row.normalized_name)
    ]
    if len(matches) != 1:
        raise LocalMusicBrainzArtistEvidenceError(
            "seed query must resolve to exactly one stable source_item_id"
        )
    return _seed(matches[0])


def direct_artists_for_seed(
    sources: LocalMusicBrainzEvidenceSources,
    seed_query: str,
    *,
    limit: int = 25,
) -> LocalArtistEvidenceResponse:
    """Return bounded direct MusicBrainz artists for one preserved seed."""
    _require_limit(limit)
    _require_source_binding(sources)
    seed = resolve_seed_query(sources.reconciliation, seed_query)
    connection, verification_seconds = _verified_database(
        sources.database, sources.evidence_artifact
    )
    with closing(connection):
        _require_direct_anchor_schema(connection)
        query_started = monotonic()
        raw_rows = connection.execute(
            """SELECT artist_id, facet, count(*)
                 FROM direct_anchor
                 WHERE genre_id = ?
                 GROUP BY artist_id, facet
                 ORDER BY artist_id, facet""",
            (seed.source_item_id,),
        ).fetchall()
        query_seconds = monotonic() - query_started
    claims = _group_artist_claims(_parse_artist_rows(raw_rows))
    return LocalArtistEvidenceResponse(
        seed_universe_count=sources.reconciliation.seed_count,
        seed=seed,
        verification_seconds=verification_seconds,
        query_seconds=query_seconds,
        artists=claims[:limit],
        total_direct_artist_count=len(claims),
        remaining_direct_artist_count=max(0, len(claims) - limit),
    )


def direct_seeds_for_artist(
    sources: LocalMusicBrainzEvidenceSources,
    artist_mbid: str,
    *,
    limit: int = 25,
) -> LocalArtistSeedResponse:
    """Return bounded direct stable seeds for one exact MusicBrainz artist ID."""
    _require_limit(limit)
    _require_source_binding(sources)
    by_id = {row.source_item_id: row for row in sources.reconciliation.dispositions}
    connection, verification_seconds = _verified_database(
        sources.database, sources.evidence_artifact
    )
    with closing(connection):
        _require_direct_anchor_schema(connection)
        query_started = monotonic()
        raw_rows = connection.execute(
            """SELECT genre_id
                 FROM direct_anchor
                 WHERE artist_id = ?
                 GROUP BY genre_id
                 ORDER BY genre_id""",
            (artist_mbid,),
        ).fetchall()
        query_seconds = monotonic() - query_started
    seed_ids = _parse_seed_ids(raw_rows)
    unknown_ids = set(seed_ids) - set(by_id)
    if unknown_ids:
        raise LocalMusicBrainzArtistEvidenceError(
            "direct evidence contains genre IDs outside the reconciliation sidecar"
        )
    seeds = tuple(_seed(by_id[seed_id]) for seed_id in seed_ids)
    return LocalArtistSeedResponse(
        artist_mbid=artist_mbid,
        verification_seconds=verification_seconds,
        query_seconds=query_seconds,
        seeds=seeds[:limit],
        total_direct_seed_count=len(seeds),
        remaining_direct_seed_count=max(0, len(seeds) - limit),
    )


def load_release_group_evidence_artifact(path: Path) -> ReleaseGroupEvidenceArtifact:
    """Parse and verify the small artifact that binds a completed SQLite database."""
    try:
        artifact = ReleaseGroupEvidenceArtifact.model_validate_json(path.read_bytes())
        verify_release_group_evidence(artifact)
    except (OSError, ValueError) as error:
        raise LocalMusicBrainzArtistEvidenceError(
            "release-group evidence artifact is invalid"
        ) from error
    return artifact


def load_musicbrainz_model_adapter_report(path: Path) -> MusicBrainzModelAdapterReport:
    """Parse and verify the small report that binds seed and target artifacts."""
    try:
        report = MusicBrainzModelAdapterReport.model_validate_json(path.read_bytes())
        verify_musicbrainz_model_adapter_report(report)
    except (OSError, ValueError) as error:
        raise LocalMusicBrainzArtistEvidenceError(
            "MusicBrainz adapter report is invalid"
        ) from error
    return report


def _require_source_binding(sources: LocalMusicBrainzEvidenceSources) -> None:
    verify_release_group_evidence(sources.evidence_artifact)
    verify_musicbrainz_model_adapter_report(sources.adapter_report)
    if (
        sources.adapter_report.seed_target_output_sha256
        != sources.evidence_artifact.seed_target_output_sha256
        or sources.adapter_report.seed_reconciliation_output_sha256
        != sources.reconciliation.output_sha256
        or sources.adapter_report.seed_count != sources.reconciliation.seed_count
        or sources.adapter_report.seed_source_id != sources.reconciliation.seed_source_id
        or sources.adapter_report.seed_source_content_sha256
        != sources.reconciliation.seed_source_content_sha256
        or sources.adapter_report.seed_identity_fingerprint
        != sources.reconciliation.seed_identity_sha256
    ):
        raise LocalMusicBrainzArtistEvidenceError(
            "evidence database and reconciliation sidecar do not share a verified seed binding"
        )


def _verified_database(
    path: Path, artifact: ReleaseGroupEvidenceArtifact
) -> tuple[sqlite3.Connection, float]:
    verification_started = monotonic()
    verify_release_group_evidence(artifact)
    if path.suffix == ".partial":
        raise LocalMusicBrainzArtistEvidenceError("partial evidence databases are not queryable")
    if not path.is_file():
        raise LocalMusicBrainzArtistEvidenceError("local evidence database does not exist")
    database_sha, database_bytes = _file_sha256(path)
    if (database_sha, database_bytes) != (
        artifact.evidence_database_sha256,
        artifact.evidence_database_bytes,
    ):
        raise LocalMusicBrainzArtistEvidenceError(
            "local evidence database does not match the completed evidence artifact"
        )
    connection = sqlite3.connect(f"file:{path.absolute()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
        connection.close()
        raise LocalMusicBrainzArtistEvidenceError("local evidence database failed integrity check")
    return connection, monotonic() - verification_started


def _file_sha256(path: Path) -> tuple[str, int]:
    digest = sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _require_direct_anchor_schema(connection: sqlite3.Connection) -> None:
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info('direct_anchor')")}
    if not columns >= _EXPECTED_DIRECT_COLUMNS:
        raise LocalMusicBrainzArtistEvidenceError(
            "local evidence database has no compatible direct_anchor table"
        )


def _seed_search_terms(source_item_id: str, name: str, normalized_name: str) -> frozenset[str]:
    alias = _ALIASES_BY_NODE_ID.get(f"legacy:{source_item_id}")
    alias_terms = alias.search_terms if alias is not None else ()
    return frozenset(
        normalize_label(value) for value in (source_item_id, name, normalized_name, *alias_terms)
    )


def _seed(row: SeedReconciliationDisposition) -> LocalResearchSeed:
    """Project a verified reconciliation row into the local CLI response."""
    return LocalResearchSeed(
        source_item_id=row.source_item_id,
        source_external_id=row.source_external_id,
        name=row.seed_name,
        disposition=row.disposition,
    )


def _parse_artist_rows(rows: list[tuple[object, ...]]) -> list[tuple[str, str, int]]:
    parsed: list[tuple[str, str, int]] = []
    for row in rows:
        if len(row) != _ARTIST_ROW_COLUMN_COUNT:
            raise LocalMusicBrainzArtistEvidenceError("direct evidence has an invalid row shape")
        artist_mbid, facet, reference_count = row
        if not isinstance(artist_mbid, str) or not isinstance(facet, str):
            raise LocalMusicBrainzArtistEvidenceError("direct evidence has non-text identifiers")
        if not isinstance(reference_count, int) or reference_count < 1:
            raise LocalMusicBrainzArtistEvidenceError(
                "direct evidence has an invalid reference count"
            )
        parsed.append((artist_mbid, facet, reference_count))
    return parsed


def _parse_seed_ids(rows: list[tuple[object, ...]]) -> tuple[str, ...]:
    parsed: list[str] = []
    for row in rows:
        if len(row) != 1 or not isinstance(row[0], str):
            raise LocalMusicBrainzArtistEvidenceError("direct evidence has an invalid seed row")
        parsed.append(row[0])
    return tuple(parsed)


def _group_artist_claims(rows: list[tuple[str, str, int]]) -> tuple[DirectArtistClaim, ...]:
    grouped: dict[str, dict[DirectFacet, int]] = defaultdict(dict)
    for artist_mbid, raw_facet, reference_count in rows:
        if raw_facet not in {"musicbrainz_genre", "musicbrainz_tag"}:
            raise LocalMusicBrainzArtistEvidenceError("direct evidence has an unknown facet")
        facet: DirectFacet = raw_facet
        grouped[artist_mbid][facet] = reference_count
    return tuple(
        DirectArtistClaim(
            artist_mbid=artist_mbid,
            facets=tuple(sorted(facets)),
            evidence_reference_count=sum(facets.values()),
        )
        for artist_mbid, facets in sorted(grouped.items())
    )


def _require_limit(limit: int) -> None:
    if not 1 <= limit <= _MAX_RESULTS:
        raise LocalMusicBrainzArtistEvidenceError(f"limit must be between 1 and {_MAX_RESULTS}")
