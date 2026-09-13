"""Seal the local H3 inputs used by a historical signal rebuild."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field

from opennoise.common import sha256_file, write_durable_bytes
from opennoise.models import FrozenModel
from opennoise.models.historical_signal import HistoricalSignalSettings  # noqa: TC001
from opennoise.storage import ObjectKey, ObjectStore
from opennoise.types import Sha256  # noqa: TC001

if TYPE_CHECKING:
    from pathlib import Path

_CHUNK_BYTES: Final = 1024 * 1024
_OBSERVATION_ROLE: Final = "genre_page_member"
_RAW_KEY_PREFIX: Final = "historical-h3/raw/sha256"
_SQLITE_KEY_PREFIX: Final = "historical-h3/membership/sha256"


class HistoricalCustodyError(ValueError):
    """Reject an H3 input that cannot be bound to its rebuild receipt."""


class HistoricalH3Object(FrozenModel):
    """One content-addressed H3 input retained in the configured object store."""

    key: ObjectKey
    sha256: Sha256
    byte_size: int = Field(gt=0)


class HistoricalH3Counts(FrozenModel):
    """Configured and observed counts for the raw source and SQLite projection."""

    declared_source_genre_rows: int = Field(gt=0)
    declared_source_memberships: int = Field(gt=0)
    stored_memberships: int = Field(gt=0)
    stored_genres: int = Field(gt=0)
    stored_artists: int = Field(gt=0)


class HistoricalH3RebuildReceipt(FrozenModel):
    """Atomic, provenance-first receipt for a reproducible local H3 rebuild."""

    revision: Literal["historical-h3-rebuild-receipt-v1"] = "historical-h3-rebuild-receipt-v1"
    raw_h3: HistoricalH3Object
    membership_sqlite: HistoricalH3Object
    counts: HistoricalH3Counts
    h3_source_sha256: Sha256
    h3_source_manifest_sha256: Sha256
    h2_manifest_sha256: Sha256
    local_display_policy_key: str = Field(min_length=1, max_length=300)
    model_settings: HistoricalSignalSettings
    rebuild_command: tuple[str, ...] = Field(min_length=1, max_length=64)
    python_version: str = Field(min_length=1, max_length=200)
    code_revision: str = Field(min_length=1, max_length=200)


def _sqlite_counts(path: Path, source_sha256: str) -> tuple[int, int, int]:
    """Count only source-scoped displayable H3 observations in a read-only DB."""
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
            hashes = {
                str(row[0])
                for row in connection.execute(
                    """SELECT DISTINCT source_artifact_sha256
                       FROM historical_genre_artist_observations
                       WHERE observation_role = ?""",
                    (_OBSERVATION_ROLE,),
                )
            }
            if hashes != {source_sha256}:
                raise HistoricalCustodyError(
                    "membership SQLite contains an unexpected H3 source hash"
                )
            row = connection.execute(
                """SELECT count(*), count(DISTINCT genre_id), count(DISTINCT source_artist_id)
                   FROM historical_genre_artist_observations
                   WHERE observation_role = ? AND source_artifact_sha256 = ?
                     AND source_artist_id IS NOT NULL""",
                (_OBSERVATION_ROLE, source_sha256),
            ).fetchone()
    except (OSError, sqlite3.Error) as error:
        raise HistoricalCustodyError("membership SQLite does not match the H3 schema") from error
    if row is None:
        raise HistoricalCustodyError("membership SQLite count query returned no row")
    return int(row[0]), int(row[1]), int(row[2])


def _code_revision() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def custody_historical_inputs(  # noqa: PLR0913
    store: ObjectStore,
    raw_path: Path,
    sqlite_path: Path,
    *,
    receipt_path: Path,
    expected_h3_source_sha256: str,
    expected_h3_source_byte_size: int,
    h3_source_manifest_sha256: str,
    h2_manifest_sha256: str,
    expected_source_genre_rows: int,
    expected_source_memberships: int,
    expected_stored_memberships: int,
    expected_stored_genres: int,
    expected_stored_artists: int,
    local_display_policy_key: str,
    model_settings: HistoricalSignalSettings,
    rebuild_command: tuple[str, ...],
    code_revision: str | None = None,
) -> HistoricalH3RebuildReceipt:
    """Verify and seal both H3 inputs, then atomically write their rebuild receipt."""
    raw_sha256, raw_size = sha256_file(raw_path)
    sqlite_sha256, sqlite_size = sha256_file(sqlite_path)
    if raw_sha256 != expected_h3_source_sha256 or raw_size != expected_h3_source_byte_size:
        raise HistoricalCustodyError("raw H3 bytes do not match the configured source manifest")
    stored_memberships, stored_genres, stored_artists = _sqlite_counts(sqlite_path, raw_sha256)
    observed = (stored_memberships, stored_genres, stored_artists)
    expected = (
        expected_stored_memberships,
        expected_stored_genres,
        expected_stored_artists,
    )
    if observed != expected:
        raise HistoricalCustodyError(f"H3 configured counts do not match: observed={observed}")
    raw_key = ObjectKey(value=f"{_RAW_KEY_PREFIX}/{raw_sha256}.json")
    sqlite_key = ObjectKey(value=f"{_SQLITE_KEY_PREFIX}/{sqlite_sha256}.sqlite")
    raw_write = store.push(raw_path, raw_key)
    sqlite_write = store.push(sqlite_path, sqlite_key)
    if (raw_write.sha256, raw_write.byte_size) != (raw_sha256, raw_size):
        raise HistoricalCustodyError("object store changed the raw H3 hash or byte size")
    if (sqlite_write.sha256, sqlite_write.byte_size) != (sqlite_sha256, sqlite_size):
        raise HistoricalCustodyError("object store changed the membership hash or byte size")
    receipt = HistoricalH3RebuildReceipt(
        raw_h3=HistoricalH3Object(key=raw_key, sha256=raw_sha256, byte_size=raw_size),
        membership_sqlite=HistoricalH3Object(
            key=sqlite_key, sha256=sqlite_sha256, byte_size=sqlite_size
        ),
        counts=HistoricalH3Counts(
            declared_source_genre_rows=expected_source_genre_rows,
            declared_source_memberships=expected_source_memberships,
            stored_memberships=stored_memberships,
            stored_genres=stored_genres,
            stored_artists=stored_artists,
        ),
        h3_source_sha256=raw_sha256,
        h3_source_manifest_sha256=h3_source_manifest_sha256,
        h2_manifest_sha256=h2_manifest_sha256,
        local_display_policy_key=local_display_policy_key,
        model_settings=model_settings,
        rebuild_command=rebuild_command,
        python_version=sys.version,
        code_revision=code_revision or _code_revision(),
    )
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    write_durable_bytes(receipt_path, (receipt.model_dump_json(indent=2) + "\n").encode("utf-8"))
    return receipt
