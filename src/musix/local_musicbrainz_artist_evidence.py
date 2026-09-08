"""Read typed MusicBrainz artist evidence from a local research SQLite database.

This module deliberately has no public-store or HTTP dependency. It reads a
completed local research database and a verified all-seed reconciliation
sidecar. Release-group support remains separate from direct artist membership.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path  # noqa: TC003  # Litestar resolves dependency dataclass annotations.
from time import monotonic
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, FiniteFloat

from musix.genre_seed_universe import normalize_label
from musix.local_musicbrainz_artist_metadata import (
    LocalArtistMetadataSources,
    LocalMusicBrainzArtistMetadataError,
    exact_canonical_names,
    verify_local_artist_metadata_sources,
)
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
    from musix.seed_reconciliation import (
        SeedReconciliationArtifact,
        SeedReconciliationDisposition,
    )

_MAX_RESULTS: Final = 100
_ARTIST_ROW_COLUMN_COUNT: Final = 3
_SUPPORT_ROW_COLUMN_COUNT: Final = 3
_EXPECTED_DIRECT_COLUMNS: Final = frozenset({"genre_id", "artist_id", "facet", "evidence_ref"})
_EXPECTED_SUPPORT_COLUMNS: Final = frozenset(
    {"genre_id", "artist_id", "facet", "release_group_id", "evidence_ref"}
)

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
    artist_metadata: LocalArtistMetadataSources | None = None


@dataclass(slots=True)
class LocalMusicBrainzArtistEvidenceStore:
    """A process-local, startup-certified reader for loopback research UI."""

    sources: LocalMusicBrainzEvidenceSources
    _ready: bool = False

    def start(self) -> None:
        """Verify immutable files once before accepting bounded queries."""
        _require_source_binding(self.sources)
        connection, _ = _verified_database(self.sources.database, self.sources.evidence_artifact)
        with closing(connection):
            _require_direct_anchor_schema(connection)
            _require_release_group_support_schema(connection)
        if self.sources.artist_metadata is not None:
            if (
                self.sources.artist_metadata.artifact.evidence_output_sha256
                != self.sources.evidence_artifact.output_sha256
            ):
                raise LocalMusicBrainzArtistEvidenceError(
                    "artist metadata does not bind the completed evidence artifact"
                )
            verify_local_artist_metadata_sources(self.sources.artist_metadata)
        self._ready = True

    @property
    def configured(self) -> bool:
        """Whether startup certification completed successfully."""
        return self._ready

    def artists_for_seed(self, seed_query: str, *, limit: int = 25) -> LocalArtistEvidenceResponse:
        """Query a startup-certified database without recalculating its full hash."""
        if not self._ready:
            raise LocalMusicBrainzArtistEvidenceError("local research evidence is not certified")
        return _direct_artists_for_seed(self.sources, seed_query, limit=limit, trusted=True)

    def seeds_for_artist(self, artist_mbid: str, *, limit: int = 25) -> LocalArtistSeedResponse:
        """Return exact direct and album-supported stable seeds after certification."""
        if not self._ready:
            raise LocalMusicBrainzArtistEvidenceError("local research evidence is not certified")
        return _direct_seeds_for_artist(self.sources, artist_mbid, limit=limit, trusted=True)


class LocalResearchSeed(FrozenModel):
    """One preserved legacy seed identity from the reconciliation sidecar."""

    source_item_id: str = Field(min_length=1)
    source_external_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    disposition: str = Field(min_length=1)


class DirectArtistClaim(FrozenModel):
    """Direct artist membership grouped by stable MusicBrainz artist ID."""

    artist_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")
    canonical_name: str | None = None
    facets: tuple[DirectFacet, ...] = Field(min_length=1, max_length=2)
    evidence_reference_count: int = Field(ge=1)


class AlbumSupportFacet(FrozenModel):
    """Capped release-group support for one source facet, not a direct claim."""

    facet: DirectFacet
    distinct_release_group_count: int = Field(ge=1)


class AlbumSupportedArtistClaim(FrozenModel):
    """One artist supported by matched release groups for a stable seed."""

    artist_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")
    canonical_name: str | None = None
    facets: tuple[AlbumSupportFacet, ...] = Field(min_length=1, max_length=2)
    distinct_release_group_count: int = Field(ge=1)


class AlbumSupportedSeedClaim(FrozenModel):
    """One stable seed supported by matched release groups for an exact artist."""

    seed: LocalResearchSeed
    facets: tuple[AlbumSupportFacet, ...] = Field(min_length=1, max_length=2)
    distinct_release_group_count: int = Field(ge=1)


class LocalArtistEvidenceResponse(FrozenModel):
    """One bounded local-research result, never a public serving response."""

    scope: Literal["local_research_only"] = "local_research_only"
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    contextual_claims_available: Literal[False] = False
    release_group_support_included: Literal[True] = True
    verification_seconds: FiniteFloat = Field(ge=0.0)
    query_seconds: FiniteFloat = Field(ge=0.0)
    seed_universe_count: int = Field(ge=1)
    seed: LocalResearchSeed
    artists: tuple[DirectArtistClaim, ...] = Field(max_length=_MAX_RESULTS)
    total_direct_artist_count: int = Field(ge=0)
    remaining_direct_artist_count: int = Field(ge=0)
    album_supported_artists: tuple[AlbumSupportedArtistClaim, ...] = Field(max_length=_MAX_RESULTS)
    total_album_supported_artist_count: int = Field(ge=0)
    remaining_album_supported_artist_count: int = Field(ge=0)


class LocalArtistSeedResponse(FrozenModel):
    """The direct stable-seed claims for one exact MusicBrainz artist ID."""

    scope: Literal["local_research_only"] = "local_research_only"
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    contextual_claims_available: Literal[False] = False
    release_group_support_included: Literal[True] = True
    verification_seconds: FiniteFloat = Field(ge=0.0)
    query_seconds: FiniteFloat = Field(ge=0.0)
    artist_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")
    seeds: tuple[LocalResearchSeed, ...] = Field(max_length=_MAX_RESULTS)
    total_direct_seed_count: int = Field(ge=0)
    remaining_direct_seed_count: int = Field(ge=0)
    album_supported_seeds: tuple[AlbumSupportedSeedClaim, ...] = Field(max_length=_MAX_RESULTS)
    total_album_supported_seed_count: int = Field(ge=0)
    remaining_album_supported_seed_count: int = Field(ge=0)


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
    """Return direct and separately album-supported artists for one stable seed."""
    return _direct_artists_for_seed(sources, seed_query, limit=limit, trusted=False)


def _direct_artists_for_seed(
    sources: LocalMusicBrainzEvidenceSources,
    seed_query: str,
    *,
    limit: int,
    trusted: bool,
) -> LocalArtistEvidenceResponse:
    """Implement the public query and the startup-certified store query."""
    _require_limit(limit)
    if not trusted:
        _require_source_binding(sources)
    seed = resolve_seed_query(sources.reconciliation, seed_query)
    connection, verification_seconds = (
        _trusted_database(sources.database)
        if trusted
        else _verified_database(sources.database, sources.evidence_artifact)
    )
    with closing(connection):
        _require_direct_anchor_schema(connection)
        _require_release_group_support_schema(connection)
        query_started = monotonic()
        raw_rows = connection.execute(
            """SELECT artist_id, facet, count(*)
                 FROM direct_anchor
                 WHERE genre_id = ?
                 GROUP BY artist_id, facet
                 ORDER BY artist_id, facet""",
            (seed.source_item_id,),
        ).fetchall()
        support_total = _support_artist_total(connection, seed.source_item_id)
        support_rows = _support_artists_for_seed(connection, seed.source_item_id, limit)
        query_seconds = monotonic() - query_started
    claims = _group_artist_claims(_parse_artist_rows(raw_rows))
    supported = _group_supported_artists(_parse_support_artist_rows(support_rows))
    names = _exact_attached_names(sources, claims, supported, certified=trusted)
    claims = tuple(
        claim.model_copy(update={"canonical_name": names.get(claim.artist_mbid)})
        for claim in claims
    )
    supported = tuple(
        claim.model_copy(update={"canonical_name": names.get(claim.artist_mbid)})
        for claim in supported
    )
    return LocalArtistEvidenceResponse(
        seed_universe_count=sources.reconciliation.seed_count,
        seed=seed,
        verification_seconds=verification_seconds,
        query_seconds=query_seconds,
        artists=claims[:limit],
        total_direct_artist_count=len(claims),
        remaining_direct_artist_count=max(0, len(claims) - limit),
        album_supported_artists=supported,
        total_album_supported_artist_count=support_total,
        remaining_album_supported_artist_count=max(0, support_total - len(supported)),
    )


def direct_seeds_for_artist(
    sources: LocalMusicBrainzEvidenceSources,
    artist_mbid: str,
    *,
    limit: int = 25,
) -> LocalArtistSeedResponse:
    """Return direct and separately album-supported seeds for one exact artist ID."""
    return _direct_seeds_for_artist(sources, artist_mbid, limit=limit, trusted=False)


def _direct_seeds_for_artist(
    sources: LocalMusicBrainzEvidenceSources,
    artist_mbid: str,
    *,
    limit: int,
    trusted: bool,
) -> LocalArtistSeedResponse:
    """Implement the public query and the startup-certified store query."""
    _require_limit(limit)
    if not trusted:
        _require_source_binding(sources)
    by_id = {row.source_item_id: row for row in sources.reconciliation.dispositions}
    connection, verification_seconds = (
        _trusted_database(sources.database)
        if trusted
        else _verified_database(sources.database, sources.evidence_artifact)
    )
    with closing(connection):
        _require_direct_anchor_schema(connection)
        _require_release_group_support_schema(connection)
        query_started = monotonic()
        raw_rows = connection.execute(
            """SELECT genre_id
                 FROM direct_anchor
                 WHERE artist_id = ?
                 GROUP BY genre_id
                 ORDER BY genre_id""",
            (artist_mbid,),
        ).fetchall()
        support_total = _support_seed_total(connection, artist_mbid)
        support_rows = _support_seeds_for_artist(connection, artist_mbid, limit)
        query_seconds = monotonic() - query_started
    seed_ids = _parse_seed_ids(raw_rows)
    unknown_ids = set(seed_ids) - set(by_id)
    if unknown_ids:
        raise LocalMusicBrainzArtistEvidenceError(
            "direct evidence contains genre IDs outside the reconciliation sidecar"
        )
    seeds = tuple(_seed(by_id[seed_id]) for seed_id in seed_ids)
    supported = _group_supported_seeds(_parse_support_seed_rows(support_rows), by_id)
    return LocalArtistSeedResponse(
        artist_mbid=artist_mbid,
        verification_seconds=verification_seconds,
        query_seconds=query_seconds,
        seeds=seeds[:limit],
        total_direct_seed_count=len(seeds),
        remaining_direct_seed_count=max(0, len(seeds) - limit),
        album_supported_seeds=supported,
        total_album_supported_seed_count=support_total,
        remaining_album_supported_seed_count=max(0, support_total - len(supported)),
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


def _exact_attached_names(
    sources: LocalMusicBrainzEvidenceSources,
    direct: tuple[DirectArtistClaim, ...],
    supported: tuple[AlbumSupportedArtistClaim, ...],
    *,
    certified: bool = False,
) -> dict[str, str]:
    metadata = sources.artist_metadata
    if metadata is None:
        return {}
    if metadata.artifact.evidence_output_sha256 != sources.evidence_artifact.output_sha256:
        raise LocalMusicBrainzArtistEvidenceError(
            "artist metadata does not bind the completed evidence artifact"
        )
    artist_ids = tuple(
        dict.fromkeys(
            (*[item.artist_mbid for item in direct], *[item.artist_mbid for item in supported])
        )
    )
    try:
        return exact_canonical_names(metadata, artist_ids, verified=certified)
    except LocalMusicBrainzArtistMetadataError as error:
        raise LocalMusicBrainzArtistEvidenceError("artist metadata is invalid") from error


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


def _trusted_database(path: Path) -> tuple[sqlite3.Connection, float]:
    """Open a read-only connection after process startup certified the file."""
    connection = sqlite3.connect(f"file:{path.absolute()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection, 0.0


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


def _require_release_group_support_schema(connection: sqlite3.Connection) -> None:
    columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info('release_group_support')")
    }
    if not columns >= _EXPECTED_SUPPORT_COLUMNS:
        raise LocalMusicBrainzArtistEvidenceError(
            "local evidence database has no compatible release_group_support table"
        )


def _support_artist_total(connection: sqlite3.Connection, genre_id: str) -> int:
    row = connection.execute(
        "SELECT count(DISTINCT artist_id) FROM release_group_support WHERE genre_id = ?",
        (genre_id,),
    ).fetchone()
    return _count_value(row, "album support artist total")


def _support_artists_for_seed(
    connection: sqlite3.Connection, genre_id: str, limit: int
) -> list[tuple[object, ...]]:
    rows = connection.execute(
        """WITH selected AS (
               SELECT artist_id FROM release_group_support
                WHERE genre_id = ?
                GROUP BY artist_id
                ORDER BY artist_id
                LIMIT ?
           )
           SELECT support.artist_id, support.facet, support.release_group_id
             FROM release_group_support AS support
             JOIN selected USING (artist_id)
            WHERE support.genre_id = ?
            ORDER BY support.artist_id, support.facet, support.release_group_id""",
        (genre_id, limit, genre_id),
    ).fetchall()
    return [tuple(row) for row in rows]


def _support_seed_total(connection: sqlite3.Connection, artist_mbid: str) -> int:
    row = connection.execute(
        "SELECT count(DISTINCT genre_id) FROM release_group_support WHERE artist_id = ?",
        (artist_mbid,),
    ).fetchone()
    return _count_value(row, "album support seed total")


def _support_seeds_for_artist(
    connection: sqlite3.Connection, artist_mbid: str, limit: int
) -> list[tuple[object, ...]]:
    rows = connection.execute(
        """WITH selected AS (
               SELECT genre_id FROM release_group_support
                WHERE artist_id = ?
                GROUP BY genre_id
                ORDER BY genre_id
                LIMIT ?
           )
           SELECT support.genre_id, support.facet, support.release_group_id
             FROM release_group_support AS support
             JOIN selected USING (genre_id)
            WHERE support.artist_id = ?
            ORDER BY support.genre_id, support.facet, support.release_group_id""",
        (artist_mbid, limit, artist_mbid),
    ).fetchall()
    return [tuple(row) for row in rows]


def _count_value(row: tuple[object, ...] | None, description: str) -> int:
    if row is None or len(row) != 1 or not isinstance(row[0], int) or row[0] < 0:
        raise LocalMusicBrainzArtistEvidenceError(f"{description} is invalid")
    return row[0]


def _parse_support_artist_rows(rows: list[tuple[object, ...]]) -> list[tuple[str, str, str]]:
    parsed: list[tuple[str, str, str]] = []
    for row in rows:
        if len(row) != _SUPPORT_ROW_COLUMN_COUNT:
            raise LocalMusicBrainzArtistEvidenceError("album support has an invalid artist row")
        artist_mbid, facet, release_group_id = row
        if not all(isinstance(value, str) and value for value in row):
            raise LocalMusicBrainzArtistEvidenceError("album support has an invalid artist row")
        if (
            not isinstance(artist_mbid, str)
            or not isinstance(facet, str)
            or not isinstance(release_group_id, str)
        ):
            raise LocalMusicBrainzArtistEvidenceError("album support has an invalid artist row")
        parsed.append((artist_mbid, facet, release_group_id))
    return parsed


def _parse_support_seed_rows(rows: list[tuple[object, ...]]) -> list[tuple[str, str, str]]:
    parsed: list[tuple[str, str, str]] = []
    for row in rows:
        if len(row) != _SUPPORT_ROW_COLUMN_COUNT:
            raise LocalMusicBrainzArtistEvidenceError("album support has an invalid seed row")
        seed_id, facet, release_group_id = row
        if not all(isinstance(value, str) and value for value in row):
            raise LocalMusicBrainzArtistEvidenceError("album support has an invalid seed row")
        if (
            not isinstance(seed_id, str)
            or not isinstance(facet, str)
            or not isinstance(release_group_id, str)
        ):
            raise LocalMusicBrainzArtistEvidenceError("album support has an invalid seed row")
        parsed.append((seed_id, facet, release_group_id))
    return parsed


def _support_facets(
    rows: list[tuple[str, str, str]], identifier: str
) -> tuple[tuple[AlbumSupportFacet, ...], int]:
    by_facet: dict[DirectFacet, set[str]] = defaultdict(set)
    all_release_groups: set[str] = set()
    for row_identifier, raw_facet, release_group_id in rows:
        if row_identifier != identifier:
            raise LocalMusicBrainzArtistEvidenceError("album support grouping is inconsistent")
        if raw_facet not in {"musicbrainz_genre", "musicbrainz_tag"}:
            raise LocalMusicBrainzArtistEvidenceError("album support has an unknown facet")
        facet: DirectFacet = raw_facet
        by_facet[facet].add(release_group_id)
        all_release_groups.add(release_group_id)
    return (
        tuple(
            AlbumSupportFacet(
                facet=facet,
                distinct_release_group_count=len(release_group_ids),
            )
            for facet, release_group_ids in sorted(by_facet.items())
        ),
        len(all_release_groups),
    )


def _group_supported_artists(
    rows: list[tuple[str, str, str]],
) -> tuple[AlbumSupportedArtistClaim, ...]:
    grouped: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row[0]].append(row)
    return tuple(
        AlbumSupportedArtistClaim(
            artist_mbid=artist_mbid,
            facets=facets,
            distinct_release_group_count=release_group_count,
        )
        for artist_mbid, artist_rows in sorted(grouped.items())
        for facets, release_group_count in (_support_facets(artist_rows, artist_mbid),)
    )


def _group_supported_seeds(
    rows: list[tuple[str, str, str]],
    by_id: dict[str, SeedReconciliationDisposition],
) -> tuple[AlbumSupportedSeedClaim, ...]:
    grouped: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row[0]].append(row)
    unknown_ids = set(grouped) - set(by_id)
    if unknown_ids:
        raise LocalMusicBrainzArtistEvidenceError(
            "album support contains genre IDs outside the reconciliation sidecar"
        )
    return tuple(
        AlbumSupportedSeedClaim(
            seed=_seed(by_id[seed_id]),
            facets=facets,
            distinct_release_group_count=release_group_count,
        )
        for seed_id, seed_rows in sorted(grouped.items())
        for facets, release_group_count in (_support_facets(seed_rows, seed_id),)
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
