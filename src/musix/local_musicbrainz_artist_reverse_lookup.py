"""Immutable reverse lookup projection for local MusicBrainz artist evidence."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from pydantic import ConfigDict, Field

from musix.models import FrozenModel
from musix.musicbrainz_release_group_evidence import (
    ReleaseGroupEvidenceArtifact,
    verify_release_group_evidence,
)

if TYPE_CHECKING:
    from pathlib import Path

_REVISION: Final = "musicbrainz-artist-reverse-lookup-v1"
_SHA256: Final = r"^[0-9a-f]{64}$"
_EXPECTED_DIRECT_COLUMNS: Final = frozenset({"artist_id", "genre_id"})
_EXPECTED_SUPPORT_COLUMNS: Final = frozenset(
    {
        "artist_id",
        "genre_id",
        "facet",
        "distinct_release_group_count",
        "combined_release_group_count",
    }
)


class LocalMusicBrainzArtistReverseLookupError(ValueError):
    """Raised when a reverse projection is not bound to its source evidence."""


class _FrozenModel(FrozenModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class ArtistReverseLookupArtifact(_FrozenModel):
    """Receipt for a source-bound, non-exportable reverse SQLite projection."""

    revision: Literal["musicbrainz-artist-reverse-lookup-v1"] = _REVISION
    scope: Literal["local_research_only"] = "local_research_only"
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    source_evidence_output_sha256: str = Field(pattern=_SHA256)
    source_evidence_database_sha256: str = Field(pattern=_SHA256)
    source_evidence_database_bytes: int = Field(gt=0)
    reverse_database_sha256: str = Field(pattern=_SHA256)
    reverse_database_bytes: int = Field(gt=0)
    direct_membership_count: int = Field(ge=0)
    support_facet_count: int = Field(ge=0)
    output_sha256: str = Field(pattern=_SHA256)


@dataclass(frozen=True, slots=True)
class LocalArtistReverseLookupSources:
    """The completed sidecar and receipt used for exact artist reverse lookups."""

    database: Path
    artifact: ArtistReverseLookupArtifact


@dataclass(frozen=True, slots=True)
class ArtistReverseLookupBuildInputs:
    """One immutable source database and one new sidecar target."""

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


def artist_reverse_lookup_artifact_sha256(artifact: ArtistReverseLookupArtifact) -> str:
    """Return the replay hash excluding the self-referential receipt value."""
    return hashlib.sha256(
        _canonical(artifact.model_dump(mode="json", exclude={"output_sha256"}))
    ).hexdigest()


def verify_artist_reverse_lookup_artifact(artifact: ArtistReverseLookupArtifact) -> None:
    """Fail closed when the small receipt does not replay."""
    if artist_reverse_lookup_artifact_sha256(artifact) != artifact.output_sha256:
        raise LocalMusicBrainzArtistReverseLookupError(
            "reverse lookup artifact hash does not replay"
        )


def load_artist_reverse_lookup_artifact(path: Path) -> ArtistReverseLookupArtifact:
    """Load and verify a reverse-lookup receipt."""
    try:
        artifact = ArtistReverseLookupArtifact.model_validate_json(path.read_bytes())
        verify_artist_reverse_lookup_artifact(artifact)
    except (OSError, ValueError) as error:
        raise LocalMusicBrainzArtistReverseLookupError(
            "reverse lookup artifact is invalid"
        ) from error
    return artifact


def build_artist_reverse_lookup(
    inputs: ArtistReverseLookupBuildInputs,
) -> ArtistReverseLookupArtifact:
    """Materialize a separate reverse projection without modifying source evidence."""
    _verify_source_database(inputs.evidence_database, inputs.evidence_artifact)
    if inputs.output_database.exists():
        raise LocalMusicBrainzArtistReverseLookupError(
            "reverse lookup output database already exists"
        )
    with closing(
        sqlite3.connect(f"file:{inputs.evidence_database.absolute()}?mode=ro", uri=True)
    ) as source:
        source.execute("PRAGMA query_only = ON")
        _require_source_schema(source)
        with closing(sqlite3.connect(inputs.output_database)) as output, output:
            _init_database(output)
            _copy_projection(source, output)
            output.execute("PRAGMA optimize")
            if output.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise LocalMusicBrainzArtistReverseLookupError(
                    "reverse lookup database failed integrity check"
                )
            direct_count = _count(output, "direct_seed")
            support_count = _count(output, "support_aggregate")
    reverse_sha256, reverse_bytes = _file_sha256(inputs.output_database)
    preliminary = ArtistReverseLookupArtifact(
        source_evidence_output_sha256=inputs.evidence_artifact.output_sha256,
        source_evidence_database_sha256=inputs.evidence_artifact.evidence_database_sha256,
        source_evidence_database_bytes=inputs.evidence_artifact.evidence_database_bytes,
        reverse_database_sha256=reverse_sha256,
        reverse_database_bytes=reverse_bytes,
        direct_membership_count=direct_count,
        support_facet_count=support_count,
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(
        update={"output_sha256": artist_reverse_lookup_artifact_sha256(preliminary)}
    )


def verify_artist_reverse_lookup_sources(
    sources: LocalArtistReverseLookupSources, evidence_artifact: ReleaseGroupEvidenceArtifact
) -> None:
    """Verify the sidecar, its receipt, and its exact completed source binding."""
    verify_release_group_evidence(evidence_artifact)
    verify_artist_reverse_lookup_artifact(sources.artifact)
    if (
        sources.artifact.source_evidence_output_sha256 != evidence_artifact.output_sha256
        or sources.artifact.source_evidence_database_sha256
        != evidence_artifact.evidence_database_sha256
        or sources.artifact.source_evidence_database_bytes
        != evidence_artifact.evidence_database_bytes
    ):
        raise LocalMusicBrainzArtistReverseLookupError(
            "reverse lookup does not bind the evidence artifact"
        )
    digest, size = _file_sha256(sources.database)
    if (digest, size) != (
        sources.artifact.reverse_database_sha256,
        sources.artifact.reverse_database_bytes,
    ):
        raise LocalMusicBrainzArtistReverseLookupError(
            "reverse lookup database does not match artifact"
        )
    with closing(
        sqlite3.connect(f"file:{sources.database.absolute()}?mode=ro", uri=True)
    ) as connection:
        connection.execute("PRAGMA query_only = ON")
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise LocalMusicBrainzArtistReverseLookupError(
                "reverse lookup database failed integrity check"
            )
        _require_reverse_schema(connection)


def open_trusted_reverse_lookup(path: Path) -> sqlite3.Connection:
    """Open a read-only sidecar after startup has verified it."""
    connection = sqlite3.connect(f"file:{path.absolute()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


def _verify_source_database(path: Path, artifact: ReleaseGroupEvidenceArtifact) -> None:
    verify_release_group_evidence(artifact)
    if not path.is_file() or path.suffix == ".partial":
        raise LocalMusicBrainzArtistReverseLookupError(
            "evidence database is unavailable or partial"
        )
    if _file_sha256(path) != (artifact.evidence_database_sha256, artifact.evidence_database_bytes):
        raise LocalMusicBrainzArtistReverseLookupError("evidence database does not match artifact")


def _require_source_schema(connection: sqlite3.Connection) -> None:
    direct = {str(row[1]) for row in connection.execute("PRAGMA table_info('direct_anchor')")}
    support = {
        str(row[1]) for row in connection.execute("PRAGMA table_info('release_group_support')")
    }
    if not direct >= {"artist_id", "genre_id"} or not support >= {
        "artist_id",
        "genre_id",
        "facet",
        "release_group_id",
    }:
        raise LocalMusicBrainzArtistReverseLookupError("evidence database schema is incompatible")


def _init_database(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE direct_seed (
            artist_id TEXT NOT NULL, genre_id TEXT NOT NULL,
            PRIMARY KEY (artist_id, genre_id)
        ) WITHOUT ROWID;
        CREATE TABLE support_aggregate (
            artist_id TEXT NOT NULL, genre_id TEXT NOT NULL, facet TEXT NOT NULL,
            distinct_release_group_count INTEGER NOT NULL CHECK (distinct_release_group_count > 0),
            combined_release_group_count INTEGER NOT NULL CHECK (combined_release_group_count > 0),
            PRIMARY KEY (artist_id, genre_id, facet)
        ) WITHOUT ROWID;
        """
    )


