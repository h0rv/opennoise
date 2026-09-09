"""Bounded, local-only MusicBrainz artist-context metadata pilot.

This module deliberately keeps raw MusicBrainz responses content addressed and
separate from its revisioned derived SQLite projection.  It makes no claim
about nationality, origin, or artist genre.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, Final, Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from musix.taxonomy.seed_reconciliation import SeedReconciliationArtifact, verify_seed_reconciliation
from musix.sources.musicbrainz import MusicBrainzArtist, MusicBrainzClient

if TYPE_CHECKING:
    from collections.abc import Callable

_SHA256: Final = r"^[0-9a-f]{64}$"
_EVIDENCE_SHA256: Final = "980b2c58e16b024d282ca1acc58b98dcab292f0e1a50917812d1b59df0340c8a"
_PILOT_SIZE: Final = 50
_COHORT_SIZE: Final = 10
_COHORTS: Final = (
    ("hiphop", "item5", "hip hop", "item5"),
    ("house", "item94", "house", "item94"),
    ("jazz", "item379", "jazz", "item379"),
    ("postpunk", "item577", "post-punk", "item577"),
    ("cumbia", "item675", "cumbia", "item675"),
)


class ArtistMetadataContextPilotError(RuntimeError):
    """Report an invalid pilot input, cache, or bounded acquisition."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode()


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1_048_576):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class PilotSelectionEntry(_FrozenModel):
    """One seed-bound direct-anchor artist selected for the pilot."""

    cohort: str = Field(min_length=1)
    source_item_id: str = Field(min_length=1)
    seed_name: str = Field(min_length=1)
    genre_id: str = Field(pattern=r"^item[0-9]+$")
    artist_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")


class PilotQueryManifest(_FrozenModel):
    """Immutable deterministic selection before any network acquisition."""

    revision: Literal["artist-metadata-context-pilot-query-manifest-v1"] = (
        "artist-metadata-context-pilot-query-manifest-v1"
    )
    evidence_database_sha256: str = Field(pattern=_SHA256)
    reconciliation_sha256: str = Field(pattern=_SHA256)
    selection_policy: Literal["direct-anchor-per-cohort-lexicographic-v1"] = (
        "direct-anchor-per-cohort-lexicographic-v1"
    )
    requested_count: Literal[50] = 50
    entries: tuple[PilotSelectionEntry, ...]
    manifest_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def exact_entries(self) -> PilotQueryManifest:
        """Require the fixed cap and an MBID only once across cohorts."""
        if (
            len(self.entries) != _PILOT_SIZE
            or len({entry.artist_mbid for entry in self.entries}) != _PILOT_SIZE
        ):
            raise ValueError("pilot manifest must contain exactly 50 unique artist MBIDs")
        expected = _sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
        if self.manifest_sha256 != expected:
            raise ValueError("pilot manifest hash does not match its contents")
        return self


class CachedRequest(_FrozenModel):
    """One cache-first request outcome, including permanent bounded failures."""

    artist_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")
    request_url: str = Field(min_length=1)
    received_at: str | None = None
    outcome: Literal["success", "failure"]
    raw_sha256: str | None = Field(default=None, pattern=_SHA256)
    raw_byte_size: int | None = Field(default=None, ge=1)
    failure: str | None = None
    failure_type: str | None = None
    http_status: int | None = Field(default=None, ge=100, le=599)
    retryable: bool | None = None
    retry_after: str | None = None
    failed_response_body_available: Literal[False] = False

    @model_validator(mode="after")
    def complete_outcome(self) -> CachedRequest:
        """Require provenance appropriate to each outcome."""
        if self.outcome == "success" and (self.raw_sha256 is None or self.raw_byte_size is None):
            raise ValueError("successful cache entry requires raw bytes")
        if self.outcome == "failure" and self.failure is None:
            raise ValueError("failed cache entry requires failure text")
        return self


