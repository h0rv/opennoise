"""Build one serving database from a sealed, local-only Phase 3 cache."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from pydantic import Field

from musix.db import Database
from musix.ml.public_graph import build_public_model
from musix.ml.publish import (
    PublicModelPublishError,
    project_public_model_explainability,
    publish_public_model,
)
from musix.ml.repository import PublicInputLoadSettings, PublicModelRepository
from musix.models import FrozenModel
from musix.models.modeling import PublicModelArtifact, PublicModelSettings
from musix.pipeline.release_manifest import verify_manifest_against_database

_POLICY_VERSION = 1


class PublicReleaseBuildError(RuntimeError):
    """Report an invalid sealed cache or a failed publication boundary."""


class PublicReleaseSettings(FrozenModel):
    """Configure the complete cache-only source-to-serving build."""

    release_directory: Path
    cache_database: Path
    serving_database: Path
    model_output: Path
    receipt_output: Path
    max_direct_memberships: int = Field(default=100_000, gt=0, le=1_000_000)
    max_artist_pairs: int = Field(default=250_000, gt=0, le=5_000_000)
    max_metadata_candidates: int = Field(default=100_000, gt=0, le=1_000_000)
    neighbors_per_genre: int = Field(default=25, ge=1, le=100)


class PublicReleaseResult(FrozenModel):
    """Record the immutable inputs and outputs selected by one build."""

    release_id: str = Field(min_length=1)
    cache_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cache_schema_version: int = Field(ge=1)
    serving_schema_version: int = Field(ge=1)
    model_logical_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    recorded_model_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_settings_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_artifacts: int = Field(gt=0)
    representative_items: int = Field(ge=0)
    profile_memberships: int = Field(ge=0)
    neighbor_rows: int = Field(ge=0)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _temporary_path(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    return Path(temporary)


def _write_atomic(path: Path, payload: bytes) -> None:
    temporary = _temporary_path(path)
    try:
        with temporary.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _snapshot_cache(source: Path, destination: Path) -> None:
    """Copy a sealed SQLite file byte-for-byte without acquiring a source lock."""
    absolute_source = source.resolve(strict=True)
    shutil.copyfile(absolute_source, destination)
    with destination.open("rb") as stream:
        os.fsync(stream.fileno())
    if _sha256(absolute_source) != _sha256(destination):
        raise PublicReleaseBuildError("sealed cache copy does not match its source hash")


def _release_policy_id(connection: sqlite3.Connection, release_id: str) -> int:
    """Create or resolve the sealed policy that owns the derived public release."""
    policy_key = f"release:{release_id}"
    row = connection.execute(
        """SELECT id, classification, local_only, basis
           FROM rights_policies
           WHERE policy_key = ? AND policy_version = ?""",
        (policy_key, _POLICY_VERSION),
    ).fetchone()
    basis = "sealed public-domain Phase 3 metadata release; metadata only; no audio or media bytes"
    if row is None:
        cursor = connection.execute(
            """INSERT INTO rights_policies
               (policy_key, policy_version, classification, local_only, basis, reviewed_at)
               VALUES (?, ?, 'public_domain', 0, ?, ?)""",
            (policy_key, _POLICY_VERSION, basis, _utc_now()),
        )
        if cursor.lastrowid is None:
            raise PublicReleaseBuildError("release policy insert returned no row ID")
        policy_id = cursor.lastrowid
        connection.executemany(
            """INSERT INTO rights_policy_permissions
               (policy_id, use_kind, decision, reason) VALUES (?, ?, ?, ?)""",
            (
                (policy_id, "normalize", "deny", "derived output does not normalize source data"),
                (policy_id, "local_search", "allow", "public metadata release"),
                (policy_id, "display", "allow", "public metadata release"),
                (policy_id, "embed", "allow", "public metadata graph release"),
                (policy_id, "train", "deny", "no training authorization is inferred"),
                (policy_id, "export", "allow", "public metadata release"),
            ),
        )
        connection.execute(
            "INSERT INTO rights_policy_seals (policy_id, sealed_at) VALUES (?, ?)",
            (policy_id, _utc_now()),
        )
        return policy_id
    if (str(row[1]), int(row[2]), str(row[3])) != ("public_domain", 0, basis):
        raise PublicReleaseBuildError("existing release policy does not match the sealed policy")
    policy_id = int(row[0])
    permissions = {
        str(item[0]): str(item[1])
        for item in connection.execute(
            "SELECT use_kind, decision FROM active_rights_policy_permissions WHERE policy_id = ?",
            (policy_id,),
        )
    }
    if permissions != {
        "normalize": "deny",
        "local_search": "allow",
        "display": "allow",
        "embed": "allow",
        "train": "deny",
        "export": "allow",
    }:
        raise PublicReleaseBuildError("existing release policy permissions do not match")
    return policy_id


def _model_payload(
    settings: PublicReleaseSettings, database: Path
) -> tuple[bytes, PublicModelArtifact]:
    load_settings = PublicInputLoadSettings(
        max_direct_memberships=settings.max_direct_memberships,
        max_artist_pairs=settings.max_artist_pairs,
        max_metadata_candidates=settings.max_metadata_candidates,
    )
    model_settings = PublicModelSettings(
        neighbors_per_genre=settings.neighbors_per_genre,
        max_direct_memberships=settings.max_direct_memberships,
        max_artist_pairs=settings.max_artist_pairs,
    )
    absolute = database.resolve(strict=True)
    with closing(
        sqlite3.connect(f"file:{absolute.as_posix()}?mode=ro&immutable=1", uri=True)
    ) as connection:
        inputs = PublicModelRepository(connection, connection).load(load_settings)
    artifact = build_public_model(inputs, model_settings)
    return artifact.model_dump_json().encode(), artifact


def _require_expected_model(manifest: dict[str, object], artifact: PublicModelArtifact) -> str:
    """Fail rather than quietly publishing a newer or differently configured reconstruction."""
    model = manifest.get("model")
    if not isinstance(model, dict):
        raise PublicReleaseBuildError("release manifest has no model boundary")
    expected = {
        "input_sha256": model.get("input_sha256"),
        "settings_sha256": model.get("settings_sha256"),
        "output_sha256": model.get("logical_output_sha256"),
    }
    actual = {
        "input_sha256": artifact.input_sha256,
        "settings_sha256": artifact.settings_sha256,
        "output_sha256": artifact.output_sha256,
    }
    for field, value in expected.items():
        if actual[field] != value:
            raise PublicReleaseBuildError(f"sealed model {field} does not match the cache build")
    recorded_file_hash = model.get("file_sha256")
    if not isinstance(recorded_file_hash, str):
        raise PublicReleaseBuildError("release manifest model file hash is missing")
    # Resource timing and peak RSS are intentionally outside the logical output hash.
    # They are useful diagnostics but cannot be a byte-identical reproduction gate.
    return recorded_file_hash


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _schema_version(path: Path) -> int:
    source_uri = f"file:{path.resolve(strict=True).as_posix()}?mode=ro&immutable=1"
    with closing(sqlite3.connect(source_uri, uri=True)) as connection:
        row = connection.execute("PRAGMA user_version").fetchone()
    if row is None:
        raise PublicReleaseBuildError("database has no schema version")
    return int(row[0])


def build_public_release(settings: PublicReleaseSettings) -> PublicReleaseResult:
    """Create a fully derived serving snapshot from one verified local cache only."""
    manifest_result = verify_manifest_against_database(
        settings.release_directory,
        settings.cache_database,
    )
    manifest_path = settings.release_directory / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise PublicReleaseBuildError("release manifest must be a JSON object")
    temporary_database = _temporary_path(settings.serving_database)
    temporary_model = _temporary_path(settings.model_output)
    temporary_receipt = _temporary_path(settings.receipt_output)
    try:
        _snapshot_cache(settings.cache_database, temporary_database)
        Database(temporary_database).initialize()
        payload, artifact = _model_payload(settings, temporary_database)
        recorded_model_file_sha256 = _require_expected_model(manifest, artifact)
        _write_atomic(temporary_model, payload)
        try:
            publication = project_public_model_explainability(temporary_database, temporary_model)
        except PublicModelPublishError as error:
            if str(error) != "public model output has not been published":
                raise
            with Database(temporary_database).connect() as connection, connection:
                policy_id = _release_policy_id(connection, str(manifest_result["release_id"]))
            publication = publish_public_model(
                temporary_database, temporary_model, policy_id=policy_id
            )
        result = PublicReleaseResult(
            release_id=str(manifest_result["release_id"]),
            cache_sha256=_sha256(settings.cache_database),
            cache_schema_version=int(manifest_result["schema_version"]),
            serving_schema_version=_schema_version(temporary_database),
            model_logical_sha256=artifact.output_sha256,
            model_file_sha256=_sha256_bytes(payload),
            recorded_model_file_sha256=recorded_model_file_sha256,
            model_input_sha256=artifact.input_sha256,
            model_settings_sha256=artifact.settings_sha256,
            input_artifacts=int(manifest_result["input_artifacts"]),
            representative_items=len(artifact.representatives),
            profile_memberships=publication.profile_memberships,
            neighbor_rows=publication.neighbor_rows,
        )
        receipt = result.model_dump_json(indent=2).encode()
        _write_atomic(temporary_receipt, receipt)
        temporary_database.replace(settings.serving_database)
        temporary_model.replace(settings.model_output)
        temporary_receipt.replace(settings.receipt_output)
        return result
    finally:
        temporary_database.unlink(missing_ok=True)
        temporary_model.unlink(missing_ok=True)
        temporary_receipt.unlink(missing_ok=True)
