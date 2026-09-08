"""Build exact MusicBrainz artist-name metadata from local release credits.

The release-group archive is a local research source.  Its nested artist
credits provide a canonical artist name and an exact MusicBrainz ID, but not a
sort name, disambiguation, artist type, or country.  This module keeps those
missing fields null and never uses the outer credited-as text as a fallback.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from musix.models.catalog import ReleaseGroupProjection
from musix.models.pipeline import ParsedSourceRecord, SourceLimits
from musix.musicbrainz_release_group_evidence import (
    ReleaseGroupEvidenceArtifact,
    verify_release_group_evidence,
)
from musix.sources.musicbrainz import MusicBrainzReleaseGroupDumpAdapter

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_REVISION: Final = "musicbrainz-release-credit-artist-metadata-v1"
_SHA256: Final = r"^[0-9a-f]{64}$"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class LocalMusicBrainzArtistMetadataError(ValueError):
    """Raised when an input or derived metadata artifact is not custody-bound."""


class ArtistMetadataSettings(_FrozenModel):
    """Bounds for a one-pass release-credit metadata projection."""

    revision: Literal["musicbrainz-release-credit-artist-metadata-settings-v1"] = (
        "musicbrainz-release-credit-artist-metadata-settings-v1"
    )
    max_archive_bytes: int = Field(default=2 * 1024**3, gt=0)
    max_member_bytes: int = Field(default=20 * 1024**3, gt=0)
    max_record_bytes: int = Field(default=2 * 1024**2, gt=0)
    max_records: int = Field(default=5_000_000, gt=0)
    max_credit_members: int = Field(default=128, gt=0, le=512)
    max_name_variants_per_artist: int = Field(default=32, gt=0, le=128)
    insert_batch_rows: int = Field(default=10_000, gt=0, le=100_000)
    progress_every_records: int = Field(default=100_000, gt=0)


class ArtistMetadataCounters(_FrozenModel):
    """Aggregate accounting for one bounded metadata projection."""

    records_seen: int = Field(ge=0)
    records_parsed: int = Field(ge=0)
    rejected_records: int = Field(ge=0)
    target_credit_observations: int = Field(ge=0)


@dataclass(frozen=True, slots=True)
class ArtistMetadataProgress:
    """Aggregate progress emitted during a local archive scan."""

    records_seen: int
    elapsed_seconds: float


class ArtistMetadataArtifact(_FrozenModel):
    """Small receipt for a separate local-only exact-ID metadata database."""

    revision: Literal["musicbrainz-release-credit-artist-metadata-v1"] = _REVISION
    scope: Literal["local_research_only"] = "local_research_only"
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    source_archive_sha256: str = Field(pattern=_SHA256)
    source_archive_bytes: int = Field(gt=0)
    source_snapshot: str = Field(min_length=1)
    source_member_name: Literal["mbdump/release-group"] = "mbdump/release-group"
    evidence_output_sha256: str = Field(pattern=_SHA256)
    evidence_database_sha256: str = Field(pattern=_SHA256)
    evidence_database_bytes: int = Field(gt=0)
    metadata_database_sha256: str = Field(pattern=_SHA256)
    metadata_database_bytes: int = Field(gt=0)
    target_artist_count: int = Field(ge=0)
    observed_artist_count: int = Field(ge=0)
    conflicting_artist_count: int = Field(ge=0)
    counters: ArtistMetadataCounters
    settings: ArtistMetadataSettings
    output_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _coverage_is_bounded(self) -> ArtistMetadataArtifact:
        if self.observed_artist_count > self.target_artist_count:
            raise ValueError("observed artists exceed exact target artists")
        if self.conflicting_artist_count > self.observed_artist_count:
            raise ValueError("conflicting artists exceed observed artists")
        return self


@dataclass(frozen=True, slots=True)
class LocalArtistMetadataSources:
    """Verified metadata inputs usable by a local evidence query only."""

    database: Path
    artifact: ArtistMetadataArtifact


@dataclass(frozen=True, slots=True)
class CertifiedLocalArtistMetadataSources:
    """Startup-certified metadata inputs for bounded process-local lookups."""

    sources: LocalArtistMetadataSources


@dataclass(frozen=True, slots=True)
class ArtistMetadataBuildInputs:
    """Immutable inputs for one exact-ID release-credit metadata build."""

    archive: Path
    evidence_database: Path
    evidence_artifact: ReleaseGroupEvidenceArtifact
    output_database: Path


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode()


def _file_sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def artist_metadata_artifact_sha256(artifact: ArtistMetadataArtifact) -> str:
    """Return the replay hash excluding its self-referential field."""
    return hashlib.sha256(
        _canonical(artifact.model_dump(mode="json", exclude={"output_sha256"}))
    ).hexdigest()


def verify_artist_metadata_artifact(artifact: ArtistMetadataArtifact) -> None:
    """Reject an altered local metadata receipt."""
    if artist_metadata_artifact_sha256(artifact) != artifact.output_sha256:
        raise LocalMusicBrainzArtistMetadataError("artist metadata artifact hash does not replay")


def load_artist_metadata_artifact(path: Path) -> ArtistMetadataArtifact:
    """Load and verify the small local metadata receipt."""
    try:
        artifact = ArtistMetadataArtifact.model_validate_json(path.read_bytes())
        verify_artist_metadata_artifact(artifact)
    except (OSError, ValueError) as error:
        raise LocalMusicBrainzArtistMetadataError("artist metadata artifact is invalid") from error
    return artifact


def build_artist_metadata(
    inputs: ArtistMetadataBuildInputs,
    settings: ArtistMetadataSettings | None = None,
    *,
    progress_callback: Callable[[ArtistMetadataProgress], None] | None = None,
) -> ArtistMetadataArtifact:
    """Stream one verified release-group archive into exact-ID name variants."""
    settings = settings or ArtistMetadataSettings()
    verify_release_group_evidence(inputs.evidence_artifact)
    _verify_evidence_database(inputs.evidence_database, inputs.evidence_artifact)
    archive_sha256, archive_bytes = _file_sha256(inputs.archive)
    if (archive_sha256, archive_bytes) != (
        inputs.evidence_artifact.source_archive_sha256,
        inputs.evidence_artifact.source_archive_bytes,
    ):
        raise LocalMusicBrainzArtistMetadataError("release-group archive does not match evidence")
    if archive_bytes > settings.max_archive_bytes:
        raise LocalMusicBrainzArtistMetadataError("release-group archive exceeds bound")
    if inputs.output_database.exists():
        raise LocalMusicBrainzArtistMetadataError("metadata output database already exists")

    target_ids = _target_artist_ids(inputs.evidence_database)
    connection = sqlite3.connect(inputs.output_database)
    try:
        _init_database(connection, settings)
        _insert_targets(connection, target_ids)
        counters = _stream_credit_variants(
            connection, inputs.archive, target_ids, settings, progress_callback
        )
        _summarize(connection)
        connection.execute("PRAGMA optimize")
        connection.commit()
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise LocalMusicBrainzArtistMetadataError("metadata database failed integrity check")
        target_count = _count(connection, "target_artist")
        observed_count = _count(connection, "artist_summary")
        conflicting_count = _count(
            connection, "artist_summary", where="canonical_name_variant_count > 1"
        )
    finally:
        connection.close()
    metadata_sha256, metadata_bytes = _file_sha256(inputs.output_database)
    preliminary = ArtistMetadataArtifact(
        source_archive_sha256=archive_sha256,
        source_archive_bytes=archive_bytes,
        source_snapshot=inputs.evidence_artifact.source_snapshot,
        evidence_output_sha256=inputs.evidence_artifact.output_sha256,
        evidence_database_sha256=inputs.evidence_artifact.evidence_database_sha256,
        evidence_database_bytes=inputs.evidence_artifact.evidence_database_bytes,
        metadata_database_sha256=metadata_sha256,
        metadata_database_bytes=metadata_bytes,
        target_artist_count=target_count,
        observed_artist_count=observed_count,
        conflicting_artist_count=conflicting_count,
        counters=counters,
        settings=settings,
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(
        update={"output_sha256": artist_metadata_artifact_sha256(preliminary)}
    )


def exact_canonical_names(
    sources: LocalArtistMetadataSources,
    artist_mbids: tuple[str, ...],
) -> dict[str, str]:
    """Return only conflict-free canonical names for exact source MBIDs."""
    certify_local_artist_metadata_sources(sources)
    return _exact_canonical_names(sources, artist_mbids, integrity_check=True)


def exact_certified_canonical_names(
    certified: CertifiedLocalArtistMetadataSources, artist_mbids: tuple[str, ...]
) -> dict[str, str]:
    """Read metadata after this process completed startup certification."""
    return _exact_canonical_names(certified.sources, artist_mbids, integrity_check=False)


def _exact_canonical_names(
    sources: LocalArtistMetadataSources,
    artist_mbids: tuple[str, ...],
    *,
    integrity_check: bool,
) -> dict[str, str]:
    if not artist_mbids:
        return {}
    with closing(sqlite3.connect(f"file:{sources.database.absolute()}?mode=ro", uri=True)) as conn:
        conn.execute("PRAGMA query_only = ON")
        if integrity_check and conn.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise LocalMusicBrainzArtistMetadataError("metadata database failed integrity check")
        placeholders = ",".join("?" for _ in artist_mbids)
        rows = conn.execute(
            f"SELECT artist_mbid, canonical_name FROM artist_summary "  # noqa: S608
            f"WHERE artist_mbid IN ({placeholders}) AND canonical_name IS NOT NULL",
            artist_mbids,
        ).fetchall()
    return {str(row[0]): str(row[1]) for row in rows}


def verify_local_artist_metadata_sources(sources: LocalArtistMetadataSources) -> None:
    """Certify immutable metadata once before a local process serves lookups."""
    verify_artist_metadata_artifact(sources.artifact)
    database_sha256, database_bytes = _file_sha256(sources.database)
    if (database_sha256, database_bytes) != (
        sources.artifact.metadata_database_sha256,
        sources.artifact.metadata_database_bytes,
    ):
        raise LocalMusicBrainzArtistMetadataError("metadata database does not match artifact")
    with closing(sqlite3.connect(f"file:{sources.database.absolute()}?mode=ro", uri=True)) as conn:
        conn.execute("PRAGMA query_only = ON")
        if conn.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise LocalMusicBrainzArtistMetadataError("metadata database failed integrity check")


def certify_local_artist_metadata_sources(
    sources: LocalArtistMetadataSources,
) -> CertifiedLocalArtistMetadataSources:
    """Return a certificate only after whole-file and SQLite startup checks."""
    verify_local_artist_metadata_sources(sources)
    return CertifiedLocalArtistMetadataSources(sources)


def _verify_evidence_database(path: Path, artifact: ReleaseGroupEvidenceArtifact) -> None:
    if not path.is_file() or path.suffix == ".partial":
        raise LocalMusicBrainzArtistMetadataError("evidence database is unavailable or partial")
    digest, size = _file_sha256(path)
    if (digest, size) != (artifact.evidence_database_sha256, artifact.evidence_database_bytes):
        raise LocalMusicBrainzArtistMetadataError("evidence database does not match artifact")
    with closing(sqlite3.connect(f"file:{path.absolute()}?mode=ro", uri=True)) as connection:
        connection.execute("PRAGMA query_only = ON")
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise LocalMusicBrainzArtistMetadataError("evidence database failed integrity check")
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        if not {"direct_anchor", "release_group_support"} <= tables:
            raise LocalMusicBrainzArtistMetadataError("evidence database schema is incompatible")


def _target_artist_ids(evidence_database: Path) -> frozenset[str]:
    with closing(sqlite3.connect(f"file:{evidence_database.absolute()}?mode=ro", uri=True)) as conn:
        conn.execute("PRAGMA query_only = ON")
        rows = conn.execute(
            "SELECT artist_id FROM direct_anchor UNION SELECT artist_id FROM release_group_support"
        )
        return frozenset(str(row[0]) for row in rows)


def _init_database(connection: sqlite3.Connection, settings: ArtistMetadataSettings) -> None:
    connection.executescript(
        """
        CREATE TABLE target_artist (
            artist_mbid TEXT PRIMARY KEY NOT NULL
        ) WITHOUT ROWID;
        CREATE TABLE canonical_name_variant (
            artist_mbid TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            occurrence_count INTEGER NOT NULL,
            representative_release_group_id TEXT NOT NULL,
            representative_record_ordinal INTEGER NOT NULL,
            representative_record_sha256 TEXT NOT NULL,
            PRIMARY KEY (artist_mbid, canonical_name)
        ) WITHOUT ROWID;
        CREATE TABLE credited_as_variant (
            artist_mbid TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            credited_as TEXT NOT NULL,
            occurrence_count INTEGER NOT NULL,
            representative_release_group_id TEXT NOT NULL,
            representative_record_ordinal INTEGER NOT NULL,
            representative_record_sha256 TEXT NOT NULL,
            PRIMARY KEY (artist_mbid, canonical_name, credited_as)
        ) WITHOUT ROWID;
        CREATE TABLE artist_summary (
            artist_mbid TEXT PRIMARY KEY NOT NULL,
            canonical_name TEXT,
            canonical_name_variant_count INTEGER NOT NULL,
            sort_name TEXT,
            disambiguation TEXT,
            artist_type TEXT,
            country TEXT
        ) WITHOUT ROWID;
        """
    )
    connection.execute(
        f"""CREATE TRIGGER canonical_name_variant_cap
            BEFORE INSERT ON canonical_name_variant
            WHEN (SELECT count(*) FROM canonical_name_variant
                  WHERE artist_mbid = NEW.artist_mbid) >= {settings.max_name_variants_per_artist}
             AND NOT EXISTS (
                 SELECT 1 FROM canonical_name_variant
                  WHERE artist_mbid = NEW.artist_mbid
                    AND canonical_name = NEW.canonical_name
             )
            BEGIN SELECT RAISE(ABORT, 'canonical name variant cap exceeded'); END"""  # noqa: S608
    )


def _insert_targets(connection: sqlite3.Connection, target_ids: frozenset[str]) -> None:
    connection.executemany(
        "INSERT INTO target_artist (artist_mbid) VALUES (?)", ((item,) for item in target_ids)
    )
    connection.commit()


def _stream_credit_variants(
    connection: sqlite3.Connection,
    archive: Path,
    target_ids: frozenset[str],
    settings: ArtistMetadataSettings,
    progress_callback: Callable[[ArtistMetadataProgress], None] | None,
) -> ArtistMetadataCounters:
    seen = parsed = rejected = observations = 0
    canonical_batch: list[tuple[str, str, str, int, str]] = []
    credited_batch: list[tuple[str, str, str, str, int, str]] = []
    limits = SourceLimits(
        max_archive_bytes=settings.max_archive_bytes,
        max_member_bytes=settings.max_member_bytes,
        max_record_bytes=settings.max_record_bytes,
        max_records=settings.max_records,
    )
    adapter = MusicBrainzReleaseGroupDumpAdapter()
    started = monotonic()
    for record in adapter.iter_records(archive, limits, start_after=-1):
        seen += 1
        if progress_callback is not None and seen % settings.progress_every_records == 0:
            progress_callback(ArtistMetadataProgress(seen, monotonic() - started))
        if not isinstance(record, ParsedSourceRecord):
            rejected += 1
            continue
        parsed += 1
        projection = record.projection
        if not isinstance(projection, ReleaseGroupProjection):
            raise LocalMusicBrainzArtistMetadataError(
                "release-group adapter emitted another projection"
            )
        release_group_id = str(projection.external_id)
        for member in projection.artist_credit[: settings.max_credit_members]:
            artist_mbid = member.artist_identity.value
            if artist_mbid not in target_ids:
                continue
            observations += 1
            canonical_batch.append(
                (
                    artist_mbid,
                    member.artist_name,
                    release_group_id,
                    record.ordinal,
                    record.exact_sha256,
                )
            )
            credited_batch.append(
                (
                    artist_mbid,
                    member.artist_name,
                    member.credited_name,
                    release_group_id,
                    record.ordinal,
                    record.exact_sha256,
                )
            )
        if len(canonical_batch) >= settings.insert_batch_rows:
            _flush_variants(connection, canonical_batch, credited_batch)
    _flush_variants(connection, canonical_batch, credited_batch)
    return ArtistMetadataCounters(
        records_seen=seen,
        records_parsed=parsed,
        rejected_records=rejected,
        target_credit_observations=observations,
    )


def _flush_variants(
    connection: sqlite3.Connection,
    canonical_batch: list[tuple[str, str, str, int, str]],
    credited_batch: list[tuple[str, str, str, str, int, str]],
) -> None:
    if not canonical_batch:
        return
    try:
        connection.executemany(
            """INSERT INTO canonical_name_variant (
               artist_mbid, canonical_name, occurrence_count,
               representative_release_group_id, representative_record_ordinal,
               representative_record_sha256
           ) VALUES (?, ?, 1, ?, ?, ?)
           ON CONFLICT (artist_mbid, canonical_name)
           DO UPDATE SET occurrence_count = occurrence_count + 1""",
            canonical_batch,
        )
    except sqlite3.IntegrityError as error:
        raise LocalMusicBrainzArtistMetadataError("canonical name variant cap exceeded") from error
    connection.executemany(
        """INSERT INTO credited_as_variant (
               artist_mbid, canonical_name, credited_as, occurrence_count,
               representative_release_group_id, representative_record_ordinal,
               representative_record_sha256
           ) VALUES (?, ?, ?, 1, ?, ?, ?)
           ON CONFLICT (artist_mbid, canonical_name, credited_as)
           DO UPDATE SET occurrence_count = occurrence_count + 1""",
        credited_batch,
    )
    connection.commit()
    canonical_batch.clear()
    credited_batch.clear()


def _summarize(connection: sqlite3.Connection) -> None:
    connection.execute(
        """INSERT INTO artist_summary (
               artist_mbid, canonical_name, canonical_name_variant_count,
               sort_name, disambiguation, artist_type, country
           )
           SELECT artist_mbid,
                  CASE WHEN count(*) = 1 THEN min(canonical_name) END,
                  count(*), NULL, NULL, NULL, NULL
             FROM canonical_name_variant
            GROUP BY artist_mbid"""
    )


def _count(connection: sqlite3.Connection, table: str, *, where: str | None = None) -> int:
    query = f"SELECT count(*) FROM {table}"  # noqa: S608 - private constant callers only.
    if where is not None:
        query = f"{query} WHERE {where}"
    row = connection.execute(query).fetchone()
    if row is None or not isinstance(row[0], int):
        raise LocalMusicBrainzArtistMetadataError("metadata count query failed")
    return row[0]