class PilotArtifact(_FrozenModel):
    """Hash-bound derived projection report for this non-exportable pilot."""

    revision: Literal["artist-metadata-context-pilot-projection-v1"] = (
        "artist-metadata-context-pilot-projection-v1"
    )
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    input_manifest_sha256: str = Field(pattern=_SHA256)
    evidence_database_sha256: str = Field(pattern=_SHA256)
    raw_source_manifest_sha256: str = Field(pattern=_SHA256)
    projection_database_sha256: str = Field(pattern=_SHA256)
    requested_count: int = Field(ge=0, le=50)
    cumulative_network_attempt_count: int = Field(ge=0, le=50)
    network_requests_this_run: int = Field(ge=0, le=50)
    cache_hit_count: int = Field(ge=0, le=50)
    success_count: int = Field(ge=0, le=50)
    failure_count: int = Field(ge=0, le=50)
    country_count: int = Field(ge=0, le=50)
    area_count: int = Field(ge=0, le=50)
    begin_area_count: int = Field(ge=0, le=50)
    aliases_count: int = Field(ge=0)
    aliases_artist_count: int = Field(ge=0, le=50)
    canonical_name_count: int = Field(ge=0, le=50)
    failure_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class PilotBuildInputs:
    """Caller-owned immutable paths and source identification for one run."""

    evidence_database: Path
    reconciliation: Path
    output_root: Path
    user_agent: str


def build_query_manifest(evidence_database: Path, reconciliation: Path) -> PilotQueryManifest:
    """Select a fixed, de-duplicated 10-artist direct-anchor cohort per seed."""
    if _file_sha256(evidence_database) != _EVIDENCE_SHA256:
        raise ArtistMetadataContextPilotError(
            "evidence database does not match the pinned input SHA256"
        )
    reconciliation_sha = _file_sha256(reconciliation)
    reconciliation_artifact = SeedReconciliationArtifact.model_validate_json(
        reconciliation.read_bytes()
    )
    verify_seed_reconciliation(reconciliation_artifact)
    dispositions = {item.source_item_id: item for item in reconciliation_artifact.dispositions}
    selected: set[str] = set()
    entries: list[PilotSelectionEntry] = []
    with sqlite3.connect(f"file:{evidence_database}?mode=ro", uri=True) as connection:
        for cohort, source_item_id, seed_name, genre_id in _COHORTS:
            disposition = dispositions.get(source_item_id)
            if disposition is None or disposition.seed_name != seed_name:
                raise ArtistMetadataContextPilotError(
                    "pilot cohort does not match the verified reconciliation artifact"
                )
            rows = connection.execute(
                "SELECT DISTINCT artist_id FROM direct_anchor "
                "WHERE genre_id = ? ORDER BY artist_id",
                (genre_id,),
            ).fetchall()
            picks = [row[0] for row in rows if row[0] not in selected][:_COHORT_SIZE]
            if len(picks) != _COHORT_SIZE:
                raise ArtistMetadataContextPilotError(
                    f"cohort {cohort} has fewer than 10 unique direct anchors"
                )
            selected.update(picks)
            entries.extend(
                PilotSelectionEntry(
                    cohort=cohort,
                    source_item_id=source_item_id,
                    seed_name=seed_name,
                    genre_id=genre_id,
                    artist_mbid=artist_id,
                )
                for artist_id in picks
            )
    entry_values = tuple(entries)
    entries_json = [entry.model_dump(mode="json") for entry in entry_values]
    return PilotQueryManifest(
        evidence_database_sha256=_EVIDENCE_SHA256,
        reconciliation_sha256=reconciliation_sha,
        entries=entry_values,
        manifest_sha256=_sha256(
            {
                "revision": "artist-metadata-context-pilot-query-manifest-v1",
                "evidence_database_sha256": _EVIDENCE_SHA256,
                "reconciliation_sha256": reconciliation_sha,
                "selection_policy": "direct-anchor-per-cohort-lexicographic-v1",
                "requested_count": 50,
                "entries": entries_json,
            }
        ),
    )


def _cache_path(root: Path, artist_mbid: str) -> Path:
    return root / "requests" / f"{artist_mbid}.json"


