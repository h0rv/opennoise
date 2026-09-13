"""Seal exact MusicBrainz artist names beside an immutable evidence graph."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Literal
from uuid import uuid4

from pydantic import Field, model_validator

from opennoise.common import (
    canonical_json,
    connect_readonly,
    connect_readwrite,
    sha256_file,
    sha256_hex,
    write_atomic_bytes,
)
from opennoise.evidence.graph_projection import (
    EvidenceGraphProjectionArtifact,
    verify_evidence_graph_projection,
)
from opennoise.models import FrozenModel
from opennoise.serving.local.musicbrainz_artist_metadata import (
    ArtistMetadataArtifact,
    verify_artist_metadata_artifact,
)

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path


_INPUT_ROLES: Final = frozenset(
    {
        "evidence_graph_database",
        "evidence_graph_receipt",
        "musicbrainz_artist_metadata_database",
        "musicbrainz_artist_metadata_receipt",
    }
)
_OVERLAY_CERTIFICATE: Final = object()
_MAX_GENRE_ARTIST_EVIDENCE: Final = 1_000


class ArtistIdentityOverlayError(ValueError):
    """Report an invalid artist-identity overlay or source binding."""


class OverlayInput(FrozenModel):
    """One byte-bound, logically identified input to the sidecar."""

    role: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    byte_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(gt=0)
    logical_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ArtistIdentityOverlayArtifact(FrozenModel):
    """Receipt for a complete, exact-ID artist-name sidecar."""

    revision: Literal["source-neutral-evidence-graph-artist-identities-v1"] = (
        "source-neutral-evidence-graph-artist-identities-v1"
    )
    inputs: tuple[OverlayInput, ...] = Field(min_length=4, max_length=4)
    database_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    database_bytes: int = Field(gt=0)
    artist_identity_count: int = Field(ge=0)
    canonical_name_count: int = Field(ge=0)
    metadata_missing_count: int = Field(ge=0)
    ambiguous_name_count: int = Field(ge=0)
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def complete(self) -> ArtistIdentityOverlayArtifact:
        """Require one disposition for every graph artist and every input role."""
        if {item.role for item in self.inputs} != _INPUT_ROLES:
            raise ValueError("overlay receipt must bind each graph and metadata input")
        if (
            self.canonical_name_count + self.metadata_missing_count + self.ambiguous_name_count
            != self.artist_identity_count
        ):
            raise ValueError("overlay receipt dispositions must account for every artist")
        return self


@dataclass(frozen=True, slots=True)
class ArtistIdentityOverlayInputs:
    """Immutable sources and a fresh output database for one sidecar build."""

    graph_database: Path
    graph_receipt: Path
    metadata_database: Path
    metadata_receipt: Path
    output_database: Path


@dataclass(frozen=True, slots=True)
class ArtistIdentityOverlaySources:
    """The sealed sidecar and its replay-verified receipt for read-only queries."""

    database: Path
    artifact: ArtistIdentityOverlayArtifact


@dataclass(frozen=True, slots=True)
class CertifiedArtistIdentityOverlaySources:
    """A startup-certified source wrapper for inexpensive exact-ID lookups."""

    sources: ArtistIdentityOverlaySources
    _certificate: object = field(repr=False, compare=False)

    def is_valid(self) -> bool:
        """Return whether the wrapper was issued by this module's certification factory."""
        return self._certificate is _OVERLAY_CERTIFICATE


@dataclass(frozen=True, slots=True)
class ArtistIdentity:
    """One exact graph artist identity, with a name or an explicit abstention."""

    artist_mbid: str
    canonical_name: str | None
    name_status: Literal["canonical_name_observed", "metadata_missing", "ambiguous_name"]
    source_artifact_sha256: str
    representative_release_group_id: str | None
    representative_record_ordinal: int | None
    representative_record_sha256: str | None


@dataclass(frozen=True, slots=True)
class CertifiedGenreArtistEvidenceSources:
    """Startup-certified graph and overlay sources for bounded genre artist queries."""

    graph_database: Path
    overlay: CertifiedArtistIdentityOverlaySources
    _certificate: object = field(repr=False, compare=False)

    def is_valid(self) -> bool:
        """Return whether the wrapper was issued by this module's certification factory."""
        return self._certificate is _OVERLAY_CERTIFICATE


