"""Bounded local-only aggregation of the verified Last.fm 360K plays member."""

from __future__ import annotations

import hashlib
import itertools
import sqlite3
import stat
import tarfile
import time
from collections.abc import Iterator  # noqa: TC003
from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, model_validator

from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001

if TYPE_CHECKING:
    from pathlib import Path

_ARCHIVE_MD5 = "635e6ed3fc873aa4ba33aba0ebce02b1"
_PLAYS_MD5 = "be672526eb7c69495c27ad27803148f1"
_PLAYS_MEMBER = "lastfm-dataset-360K/usersha1-artmbid-artname-plays.tsv"
_PLAY_FIELD_COUNT = 4
_PREFIX_ARTIST_COUNT = 22_166
_PREFIX_CATALOG_OVERLAP = 702
_PREFIX_PRIVACY_PAIR_COUNT = 362
_LISTENBRAINZ_NORMALIZED_PAIR_COUNT = 13_175


class LastFm360kProbeError(ValueError):
    """The local-only Last.fm aggregate cannot safely continue."""


class LastFm360kSettings(FrozenModel):
    """Predeclared resource and privacy bounds for one all-time source scan."""

    revision: Literal["lastfm-360k-full-aggregate-settings-v1"] = (
        "lastfm-360k-full-aggregate-settings-v1"
    )
    sample_strategy: Literal["full_plays_member_source_order"] = "full_plays_member_source_order"
    maximum_rows: int = Field(default=17_559_530, ge=1, le=17_559_530)
    maximum_archive_bytes: int = Field(default=600_000_000, ge=1, le=600_000_000)
    maximum_line_bytes: int = Field(default=1_000_000, ge=1, le=2_000_000)
    maximum_exact_artists_per_user: int = Field(default=10, ge=2, le=10)
    maximum_unique_exact_artists: int = Field(default=300_000, ge=1, le=300_000)
    maximum_distinct_user_blocks: int = Field(default=400_000, ge=1, le=400_000)
    maximum_candidate_pairs: int = Field(default=20_000_000, ge=1, le=20_000_000)
    maximum_working_database_bytes: int = Field(default=4_000_000_000, ge=1, le=4_000_000_000)
    minimum_distinct_users: int = Field(default=5, ge=5, le=100)
    commit_every_user_blocks: int = Field(default=2_000, ge=1, le=10_000)


class LastFm360kPrefixReference(FrozenModel):
    """Frozen first-100k diagnostic counts, kept distinct from the full scan."""

    raw_rows: Literal[100_000] = 100_000
    unique_exact_artist_mbid_count: Literal[22_166] = _PREFIX_ARTIST_COUNT
    catalog_exact_artist_overlap_count: Literal[702] = _PREFIX_CATALOG_OVERLAP
    privacy_filtered_pair_count: Literal[362] = _PREFIX_PRIVACY_PAIR_COUNT
    caveat: Literal["source_order_prefix_first_ten_exact_artists_per_user"] = (
        "source_order_prefix_first_ten_exact_artists_per_user"
    )


class ListenBrainzCoListenReference(FrozenModel):
    """Published aggregate reference with intentionally non-comparable semantics."""

    normalized_artist_pair_count: Literal[13_175] = _LISTENBRAINZ_NORMALIZED_PAIR_COUNT
    caveat: Literal["daily_timestamped_listens_not_comparable_to_all_time_plays"] = (
        "daily_timestamped_listens_not_comparable_to_all_time_plays"
    )


