"""Bounded MusicBrainz artist-to-Spotify identity bridging.

The adapter reads only MusicBrainz artist relations.  It never reads audio,
recordings, or media bytes.  Spotify IDs are accepted only when they occur in
the immutable historical H3 ``source_artist_id`` universe; H3 is a join
boundary here, not a source of negative membership labels.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sqlite3
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final, Literal, Protocol, override
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, TypeAdapter, model_validator

from musix.models import FrozenModel
from musix.storage import ObjectKey, ObjectStore, ObjectWrite

if TYPE_CHECKING:
    from collections.abc import Iterator

_REVISION: Final = "musicbrainz-spotify-bridge-v1"
_SETTINGS_REVISION: Final = "musicbrainz-spotify-bridge-settings-v1"
_RECEIPT_REVISION: Final = "musicbrainz-spotify-bridge-publication-v1"
_SHA256: Final = r"^[0-9a-f]{64}$"
_SPOTIFY_ID: Final = re.compile(r"^[A-Za-z0-9]{22}$")
_PATH_WITH_TRAILING_SLASH_PARTS: Final = 4
_JSON_OBJECT = TypeAdapter(dict[str, object])

type BridgeDisposition = Literal["accepted", "conflict"]
type ConflictKind = Literal["spotify_id_multiple_musicbrainz_artists"]


class MusicBrainzSpotifyBridgeError(ValueError):
    """Report an invalid source, historical boundary, or bridge invariant."""


class SpotifyBridgeSettings(FrozenModel):
    """Explicit archive, relation, and output bounds included in the hash."""

    revision: Literal["musicbrainz-spotify-bridge-settings-v1"] = _SETTINGS_REVISION
    max_archive_bytes: int = Field(default=8 * 1024**3, gt=0)
    max_member_bytes: int = Field(default=64 * 1024**3, gt=0)
    max_record_bytes: int = Field(default=64 * 1024**2, gt=0)
    max_records: int = Field(default=10_000_000, gt=0)
    max_decompression_ratio: int = Field(default=128, gt=0)
    max_relations_per_artist: int = Field(default=512, gt=0, le=10_000)
    max_bridge_rows: int = Field(default=1_000_000, gt=0)


class SpotifyBridgeRow(FrozenModel):
    """One distinct direct Spotify relation retained at the H3 join boundary."""

    musicbrainz_artist_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    spotify_artist_id: str = Field(pattern=r"^[A-Za-z0-9]{22}$")
    relation_url: str = Field(pattern=r"^https://open\.spotify\.com/artist/[A-Za-z0-9]{22}/?$")
    source_url: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    source_record_ordinal: int = Field(gt=0)
    source_record_sha256: str = Field(pattern=_SHA256)
    source_record_byte_length: int = Field(ge=1)
    evidence_ref: str = Field(min_length=1)
    disposition: BridgeDisposition


class SpotifyBridgeConflict(FrozenModel):
    """A collision that is retained for review and never promoted."""

    kind: ConflictKind
    identity: str = Field(min_length=1)
    musicbrainz_artist_ids: tuple[str, ...] = Field(min_length=1)
    spotify_artist_ids: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)


class SpotifyBridgeCounters(FrozenModel):
    """Explicit accounting for archive, relation, join, and collision paths."""

    archive_member_count: int = Field(ge=0)
    malformed_member_path_count: int = Field(ge=0)
    member_over_limit_count: int = Field(ge=0)
    records_seen: int = Field(ge=0)
    records_parsed: int = Field(ge=0)
    malformed_json_count: int = Field(ge=0)
    malformed_artist_shape_count: int = Field(ge=0)
    record_over_limit_count: int = Field(ge=0)
    malformed_relation_count: int = Field(ge=0)
    malformed_spotify_url_count: int = Field(ge=0)
    ignored_non_spotify_relation_count: int = Field(ge=0)
    duplicate_claim_count: int = Field(ge=0)
    historical_target_claim_count: int = Field(ge=0)
    distinct_claim_count: int = Field(ge=0)
    accepted_bridge_count: int = Field(ge=0)
    conflict_claim_count: int = Field(ge=0)
    musicbrainz_alias_count: int = Field(ge=0)
    spotify_conflict_count: int = Field(ge=0)
    historical_artist_count: int = Field(ge=0)
    historical_artist_with_bridge_count: int = Field(ge=0)
    historical_artist_without_bridge_count: int = Field(ge=0)


class MusicBrainzSpotifyBridgeArtifact(FrozenModel):
    """Hash-bound direct Spotify bridge and collision audit."""

    revision: Literal["musicbrainz-spotify-bridge-v1"] = _REVISION
    source_archive_sha256: str = Field(pattern=_SHA256)
    source_archive_byte_size: int = Field(ge=1)
    historical_database_sha256: str = Field(pattern=_SHA256)
    historical_artist_count: int = Field(ge=0)
    settings: SpotifyBridgeSettings
    settings_sha256: str = Field(pattern=_SHA256)
    counters: SpotifyBridgeCounters
    rows: tuple[SpotifyBridgeRow, ...]
    conflicts: tuple[SpotifyBridgeConflict, ...]
    output_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _complete(self) -> MusicBrainzSpotifyBridgeArtifact:
        if self.settings_sha256 != settings_sha256(self.settings):
            raise ValueError("Spotify bridge settings hash does not match settings")
        if self.historical_artist_count != self.counters.historical_artist_count:
            raise ValueError("Spotify bridge historical count does not match counters")
        if len(self.rows) != self.counters.distinct_claim_count:
            raise ValueError("Spotify bridge row count does not match counters")
        if len(self.conflicts) != self.counters.spotify_conflict_count:
            raise ValueError("Spotify bridge conflict count does not match counters")
        return self


class SpotifyBridgePublicationReceipt(FrozenModel):
    """Object-store receipt binding bytes, logical hash, and source custody."""

    revision: Literal["musicbrainz-spotify-bridge-publication-v1"] = _RECEIPT_REVISION
    artifact: ObjectWrite
    artifact_sha256: str = Field(pattern=_SHA256)
    logical_output_sha256: str = Field(pattern=_SHA256)
    source_archive_sha256: str = Field(pattern=_SHA256)
    historical_database_sha256: str = Field(pattern=_SHA256)
    content_policy: Literal["metadata_only_no_audio"] = "metadata_only_no_audio"


class _ReadableStream(Protocol):
    def read(self, size: int = -1, /) -> bytes: ...

    def readline(self, size: int = -1, /) -> bytes: ...


class _HashingReader(io.RawIOBase):
    def __init__(self, stream: _ReadableStream) -> None:
        super().__init__()
        self._stream = stream
        self.digest = hashlib.sha256()

    @override
    def read(self, size: int = -1) -> bytes:
        data = self._stream.read(size)
        if not isinstance(data, bytes):
            raise TypeError("archive stream returned non-bytes")
        self.digest.update(data)
        return data

    @override
    def readable(self) -> bool:
        return True

    @override
    def seekable(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class _RawRecord:
    ordinal: int
    payload: bytes | None
    byte_length: int
    sha256: str


@dataclass(slots=True)
class _ArchiveStats:
    archive_member_count: int = 0
    malformed_member_path_count: int = 0
    member_over_limit_count: int = 0
    record_over_limit_count: int = 0


@dataclass(frozen=True, slots=True)
class _URLProvider:
    """Provider URL parser registration; new providers can be added independently."""

    provider: Literal["spotify"]
    hostname: str
    path_segment: str
    identifier_pattern: re.Pattern[str]


_URL_PROVIDERS: tuple[_URLProvider, ...] = (
    _URLProvider("spotify", "open.spotify.com", "artist", _SPOTIFY_ID),
)


def settings_sha256(settings: SpotifyBridgeSettings) -> str:
    """Hash the explicit bounded settings."""
    return _sha256_json(settings.model_dump(mode="json"))


def _sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    ).hexdigest()


def bridge_artifact_sha256(artifact: MusicBrainzSpotifyBridgeArtifact) -> str:
    """Hash all logical bridge fields except the self-referential hash."""
    return _sha256_json(artifact.model_dump(mode="json", exclude={"output_sha256"}))


def _safe_member(name: str) -> PurePosixPath | None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        return None
    return path


def _raw_lines(  # noqa: C901
    stream: _ReadableStream, settings: SpotifyBridgeSettings
) -> Iterator[_RawRecord]:
    ordinal = 0
    while True:
        first = stream.readline(settings.max_record_bytes + 2)
        if not first:
            return
        chunks = [first]
        last = first
        raw_length = len(first)
        oversized = len(first) > settings.max_record_bytes
        raw_digest = hashlib.sha256(first)
        while not last.endswith(b"\n"):
            continuation = stream.readline(64 * 1024)
            if not continuation:
                break
            last = continuation
            raw_digest.update(continuation)
            raw_length += len(continuation)
            if not oversized:
                if raw_length <= settings.max_record_bytes + 2:
                    chunks.append(continuation)
                else:
                    oversized = True
                    chunks.clear()
            if oversized and not continuation.endswith(b"\n"):
                continue
            if continuation.endswith(b"\n"):
                break
        if oversized:
            ordinal += 1
            yield _RawRecord(
                ordinal=ordinal,
                payload=None,
                byte_length=raw_length,
                sha256=raw_digest.hexdigest(),
            )
            continue
        payload = b"".join(chunks).rstrip(b"\r\n")
        if not payload.strip():
            continue
        ordinal += 1
        yield _RawRecord(
            ordinal=ordinal,
            payload=payload if len(payload) <= settings.max_record_bytes else None,
            byte_length=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
        )


def _provider_id_from_url(value: object, provider: _URLProvider) -> tuple[str, str] | None:
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.netloc.casefold() != provider.hostname:
        return None
    parts = parsed.path.split("/")
    if (
        len(parts) not in {3, 4}
        or parts[1] != provider.path_segment
        or (len(parts) == _PATH_WITH_TRAILING_SLASH_PARTS and parts[3])
    ):
        return None
    identifier = parts[2]
    if not provider.identifier_pattern.fullmatch(identifier):
        return None
    return identifier, f"https://{provider.hostname}/{provider.path_segment}/{identifier}"


def _spotify_id_from_url(value: object) -> tuple[str, str] | None:
    """Return a direct Spotify artist ID through the provider registry."""
    return _provider_id_from_url(value, _URL_PROVIDERS[0])


def _iter_artist_records(  # noqa: C901
    archive_path: Path, settings: SpotifyBridgeSettings, stats: _ArchiveStats
) -> tuple[Iterator[_RawRecord], _HashingReader, int]:
    """Return a lazy artist iterator plus its live archive hash reader."""
    archive_size = archive_path.stat().st_size
    if archive_size > settings.max_archive_bytes:
        raise MusicBrainzSpotifyBridgeError("archive exceeds max_archive_bytes")
    original = archive_path.open("rb")
    hashing = _HashingReader(original)
    archive = tarfile.open(fileobj=hashing, mode="r|xz")  # noqa: SIM115

    def records() -> Iterator[_RawRecord]:  # noqa: C901, PLR0912
        found_artist = False
        schema_number: str | None = None
        try:
            for member in archive:
                stats.archive_member_count += 1
                member_path = _safe_member(member.name)
                if member_path is None:
                    stats.malformed_member_path_count += 1
                    continue
                if member.size > settings.max_member_bytes:
                    stats.member_over_limit_count += 1
                    continue
                if member.size > archive_size * settings.max_decompression_ratio:
                    stats.member_over_limit_count += 1
                    continue
                if not member.isfile():
                    continue
                stream = archive.extractfile(member)
                if stream is None:
                    continue
                try:
                    if member_path == PurePosixPath("JSON_DUMPS_SCHEMA_NUMBER"):
                        schema_number = stream.read(32).decode("ascii", errors="replace").strip()
                    elif member_path == PurePosixPath("mbdump/artist"):
                        if found_artist:
                            raise MusicBrainzSpotifyBridgeError("archive repeats mbdump/artist")
                        found_artist = True
                        yield from _raw_lines(stream, settings)
                finally:
                    stream.close()
        finally:
            archive.close()
            original.close()
        if not found_artist:
            raise MusicBrainzSpotifyBridgeError("archive has no mbdump/artist member")
        if schema_number != "1":
            raise MusicBrainzSpotifyBridgeError(f"unsupported JSON dump schema: {schema_number!r}")

    return records(), hashing, archive_size


def _historical_database_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _open_historical_targets(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise MusicBrainzSpotifyBridgeError("historical database does not exist")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        connection.execute(
            "CREATE TEMP TABLE spotify_targets (spotify_artist_id TEXT PRIMARY KEY) WITHOUT ROWID"
        )
        connection.execute(
            """
            INSERT INTO spotify_targets(spotify_artist_id)
            SELECT DISTINCT source_artist_id
              FROM historical_genre_artist_observations
             WHERE source_artist_id IS NOT NULL
            """
        )
    except sqlite3.Error as error:
        connection.close()
        raise MusicBrainzSpotifyBridgeError(
            "historical database lacks the H3 artist observation table"
        ) from error
    else:
        return connection


def _claim_row(  # noqa: C901, PLR0912
    payload: bytes, settings: SpotifyBridgeSettings
) -> tuple[str, tuple[tuple[str, str, str], ...], int, int, int, int]:
    """Parse one artist into MBID and direct Spotify relation claims."""
    try:
        value = _JSON_OBJECT.validate_json(payload)
    except ValueError:
        return "", (), 1, 0, 0, 0
    raw_id = value.get("id")
    try:
        artist_id = str(UUID(raw_id)) if isinstance(raw_id, str) else ""
    except ValueError:
        artist_id = ""
    if not artist_id:
        return "", (), 0, 1, 0, 0
    relations = value.get("relations")
    if relations is None:
        return artist_id, (), 0, 0, 0, 0
    if not isinstance(relations, list):
        return artist_id, (), 0, 1, 0, 0
    if len(relations) > settings.max_relations_per_artist:
        return artist_id, (), 0, 1, 0, 1
    claims: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    malformed = 0
    ignored = 0
    for relation in relations:
        if not isinstance(relation, dict):
            malformed += 1
            continue
        if relation.get("target-type") != "url":
            ignored += 1
            continue
        url_value = relation.get("url")
        target = url_value.get("resource") if isinstance(url_value, dict) else None
        parsed = _spotify_id_from_url(target)
        if parsed is None:
            if isinstance(target, str) and "spotify" in target.casefold():
                malformed += 1
            else:
                ignored += 1
            continue
        spotify_id, canonical_url = parsed
        if spotify_id in seen:
            continue
        seen.add(spotify_id)
        claims.append((spotify_id, canonical_url, str(target)))
    return artist_id, tuple(claims), 0, 0, malformed, ignored


def _build_conflicts(
    connection: sqlite3.Connection,
) -> tuple[tuple[SpotifyBridgeConflict, ...], set[tuple[str, str]]]:
    conflicts: list[SpotifyBridgeConflict] = []
    conflict_pairs: set[tuple[str, str]] = set()
    identities = connection.execute(
        """
        SELECT spotify_artist_id
          FROM bridge_claims
         GROUP BY spotify_artist_id
        HAVING count(*) > 1
         ORDER BY spotify_artist_id
        """
    )
    for (identity,) in identities:
        rows = tuple(
            connection.execute(
                """
                SELECT musicbrainz_artist_id, spotify_artist_id, evidence_ref
                  FROM bridge_claims
                 WHERE spotify_artist_id = ?
                 ORDER BY musicbrainz_artist_id, spotify_artist_id
                """,
                (identity,),
            )
        )
        conflicts.append(
            SpotifyBridgeConflict(
                kind="spotify_id_multiple_musicbrainz_artists",
                identity=str(identity),
                musicbrainz_artist_ids=tuple(sorted({str(row[0]) for row in rows})),
                spotify_artist_ids=(str(identity),),
                evidence_refs=tuple(str(row[2]) for row in rows),
            )
        )
        conflict_pairs.update((str(row[0]), str(row[1])) for row in rows)
    return tuple(conflicts), conflict_pairs


def build_musicbrainz_spotify_bridge(  # noqa: PLR0915
    archive_path: Path,
    historical_database_path: Path,
    settings: SpotifyBridgeSettings | None = None,
) -> MusicBrainzSpotifyBridgeArtifact:
    """Extract one bounded bridge against the H3 Spotify ID universe."""
    resolved = settings or SpotifyBridgeSettings()
    historical_sha = _historical_database_sha256(historical_database_path)
    connection = _open_historical_targets(historical_database_path)
    counters = dict.fromkeys(SpotifyBridgeCounters.model_fields, 0)
    try:
        connection.execute(
            """
            CREATE TEMP TABLE bridge_claims (
                musicbrainz_artist_id TEXT NOT NULL,
                spotify_artist_id TEXT NOT NULL,
                relation_url TEXT NOT NULL,
                source_url TEXT NOT NULL,
                source_record_id TEXT NOT NULL,
                source_record_ordinal INTEGER NOT NULL,
                source_record_sha256 TEXT NOT NULL,
                source_record_byte_length INTEGER NOT NULL,
                evidence_ref TEXT NOT NULL,
                PRIMARY KEY (musicbrainz_artist_id, spotify_artist_id)
            ) WITHOUT ROWID
            """
        )
        archive_stats = _ArchiveStats()
        records, hashing, archive_size = _iter_artist_records(archive_path, resolved, archive_stats)
        for raw in records:
            counters["records_seen"] += 1
            if counters["records_seen"] > resolved.max_records:
                raise MusicBrainzSpotifyBridgeError("archive exceeds max_records")
            if raw.byte_length > resolved.max_record_bytes:
                counters["record_over_limit_count"] += 1
                continue
            if raw.payload is None:
                continue
            artist_id, claims, malformed_json, malformed_shape, malformed_url, ignored = _claim_row(
                raw.payload, resolved
            )
            counters["malformed_json_count"] += malformed_json
            counters["malformed_artist_shape_count"] += malformed_shape
            counters["malformed_relation_count"] += malformed_shape
            counters["malformed_spotify_url_count"] += malformed_url
            counters["ignored_non_spotify_relation_count"] += ignored
            if not artist_id:
                continue
            counters["records_parsed"] += 1
            source_record_id = f"musicbrainz:artist:{artist_id}"
            for spotify_id, relation_url, source_url in claims:
                target = connection.execute(
                    "SELECT 1 FROM spotify_targets WHERE spotify_artist_id = ?", (spotify_id,)
                ).fetchone()
                if target is None:
                    continue
                counters["historical_target_claim_count"] += 1
                evidence_ref = f"musicbrainz:spotify-artist:{raw.sha256}:{artist_id}:{spotify_id}"
                inserted = connection.execute(
                    """
                    INSERT OR IGNORE INTO bridge_claims VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        artist_id,
                        spotify_id,
                        relation_url,
                        source_url,
                        source_record_id,
                        raw.ordinal,
                        raw.sha256,
                        raw.byte_length,
                        evidence_ref,
                    ),
                ).rowcount
                if inserted == 0:
                    counters["duplicate_claim_count"] += 1
        archive_sha = hashing.digest.hexdigest()
        counters.update(
            archive_member_count=archive_stats.archive_member_count,
            malformed_member_path_count=archive_stats.malformed_member_path_count,
            member_over_limit_count=archive_stats.member_over_limit_count,
        )
        conflicts, conflict_pairs = _build_conflicts(connection)
        rows_raw = tuple(
            connection.execute(
                """
                SELECT musicbrainz_artist_id, spotify_artist_id, relation_url, source_url,
                       source_record_id, source_record_ordinal, source_record_sha256,
                       source_record_byte_length, evidence_ref
                  FROM bridge_claims ORDER BY musicbrainz_artist_id, spotify_artist_id
                """
            )
        )
        if len(rows_raw) > resolved.max_bridge_rows:
            raise MusicBrainzSpotifyBridgeError("bridge exceeds max_bridge_rows")
        rows = tuple(
            SpotifyBridgeRow(
                musicbrainz_artist_id=str(row[0]),
                spotify_artist_id=str(row[1]),
                relation_url=str(row[2]),
                source_url=str(row[3]),
                source_record_id=str(row[4]),
                source_record_ordinal=int(row[5]),
                source_record_sha256=str(row[6]),
                source_record_byte_length=int(row[7]),
                evidence_ref=str(row[8]),
                disposition="conflict"
                if (str(row[0]), str(row[1])) in conflict_pairs
                else "accepted",
            )
            for row in rows_raw
        )
        historical_count = int(
            connection.execute("SELECT count(*) FROM spotify_targets").fetchone()[0]
        )
        bridged_count = int(
            connection.execute(
                """
                SELECT count(*) FROM (
                    SELECT spotify_artist_id FROM bridge_claims
                     GROUP BY spotify_artist_id HAVING count(*) = 1
                )
                """
            ).fetchone()[0]
        )
        alias_count = int(
            connection.execute(
                """
                SELECT count(*) FROM (
                    SELECT musicbrainz_artist_id FROM bridge_claims
                     GROUP BY musicbrainz_artist_id HAVING count(*) > 1
                )
                """
            ).fetchone()[0]
        )
        counters.update(
            distinct_claim_count=len(rows),
            accepted_bridge_count=sum(row.disposition == "accepted" for row in rows),
            conflict_claim_count=sum(row.disposition == "conflict" for row in rows),
            musicbrainz_alias_count=alias_count,
            spotify_conflict_count=sum(
                conflict.kind == "spotify_id_multiple_musicbrainz_artists" for conflict in conflicts
            ),
            historical_artist_count=historical_count,
            historical_artist_with_bridge_count=bridged_count,
            historical_artist_without_bridge_count=historical_count - bridged_count,
        )
        counter_model = SpotifyBridgeCounters(**counters)
        provisional = MusicBrainzSpotifyBridgeArtifact(
            source_archive_sha256=archive_sha,
            source_archive_byte_size=archive_size,
            historical_database_sha256=historical_sha,
            historical_artist_count=historical_count,
            settings=resolved,
            settings_sha256=settings_sha256(resolved),
            counters=counter_model,
            rows=rows,
            conflicts=conflicts,
            output_sha256="0" * 64,
        )
        return provisional.model_copy(update={"output_sha256": bridge_artifact_sha256(provisional)})
    finally:
        connection.close()