@dataclass(frozen=True, slots=True)
class GenreArtistEvidence:
    """One unique artist's exact membership evidence joined to its name disposition."""

    artist: ArtistIdentity
    membership_claim_count: int
    artist_direct_claim_count: int
    release_group_support_claim_count: int
    reviewed_alias_claim_count: int
    representative_evidence_kind: str
    representative_source: str
    representative_facet: str
    representative_provenance_ref: str
    representative_release_group_id: str
    evidence_weight: None = None


@dataclass(frozen=True, slots=True)
class GenreArtistEvidencePage:
    """A bounded unique-artist page with complete matching-population accounting."""

    total_artist_count: int
    total_unnamed_artist_count: int
    returned_artist_count: int
    returned_unnamed_artist_count: int
    artists: tuple[GenreArtistEvidence, ...]


def artist_identity_overlay_sha256(artifact: ArtistIdentityOverlayArtifact) -> str:
    """Return the canonical logical digest for an overlay receipt."""
    return sha256_hex(canonical_json(artifact.model_dump(mode="json", exclude={"output_sha256"})))


def verify_artist_identity_overlay(artifact: ArtistIdentityOverlayArtifact) -> None:
    """Reject a receipt whose self-replay digest does not match."""
    if artist_identity_overlay_sha256(artifact) != artifact.output_sha256:
        raise ArtistIdentityOverlayError("artist identity overlay receipt hash does not replay")


def load_artist_identity_overlay(path: Path) -> ArtistIdentityOverlayArtifact:
    """Parse and verify a serialized overlay receipt."""
    try:
        artifact = ArtistIdentityOverlayArtifact.model_validate_json(path.read_bytes())
        verify_artist_identity_overlay(artifact)
    except (OSError, ValueError) as error:
        raise ArtistIdentityOverlayError("artist identity overlay receipt is invalid") from error
    return artifact


def build_artist_identity_overlay(
    inputs: ArtistIdentityOverlayInputs,
) -> ArtistIdentityOverlayArtifact:
    """Build and atomically publish a complete exact-ID name sidecar.

    Both source databases are attached read-only.  The graph is never changed;
    the output contains every graph ``musicbrainz_artist`` identity, including
    explicit abstentions when the sealed metadata has no unambiguous name.
    """
    if inputs.output_database.exists():
        raise ArtistIdentityOverlayError("overlay output database already exists")
    graph, graph_receipt, metadata, metadata_receipt = _load_inputs(inputs)
    temporary = inputs.output_database.with_name(
        f".{inputs.output_database.name}.{uuid4().hex}.partial"
    )
    try:
        with closing(connect_readwrite(temporary)) as database, database:
            _schema(database)
            _attach_readonly(database, "graph_source", inputs.graph_database)
            _attach_readonly(database, "metadata_source", inputs.metadata_database)
            database.executemany(
                """INSERT INTO artifact_input (
                       role, locator, byte_sha256, byte_count, logical_sha256
                   ) VALUES (?, ?, ?, ?, ?)""",
                (
                    (
                        item.role,
                        item.locator,
                        item.byte_sha256,
                        item.byte_count,
                        item.logical_sha256,
                    )
                    for item in (graph, graph_receipt, metadata, metadata_receipt)
                ),
            )
            database.execute(
                """INSERT INTO artist_identity (
                       artist_mbid, canonical_name, name_status, source_artifact_sha256,
                       representative_release_group_id, representative_record_ordinal,
                       representative_record_sha256
                   )
                   SELECT graph_identity.identifier,
                          summary.canonical_name,
                          CASE
                              WHEN summary.artist_mbid IS NULL THEN 'metadata_missing'
                              WHEN summary.canonical_name IS NULL THEN 'ambiguous_name'
                              ELSE 'canonical_name_observed'
                          END,
                          ?, variant.representative_release_group_id,
                          variant.representative_record_ordinal,
                          variant.representative_record_sha256
                     FROM graph_source.identity AS graph_identity
                LEFT JOIN metadata_source.artist_summary AS summary
                       ON summary.artist_mbid = graph_identity.identifier
                LEFT JOIN metadata_source.canonical_name_variant AS variant
                       ON variant.artist_mbid = summary.artist_mbid
                      AND variant.canonical_name = summary.canonical_name
                    WHERE graph_identity.namespace = 'musicbrainz_artist'
                 ORDER BY graph_identity.identifier""",
                (metadata_receipt.logical_sha256,),
            )
            if database.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ArtistIdentityOverlayError("overlay foreign key check failed")
            if database.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise ArtistIdentityOverlayError("overlay integrity check failed")
        digest, size = sha256_file(temporary)
        with closing(connect_readonly(temporary)) as database:
            counts = _counts(database)
        if counts["artist_identity"] != _graph_artist_count(inputs.graph_database):
            raise ArtistIdentityOverlayError("overlay did not account for every graph artist")
        base = ArtistIdentityOverlayArtifact(
            inputs=(graph, graph_receipt, metadata, metadata_receipt),
            database_sha256=digest,
            database_bytes=size,
            artist_identity_count=counts["artist_identity"],
            canonical_name_count=counts["canonical_name_observed"],
            metadata_missing_count=counts["metadata_missing"],
            ambiguous_name_count=counts["ambiguous_name"],
            output_sha256="0" * 64,
        )
        artifact = base.model_copy(update={"output_sha256": artist_identity_overlay_sha256(base)})
        verify_artist_identity_overlay(artifact)
        temporary.replace(inputs.output_database)
        return artifact
    finally:
        temporary.unlink(missing_ok=True)