class LastFm360kAggregateArtifact(FrozenModel):
    """Counts-only local receipt; it never serializes people, artists, or pairs."""

    revision: Literal["lastfm-360k-full-aggregate-v1"] = "lastfm-360k-full-aggregate-v1"
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    model_input_allowed: Literal[False] = False
    independent_genre_gold: Literal[False] = False
    working_database_local_aggregate_custody: Literal[True] = True
    working_database_has_no_user_ids: Literal[True] = True
    working_database_pair_floor: int = Field(default=5, ge=5)
    source_archive_sha256: Sha256
    source_archive_byte_size: int = Field(ge=0)
    source_archive_md5: Literal["635e6ed3fc873aa4ba33aba0ebce02b1"] = _ARCHIVE_MD5
    source_plays_tsv_md5: Literal["be672526eb7c69495c27ad27803148f1"] = _PLAYS_MD5
    catalog_database_sha256: Sha256
    catalog_exact_artist_mbid_count: int = Field(ge=0)
    settings: LastFm360kSettings
    raw_rows_seen: int = Field(ge=0)
    valid_rows: int = Field(ge=0)
    malformed_rows: int = Field(ge=0)
    exact_artist_mbid_rows: int = Field(ge=0)
    unique_exact_artist_mbid_count: int = Field(ge=0)
    catalog_exact_artist_overlap_count: int = Field(ge=0)
    completed_user_block_count: int = Field(ge=0)
    candidate_pair_count: int = Field(ge=0)
    privacy_filtered_pair_count: int = Field(ge=0)
    working_database_byte_size: int = Field(ge=0)
    working_database_sha256: Sha256
    elapsed_seconds: float = Field(ge=0)
    prefix_reference: LastFm360kPrefixReference = LastFm360kPrefixReference()
    listenbrainz_reference: ListenBrainzCoListenReference = ListenBrainzCoListenReference()


class LastFm360kSealedV1Artifact(FrozenModel):
    """Original completed v1 report, preserved without a rewrite."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    revision: Literal["lastfm-360k-full-aggregate-v1"] = "lastfm-360k-full-aggregate-v1"
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    model_input_allowed: Literal[False] = False
    independent_genre_gold: Literal[False] = False
    source_archive_sha256: Sha256
    source_archive_byte_size: int = Field(ge=0)
    source_archive_md5: Literal["635e6ed3fc873aa4ba33aba0ebce02b1"] = _ARCHIVE_MD5
    source_plays_tsv_md5: Literal["be672526eb7c69495c27ad27803148f1"] = _PLAYS_MD5
    catalog_database_sha256: Sha256
    catalog_exact_artist_mbid_count: int = Field(ge=0)
    settings: LastFm360kSettings
    raw_rows_seen: int = Field(ge=0)
    valid_rows: int = Field(ge=0)
    malformed_rows: int = Field(ge=0)
    exact_artist_mbid_rows: int = Field(ge=0)
    unique_exact_artist_mbid_count: int = Field(ge=0)
    catalog_exact_artist_overlap_count: int = Field(ge=0)
    completed_user_block_count: int = Field(ge=0)
    candidate_pair_count: int = Field(ge=0)
    privacy_filtered_pair_count: int = Field(ge=0)
    prefix_reference: LastFm360kPrefixReference = LastFm360kPrefixReference()
    listenbrainz_reference: ListenBrainzCoListenReference = ListenBrainzCoListenReference()


class LastFm360kSealedV1CompanionReceipt(FrozenModel):
    """Receipt that binds the preserved v1 report to its final aggregate DB."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    revision: Literal["lastfm-360k-full-aggregate-receipt-v1"] = (
        "lastfm-360k-full-aggregate-receipt-v1"
    )
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    model_input_allowed: Literal[False] = False
    independent_genre_gold: Literal[False] = False
    source_aggregate_artifact_logical_sha256: Sha256
    working_database_local_aggregate_custody: Literal[True] = True
    working_database_has_no_user_ids: Literal[True] = True
    working_database_pair_floor: int = Field(ge=5)
    working_database_byte_size: int = Field(ge=0)
    working_database_sha256: Sha256
    privacy_filtered_pair_count: int = Field(ge=0)
    minimum_retained_pair_distinct_user_count: int = Field(ge=5)
    maximum_retained_pair_distinct_user_count: int = Field(ge=5)
    retained_pair_rows_below_privacy_floor: Literal[0] = 0
    notes: str

    @model_validator(mode="after")
    def _verify_privacy_floor(self) -> LastFm360kSealedV1CompanionReceipt:
        if self.minimum_retained_pair_distinct_user_count < self.working_database_pair_floor:
            raise ValueError("retained pair support is below the declared privacy floor")
        return self


