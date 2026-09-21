"""Verify and restore the raw source vault for one sealed release manifest."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import Final, Literal

from pydantic import Field, model_validator

from opennoise.models import FrozenModel
from opennoise.pipeline.release_manifest import RELEASE_MANIFEST_NAME, load_release_manifest
from opennoise.storage import ObjectKey, ObjectStore
from opennoise.types import Sha256  # noqa: TC001

_CHUNK_BYTES: Final = 1024 * 1024
_RAW_PREFIX: Final = "raw/sha256"


class SourceVaultReplayError(ValueError):
    """Report a manifest, vault, or restore boundary failure."""


class ReleaseManifestInput(FrozenModel):
    """The immutable fields needed to locate one manifest-bound source object."""

    source_key: str = Field(min_length=1, max_length=300)
    artifact_sha256: Sha256
    byte_size: int = Field(ge=0)


class SourceVaultObject(FrozenModel):
    """One verified source object and its content-addressed object-store key."""

    source_key: str = Field(min_length=1, max_length=300)
    artifact_sha256: Sha256
    byte_size: int = Field(ge=0)
    object_key: ObjectKey


class SourceVaultReplayReport(FrozenModel):
    """Manifest-bound proof that every selected raw source object was verified."""

    revision: Literal["source-vault-replay-v1"] = "source-vault-replay-v1"
    release_id: str = Field(min_length=1, max_length=300)
    manifest_sha256: Sha256
    source_vault_layout: Literal["raw/sha256/<artifact_sha256>"] = "raw/sha256/<artifact_sha256>"
    object_count: int = Field(ge=0)
    total_byte_size: int = Field(ge=0)
    complete: bool
    objects: tuple[SourceVaultObject, ...] = Field(max_length=128)

    @model_validator(mode="after")
    def check_totals(self) -> SourceVaultReplayReport:
        """Ensure the report cannot self-assert complete with inconsistent totals."""
        if not self.complete or self.object_count != len(self.objects):
            raise ValueError("source vault replay report is incomplete")
        if self.object_count == 0 or len({item.artifact_sha256 for item in self.objects}) != (
            self.object_count
        ):
            raise ValueError("source vault replay objects must be unique")
        if any(
            item.object_key.value != f"{_RAW_PREFIX}/{item.artifact_sha256}"
            for item in self.objects
        ):
            raise ValueError("source vault object keys must be content-addressed raw objects")
        if self.total_byte_size != sum(item.byte_size for item in self.objects):
            raise ValueError("source vault replay byte total is inconsistent")
        return self


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK_BYTES):
            digest.update(chunk)
            byte_size += len(chunk)
    return digest.hexdigest(), byte_size


def _manifest(path: Path) -> tuple[str, str, tuple[ReleaseManifestInput, ...]]:
    if path.name != RELEASE_MANIFEST_NAME:
        raise SourceVaultReplayError(f"manifest path must be named {RELEASE_MANIFEST_NAME}")
    try:
        payload = load_release_manifest(path.parent)
        release_id = str(payload["release_id"])
        raw_inputs = payload["inputs"]
        inputs = tuple(ReleaseManifestInput.model_validate(item) for item in raw_inputs)
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise SourceVaultReplayError(f"invalid release manifest: {path}") from error
    if not inputs:
        raise SourceVaultReplayError("release manifest has no source inputs")
    source_keys = tuple(item.source_key for item in inputs)
    artifact_keys = tuple(item.artifact_sha256 for item in inputs)
    if len(set(source_keys)) != len(source_keys) or len(set(artifact_keys)) != len(artifact_keys):
        raise SourceVaultReplayError("release manifest source inputs must be unique")
    manifest_sha256, _ = _hash_file(path)
    return manifest_sha256, release_id, inputs


def _source_path(vault: Path, artifact_sha256: str) -> Path:
    return vault / "raw" / "sha256" / artifact_sha256


def _require_bytes(path: Path, expected_sha256: str, expected_size: int, label: str) -> None:
    actual_sha256, actual_size = _hash_file(path)
    if (actual_sha256, actual_size) != (expected_sha256, expected_size):
        raise SourceVaultReplayError(f"{label} does not match report")


def _require_object(store: ObjectStore, item: SourceVaultObject) -> None:
    metadata = store.inspect(item.object_key)
    if (metadata.sha256, metadata.byte_size) != (item.artifact_sha256, item.byte_size):
        raise SourceVaultReplayError(f"object store does not match report: {item.source_key}")


def verify_source_vault(
    manifest_path: Path,
    vault_path: Path,
    *,
    object_store: ObjectStore | None = None,
) -> SourceVaultReplayReport:
    """Hash every manifest input and optionally publish it to an object store."""
    manifest_sha256, release_id, inputs = _manifest(manifest_path.resolve(strict=True))
    verified: list[SourceVaultObject] = []
    total_byte_size = 0
    for item in inputs:
        path = _source_path(vault_path, item.artifact_sha256)
        if not path.is_file():
            raise SourceVaultReplayError(f"source object is missing: {path}")
        actual_sha256, actual_size = _hash_file(path)
        if (actual_sha256, actual_size) != (item.artifact_sha256, item.byte_size):
            raise SourceVaultReplayError(
                f"source object does not match manifest: {item.source_key}"
            )
        object_key = ObjectKey(value=f"{_RAW_PREFIX}/{item.artifact_sha256}")
        if object_store is not None:
            stored = object_store.push(path, object_key)
            if (stored.sha256, stored.byte_size) != (actual_sha256, actual_size):
                raise SourceVaultReplayError(
                    f"object store changed source bytes: {item.source_key}"
                )
        verified.append(
            SourceVaultObject(
                source_key=item.source_key,
                artifact_sha256=item.artifact_sha256,
                byte_size=item.byte_size,
                object_key=object_key,
            )
        )
        total_byte_size += item.byte_size
    return SourceVaultReplayReport(
        release_id=release_id,
        manifest_sha256=manifest_sha256,
        object_count=len(verified),
        total_byte_size=total_byte_size,
        complete=True,
        objects=tuple(verified),
    )


def restore_source_vault(
    report: SourceVaultReplayReport,
    object_store: ObjectStore,
    destination: Path,
    *,
    manifest_path: Path,
) -> None:
    """Restore a report into a new destination after rechecking its manifest binding."""
    manifest_sha256, release_id, inputs = _manifest(manifest_path.resolve(strict=True))
    if (manifest_sha256, release_id) != (report.manifest_sha256, report.release_id):
        raise SourceVaultReplayError("restore manifest does not match replay report")
    expected = {item.artifact_sha256: (item.source_key, item.byte_size) for item in inputs}
    if {
        item.artifact_sha256: (item.source_key, item.byte_size) for item in report.objects
    } != expected:
        raise SourceVaultReplayError("replay report objects do not match the release manifest")
    if destination.is_symlink() or destination.exists():
        raise SourceVaultReplayError("restore destination must not already exist")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.restore-", dir=destination.parent))
    try:
        for item in report.objects:
            _require_object(object_store, item)
            target = staging / item.object_key.value
            object_store.pull(item.object_key, target)
            _require_bytes(target, item.artifact_sha256, item.byte_size, item.source_key)
        staging.replace(destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def write_report(report: SourceVaultReplayReport, path: Path) -> None:
    """Atomically write a JSON replay report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(report.model_dump_json(indent=2))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load_report(path: Path) -> SourceVaultReplayReport:
    """Parse a replay report at the CLI boundary."""
    try:
        return SourceVaultReplayReport.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SourceVaultReplayError(f"invalid source-vault replay report: {path}") from error
