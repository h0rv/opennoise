"""Offline, review-only evidence from the MSD Last.fm SQLite companion set.

The Million Song Dataset Last.fm release is *track*-tag and track-similarity
data.  This module deliberately does not reinterpret it as an artist genre
oracle: an exact tag on a track is retained as support for the MBID carried by
the separate MSD metadata database.  Missing MBIDs are review rows, and an
artist with exact support for more than one target is a conflict, not a winner.
"""
# The only SQL interpolation below emits a generated count of ``?`` markers;
# all values remain bound parameters. Ruff cannot infer that constrained form.
# ruff: noqa: S608

from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opennoise.storage import ObjectKey, ObjectStore, ObjectWrite
from opennoise.taxonomy.seeds.reconciliation import SeedReconciliationArtifact
from opennoise.taxonomy.seeds.universe import normalize_label

_SHA256: Final = r"^[0-9a-f]{64}$"
_MAX_TARGETS: Final = 6_291
_MAX_SERIALIZED_SIMILARITY_BYTES: Final = 1_048_576
_SIMILARITY_PAIR_SIZE: Final = 2
_MSD_URLS: Final = {
    "track_metadata": "https://millionsongdataset.com/sites/default/files/AdditionalFiles/track_metadata.db",
    "lastfm_tags": "https://millionsongdataset.com/sites/default/files/lastfm/lastfm_tags.db",
    "lastfm_similarity": "https://millionsongdataset.com/sites/default/files/lastfm/lastfm_similars.db",
}