class LastFm360kSealedV1Envelope(FrozenModel):
    """Validated original v1 report plus its separately emitted custody receipt."""

    revision: Literal["lastfm-360k-full-aggregate-envelope-v2"] = (
        "lastfm-360k-full-aggregate-envelope-v2"
    )
    original_artifact_sha256: Sha256
    original_artifact: LastFm360kSealedV1Artifact
    companion_receipt: LastFm360kSealedV1CompanionReceipt

    @model_validator(mode="after")
    def _verify_cross_artifact_counts(self) -> LastFm360kSealedV1Envelope:
        if (
            self.original_artifact.privacy_filtered_pair_count
            != self.companion_receipt.privacy_filtered_pair_count
        ):
            raise ValueError("original artifact and companion pair counts differ")
        if (
            self.original_artifact.settings.minimum_distinct_users
            != self.companion_receipt.working_database_pair_floor
        ):
            raise ValueError("original artifact and companion privacy floors differ")
        return self


@dataclass(slots=True)
class _Counts:
    raw_rows_seen: int = 0
    valid_rows: int = 0
    malformed_rows: int = 0
    exact_artist_mbid_rows: int = 0
    completed_user_block_count: int = 0


def run_lastfm_360k_full_aggregate(
    *,
    archive_path: Path,
    catalog_path: Path,
    working_database_path: Path,
    settings: LastFm360kSettings | None = None,
) -> LastFm360kAggregateArtifact:
    """Stream one plays member and persist only aggregate artist state locally."""
    config = settings or LastFm360kSettings()
    _verify_archive(archive_path, config)
    if working_database_path.exists():
        raise LastFm360kProbeError("working aggregate database already exists")
    catalog_ids = _catalog_artist_ids(catalog_path)
    working_database_path.parent.mkdir(parents=True, exist_ok=True)
    created_working_database = False
    started_at = time.monotonic()
    try:
        with closing(sqlite3.connect(working_database_path)) as database:
            created_working_database = True
            _initialize_working_database(database)
            counts = _Counts()
            observed_artists: set[str] = set()
            _consume_plays_member(archive_path, database, counts, observed_artists, config)
            database.executemany(
                "INSERT INTO observed_artists (artist_id) VALUES (?)",
                ((artist_id,) for artist_id in observed_artists),
            )
            database.commit()
            _verify_working_database_size(database, config)
            unique_artists = _count(database, "SELECT COUNT(*) FROM observed_artists")
            overlap = _catalog_overlap(database, catalog_ids)
            candidate_pairs = _count(database, "SELECT COUNT(*) FROM pair_support")
            privacy_pairs = _count(
                database,
                "SELECT COUNT(*) FROM pair_support WHERE distinct_user_count >= ?",
                (config.minimum_distinct_users,),
            )
            database.execute("PRAGMA secure_delete = ON")
            database.execute(
                "DELETE FROM pair_support WHERE distinct_user_count < ?",
                (config.minimum_distinct_users,),
            )
            database.commit()
            _verify_working_database_size(database, config)
    except Exception:
        if created_working_database:
            working_database_path.unlink(missing_ok=True)
        raise
    return LastFm360kAggregateArtifact(
        source_archive_sha256=_sha256_file(archive_path),
        source_archive_byte_size=archive_path.stat().st_size,
        catalog_database_sha256=_sha256_file(catalog_path),
        catalog_exact_artist_mbid_count=len(catalog_ids),
        settings=config,
        working_database_pair_floor=config.minimum_distinct_users,
        raw_rows_seen=counts.raw_rows_seen,
        valid_rows=counts.valid_rows,
        malformed_rows=counts.malformed_rows,
        exact_artist_mbid_rows=counts.exact_artist_mbid_rows,
        unique_exact_artist_mbid_count=unique_artists,
        catalog_exact_artist_overlap_count=overlap,
        completed_user_block_count=counts.completed_user_block_count,
        candidate_pair_count=candidate_pairs,
        privacy_filtered_pair_count=privacy_pairs,
        working_database_byte_size=working_database_path.stat().st_size,
        working_database_sha256=_sha256_file(working_database_path),
        elapsed_seconds=time.monotonic() - started_at,
    )