async def _load_or_fetch(
    client: MusicBrainzClient, root: Path, artist_mbid: str
) -> tuple[MusicBrainzArtist | None, CachedRequest, bool]:
    request_path = _cache_path(root, artist_mbid)
    if request_path.exists():
        cached = CachedRequest.model_validate_json(request_path.read_bytes())
        if cached.outcome == "failure":
            return None, cached, True
        if cached.raw_sha256 is None:
            raise ArtistMetadataContextPilotError("successful cache entry is missing its raw hash")
        raw_path = root / "raw" / "sha256" / cached.raw_sha256 / "artist.json"
        raw = raw_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != cached.raw_sha256:
            raise ArtistMetadataContextPilotError(
                "cached raw response hash does not match request entry"
            )
        if len(raw) != cached.raw_byte_size:
            raise ArtistMetadataContextPilotError(
                "cached raw response byte size does not match request entry"
            )
        return MusicBrainzArtist.model_validate_json(raw), cached, True
    try:
        response = await client.fetch_artist_response(UUID(artist_mbid))
    except (httpx.HTTPError, ValueError) as error:
        failed_response = error.response if isinstance(error, httpx.HTTPStatusError) else None
        status = failed_response.status_code if failed_response is not None else None
        cached = CachedRequest(
            artist_mbid=artist_mbid,
            request_url=f"https://musicbrainz.org/ws/2/artist/{artist_mbid}?fmt=json&inc=aliases%2Bgenres%2Btags",
            outcome="failure",
            failure=f"{type(error).__name__}: {error}",
            failure_type=type(error).__name__,
            http_status=status,
            retryable=isinstance(error, httpx.TimeoutException)
            or status in {429, 500, 502, 503, 504},
            retry_after=(failed_response.headers.get("Retry-After") if failed_response else None),
        )
        _atomic_write(request_path, cached.model_dump_json(indent=2).encode() + b"\n")
        return None, cached, False
    raw_sha = hashlib.sha256(response.raw_bytes).hexdigest()
    raw_path = root / "raw" / "sha256" / raw_sha / "artist.json"
    if raw_path.exists() and raw_path.read_bytes() != response.raw_bytes:
        raise ArtistMetadataContextPilotError(
            "content-addressed raw response path conflicts with bytes"
        )
    if not raw_path.exists():
        _atomic_write(raw_path, response.raw_bytes)
    cached = CachedRequest(
        artist_mbid=artist_mbid,
        request_url=response.request_url,
        received_at=response.received_at.isoformat(),
        outcome="success",
        raw_sha256=raw_sha,
        raw_byte_size=len(response.raw_bytes),
    )
    _atomic_write(request_path, cached.model_dump_json(indent=2).encode() + b"\n")
    return response.artist, cached, False


def _initialize_projection(connection: sqlite3.Connection) -> None:
    connection.executescript("""
        PRAGMA journal_mode=DELETE;
        CREATE TABLE artist_context (
            artist_mbid TEXT PRIMARY KEY, canonical_name TEXT NOT NULL, country TEXT,
            area_id TEXT, area_name TEXT, area_type TEXT,
            begin_area_id TEXT, begin_area_name TEXT, begin_area_type TEXT,
            raw_sha256 TEXT NOT NULL, request_url TEXT NOT NULL, received_at TEXT NOT NULL
        ) WITHOUT ROWID;
        CREATE TABLE artist_alias (
            artist_mbid TEXT NOT NULL, alias_name TEXT NOT NULL, locale TEXT,
            PRIMARY KEY (artist_mbid, alias_name, locale)
        ) WITHOUT ROWID;
    """)


def _write_artist(
    connection: sqlite3.Connection, artist: MusicBrainzArtist, request: CachedRequest
) -> None:
    if request.raw_sha256 is None or request.received_at is None:
        raise ArtistMetadataContextPilotError("successful projection input lacks source provenance")
    connection.execute(
        "INSERT INTO artist_context VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            str(artist.id),
            artist.name,
            artist.country,
            str(artist.area.id) if artist.area else None,
            artist.area.name if artist.area else None,
            artist.area.type if artist.area else None,
            str(artist.begin_area.id) if artist.begin_area else None,
            artist.begin_area.name if artist.begin_area else None,
            artist.begin_area.type if artist.begin_area else None,
            request.raw_sha256,
            str(request.request_url),
            request.received_at,
        ),
    )
    connection.executemany(
        "INSERT OR IGNORE INTO artist_alias VALUES (?, ?, ?)",
        ((str(artist.id), alias.name, alias.locale) for alias in artist.aliases),
    )


def _raw_manifest(root: Path, manifest: PilotQueryManifest) -> str:
    entries = [
        CachedRequest.model_validate_json(
            _cache_path(root, entry.artist_mbid).read_bytes()
        ).model_dump(mode="json")
        for entry in manifest.entries
    ]
    payload = {
        "revision": "artist-metadata-context-pilot-raw-manifest-v1",
        "query_manifest_sha256": manifest.manifest_sha256,
        "requests": entries,
    }
    _atomic_write(root / "raw-manifest.json", _canonical_json(payload) + b"\n")
    return _sha256(payload)