class MsdLastFmError(RuntimeError):
    """Report a rejected source cache, SQLite schema, or evidence artifact."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _file_sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1_048_576):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class MsdLastFmSourceFile(_StrictModel):
    """One immutable but manually supplied local SQLite input.

    A URL documents the intended MSD counterpart only.  It is not an
    acquisition record and must never upgrade the supplied bytes to official
    or verified provenance.
    """

    role: Literal["track_metadata", "lastfm_tags", "lastfm_similarity"]
    original_url: str = Field(pattern=r"^https://")
    sha256: str = Field(pattern=_SHA256)
    byte_size: int = Field(gt=0)
    acquired_at: datetime
    cache_path: str = Field(min_length=1)
    provenance: Literal["unverified_local_input"] = "unverified_local_input"
    acquisition_attested: Literal[False] = False
    content_kind: Literal["sqlite_metadata"] = "sqlite_metadata"
    audio_included: Literal[False] = False


class MsdLastFmSourceCache(_StrictModel):
    """Content-addressed local custody for three unverified local inputs."""

    revision: Literal["msd-lastfm-source-cache-v1"] = "msd-lastfm-source-cache-v1"
    source_reference_docs: tuple[str, str] = (
        "https://millionsongdataset.com/pages/tasks-demos",
        "https://millionsongdataset.com/faq",
    )
    files: tuple[MsdLastFmSourceFile, ...] = Field(min_length=3, max_length=3)
    output_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _complete(self) -> MsdLastFmSourceCache:
        if {item.role for item in self.files} != set(_MSD_URLS):
            raise ValueError("MSD cache must contain metadata, tags, and similarity SQLite files")
        if any(item.original_url != _MSD_URLS[item.role] for item in self.files):
            raise ValueError("MSD cache file does not use its official metadata-only URL")
        expected = _sha256(self.model_dump(mode="json", exclude={"output_sha256"}))
        if self.output_sha256 != expected:
            raise ValueError("MSD source cache hash does not match its content")
        return self


def cache_msd_lastfm_sqlite_files(
    *,
    metadata_db: Path,
    tags_db: Path,
    similarity_db: Path,
    cache_root: Path,
    acquired_at: datetime | None = None,
) -> MsdLastFmSourceCache:
    """Copy only supplied SQLite metadata into immutable SHA-256 cache paths.

    Downloading is intentionally separate: callers can only pass the three
    SQLite files, never a dataset directory that might contain audio HDF5.
    """
    when = acquired_at or datetime.now(UTC)
    inputs: tuple[
        tuple[Literal["track_metadata", "lastfm_tags", "lastfm_similarity"], Path], ...
    ] = (
        ("track_metadata", metadata_db),
        ("lastfm_tags", tags_db),
        ("lastfm_similarity", similarity_db),
    )
    files: list[MsdLastFmSourceFile] = []
    for role, source in inputs:
        if not source.is_file():
            raise FileNotFoundError(source)
        digest, size = _file_sha256(source)
        destination = cache_root / "raw" / "sha256" / digest / f"{role}.sqlite"
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(".partial")
            try:
                shutil.copyfile(source, temporary)
                if _file_sha256(temporary) != (digest, size):
                    raise MsdLastFmError("source changed while being cached")
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
        if _file_sha256(destination) != (digest, size):
            raise MsdLastFmError("existing MSD source cache object is corrupt")
        files.append(
            MsdLastFmSourceFile(
                role=role,
                original_url=_MSD_URLS[role],
                sha256=digest,
                byte_size=size,
                acquired_at=when,
                cache_path=str(destination),
            )
        )
    preliminary = MsdLastFmSourceCache.model_construct(files=tuple(files), output_sha256="0" * 64)
    cache = MsdLastFmSourceCache(
        **preliminary.model_dump(mode="python", exclude={"output_sha256"}),
        output_sha256=_sha256(preliminary.model_dump(mode="json", exclude={"output_sha256"})),
    )
    _atomic_write(
        cache_root / "receipts" / "sha256" / f"{cache.output_sha256}.json",
        (cache.model_dump_json(indent=2) + "\n").encode(),
    )
    return cache


def load_msd_lastfm_source_cache(path: Path) -> MsdLastFmSourceCache:
    """Load and rehash a cache receipt before any SQLite data is opened."""
    cache = MsdLastFmSourceCache.model_validate_json(path.read_bytes())
    for item in cache.files:
        cached = Path(item.cache_path)
        if _file_sha256(cached) != (item.sha256, item.byte_size):
            raise MsdLastFmError(f"cached {item.role} file does not match its receipt")
    return cache


class MsdLastFmTarget(_StrictModel):
    """One stable target vocabulary row; no spatial or historical values are accepted."""

    target_id: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=500)
    normalized_label: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _normalized(self) -> MsdLastFmTarget:
        if self.normalized_label != normalize_label(self.label):
            raise ValueError("target normalized label does not match label")
        return self


def targets_from_seed_reconciliation(path: Path) -> tuple[MsdLastFmTarget, ...]:
    """Project all 6,291 source IDs/names, without reading coordinates or H3."""
    artifact = SeedReconciliationArtifact.model_validate_json(path.read_bytes())
    targets = tuple(
        MsdLastFmTarget(
            target_id=row.source_item_id, label=row.seed_name, normalized_label=row.normalized_name
        )
        for row in artifact.dispositions
    )
    if len(targets) != _MAX_TARGETS:
        raise MsdLastFmError(f"expected 6,291 targets, found {len(targets)}")
    if len({target.target_id for target in targets}) != len(targets):
        raise MsdLastFmError("target IDs must be unique")
    return targets


class ArtistTagSupport(_StrictModel):
    """Exact Last.fm tag evidence on one MSD track, linked only through an MBID."""

    target_id: str
    target_label: str
    source_tag: str
    track_id: str
    artist_mbid: UUID
    artist_name: str
    source_weight: int = Field(ge=0)
    evidence_kind: Literal["exact_track_tag_support"] = "exact_track_tag_support"
    artist_relation: Literal["metadata_mbid_linked_track_support"] = (
        "metadata_mbid_linked_track_support"
    )


class NameOnlyTagReview(_StrictModel):
    """An exact source tag whose metadata artist cannot be MBID-linked."""

    target_id: str
    target_label: str
    source_tag: str
    track_id: str
    artist_name: str
    source_weight: int = Field(ge=0)
    reason: Literal["missing_or_invalid_metadata_artist_mbid"] = (
        "missing_or_invalid_metadata_artist_mbid"
    )


class ArtistSimilaritySupport(_StrictModel):
    """One directed Last.fm track-similarity relation with both artist MBIDs."""

    source_track_id: str
    target_track_id: str
    source_artist_mbid: UUID
    target_artist_mbid: UUID
    score: float = Field(ge=0.0, le=1.0)
    rank: int = Field(ge=1)
    evidence_kind: Literal["directed_track_similarity_support"] = (
        "directed_track_similarity_support"
    )


class ArtistTargetConflict(_StrictModel):
    """Retain a multi-target exact-tag conflict without selecting a label."""

    artist_mbid: UUID
    target_ids: tuple[str, ...] = Field(min_length=2)
    reason: Literal["multiple_exact_target_tags"] = "multiple_exact_target_tags"


class TargetAbstention(_StrictModel):
    """Record a target with no exact MBID-linked track tag in this source."""

    target_id: str
    target_label: str
    reason: Literal["no_exact_mbid_linked_track_tag"] = "no_exact_mbid_linked_track_tag"


class IncrementalCoverage(_StrictModel):
    """Cumulative artist and target coverage at a deterministic support prefix."""

    fraction: Literal[25, 50, 75, 100]
    processed_support_count: int = Field(ge=0)
    artist_count: int = Field(ge=0)
    target_count: int = Field(ge=0)


class HeldOutAnchorRecovery(_StrictModel):
    """Recovery of deterministically held-out track anchors through other tracks."""

    held_out_track_anchor_count: int = Field(ge=0)
    recovered_by_different_track_count: int = Field(ge=0)
    recall: float = Field(ge=0.0, le=1.0)
    split: Literal["sha256_track_id_mod_5_equals_0"] = "sha256_track_id_mod_5_equals_0"


class MsdLastFmCoverage(_StrictModel):
    """Counts, coverage prefixes, and the non-semantic source recovery metric."""

    target_count: int = Field(ge=0, le=_MAX_TARGETS)
    exact_mbid_track_tag_support_count: int = Field(ge=0)
    name_only_review_count: int = Field(ge=0)
    similarity_support_count: int = Field(ge=0)
    conflict_count: int = Field(ge=0)
    abstention_count: int = Field(ge=0)
    incremental: tuple[IncrementalCoverage, ...] = Field(min_length=4, max_length=4)
    held_out_anchor_recovery: HeldOutAnchorRecovery


class MsdLastFmEvidenceArtifact(_StrictModel):
    """Immutable review evidence; it is intentionally not a promoted membership model."""

    revision: Literal["msd-lastfm-evidence-v1"] = "msd-lastfm-evidence-v1"
    source_cache_sha256: str = Field(pattern=_SHA256)
    source_provenance: Literal["unverified_local_input"] = "unverified_local_input"
    target_identity_sha256: str = Field(pattern=_SHA256)
    historical_inputs_read: Literal[False] = False
    audio_inputs_read: Literal[False] = False
    spotify_inputs_read: Literal[False] = False
    tag_supports: tuple[ArtistTagSupport, ...]
    name_only_reviews: tuple[NameOnlyTagReview, ...]
    similarity_supports: tuple[ArtistSimilaritySupport, ...]
    conflicts: tuple[ArtistTargetConflict, ...]
    abstentions: tuple[TargetAbstention, ...]
    coverage: MsdLastFmCoverage
    output_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _complete(self) -> MsdLastFmEvidenceArtifact:
        if self.coverage.target_count != len(self.abstentions) + len(
            {item.target_id for item in self.tag_supports}
        ):
            raise ValueError("target coverage must partition mapped and abstained targets")
        if self.coverage.exact_mbid_track_tag_support_count != len(self.tag_supports):
            raise ValueError("tag support coverage does not match rows")
        if self.coverage.name_only_review_count != len(self.name_only_reviews):
            raise ValueError("review coverage does not match rows")
        if self.coverage.similarity_support_count != len(self.similarity_supports):
            raise ValueError("similarity coverage does not match rows")
        expected = _sha256(self.model_dump(mode="json", exclude={"output_sha256"}))
        if self.output_sha256 != expected:
            raise ValueError("MSD evidence artifact hash does not match content")
        return self


class MsdLastFmEvidenceReceipt(_StrictModel):
    """Object-store custody for the artifact and its compact source-cache receipt."""

    artifact: ObjectWrite
    source_cache_receipt: ObjectWrite
    logical_output_sha256: str = Field(pattern=_SHA256)
    no_audio_or_historical_inputs: Literal[True] = True


def _readonly_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _valid_mbid(value: object) -> UUID | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _parse_similarity(value: object) -> tuple[tuple[str, float], ...]:
    """Parse MSD's serialized target list without executing source-provided code."""
    if not isinstance(value, (str, bytes)):
        return ()
    raw = value.decode("utf-8", "replace") if isinstance(value, bytes) else value
    if len(raw.encode("utf-8")) > _MAX_SERIALIZED_SIMILARITY_BYTES:
        return ()
    try:
        loaded: object = json.loads(raw)
    except json.JSONDecodeError:
        try:
            loaded = ast.literal_eval(raw)
        except (MemoryError, RecursionError, SyntaxError, ValueError):
            return ()
    if not isinstance(loaded, (list, tuple)):
        return ()
    pairs: list[tuple[str, float]] = []
    for item in loaded:
        if (
            not isinstance(item, (list, tuple))
            or len(item) != _SIMILARITY_PAIR_SIZE
            or not isinstance(item[0], str)
        ):
            continue
        if isinstance(item[1], (int, float)) and 0.0 <= float(item[1]) <= 1.0:
            pairs.append((item[0], float(item[1])))
    return tuple(pairs)