def verify_musicbrainz_spotify_bridge(artifact: MusicBrainzSpotifyBridgeArtifact) -> None:
    """Replay hashes, row bounds, and collision dispositions."""
    if artifact.output_sha256 != bridge_artifact_sha256(artifact):
        raise ValueError("Spotify bridge output hash does not replay")
    if artifact.settings_sha256 != settings_sha256(artifact.settings):
        raise ValueError("Spotify bridge settings hash does not replay")
    if len(artifact.rows) != artifact.counters.distinct_claim_count:
        raise ValueError("Spotify bridge row count does not replay")
    for row in artifact.rows:
        if row.disposition == "accepted" and any(
            row.spotify_artist_id in conflict.spotify_artist_ids for conflict in artifact.conflicts
        ):
            raise ValueError("Spotify bridge conflict row was marked accepted")


def write_musicbrainz_spotify_bridge(artifact: MusicBrainzSpotifyBridgeArtifact, path: Path) -> str:
    """Atomically write one canonical bridge artifact."""
    verify_musicbrainz_spotify_bridge(artifact)
    payload = (
        json.dumps(
            artifact.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )
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


def publish_musicbrainz_spotify_bridge(
    artifact: MusicBrainzSpotifyBridgeArtifact, *, output_path: Path, store: ObjectStore
) -> SpotifyBridgePublicationReceipt:
    """Write and push one verified bridge through immutable object storage."""
    artifact_sha = write_musicbrainz_spotify_bridge(artifact, output_path)
    stored = store.push(
        output_path,
        ObjectKey(value=f"musicbrainz-spotify-bridge/sha256/{artifact_sha}.json"),
    )
    if stored.sha256 != artifact_sha:
        raise ValueError("object store changed Spotify bridge artifact bytes")
    return SpotifyBridgePublicationReceipt(
        artifact=stored,
        artifact_sha256=artifact_sha,
        logical_output_sha256=artifact.output_sha256,
        source_archive_sha256=artifact.source_archive_sha256,
        historical_database_sha256=artifact.historical_database_sha256,
    )