def load_lastfm_360k_sealed_v1_envelope(
    *, artifact_path: Path, companion_receipt_path: Path, database_path: Path
) -> LastFm360kSealedV1Envelope:
    """Bind the immutable v1 report and its companion to a verified local DB."""
    artifact_bytes = artifact_path.read_bytes()
    original_artifact = LastFm360kSealedV1Artifact.model_validate_json(artifact_bytes)
    companion_receipt = LastFm360kSealedV1CompanionReceipt.model_validate_json(
        companion_receipt_path.read_bytes()
    )
    original_sha256 = hashlib.sha256(artifact_bytes).hexdigest()
    if original_sha256 != companion_receipt.source_aggregate_artifact_logical_sha256:
        raise LastFm360kProbeError("companion receipt does not bind the original artifact")
    _verify_sealed_v1_database(database_path, companion_receipt)
    return LastFm360kSealedV1Envelope(
        original_artifact_sha256=original_sha256,
        original_artifact=original_artifact,
        companion_receipt=companion_receipt,
    )


def _verify_sealed_v1_database(path: Path, receipt: LastFm360kSealedV1CompanionReceipt) -> None:
    """Verify the final privacy-filtered aggregate without opening it writable."""
    before = _regular_file_identity(path)
    if before[2] != receipt.working_database_byte_size:
        raise LastFm360kProbeError("aggregate database byte size does not match companion receipt")
    if _sha256_file(path) != receipt.working_database_sha256:
        raise LastFm360kProbeError("aggregate database hash does not match companion receipt")
    try:
        with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as database:
            pair_count, minimum_support, maximum_support, below_floor_count = database.execute(
                """SELECT COUNT(*), MIN(distinct_user_count), MAX(distinct_user_count),
                          SUM(CASE WHEN distinct_user_count < ? THEN 1 ELSE 0 END)
                   FROM pair_support""",
                (receipt.working_database_pair_floor,),
            ).fetchone()
    except sqlite3.Error as error:
        raise LastFm360kProbeError("cannot read final aggregate database") from error
    if (
        pair_count != receipt.privacy_filtered_pair_count
        or minimum_support != receipt.minimum_retained_pair_distinct_user_count
        or maximum_support != receipt.maximum_retained_pair_distinct_user_count
        or below_floor_count != receipt.retained_pair_rows_below_privacy_floor
    ):
        raise LastFm360kProbeError(
            "aggregate database privacy query does not match companion receipt"
        )
    if (
        _regular_file_identity(path) != before
        or _sha256_file(path) != receipt.working_database_sha256
    ):
        raise LastFm360kProbeError("aggregate database changed during verification")


def _regular_file_identity(path: Path) -> tuple[int, int, int, int]:
    try:
        status = path.lstat()
    except OSError as error:
        raise LastFm360kProbeError("aggregate database is unavailable") from error
    if not stat.S_ISREG(status.st_mode):
        raise LastFm360kProbeError("aggregate database must be a regular file")
    return status.st_dev, status.st_ino, status.st_size, status.st_mtime_ns