@dataclass(frozen=True, slots=True)
class _ArtistIdentity:
    mbid: UUID | None
    name: str


class _BoundedArtistLookup:
    def __init__(self, metadata_db: Path, *, capacity: int = 50_000) -> None:
        self._connection = _readonly_connection(metadata_db)
        self._capacity = capacity
        self._cache: OrderedDict[str, _ArtistIdentity | None] = OrderedDict()

    def get(self, track_id: str) -> _ArtistIdentity | None:
        found = self._cache.get(track_id)
        if track_id in self._cache:
            self._cache.move_to_end(track_id)
            return found
        row = self._connection.execute(
            "SELECT artist_mbid, artist_name FROM songs WHERE track_id = ? LIMIT 1", (track_id,)
        ).fetchone()
        value = (
            None
            if row is None
            else _ArtistIdentity(_valid_mbid(row["artist_mbid"]), str(row["artist_name"] or ""))
        )
        self._cache[track_id] = value
        if len(self._cache) > self._capacity:
            self._cache.popitem(last=False)
        return value

    def close(self) -> None:
        self._connection.close()


def _cache_paths(cache: MsdLastFmSourceCache) -> dict[str, Path]:
    return {item.role: Path(item.cache_path) for item in cache.files}


def _held_out_recovery(supports: tuple[ArtistTagSupport, ...]) -> HeldOutAnchorRecovery:
    groups: dict[tuple[UUID, str], set[str]] = defaultdict(set)
    for item in supports:
        groups[(item.artist_mbid, item.target_id)].add(item.track_id)
    held = recovered = 0
    for (artist, target), tracks in groups.items():
        for track in tracks:
            key = f"{artist}:{target}:{track}".encode()
            if hashlib.sha256(key).digest()[0] % 5 == 0:
                held += 1
                if len(tracks) > 1:
                    recovered += 1
    return HeldOutAnchorRecovery(
        held_out_track_anchor_count=held,
        recovered_by_different_track_count=recovered,
        recall=0.0 if held == 0 else recovered / held,
    )