def write_artist_identity_overlay(path: Path, artifact: ArtistIdentityOverlayArtifact) -> None:
    """Atomically write a replay-verified overlay receipt."""
    verify_artist_identity_overlay(artifact)
    write_atomic_bytes(path, canonical_json(artifact.model_dump(mode="json")) + b"\n")


def certify_artist_identity_overlay_sources(
    sources: ArtistIdentityOverlaySources,
) -> CertifiedArtistIdentityOverlaySources:
    """Return a wrapper only after the sidecar's bytes and SQLite state verify."""
    verify_artist_identity_overlay_sources(sources)
    return CertifiedArtistIdentityOverlaySources(sources, _OVERLAY_CERTIFICATE)


def verify_artist_identity_overlay_sources(sources: ArtistIdentityOverlaySources) -> None:
    """Verify receipt, immutable sidecar bytes, SQLite health, and row accounting."""
    verify_artist_identity_overlay(sources.artifact)
    if sha256_file(sources.database) != (
        sources.artifact.database_sha256,
        sources.artifact.database_bytes,
    ):
        raise ArtistIdentityOverlayError("overlay database does not match receipt")
    with closing(connect_readonly(sources.database)) as database:
        database.execute("PRAGMA query_only = ON")
        if database.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ArtistIdentityOverlayError("overlay database failed integrity check")
        if database.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ArtistIdentityOverlayError("overlay database failed foreign key check")
        counts = _counts(database)
    if (
        counts["artist_identity"] != sources.artifact.artist_identity_count
        or counts["canonical_name_observed"] != sources.artifact.canonical_name_count
        or counts["metadata_missing"] != sources.artifact.metadata_missing_count
        or counts["ambiguous_name"] != sources.artifact.ambiguous_name_count
    ):
        raise ArtistIdentityOverlayError("overlay row counts do not match receipt")


def artist_identity_for(
    sources: ArtistIdentityOverlaySources, artist_mbid: str
) -> ArtistIdentity | None:
    """Return one exact graph artist identity after source verification."""
    certify_artist_identity_overlay_sources(sources)
    return _artist_identity_for(sources.database, artist_mbid)


def certified_artist_identity_for(
    certified: CertifiedArtistIdentityOverlaySources, artist_mbid: str
) -> ArtistIdentity | None:
    """Look up one exact artist in already startup-certified sidecar sources."""
    if not certified.is_valid():
        raise ArtistIdentityOverlayError("overlay sources are not startup-certified")
    return _artist_identity_for(certified.sources.database, artist_mbid)


