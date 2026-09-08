"""Stream MusicBrainz release-group claims into research-only artist support.

Release-group genres and tags describe a release group.  They are useful
support for a credited artist/genre relationship, but are deliberately never
represented as artist-direct facts.  The large evidence rows live in SQLite;
the small JSON artifact is a hash-bound accounting and evaluation receipt.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tarfile
from collections import OrderedDict
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import Final, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from musix.genre_seed_universe import normalize_label
from musix.models.sources import DownloadSource
from musix.musicbrainz_seed_targets import (
    MusicBrainzSeedTargetArtifact,
    verify_seed_target_artifact,
)
from musix.pipeline.source_cache import (
    SourceCacheError,
    SourceCacheReceipt,
    verify_source_cache_receipt,
)
from musix.storage import ObjectKey, ObjectStore, ObjectWrite

_REVISION: Final = "musicbrainz-release-group-artist-support-v1"
_JSON: Final = TypeAdapter(dict[str, object])
_SHA256: Final = r"^[0-9a-f]{64}$"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class MusicBrainzReleaseGroupEvidenceError(ValueError):
    """Report an unsafe dump or a broken provenance boundary."""


class ReleaseGroupEvidenceSettings(_FrozenModel):
    """Laptop-safe bounds and the anti-prolific-release weighting policy."""

    revision: Literal["musicbrainz-release-group-artist-support-settings-v1"] = (
        "musicbrainz-release-group-artist-support-settings-v1"
    )
    max_archive_bytes: int = Field(default=2 * 1024**3, gt=0)
    # The pinned 2026-09-05 release-group member expands to 18,124,249,055
    # bytes.  Twenty GiB accepts that one declared metadata member while
    # remaining a meaningful laptop-safe expansion bound.
    max_member_bytes: int = Field(default=20 * 1024**3, gt=0)
    max_archive_members: int = Field(default=8, gt=0, le=64)
    max_record_bytes: int = Field(default=2 * 1024**2, gt=0)
    max_records: int = Field(default=5_000_000, gt=0)
    max_artist_credits_per_release_group: int = Field(default=128, gt=0, le=512)
    max_genres_per_release_group: int = Field(default=128, gt=0, le=512)
    max_tags_per_release_group: int = Field(default=512, gt=0, le=2_000)
    max_release_groups_per_membership: int = Field(default=3, gt=0, le=32)
    heldout_direct_anchor_percent: int = Field(default=20, ge=1, le=80)
    checkpoint_every_records: int = Field(default=10_000, ge=100, le=100_000)
    insert_batch_rows: int = Field(default=10_000, ge=100, le=100_000)
    max_cached_memberships: int = Field(default=100_000, ge=1_000, le=1_000_000)

    @model_validator(mode="after")
    def _cache_covers_pending_batch(self) -> ReleaseGroupEvidenceSettings:
        """Keep unflushed cap counts resident until their rows reach SQLite."""
        if self.max_cached_memberships < self.insert_batch_rows:
            raise ValueError("max_cached_memberships must be at least insert_batch_rows")
        return self


class ReleaseGroupEvidenceCounters(_FrozenModel):
    archive_member_count: int = Field(ge=0)
    records_seen: int = Field(ge=0)
    records_parsed: int = Field(ge=0)
    records_over_limit: int = Field(ge=0)
    malformed_records: int = Field(ge=0)
    malformed_claims: int = Field(ge=0)
    release_groups_with_matched_claims: int = Field(ge=0)
    raw_support_rows: int = Field(ge=0)
    capped_support_rows: int = Field(ge=0)


class ReleaseGroupEvidenceCoverage(_FrozenModel):
    seed_count: int = Field(ge=1)
    direct_anchor_genre_count: int = Field(ge=0)
    direct_anchor_membership_count: int = Field(ge=0)
    support_genre_count: int = Field(ge=0)
    support_membership_count: int = Field(ge=0)
    new_support_genre_count: int = Field(ge=0)
    new_support_membership_count: int = Field(ge=0)
    direct_anchor_recovered_count: int = Field(ge=0)
    heldout_direct_anchor_count: int = Field(ge=0)
    heldout_direct_anchor_recovered_count: int = Field(ge=0)
    heldout_direct_anchor_recovery: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _bounded(self) -> ReleaseGroupEvidenceCoverage:
        if self.direct_anchor_recovered_count > self.direct_anchor_membership_count:
            raise ValueError("recovered direct anchors exceed the direct anchor set")
        if self.heldout_direct_anchor_recovered_count > self.heldout_direct_anchor_count:
            raise ValueError("heldout recovery exceeds heldout anchors")
        if self.new_support_genre_count > self.support_genre_count:
            raise ValueError("new support genres exceed support genres")
        if self.new_support_membership_count > self.support_membership_count:
            raise ValueError("new support memberships exceed support memberships")
        return self


class ReleaseGroupEvidenceArtifact(_FrozenModel):
    """Small, immutable receipt for a separately stored evidence SQLite database."""

    revision: Literal["musicbrainz-release-group-artist-support-v1"] = _REVISION
    source_id: str = Field(min_length=1)
    source_snapshot: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    source_archive_sha256: str = Field(pattern=_SHA256)
    source_archive_bytes: int = Field(gt=0)
    source_member_name: Literal["mbdump/release-group"] = "mbdump/release-group"
    source_member_bytes: int = Field(gt=0)
    source_cache_receipt_sha256: str = Field(pattern=_SHA256)
    seed_target_output_sha256: str = Field(pattern=_SHA256)
    settings: ReleaseGroupEvidenceSettings
    evidence_database_sha256: str = Field(pattern=_SHA256)
    evidence_database_bytes: int = Field(gt=0)
    counters: ReleaseGroupEvidenceCounters
    coverage: ReleaseGroupEvidenceCoverage
    output_sha256: str = Field(pattern=_SHA256)


class ReleaseGroupEvidencePublicationReceipt(_FrozenModel):
    artifact: ObjectWrite
    evidence_database: ObjectWrite
    logical_output_sha256: str = Field(pattern=_SHA256)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode()


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_sha(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def artifact_sha256(artifact: ReleaseGroupEvidenceArtifact) -> str:
    return _sha(artifact.model_dump(mode="json", exclude={"output_sha256"}))


def verify_release_group_evidence(artifact: ReleaseGroupEvidenceArtifact) -> None:
    """Fail closed if the receipt or its SQLite payload was altered."""
    if artifact_sha256(artifact) != artifact.output_sha256:
        raise MusicBrainzReleaseGroupEvidenceError("release-group evidence hash does not replay")


def _source_cache_hash(
    receipt: SourceCacheReceipt, source: DownloadSource, manifest_sha256: str
) -> str:
    """Verify the receipt against the current manifest before accepting its object."""
    try:
        verify_source_cache_receipt(receipt, (source,), declared_manifest_sha256=manifest_sha256)
    except SourceCacheError as error:
        raise MusicBrainzReleaseGroupEvidenceError(str(error)) from error
    matches = tuple(entry for entry in receipt.entries if entry.source_id == source.id)
    if len(matches) != 1:
        raise MusicBrainzReleaseGroupEvidenceError(
            "source cache receipt does not contain the source"
        )
    entry = matches[0]
    if entry.sha256 != source.verified_sha256() or entry.expected_bytes != source.expected_bytes:
        raise MusicBrainzReleaseGroupEvidenceError(
            "source cache receipt does not match pinned source"
        )
    return _sha(receipt.model_dump(mode="json"))


def _safe_member(name: str) -> PurePosixPath | None:
    path = PurePosixPath(name)
    return None if path.is_absolute() or ".." in path.parts else path


class _LineReader(Protocol):
    """Describe the sole operation needed to stream JSONL archive members."""

    def readline(self, size: int = -1, /) -> bytes: ...


def _lines(reader: _LineReader, maximum: int) -> Iterator[bytes | None]:
    while True:
        line = reader.readline(maximum + 1)
        if not isinstance(line, bytes) or not line:
            return
        if len(line) > maximum and not line.endswith(b"\n"):
            while line and not line.endswith(b"\n"):
                line = reader.readline(64 * 1024)
            yield None
            continue
        payload = line.rstrip(b"\r\n")
        if payload:
            yield payload


def _tag_name(raw: object) -> str | None:
    try:
        value = _JSON.validate_python(raw)
    except ValueError:
        return None
    name = value.get("name")
    count = value.get("count")
    if not isinstance(name, str) or not name.strip():
        return None
    if isinstance(count, bool) or (
        count is not None and (not isinstance(count, int) or count <= 0)
    ):
        return None
    return name.strip()


def _genre_name(raw: object) -> str | None:
    try:
        value = _JSON.validate_python(raw)
    except ValueError:
        return None
    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    raw_id = value.get("id")
    if not isinstance(raw_id, str):
        return None
    try:
        UUID(raw_id)
    except ValueError:
        return None
    return name.strip()


def _matched_seed_ids(
    value: str, exact: dict[str, tuple[str, ...]], normalized: dict[str, tuple[str, ...]]
) -> tuple[str, ...]:
    return exact.get(value, normalized.get(normalize_label(value), ()))


def _init_database(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE direct_anchor (
            genre_id TEXT NOT NULL, artist_id TEXT NOT NULL, facet TEXT NOT NULL,
            evidence_ref TEXT NOT NULL, PRIMARY KEY (genre_id, artist_id, facet, evidence_ref)
        ) WITHOUT ROWID;
        CREATE TABLE release_group_support (
            genre_id TEXT NOT NULL, artist_id TEXT NOT NULL, facet TEXT NOT NULL,
            release_group_id TEXT NOT NULL, evidence_ref TEXT NOT NULL,
            PRIMARY KEY (genre_id, artist_id, facet, release_group_id)
        ) WITHOUT ROWID;
        CREATE TABLE typed_evidence (
            evidence_kind TEXT NOT NULL CHECK (evidence_kind IN ('artist_direct', 'release_group_support')),
            genre_id TEXT NOT NULL, artist_id TEXT NOT NULL, facet TEXT NOT NULL,
            release_group_id TEXT, evidence_ref TEXT NOT NULL, weight REAL NOT NULL CHECK (weight > 0),
            CHECK ((evidence_kind = 'artist_direct' AND release_group_id IS NULL)
                OR (evidence_kind = 'release_group_support' AND release_group_id IS NOT NULL))
        );
        CREATE TABLE build_checkpoint (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            records_seen INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )


def _insert_direct_anchors(
    connection: sqlite3.Connection, seed_target: MusicBrainzSeedTargetArtifact
) -> None:
    rows = []
    for row in seed_target.evidence:
        facet = "musicbrainz_genre" if row.facet == "genre" else "musicbrainz_tag"
        rows.append((row.seed_source_item_id, row.artist_id, facet, row.evidence_ref))
        if len(rows) >= 10_000:
            connection.executemany("INSERT OR IGNORE INTO direct_anchor VALUES (?, ?, ?, ?)", rows)
            rows.clear()
    if rows:
        connection.executemany("INSERT OR IGNORE INTO direct_anchor VALUES (?, ?, ?, ?)", rows)
    connection.execute(
        "INSERT INTO typed_evidence SELECT 'artist_direct', genre_id, artist_id, facet, NULL, evidence_ref, 1.0 FROM direct_anchor"
    )


def _coverage(
    connection: sqlite3.Connection, seed_count: int, settings: ReleaseGroupEvidenceSettings
) -> ReleaseGroupEvidenceCoverage:
    direct_genres, direct_memberships = connection.execute(
        "SELECT count(DISTINCT genre_id), count(DISTINCT genre_id || char(0) || artist_id) FROM direct_anchor"
    ).fetchone()
    support_genres, support_memberships = connection.execute(
        "SELECT count(DISTINCT genre_id), count(DISTINCT genre_id || char(0) || artist_id) FROM release_group_support"
    ).fetchone()
    new_genres = connection.execute(
        "SELECT count(*) FROM (SELECT DISTINCT genre_id FROM release_group_support EXCEPT SELECT DISTINCT genre_id FROM direct_anchor)"
    ).fetchone()[0]
    new_memberships = connection.execute(
        """SELECT count(*) FROM (SELECT DISTINCT genre_id, artist_id FROM release_group_support
             EXCEPT SELECT DISTINCT genre_id, artist_id FROM direct_anchor)"""
    ).fetchone()[0]
    recovered = connection.execute(
        """SELECT count(*) FROM (SELECT DISTINCT genre_id, artist_id FROM direct_anchor
             INTERSECT SELECT DISTINCT genre_id, artist_id FROM release_group_support)"""
    ).fetchone()[0]
    heldout = connection.execute(
        "SELECT genre_id, artist_id FROM (SELECT DISTINCT genre_id, artist_id FROM direct_anchor)"
    ).fetchall()
    heldout_keys = {
        (str(row[0]), str(row[1]))
        for row in heldout
        if int(hashlib.sha256(f"{row[0]}\0{row[1]}".encode()).hexdigest()[:8], 16) % 100
        < settings.heldout_direct_anchor_percent
    }
    recovered_keys = {
        (str(row[0]), str(row[1]))
        for row in connection.execute(
            "SELECT DISTINCT genre_id, artist_id FROM release_group_support"
        )
    }
    heldout_recovered = len(heldout_keys & recovered_keys)
    return ReleaseGroupEvidenceCoverage(
        seed_count=seed_count,
        direct_anchor_genre_count=int(direct_genres),
        direct_anchor_membership_count=int(direct_memberships),
        support_genre_count=int(support_genres),
        support_membership_count=int(support_memberships),
        new_support_genre_count=int(new_genres),
        new_support_membership_count=int(new_memberships),
        direct_anchor_recovered_count=int(recovered),
        heldout_direct_anchor_count=len(heldout_keys),
        heldout_direct_anchor_recovered_count=heldout_recovered,
        heldout_direct_anchor_recovery=(
            heldout_recovered / len(heldout_keys) if heldout_keys else 0.0
        ),
    )


def build_release_group_evidence(  # noqa: C901, PLR0912, PLR0915
    archive_path: Path,
    seed_target: MusicBrainzSeedTargetArtifact,
    source: DownloadSource,
    source_cache_receipt: SourceCacheReceipt,
    manifest_sha256: str,
    database_path: Path,
    settings: ReleaseGroupEvidenceSettings | None = None,
) -> ReleaseGroupEvidenceArtifact:
    """Stream one pinned release-group dump into typed direct/support SQLite evidence."""
    resolved = settings or ReleaseGroupEvidenceSettings()
    verify_seed_target_artifact(seed_target)
    if source.adapter != "musicbrainz_release_group_json_dump_v1":
        raise MusicBrainzReleaseGroupEvidenceError("source is not a release-group JSON dump")
    receipt_sha = _source_cache_hash(source_cache_receipt, source, manifest_sha256)
    archive_sha, archive_bytes = _file_sha(archive_path)
    if archive_sha != source.verified_sha256() or archive_bytes != source.expected_bytes:
        raise MusicBrainzReleaseGroupEvidenceError("archive bytes do not match the pinned source")
    if archive_bytes > resolved.max_archive_bytes:
        raise MusicBrainzReleaseGroupEvidenceError("archive exceeds max_archive_bytes")
    exact: dict[str, list[str]] = {}
    normalized: dict[str, list[str]] = {}
    for row in seed_target.coverage:
        exact.setdefault(row.seed_name, []).append(row.seed_source_item_id)
        normalized.setdefault(row.normalized_name, []).append(row.seed_source_item_id)
    exact_ids = {key: tuple(sorted(value)) for key, value in exact.items()}
    normalized_ids = {key: tuple(sorted(value)) for key, value in normalized.items()}
    database_path.parent.mkdir(parents=True, exist_ok=True)
    final_database_path = database_path
    database_path = final_database_path.with_suffix(f"{final_database_path.suffix}.partial")
    if database_path.exists():
        raise MusicBrainzReleaseGroupEvidenceError(
            f"interrupted staging database retained at {database_path}; inspect or resume it explicitly"
        )
    counters = dict.fromkeys(ReleaseGroupEvidenceCounters.model_fields, 0)
    member_bytes = 0
    with sqlite3.connect(database_path) as connection, archive_path.open("rb") as input_stream:
        # A durable rollback journal makes every checkpoint a valid SQLite state if
        # the process is stopped.  The final name is only replaced after the full
        # database has passed integrity validation below.
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=FULL")
        _init_database(connection)
        _insert_direct_anchors(connection, seed_target)
        connection.execute("INSERT INTO build_checkpoint VALUES (1, 0, datetime('now'))")
        connection.commit()
        membership_counts: OrderedDict[tuple[str, str, str], int] = OrderedDict()
        pending_rows: list[tuple[str, str, str, str, str]] = []

        def flush_support_rows() -> None:
            if pending_rows:
                connection.executemany(
                    "INSERT OR IGNORE INTO release_group_support VALUES (?, ?, ?, ?, ?)",
                    pending_rows,
                )
                pending_rows.clear()

        def accepted_count(key: tuple[str, str, str]) -> int:
            cached = membership_counts.get(key)
            if cached is not None:
                membership_counts.move_to_end(key)
                return cached
            count = int(
                connection.execute(
                    "SELECT count(*) FROM release_group_support "
                    "WHERE genre_id = ? AND artist_id = ? AND facet = ?",
                    key,
                ).fetchone()[0]
            )
            membership_counts[key] = count
            if len(membership_counts) > resolved.max_cached_memberships:
                membership_counts.popitem(last=False)
            return count

        found = False
        with tarfile.open(fileobj=input_stream, mode="r|xz") as archive:
            for member in archive:
                counters["archive_member_count"] += 1
                if counters["archive_member_count"] > resolved.max_archive_members:
                    raise MusicBrainzReleaseGroupEvidenceError(
                        "archive exceeds max_archive_members"
                    )
                safe = _safe_member(member.name)
                if safe is None or not member.isfile() or member.size > resolved.max_member_bytes:
                    continue
                if safe != PurePosixPath("mbdump/release-group"):
                    continue
                if found:
                    raise MusicBrainzReleaseGroupEvidenceError(
                        "archive repeats mbdump/release-group"
                    )
                found = True
                member_bytes = member.size
                stream = archive.extractfile(member)
                if stream is None:
                    raise MusicBrainzReleaseGroupEvidenceError(
                        "release-group member cannot be read"
                    )
                for payload in _lines(stream, resolved.max_record_bytes):
                    counters["records_seen"] += 1
                    if counters["records_seen"] > resolved.max_records:
                        raise MusicBrainzReleaseGroupEvidenceError("archive exceeds max_records")
                    if payload is None:
                        counters["records_over_limit"] += 1
                        continue
                    try:
                        raw = _JSON.validate_json(payload)
                        group_id = str(UUID(str(raw["id"])))
                        credits = raw.get("artist-credit", [])
                        genres = raw.get("genres", [])
                        tags = raw.get("tags", [])
                        if (
                            not isinstance(credits, list)
                            or not isinstance(genres, list)
                            or not isinstance(tags, list)
                        ):
                            raise ValueError
                        if (
                            len(credits) > resolved.max_artist_credits_per_release_group
                            or len(genres) > resolved.max_genres_per_release_group
                            or len(tags) > resolved.max_tags_per_release_group
                        ):
                            raise ValueError
                        artist_ids = tuple(
                            sorted(
                                {
                                    str(UUID(str(item["artist"]["id"])))
                                    for item in credits
                                    if isinstance(item, dict)
                                    and isinstance(item.get("artist"), dict)
                                }
                            )
                        )
                    except (KeyError, TypeError, ValueError):
                        counters["malformed_records"] += 1
                        continue
                    counters["records_parsed"] += 1
                    claims: set[tuple[str, str]] = set()
                    for raw_genre in genres:
                        name = _genre_name(raw_genre)
                        if name is None:
                            counters["malformed_claims"] += 1
                            continue
                        claims.update(
                            (seed, "musicbrainz_genre")
                            for seed in _matched_seed_ids(name, exact_ids, normalized_ids)
                        )
                    for raw_tag in tags:
                        name = _tag_name(raw_tag)
                        if name is None:
                            counters["malformed_claims"] += 1
                            continue
                        claims.update(
                            (seed, "musicbrainz_tag")
                            for seed in _matched_seed_ids(name, exact_ids, normalized_ids)
                        )
                    if claims and artist_ids:
                        counters["release_groups_with_matched_claims"] += 1
                    rows = [
                        (
                            seed,
                            artist,
                            facet,
                            group_id,
                            f"musicbrainz:release-group:{archive_sha}:{group_id}:{facet}:{seed}",
                        )
                        for seed, facet in sorted(claims)
                        for artist in artist_ids
                    ]
                    counters["raw_support_rows"] += len(rows)
                    for row in rows:
                        key = row[:3]
                        count = accepted_count(key)
                        if count >= resolved.max_release_groups_per_membership:
                            continue
                        membership_counts[key] = count + 1
                        pending_rows.append(row)
                        if len(pending_rows) >= resolved.insert_batch_rows:
                            flush_support_rows()
                    if counters["records_seen"] % resolved.checkpoint_every_records == 0:
                        flush_support_rows()
                        connection.execute(
                            "UPDATE build_checkpoint SET records_seen = ?, updated_at = datetime('now') "
                            "WHERE singleton = 1",
                            (counters["records_seen"],),
                        )
                        connection.commit()
        if not found:
            raise MusicBrainzReleaseGroupEvidenceError("archive has no mbdump/release-group member")
        flush_support_rows()
        counters["capped_support_rows"] = connection.execute(
            "SELECT count(*) FROM release_group_support"
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO typed_evidence SELECT 'release_group_support', genre_id, artist_id, facet, release_group_id, evidence_ref, 1.0 FROM release_group_support"
        )
        coverage = _coverage(connection, seed_target.seed_count, resolved)
        connection.execute("DROP TABLE build_checkpoint")
        connection.commit()
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise MusicBrainzReleaseGroupEvidenceError("staging database failed integrity check")
    database_path.replace(final_database_path)
    database_path = final_database_path
    database_sha, database_bytes = _file_sha(database_path)
    preliminary = ReleaseGroupEvidenceArtifact(
        source_id=source.id,
        source_snapshot=source.snapshot,
        source_url=str(source.url),
        source_archive_sha256=archive_sha,
        source_archive_bytes=archive_bytes,
        source_member_bytes=member_bytes,
        source_cache_receipt_sha256=receipt_sha,
        seed_target_output_sha256=seed_target.output_sha256,
        settings=resolved,
        evidence_database_sha256=database_sha,
        evidence_database_bytes=database_bytes,
        counters=ReleaseGroupEvidenceCounters(**counters),
        coverage=coverage,
        output_sha256="0" * 64,
    )
    artifact = preliminary.model_copy(update={"output_sha256": artifact_sha256(preliminary)})
    verify_release_group_evidence(artifact)
    return artifact


def publish_release_group_evidence(
    artifact: ReleaseGroupEvidenceArtifact,
    *,
    database_path: Path,
    output_path: Path,
    store: ObjectStore,
) -> ReleaseGroupEvidencePublicationReceipt:
    """Write and content-address both the compact receipt and typed SQLite evidence."""
    verify_release_group_evidence(artifact)
    database_sha, database_bytes = _file_sha(database_path)
    if (database_sha, database_bytes) != (
        artifact.evidence_database_sha256,
        artifact.evidence_database_bytes,
    ):
        raise MusicBrainzReleaseGroupEvidenceError(
            "evidence database differs from artifact receipt"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(_canonical(artifact.model_dump(mode="json")) + b"\n")
    artifact_write = store.push(
        output_path,
        ObjectKey(value=f"musicbrainz-release-group-evidence/sha256/{artifact.output_sha256}.json"),
    )
    database_write = store.push(
        database_path,
        ObjectKey(value=f"musicbrainz-release-group-evidence/sha256/{database_sha}.sqlite"),
    )
    return ReleaseGroupEvidencePublicationReceipt(
        artifact=artifact_write,
        evidence_database=database_write,
        logical_output_sha256=artifact.output_sha256,
    )