def _incremental_coverage(
    supports: tuple[ArtistTagSupport, ...],
) -> tuple[IncrementalCoverage, ...]:
    ordered = sorted(
        supports, key=lambda item: (item.track_id, item.target_id, str(item.artist_mbid))
    )
    result: list[IncrementalCoverage] = []
    for fraction in (25, 50, 75, 100):
        count = (len(ordered) * fraction + 99) // 100
        prefix = ordered[:count]
        result.append(
            IncrementalCoverage(
                fraction=fraction,
                processed_support_count=len(prefix),
                artist_count=len({item.artist_mbid for item in prefix}),
                target_count=len({item.target_id for item in prefix}),
            )
        )
    return tuple(result)


def build_msd_lastfm_evidence(  # noqa: C901, PLR0912, PLR0913, PLR0915 -- bounded streaming paths.
    source_cache: MsdLastFmSourceCache,
    targets: tuple[MsdLastFmTarget, ...],
    *,
    maximum_similarity_rows: int = 200_000,
    maximum_similarity_edges: int = 1_000_000,
    maximum_tag_rows: int = 2_000_000,
    maximum_tag_supports: int = 2_000_000,
    maximum_name_only_reviews: int = 2_000_000,
) -> MsdLastFmEvidenceArtifact:
    """Stream supported exact tags and directed similarity; never infer by artist name."""
    if maximum_tag_rows <= 0 or maximum_tag_supports <= 0 or maximum_name_only_reviews <= 0:
        raise MsdLastFmError("tag row and output caps must be positive")
    if len(targets) > _MAX_TARGETS or len({item.target_id for item in targets}) != len(targets):
        raise MsdLastFmError("targets must have unique IDs and contain at most 6,291 rows")
    paths = _cache_paths(source_cache)
    target_by_normalized = {item.normalized_label: item for item in targets}
    supports: list[ArtistTagSupport] = []
    reviews: list[NameOnlyTagReview] = []
    seen_supports: set[tuple[str, str, str, UUID]] = set()
    seen_reviews: set[tuple[str, str, str]] = set()
    tag_row_count = 0
    lookup = _BoundedArtistLookup(paths["track_metadata"])
    tags_connection = _readonly_connection(paths["lastfm_tags"])
    try:
        tags_connection.create_function(
            "opennoise_normalize", 1, normalize_label, deterministic=True
        )
        placeholders = ",".join("?" for _ in target_by_normalized)
        # Only a count of literal ``?`` bind markers is interpolated; all target values bind below.
        query = f"""
            SELECT tids.tid AS track_id, tags.tag AS tag, tid_tag.val AS weight
              FROM tid_tag
              JOIN tids ON tids.rowid = tid_tag.tid
              JOIN tags ON tags.rowid = tid_tag.tag
             WHERE opennoise_normalize(tags.tag) IN ({placeholders})
             ORDER BY tids.tid, tags.tag
        """
        cursor = tags_connection.execute(query, tuple(target_by_normalized))
        while rows := cursor.fetchmany(5_000):
            for row in rows:
                tag_row_count += 1
                if tag_row_count > maximum_tag_rows:
                    raise MsdLastFmError("lastfm tag input exceeds maximum_tag_rows")  # noqa: TRY301
                track_id, tag = str(row["track_id"]), str(row["tag"])
                target = target_by_normalized[normalize_label(tag)]
                identity = lookup.get(track_id)
                weight = int(row["weight"] or 0)
                if identity is None or identity.mbid is None:
                    review_key = (target.target_id, tag, track_id)
                    if review_key in seen_reviews:
                        raise MsdLastFmError("duplicate exact Last.fm tag review row")  # noqa: TRY301
                    seen_reviews.add(review_key)
                    if len(reviews) >= maximum_name_only_reviews:
                        raise MsdLastFmError(  # noqa: TRY301
                            "Last.fm tag reviews exceed maximum_name_only_reviews"
                        )
                    reviews.append(
                        NameOnlyTagReview(
                            target_id=target.target_id,
                            target_label=target.label,
                            source_tag=tag,
                            track_id=track_id,
                            artist_name="" if identity is None else identity.name,
                            source_weight=weight,
                        )
                    )
                else:
                    support_key = (target.target_id, tag, track_id, identity.mbid)
                    if support_key in seen_supports:
                        raise MsdLastFmError("duplicate exact Last.fm tag support row")  # noqa: TRY301
                    seen_supports.add(support_key)
                    if len(supports) >= maximum_tag_supports:
                        raise MsdLastFmError("Last.fm tag supports exceed maximum_tag_supports")  # noqa: TRY301
                    supports.append(
                        ArtistTagSupport(
                            target_id=target.target_id,
                            target_label=target.label,
                            source_tag=tag,
                            track_id=track_id,
                            artist_mbid=identity.mbid,
                            artist_name=identity.name,
                            source_weight=weight,
                        )
                    )
    except sqlite3.Error as error:
        raise MsdLastFmError(
            "unsupported lastfm_tags.db schema; expected tids/tags/tid_tag"
        ) from error
    except MsdLastFmError:
        lookup.close()
        raise
    finally:
        tags_connection.close()

    similarities: list[ArtistSimilaritySupport] = []
    similarity_connection = _readonly_connection(paths["lastfm_similarity"])
    try:
        cursor = similarity_connection.execute("SELECT tid, target FROM similars_src ORDER BY tid")
        row_count = 0
        while row_count < maximum_similarity_rows and (rows := cursor.fetchmany(1_000)):
            for row in rows:
                row_count += 1
                if row_count > maximum_similarity_rows:
                    break
                source_track = str(row["tid"])
                source_identity = lookup.get(source_track)
                if source_identity is None or source_identity.mbid is None:
                    continue
                for rank, (target_track, score) in enumerate(
                    _parse_similarity(row["target"]), start=1
                ):
                    target_identity = lookup.get(target_track)
                    if target_identity is None or target_identity.mbid is None:
                        continue
                    similarities.append(
                        ArtistSimilaritySupport(
                            source_track_id=source_track,
                            target_track_id=target_track,
                            source_artist_mbid=source_identity.mbid,
                            target_artist_mbid=target_identity.mbid,
                            score=score,
                            rank=rank,
                        )
                    )
                    if len(similarities) >= maximum_similarity_edges:
                        break
                if len(similarities) >= maximum_similarity_edges:
                    break
            if len(similarities) >= maximum_similarity_edges:
                break
    except sqlite3.Error as error:
        raise MsdLastFmError(
            "unsupported lastfm_similars.db schema; expected similars_src(tid,target)"
        ) from error
    finally:
        similarity_connection.close()
        lookup.close()

    supports_tuple = tuple(supports)
    targets_by_artist: dict[UUID, set[str]] = defaultdict(set)
    for item in supports_tuple:
        targets_by_artist[item.artist_mbid].add(item.target_id)
    conflicts = tuple(
        ArtistTargetConflict(artist_mbid=artist, target_ids=tuple(sorted(target_ids)))
        for artist, target_ids in sorted(
            (
                (artist, target_ids)
                for artist, target_ids in targets_by_artist.items()
                if len(target_ids) > 1
            ),
            key=lambda item: str(item[0]),
        )
    )
    mapped = {item.target_id for item in supports_tuple}
    abstentions = tuple(
        TargetAbstention(target_id=item.target_id, target_label=item.label)
        for item in targets
        if item.target_id not in mapped
    )
    coverage = MsdLastFmCoverage(
        target_count=len(targets),
        exact_mbid_track_tag_support_count=len(supports_tuple),
        name_only_review_count=len(reviews),
        similarity_support_count=len(similarities),
        conflict_count=len(conflicts),
        abstention_count=len(abstentions),
        incremental=_incremental_coverage(supports_tuple),
        held_out_anchor_recovery=_held_out_recovery(supports_tuple),
    )
    target_identity_sha256 = _sha256([item.model_dump(mode="json") for item in targets])
    preliminary = MsdLastFmEvidenceArtifact.model_construct(
        source_cache_sha256=source_cache.output_sha256,
        target_identity_sha256=target_identity_sha256,
        tag_supports=supports_tuple,
        name_only_reviews=tuple(reviews),
        similarity_supports=tuple(similarities),
        conflicts=conflicts,
        abstentions=abstentions,
        coverage=coverage,
        output_sha256="0" * 64,
    )
    return MsdLastFmEvidenceArtifact(
        **preliminary.model_dump(mode="python", exclude={"output_sha256"}),
        output_sha256=_sha256(preliminary.model_dump(mode="json", exclude={"output_sha256"})),
    )