def _consume_plays_member(  # noqa: C901, PLR0912, PLR0915
    archive_path: Path,
    database: sqlite3.Connection,
    counts: _Counts,
    observed_artists: set[str],
    config: LastFm360kSettings,
) -> None:
    current_user: bytes | None = None
    selected_artists: list[str] = []
    selected_artist_set: set[str] = set()
    completed_user_digests: set[bytes] = set()
    blocks_since_commit = 0
    plays_digest = hashlib.md5(usedforsecurity=False)
    with tarfile.open(archive_path, mode="r|gz") as archive:
        for member in archive:
            if member.name != _PLAYS_MEMBER:
                continue
            stream = archive.extractfile(member)
            if stream is None:
                raise LastFm360kProbeError("plays member cannot be opened")
            try:
                for line in stream:
                    if counts.raw_rows_seen >= config.maximum_rows:
                        raise LastFm360kProbeError("plays member exceeds row limit")
                    if len(line) > config.maximum_line_bytes:
                        raise LastFm360kProbeError("plays row exceeds byte limit")
                    plays_digest.update(line)
                    counts.raw_rows_seen += 1
                    parsed = _parse_play_row(line)
                    if parsed is None:
                        counts.malformed_rows += 1
                        continue
                    user_hash, artist_id = parsed
                    counts.valid_rows += 1
                    if current_user != user_hash:
                        if current_user is not None:
                            _flush_user_block(database, selected_artists)
                            counts.completed_user_block_count += 1
                            blocks_since_commit += 1
                            completed_user_digests.add(_user_digest(current_user))
                            if blocks_since_commit >= config.commit_every_user_blocks:
                                database.commit()
                                _verify_pair_bound(database, config)
                                _verify_working_database_size(database, config)
                                blocks_since_commit = 0
                        if _user_digest(user_hash) in completed_user_digests:
                            raise LastFm360kProbeError("plays rows are not grouped by user")
                        if len(completed_user_digests) >= config.maximum_distinct_user_blocks:
                            raise LastFm360kProbeError("distinct user-block count exceeds bound")
                        current_user = user_hash
                        selected_artists = []
                        selected_artist_set = set()
                    if artist_id is None:
                        continue
                    counts.exact_artist_mbid_rows += 1
                    observed_artists.add(artist_id)
                    if len(observed_artists) > config.maximum_unique_exact_artists:
                        raise LastFm360kProbeError("unique exact artist count exceeds bound")
                    if (
                        artist_id not in selected_artist_set
                        and len(selected_artists) < config.maximum_exact_artists_per_user
                    ):
                        selected_artist_set.add(artist_id)
                        selected_artists.append(artist_id)
                if current_user is not None:
                    _flush_user_block(database, selected_artists)
                    counts.completed_user_block_count += 1
                    _verify_pair_bound(database, config)
                if plays_digest.hexdigest() != _PLAYS_MD5:
                    raise LastFm360kProbeError("plays member MD5 does not match source receipt")
            finally:
                stream.close()
            return
    raise LastFm360kProbeError("plays member is unavailable")


def _parse_play_row(line: bytes) -> tuple[bytes, str | None] | None:
    fields = line.rstrip(b"\n").split(b"\t", maxsplit=3)
    if len(fields) != _PLAY_FIELD_COUNT:
        return None
    user_hash, raw_artist_id, _discarded_artist_name, raw_play_count = fields
    if not user_hash or _parse_nonnegative_int(raw_play_count) is None:
        return None
    try:
        artist_id = str(UUID(raw_artist_id.decode("ascii")))
    except (UnicodeDecodeError, ValueError):
        return user_hash, None
    return user_hash, artist_id


def _parse_nonnegative_int(value: bytes) -> int | None:
    try:
        result = int(value)
    except ValueError:
        return None
    return result if result >= 0 else None


def _flush_user_block(database: sqlite3.Connection, artists: list[str]) -> None:
    for left_artist, right_artist in itertools.combinations(sorted(artists), 2):
        database.execute(
            """INSERT INTO pair_support (left_artist, right_artist, distinct_user_count)
               VALUES (?, ?, 1)
               ON CONFLICT (left_artist, right_artist) DO UPDATE SET
                 distinct_user_count = distinct_user_count + 1""",
            (left_artist, right_artist),
        )