def certify_genre_artist_evidence_sources(
    graph_database: Path, overlay: CertifiedArtistIdentityOverlaySources
) -> CertifiedGenreArtistEvidenceSources:
    """Bind an already certified sidecar to the exact graph it was built from."""
    if not overlay.is_valid():
        raise ArtistIdentityOverlayError("overlay sources are not startup-certified")
    graph_input = next(
        item for item in overlay.sources.artifact.inputs if item.role == "evidence_graph_database"
    )
    if sha256_file(graph_database) != (graph_input.byte_sha256, graph_input.byte_count):
        raise ArtistIdentityOverlayError("graph database does not match overlay receipt")
    _verify_graph_database(graph_database)
    return CertifiedGenreArtistEvidenceSources(graph_database, overlay, _OVERLAY_CERTIFICATE)


def genre_artist_evidence_for(
    certified: CertifiedGenreArtistEvidenceSources, stable_seed_id: str, *, limit: int = 100
) -> GenreArtistEvidencePage:
    """Return at most ``limit`` unique artists, including unnamed artists.

    The source graph stores unweighted observations, so ``evidence_weight`` is
    deliberately null rather than a fabricated aggregate score.
    """
    if not certified.is_valid() or not certified.overlay.is_valid():
        raise ArtistIdentityOverlayError("genre artist sources are not startup-certified")
    if not 1 <= limit <= _MAX_GENRE_ARTIST_EVIDENCE:
        raise ArtistIdentityOverlayError("genre artist lookup limit must be between 1 and 1000")
    with closing(connect_readonly(certified.graph_database)) as database:
        database.execute("PRAGMA query_only = ON")
        _attach_readonly(database, "overlay_source", certified.overlay.sources.database)
        rows = database.execute(
            """WITH membership AS (
                   SELECT subject_identifier, evidence_kind, source, facet,
                          provenance_ref, release_group_id
                     FROM claim
                    WHERE subject_namespace = 'musicbrainz_artist'
                      AND predicate = 'artist_membership'
                      AND object_namespace = 'stable_seed'
                      AND object_identifier = ?
                 ), aggregate AS (
                   SELECT subject_identifier,
                          count(*) AS membership_claim_count,
                          sum(evidence_kind = 'artist_direct') AS artist_direct_claim_count,
                          sum(evidence_kind = 'release_group_support')
                              AS release_group_support_claim_count,
                          sum(evidence_kind = 'reviewed_alias_context')
                              AS reviewed_alias_claim_count
                     FROM membership
                 GROUP BY subject_identifier
                 ), representative AS (
                   SELECT subject_identifier, evidence_kind, source, facet,
                          provenance_ref, release_group_id,
                          row_number() OVER (
                              PARTITION BY subject_identifier
                              ORDER BY evidence_kind, source, facet,
                                       release_group_id, provenance_ref
                          ) AS ordinal
                     FROM membership
                 ), joined AS (
                   SELECT overlay.artist_mbid, overlay.canonical_name, overlay.name_status,
                          overlay.source_artifact_sha256,
                          overlay.representative_release_group_id,
                          overlay.representative_record_ordinal,
                          overlay.representative_record_sha256,
                          aggregate.membership_claim_count,
                          aggregate.artist_direct_claim_count,
                          aggregate.release_group_support_claim_count,
                          aggregate.reviewed_alias_claim_count,
                          representative.evidence_kind,
                          representative.source, representative.facet,
                          representative.provenance_ref, representative.release_group_id
                     FROM aggregate
                     JOIN overlay_source.artist_identity AS overlay
                       ON overlay.artist_mbid = aggregate.subject_identifier
                     JOIN representative
                       ON representative.subject_identifier = aggregate.subject_identifier
                      AND representative.ordinal = 1
                 )
                 SELECT *, count(*) OVER () AS total_artist_count,
                        sum(canonical_name IS NULL) OVER () AS total_unnamed_artist_count
                   FROM joined
               ORDER BY artist_direct_claim_count DESC,
                        release_group_support_claim_count DESC,
                        reviewed_alias_claim_count DESC, artist_mbid
                  LIMIT ?""",
            (stable_seed_id, limit),
        ).fetchall()
    artists = tuple(
        GenreArtistEvidence(
            artist=_artist_identity_from_row(row[:7]),
            membership_claim_count=int(row[7]),
            artist_direct_claim_count=int(row[8]),
            release_group_support_claim_count=int(row[9]),
            reviewed_alias_claim_count=int(row[10]),
            representative_evidence_kind=str(row[11]),
            representative_source=str(row[12]),
            representative_facet=str(row[13]),
            representative_provenance_ref=str(row[14]),
            representative_release_group_id=str(row[15]),
        )
        for row in rows
    )
    total_artists = 0 if not rows else int(rows[0][16])
    total_unnamed = 0 if not rows else int(rows[0][17])
    return GenreArtistEvidencePage(
        total_artist_count=total_artists,
        total_unnamed_artist_count=total_unnamed,
        returned_artist_count=len(artists),
        returned_unnamed_artist_count=sum(
            artist.artist.canonical_name is None for artist in artists
        ),
        artists=artists,
    )