def publish_msd_lastfm_evidence(
    artifact: MsdLastFmEvidenceArtifact,
    *,
    source_cache_receipt: Path,
    output: Path,
    store: ObjectStore,
) -> MsdLastFmEvidenceReceipt:
    """Publish derived evidence and a small source-cache receipt, never raw SQLite bytes."""
    cache = load_msd_lastfm_source_cache(source_cache_receipt)
    if cache.output_sha256 != artifact.source_cache_sha256:
        raise MsdLastFmError("artifact is not bound to the supplied source cache receipt")
    receipt_write = store.push(
        source_cache_receipt,
        ObjectKey(value=f"msd-lastfm/source-cache/sha256/{cache.output_sha256}.json"),
    )
    payload = (artifact.model_dump_json(indent=2) + "\n").encode()
    _atomic_write(output, payload)
    byte_sha = hashlib.sha256(payload).hexdigest()
    artifact_write = store.push(
        output,
        ObjectKey(value=f"msd-lastfm/evidence/sha256/{artifact.output_sha256}/{byte_sha}.json"),
    )
    if artifact_write.sha256 != byte_sha:
        raise MsdLastFmError("object store changed published MSD evidence")
    return MsdLastFmEvidenceReceipt(
        artifact=artifact_write,
        source_cache_receipt=receipt_write,
        logical_output_sha256=artifact.output_sha256,
    )