def run_pilot(
    inputs: PilotBuildInputs, *, progress: Callable[[str], None] | None = None
) -> PilotArtifact:
    """Acquire at most 50 cache-first artist responses and build a separate projection."""
    root = inputs.output_root
    manifest = build_query_manifest(inputs.evidence_database, inputs.reconciliation)
    manifest_path = root / "query-manifest.json"
    if (
        manifest_path.exists()
        and PilotQueryManifest.model_validate_json(manifest_path.read_bytes()) != manifest
    ):
        raise ArtistMetadataContextPilotError(
            "existing immutable query manifest differs from deterministic selection"
        )
    _atomic_write(manifest_path, manifest.model_dump_json(indent=2).encode() + b"\n")
    started = monotonic()
    results: list[tuple[MusicBrainzArtist | None, CachedRequest, bool]] = []

    async def acquire() -> None:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as http_client:
            client = MusicBrainzClient(http_client, user_agent=inputs.user_agent)
            for index, entry in enumerate(manifest.entries, start=1):
                results.append(await _load_or_fetch(client, root, entry.artist_mbid))
                if progress is not None:
                    progress(
                        f"artist metadata pilot {index}/{_PILOT_SIZE} "
                        f"elapsed_seconds={monotonic() - started:.3f}"
                    )

    asyncio.run(acquire())
    temporary = root / ".metadata.sqlite.tmp"
    temporary.unlink(missing_ok=True)
    with sqlite3.connect(temporary) as connection:
        _initialize_projection(connection)
        for artist, request, _ in results:
            if artist is not None:
                _write_artist(connection, artist, request)
        connection.commit()
    database = root / "metadata.sqlite"
    temporary.replace(database)
    raw_sha = _raw_manifest(root, manifest)
    with sqlite3.connect(database) as connection:
        (
            country_count,
            area_count,
            begin_area_count,
            aliases_count,
            aliases_artist_count,
            canonical_name_count,
        ) = connection.execute(
            "SELECT count(country), count(area_id), count(begin_area_id), "
            "(SELECT count(*) FROM artist_alias), "
            "(SELECT count(DISTINCT artist_mbid) FROM artist_alias), count(canonical_name) "
            "FROM artist_context"
        ).fetchone()
    # A request cache entry is created exactly once, immediately after its one
    # network attempt (including a bounded failure), so the cache itself is
    # the authoritative cumulative request count across resumed invocations.
    cached_request_count = sum(
        _cache_path(root, entry.artist_mbid).exists() for entry in manifest.entries
    )
    failure_counts: dict[str, int] = {}
    for artist, request, _ in results:
        if artist is not None:
            continue
        failure_kind = request.failure_type or (
            request.failure.split(":", maxsplit=1)[0] if request.failure else "unknown"
        )
        failure_counts[failure_kind] = failure_counts.get(failure_kind, 0) + 1
    artifact = PilotArtifact(
        input_manifest_sha256=manifest.manifest_sha256,
        evidence_database_sha256=_EVIDENCE_SHA256,
        raw_source_manifest_sha256=raw_sha,
        projection_database_sha256=_file_sha256(database),
        requested_count=50,
        cumulative_network_attempt_count=cached_request_count,
        network_requests_this_run=sum(not cached for _, _, cached in results),
        cache_hit_count=sum(cached for _, _, cached in results),
        success_count=sum(artist is not None for artist, _, _ in results),
        failure_count=sum(artist is None for artist, _, _ in results),
        country_count=country_count,
        area_count=area_count,
        begin_area_count=begin_area_count,
        aliases_count=aliases_count,
        aliases_artist_count=aliases_artist_count,
        canonical_name_count=canonical_name_count,
        failure_counts=dict(sorted(failure_counts.items())),
    )
    _atomic_write(root / "artifact.json", artifact.model_dump_json(indent=2).encode() + b"\n")
    report = {
        **artifact.model_dump(mode="json"),
        "elapsed_seconds": monotonic() - started,
        "interpretation": (
            "Source country and area fields are provider-qualified observations, "
            "not inferred current residence, nationality, origin, or genre claims."
        ),
    }
    _atomic_write(root / "report.json", _canonical_json(report) + b"\n")
    return artifact