def _artist_identity_for(database_path: Path, artist_mbid: str) -> ArtistIdentity | None:
    with closing(connect_readonly(database_path)) as database:
        database.execute("PRAGMA query_only = ON")
        row = database.execute(
            """SELECT artist_mbid, canonical_name, name_status, source_artifact_sha256,
                      representative_release_group_id, representative_record_ordinal,
                      representative_record_sha256
                 FROM artist_identity WHERE artist_mbid = ?""",
            (artist_mbid,),
        ).fetchone()
    if row is None:
        return None
    return _artist_identity_from_row(row)


def _artist_identity_from_row(row: tuple[object, ...]) -> ArtistIdentity:
    status = str(row[2])
    if status not in {"canonical_name_observed", "metadata_missing", "ambiguous_name"}:
        raise ArtistIdentityOverlayError("overlay contains an invalid artist name status")
    return ArtistIdentity(
        artist_mbid=str(row[0]),
        canonical_name=None if row[1] is None else str(row[1]),
        name_status=status,
        source_artifact_sha256=str(row[3]),
        representative_release_group_id=None if row[4] is None else str(row[4]),
        representative_record_ordinal=_nullable_ordinal(row[5]),
        representative_record_sha256=None if row[6] is None else str(row[6]),
    )


def _nullable_ordinal(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    raise ArtistIdentityOverlayError("overlay contains a non-integer representative ordinal")


def _load_inputs(
    inputs: ArtistIdentityOverlayInputs,
) -> tuple[OverlayInput, OverlayInput, OverlayInput, OverlayInput]:
    try:
        graph_receipt = EvidenceGraphProjectionArtifact.model_validate_json(
            inputs.graph_receipt.read_bytes()
        )
        verify_evidence_graph_projection(graph_receipt)
        metadata_receipt = ArtistMetadataArtifact.model_validate_json(
            inputs.metadata_receipt.read_bytes()
        )
        verify_artist_metadata_artifact(metadata_receipt)
        graph_sha, graph_bytes = sha256_file(inputs.graph_database)
        metadata_sha, metadata_bytes = sha256_file(inputs.metadata_database)
        receipt_sha, receipt_bytes = sha256_file(inputs.graph_receipt)
        metadata_receipt_sha, metadata_receipt_bytes = sha256_file(inputs.metadata_receipt)
    except (OSError, ValueError) as error:
        raise ArtistIdentityOverlayError("overlay inputs are invalid") from error
    if (graph_sha, graph_bytes) != (
        graph_receipt.database_sha256,
        graph_receipt.database_bytes,
    ):
        raise ArtistIdentityOverlayError("graph database does not match graph receipt")
    if (metadata_sha, metadata_bytes) != (
        metadata_receipt.metadata_database_sha256,
        metadata_receipt.metadata_database_bytes,
    ):
        raise ArtistIdentityOverlayError("metadata database does not match metadata receipt")
    _verify_graph_database(inputs.graph_database)
    _verify_metadata_database(inputs.metadata_database)
    return (
        OverlayInput(
            role="evidence_graph_database",
            locator=inputs.graph_database.name,
            byte_sha256=graph_sha,
            byte_count=graph_bytes,
            logical_sha256=graph_receipt.database_sha256,
        ),
        OverlayInput(
            role="evidence_graph_receipt",
            locator=inputs.graph_receipt.name,
            byte_sha256=receipt_sha,
            byte_count=receipt_bytes,
            logical_sha256=graph_receipt.output_sha256,
        ),
        OverlayInput(
            role="musicbrainz_artist_metadata_database",
            locator=inputs.metadata_database.name,
            byte_sha256=metadata_sha,
            byte_count=metadata_bytes,
            logical_sha256=metadata_receipt.metadata_database_sha256,
        ),
        OverlayInput(
            role="musicbrainz_artist_metadata_receipt",
            locator=inputs.metadata_receipt.name,
            byte_sha256=metadata_receipt_sha,
            byte_count=metadata_receipt_bytes,
            logical_sha256=metadata_receipt.output_sha256,
        ),
    )


def _attach_readonly(database: sqlite3.Connection, name: str, path: Path) -> None:
    """Attach a SQLite source through its immutable read-only URI."""
    database.execute(f"ATTACH DATABASE ? AS {name}", (f"file:{path.resolve()}?mode=ro",))


def _verify_graph_database(path: Path) -> None:
    with closing(connect_readonly(path)) as database:
        database.execute("PRAGMA query_only = ON")
        if database.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ArtistIdentityOverlayError("graph database failed integrity check")
        if database.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ArtistIdentityOverlayError("graph database failed foreign key check")
        columns = {str(row[1]) for row in database.execute("PRAGMA table_info(identity)")}
    if not {"namespace", "identifier"} <= columns:
        raise ArtistIdentityOverlayError("graph database schema is incompatible")


def _verify_metadata_database(path: Path) -> None:
    with closing(connect_readonly(path)) as database:
        database.execute("PRAGMA query_only = ON")
        if database.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ArtistIdentityOverlayError("metadata database failed integrity check")
        summary_columns = {
            str(row[1]) for row in database.execute("PRAGMA table_info(artist_summary)")
        }
        variant_columns = {
            str(row[1]) for row in database.execute("PRAGMA table_info(canonical_name_variant)")
        }
    if (
        not {"artist_mbid", "canonical_name"} <= summary_columns
        or not {
            "artist_mbid",
            "canonical_name",
            "representative_release_group_id",
            "representative_record_ordinal",
            "representative_record_sha256",
        }
        <= variant_columns
    ):
        raise ArtistIdentityOverlayError("metadata database schema is incompatible")


def _schema(database: sqlite3.Connection) -> None:
    database.executescript(
        """PRAGMA journal_mode=OFF;
PRAGMA synchronous=OFF;
PRAGMA temp_store=MEMORY;
PRAGMA foreign_keys=ON;
CREATE TABLE artifact_input(
role TEXT PRIMARY KEY NOT NULL,locator TEXT NOT NULL,byte_sha256 TEXT NOT NULL,
byte_count INTEGER NOT NULL,logical_sha256 TEXT NOT NULL) WITHOUT ROWID;
CREATE TABLE artist_identity(
artist_mbid TEXT PRIMARY KEY NOT NULL,canonical_name TEXT,
name_status TEXT NOT NULL CHECK(name_status IN
('canonical_name_observed','metadata_missing','ambiguous_name')),
source_artifact_sha256 TEXT NOT NULL,
representative_release_group_id TEXT,representative_record_ordinal INTEGER,
representative_record_sha256 TEXT,
CHECK((name_status='canonical_name_observed') = (canonical_name IS NOT NULL)),
CHECK((name_status='canonical_name_observed') =
      (representative_release_group_id IS NOT NULL AND representative_record_ordinal IS NOT NULL
       AND representative_record_sha256 IS NOT NULL))) WITHOUT ROWID;
CREATE INDEX artist_identity_canonical_name ON artist_identity(canonical_name);
"""
    )


def _counts(database: sqlite3.Connection) -> dict[str, int]:
    queries = {
        "artist_identity": "SELECT count(*) FROM artist_identity",
        "canonical_name_observed": (
            "SELECT count(*) FROM artist_identity WHERE name_status = 'canonical_name_observed'"
        ),
        "metadata_missing": (
            "SELECT count(*) FROM artist_identity WHERE name_status = 'metadata_missing'"
        ),
        "ambiguous_name": (
            "SELECT count(*) FROM artist_identity WHERE name_status = 'ambiguous_name'"
        ),
    }
    return {name: int(database.execute(query).fetchone()[0]) for name, query in queries.items()}


def _graph_artist_count(path: Path) -> int:
    with closing(connect_readonly(path)) as database:
        row = database.execute(
            "SELECT count(*) FROM identity WHERE namespace = 'musicbrainz_artist'"
        ).fetchone()
    if row is None:
        raise ArtistIdentityOverlayError("graph artist count query failed")
    return int(row[0])