def _verify_pair_bound(database: sqlite3.Connection, config: LastFm360kSettings) -> None:
    if _count(database, "SELECT COUNT(*) FROM pair_support") > config.maximum_candidate_pairs:
        raise LastFm360kProbeError("candidate pair count exceeds bound")


def _verify_working_database_size(database: sqlite3.Connection, config: LastFm360kSettings) -> None:
    page_size = _count(database, "PRAGMA page_size")
    page_count = _count(database, "PRAGMA page_count")
    if page_size * page_count > config.maximum_working_database_bytes:
        raise LastFm360kProbeError("working aggregate database exceeds byte limit")


def _user_digest(user_hash: bytes) -> bytes:
    """Hold an ephemeral keyed-size digest, never the raw source user hash."""
    return hashlib.blake2s(user_hash, digest_size=16).digest()


def _initialize_working_database(database: sqlite3.Connection) -> None:
    database.executescript(
        """PRAGMA journal_mode = OFF;
           PRAGMA synchronous = OFF;
           CREATE TABLE observed_artists (artist_id TEXT PRIMARY KEY) WITHOUT ROWID;
           CREATE TABLE pair_support (
             left_artist TEXT NOT NULL,
             right_artist TEXT NOT NULL,
             distinct_user_count INTEGER NOT NULL,
             PRIMARY KEY (left_artist, right_artist)
           ) WITHOUT ROWID;"""
    )


def _catalog_artist_ids(path: Path) -> frozenset[str]:
    try:
        with closing(sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)) as database:
            rows = database.execute(
                """SELECT DISTINCT identifier.normalized_value
                   FROM entity_identifiers AS identifier
                   JOIN identifier_types AS identifier_type
                     ON identifier_type.id = identifier.identifier_type_id
                   WHERE identifier_type.type_key = 'musicbrainz_artist_id'"""
            )
            return frozenset(str(value) for (value,) in rows)
    except sqlite3.Error as error:
        raise LastFm360kProbeError("cannot load local catalog artist identifiers") from error


def _catalog_overlap(database: sqlite3.Connection, catalog_ids: frozenset[str]) -> int:
    database.execute("CREATE TEMP TABLE catalog_artists (artist_id TEXT PRIMARY KEY) WITHOUT ROWID")
    database.executemany(
        "INSERT INTO catalog_artists (artist_id) VALUES (?)",
        ((artist_id,) for artist_id in catalog_ids),
    )
    return _count(
        database,
        """SELECT COUNT(*) FROM observed_artists
           JOIN catalog_artists USING (artist_id)""",
    )


def _count(database: sqlite3.Connection, statement: str, parameters: tuple[int, ...] = ()) -> int:
    return int(database.execute(statement, parameters).fetchone()[0])


def _verify_archive(path: Path, config: LastFm360kSettings) -> None:
    if not path.is_file() or path.stat().st_size > config.maximum_archive_bytes:
        raise LastFm360kProbeError("archive is unavailable or exceeds byte limit")
    if _md5_file(path) != _ARCHIVE_MD5:
        raise LastFm360kProbeError("archive MD5 does not match source receipt")


def _md5_file(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def iter_plays_rows_for_test(archive_path: Path) -> Iterator[bytes]:
    """Expose only the plays member for parser fixtures; never reads profile rows."""
    with tarfile.open(archive_path, mode="r|gz") as archive:
        for member in archive:
            if member.name != _PLAYS_MEMBER:
                continue
            stream = archive.extractfile(member)
            if stream is None:
                raise LastFm360kProbeError("plays member cannot be opened")
            try:
                yield from stream
            finally:
                stream.close()
            return
    raise LastFm360kProbeError("plays member is unavailable")