def _copy_projection(source: sqlite3.Connection, output: sqlite3.Connection) -> None:
    output.executemany(
        "INSERT INTO direct_seed VALUES (?, ?)",
        source.execute(
            "SELECT DISTINCT artist_id, genre_id FROM direct_anchor ORDER BY artist_id, genre_id"
        ),
    )
    output.executemany(
        "INSERT INTO support_aggregate VALUES (?, ?, ?, ?, ?)",
        source.execute(
            """WITH facet_counts AS (
                   SELECT artist_id, genre_id, facet,
                          count(DISTINCT release_group_id) AS facet_count
                     FROM release_group_support GROUP BY artist_id, genre_id, facet
               ), combined_counts AS (
                   SELECT artist_id, genre_id, count(DISTINCT release_group_id) AS combined_count
                     FROM release_group_support GROUP BY artist_id, genre_id
               )
               SELECT facet_counts.artist_id, facet_counts.genre_id, facet_counts.facet,
                      facet_counts.facet_count, combined_counts.combined_count
                 FROM facet_counts JOIN combined_counts USING (artist_id, genre_id)
                ORDER BY facet_counts.artist_id, facet_counts.genre_id, facet_counts.facet"""
        ),
    )


def _require_reverse_schema(connection: sqlite3.Connection) -> None:
    direct = {str(row[1]) for row in connection.execute("PRAGMA table_info('direct_seed')")}
    support = {str(row[1]) for row in connection.execute("PRAGMA table_info('support_aggregate')")}
    if not direct >= _EXPECTED_DIRECT_COLUMNS or not support >= _EXPECTED_SUPPORT_COLUMNS:
        raise LocalMusicBrainzArtistReverseLookupError(
            "reverse lookup database schema is incompatible"
        )


def _count(
    connection: sqlite3.Connection, table: Literal["direct_seed", "support_aggregate"]
) -> int:
    row = connection.execute(f"SELECT count(*) FROM {table}").fetchone()  # noqa: S608
    if row is None or not isinstance(row[0], int):
        raise LocalMusicBrainzArtistReverseLookupError("reverse lookup count is invalid")
    return row[0]
