"""Restore a sealed SQLite catalog snapshot without mutating its source."""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from pydantic import Field

from opennoise.models import FrozenModel


class CatalogSnapshotRestoreError(RuntimeError):
    """Report a failed closed catalog snapshot restoration."""


class CatalogSnapshotRestoreReceipt(FrozenModel):
    """Bind one restored catalog path to the exact sealed source bytes."""

    revision: str = Field(default="catalog-snapshot-restore-v1", min_length=1)
    source_path: Path
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    destination_path: Path
    destination_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(gt=0)
    expected_taxonomy_catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    integrity_check: tuple[str, ...] = Field(min_length=1)
    foreign_key_violation_count: int = Field(ge=0)


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of one regular file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_checks(path: Path) -> tuple[tuple[str, ...], int]:
    """Verify the copied snapshot is a usable SQLite catalog before publication."""
    source_uri = f"file:{path.resolve(strict=True).as_posix()}?mode=ro&immutable=1"
    with closing(sqlite3.connect(source_uri, uri=True)) as connection:
        integrity = tuple(str(row[0]) for row in connection.execute("PRAGMA integrity_check"))
        violations = tuple(connection.execute("PRAGMA foreign_key_check"))
    if integrity != ("ok",):
        raise CatalogSnapshotRestoreError("catalog snapshot failed SQLite integrity_check")
    if violations:
        raise CatalogSnapshotRestoreError("catalog snapshot has foreign-key violations")
    return integrity, len(violations)


def _copy_atomically(source: Path, destination: Path) -> None:
    """Copy source bytes through a sibling temporary file, then atomically replace destination."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with source.open("rb") as input_stream, os.fdopen(descriptor, "wb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def restore_catalog_snapshot(
    source: Path,
    destination: Path,
    *,
    expected_taxonomy_catalog_sha256: str,
) -> CatalogSnapshotRestoreReceipt:
    """Copy a sealed pre-hydration catalog only when both byte identities agree.

    The caller must supply the target snapshot hash.  A mismatch is detected
    before writing, so a wrong source cannot replace an existing destination.
    """
    source_path = source.resolve(strict=True)
    destination_path = destination.resolve(strict=False)
    if not source_path.is_file():
        raise CatalogSnapshotRestoreError("catalog snapshot source must be a regular file")
    if source_path == destination_path:
        raise CatalogSnapshotRestoreError(
            "catalog snapshot destination must differ from its source"
        )
    source_sha256 = sha256_file(source_path)
    if source_sha256 != expected_taxonomy_catalog_sha256:
        raise CatalogSnapshotRestoreError(
            "catalog snapshot source hash does not match the expected taxonomy catalog hash"
        )
    _copy_atomically(source_path, destination_path)
    destination_sha256 = sha256_file(destination_path)
    if destination_sha256 != expected_taxonomy_catalog_sha256:
        raise CatalogSnapshotRestoreError("restored catalog hash does not match the expected hash")
    if sha256_file(source_path) != expected_taxonomy_catalog_sha256:
        raise CatalogSnapshotRestoreError("catalog snapshot source changed during restoration")
    integrity_check, foreign_key_violation_count = _sqlite_checks(destination_path)
    return CatalogSnapshotRestoreReceipt(
        source_path=source_path,
        source_sha256=source_sha256,
        destination_path=destination_path,
        destination_sha256=destination_sha256,
        byte_size=destination_path.stat().st_size,
        expected_taxonomy_catalog_sha256=expected_taxonomy_catalog_sha256,
        integrity_check=integrity_check,
        foreign_key_violation_count=foreign_key_violation_count,
    )
