"""Project a receipt-bound schema-12 replay candidate into local-only serving rows."""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any, Literal

from opennoise.db import Database
from opennoise.ml.public_graph import build_public_model
from opennoise.ml.public_model_gate import require_public_model_gate
from opennoise.ml.publish import PublicModelPublishSummary, publish_public_model
from opennoise.ml.repository import PublicInputLoadSettings, PublicModelRepository
from opennoise.models import FrozenModel
from opennoise.models.modeling import PublicModelArtifact, PublicModelSettings
from opennoise.pipeline.public_release import _release_policy_id
from opennoise.pipeline.release_manifest import load_release_manifest
from opennoise.pipeline.source_vault_replay import CandidateCombinedReplayReport
from opennoise.types import Sha256  # noqa: TC001

_CANDIDATE_SCHEMA_VERSION = 12
_EXPECTED_LAYOUT_POINTS = {
    "public": 468,
    "public-direct": 468,
    "public-community": 468,
    "public-taxonomy": 598,
}
_EXPECTED_REPRESENTATIVE_ITEMS = 3_344
_EXPECTED_PROFILE_MEMBERSHIPS = 26_525
_EXPECTED_NEIGHBOR_ROWS = 34_348


class CandidatePublicProjectionError(RuntimeError):
    """Report a candidate projection boundary or output failure."""


class CandidatePublicProjectionSettings(FrozenModel):
    """All explicit inputs and fresh destinations for a local-only projection."""

    release_directory: Path
    candidate_database: Path
    replay_receipt: Path
    expected_candidate_sha256: Sha256
    expected_replay_receipt_sha256: Sha256
    output_database: Path
    model_output: Path
    report_output: Path


class CandidatePublicProjectionReport(FrozenModel):
    """Uncertified receipt for one independently writable candidate projection."""

    revision: str = "phase3-candidate-public-projection-v1"
    release_id: str
    manifest_sha256: Sha256
    replay_receipt_sha256: Sha256
    candidate_sha256: Sha256
    candidate_schema_version: int
    certified_database: Literal[False] = False
    byte_identical_database_replay: Literal[False] = False
    model_input_sha256: Sha256
    model_settings_sha256: Sha256
    model_logical_sha256: Sha256
    model_file_sha256: Sha256
    serving_database_sha256: Sha256
    representative_items: int
    profile_memberships: int
    neighbor_rows: int
    layout_points: dict[str, int]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _require_fresh_outputs(settings: CandidatePublicProjectionSettings) -> None:
    outputs = (settings.output_database, settings.model_output, settings.report_output)
    if len({path.resolve() for path in outputs}) != len(outputs):
        raise CandidatePublicProjectionError("projection output paths must be distinct")
    for path in outputs:
        if path.exists() or path.is_symlink():
            raise CandidatePublicProjectionError(f"projection output already exists: {path}")
        if not path.parent.is_dir():
            raise CandidatePublicProjectionError(
                f"projection output parent does not exist: {path.parent}"
            )


def _load_receipt(path: Path, expected_sha256: Sha256) -> CandidateCombinedReplayReport:
    actual_sha256 = _sha256(path)
    if actual_sha256 != expected_sha256:
        raise CandidatePublicProjectionError(
            "replay receipt hash does not match the requested input"
        )
    try:
        return CandidateCombinedReplayReport.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise CandidatePublicProjectionError("combined replay receipt is invalid") from error


def _manifest_source_artifacts(manifest: dict[str, Any]) -> set[tuple[str, str]]:
    inputs = manifest["inputs"]
    if not isinstance(inputs, list):  # guarded by load_release_manifest
        raise CandidatePublicProjectionError("release manifest inputs are invalid")
    return {
        (str(item["source_key"]), str(item["artifact_sha256"]))
        for item in inputs
        if isinstance(item, dict)
    }


def _receipt_artifact_hashes(receipt: CandidateCombinedReplayReport) -> set[str]:
    return {
        *(item.artifact_sha256 for item in receipt.wikidata_objects),
        *(item.artifact_sha256 for item in receipt.listenbrainz_daily_objects),
        receipt.sealed_joint_artifact_sha256,
    }


def _verify_candidate_boundary(
    settings: CandidatePublicProjectionSettings,
) -> tuple[dict[str, Any], CandidateCombinedReplayReport, str, str]:
    candidate = settings.candidate_database.resolve(strict=True)
    candidate_sha256 = _sha256(candidate)
    if candidate_sha256 != settings.expected_candidate_sha256:
        raise CandidatePublicProjectionError(
            "candidate database hash does not match the requested input"
        )
    manifest_path = settings.release_directory.resolve(strict=True) / "release-manifest.json"
    manifest_sha256 = _sha256(manifest_path)
    manifest = load_release_manifest(settings.release_directory)
    receipt = _load_receipt(
        settings.replay_receipt.resolve(strict=True), settings.expected_replay_receipt_sha256
    )
    if receipt.manifest_sha256 != manifest_sha256 or receipt.release_id != manifest["release_id"]:
        raise CandidatePublicProjectionError(
            "replay receipt does not bind the requested release manifest"
        )
    if receipt.database_path.resolve() != candidate:
        raise CandidatePublicProjectionError(
            "replay receipt does not bind the requested candidate database"
        )
    if receipt.database_schema_version != _CANDIDATE_SCHEMA_VERSION:
        raise CandidatePublicProjectionError("replay receipt is not for a schema-12 candidate")
    manifest_source_artifacts = _manifest_source_artifacts(manifest)
    manifest_hashes = {artifact_hash for _source_key, artifact_hash in manifest_source_artifacts}
    if _receipt_artifact_hashes(receipt) != manifest_hashes:
        raise CandidatePublicProjectionError(
            "replay receipt artifacts do not match the release manifest"
        )
    with closing(
        sqlite3.connect(f"file:{candidate.as_posix()}?mode=ro&immutable=1", uri=True)
    ) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        version = connection.execute("PRAGMA user_version").fetchone()
        actual_source_artifacts = {
            (str(row[0]), str(row[1]))
            for row in connection.execute(
                """SELECT source.source_key, artifact.sha256
                   FROM data_sources AS source
                   JOIN source_snapshots AS snapshot ON snapshot.source_id = source.id
                   JOIN source_artifacts AS artifact ON artifact.snapshot_id = snapshot.id"""
            )
        }
    if integrity is None or integrity[0] != "ok":
        raise CandidatePublicProjectionError("candidate database integrity check failed")
    if version is None or int(version[0]) != _CANDIDATE_SCHEMA_VERSION:
        raise CandidatePublicProjectionError("candidate database is not schema 12")
    if actual_source_artifacts != manifest_source_artifacts:
        raise CandidatePublicProjectionError(
            "candidate source-key/artifact hashes do not match the release manifest"
        )
    return manifest, receipt, manifest_sha256, candidate_sha256


def _temporary_file(destination: Path) -> Path:
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(descriptor)
    return Path(raw_path)


def _copy_candidate(source: Path, destination: Path, expected_sha256: Sha256) -> None:
    if _sha256(source) != expected_sha256:
        raise CandidatePublicProjectionError(
            "candidate database changed after boundary verification"
        )
    shutil.copyfile(source, destination)
    with destination.open("rb") as stream:
        os.fsync(stream.fileno())
    if _sha256(destination) != expected_sha256:
        raise CandidatePublicProjectionError("candidate copy does not match its input hash")


def _build_model(database: Path) -> tuple[bytes, PublicModelArtifact]:
    load_settings = PublicInputLoadSettings()
    model_settings = PublicModelSettings()
    with closing(
        sqlite3.connect(f"file:{database.as_posix()}?mode=ro&immutable=1", uri=True)
    ) as connection:
        connection.row_factory = sqlite3.Row
        inputs = PublicModelRepository(connection, connection).load(load_settings)
    artifact = build_public_model(inputs, model_settings)
    return artifact.model_dump_json().encode(), artifact


def _require_manifest_model(manifest: dict[str, Any], artifact: PublicModelArtifact) -> None:
    model = manifest.get("model")
    if not isinstance(model, dict):
        raise CandidatePublicProjectionError("release manifest has no model boundary")
    actual = {
        "input_sha256": artifact.input_sha256,
        "settings_sha256": artifact.settings_sha256,
        "logical_output_sha256": artifact.output_sha256,
    }
    for field, value in actual.items():
        if model.get(field) != value:
            raise CandidatePublicProjectionError(f"candidate model {field} does not match manifest")


def _require_projection_summary(summary: PublicModelPublishSummary) -> dict[str, int]:
    layout_points = {item.layout_key: item.coordinate_genres for item in summary.layouts}
    if (
        layout_points != _EXPECTED_LAYOUT_POINTS
        or summary.representative_items != _EXPECTED_REPRESENTATIVE_ITEMS
        or summary.profile_memberships != _EXPECTED_PROFILE_MEMBERSHIPS
        or summary.neighbor_rows != _EXPECTED_NEIGHBOR_ROWS
    ):
        raise CandidatePublicProjectionError(
            "persisted public projection does not match Phase 3 counts"
        )
    return layout_points


def _checkpoint_database(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("PRAGMA journal_mode = DELETE")


def _verify_projected_database(path: Path) -> None:
    with closing(
        sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)
    ) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        foreign_keys = tuple(connection.execute("PRAGMA foreign_key_check"))
    if integrity is None or integrity[0] != "ok" or foreign_keys:
        raise CandidatePublicProjectionError(
            "projected database integrity or foreign-key check failed"
        )


def _publish_no_replace(staged: Path, destination: Path) -> None:
    try:
        os.link(staged, destination, follow_symlinks=False)
    except FileExistsError as error:
        raise CandidatePublicProjectionError(
            f"projection output already exists: {destination}"
        ) from error
    staged.unlink()


def project_candidate_public_model(
    settings: CandidatePublicProjectionSettings,
) -> CandidatePublicProjectionReport:
    """Build and publish only into fresh local destinations after all input checks pass."""
    _require_fresh_outputs(settings)
    manifest, receipt, manifest_sha256, candidate_sha256 = _verify_candidate_boundary(settings)
    staged_database = _temporary_file(settings.output_database)
    staged_model = _temporary_file(settings.model_output)
    staged_report = _temporary_file(settings.report_output)
    try:
        _copy_candidate(
            settings.candidate_database.resolve(strict=True),
            staged_database,
            settings.expected_candidate_sha256,
        )
        Database(staged_database).initialize()
        model_payload, artifact = _build_model(staged_database)
        _require_manifest_model(manifest, artifact)
        staged_model.write_bytes(model_payload)
        gate = require_public_model_gate(artifact)
        with Database(staged_database).connect() as connection, connection:
            policy_id = _release_policy_id(connection, receipt.release_id)
        summary = publish_public_model(staged_database, staged_model, policy_id=policy_id)
        layout_points = _require_projection_summary(summary)
        _checkpoint_database(staged_database)
        _verify_projected_database(staged_database)
        report = CandidatePublicProjectionReport(
            release_id=receipt.release_id,
            manifest_sha256=manifest_sha256,
            replay_receipt_sha256=settings.expected_replay_receipt_sha256,
            candidate_sha256=candidate_sha256,
            candidate_schema_version=_CANDIDATE_SCHEMA_VERSION,
            model_input_sha256=artifact.input_sha256,
            model_settings_sha256=artifact.settings_sha256,
            model_logical_sha256=artifact.output_sha256,
            model_file_sha256=_sha256(staged_model),
            serving_database_sha256=_sha256(staged_database),
            representative_items=summary.representative_items,
            profile_memberships=summary.profile_memberships,
            neighbor_rows=summary.neighbor_rows,
            layout_points=layout_points,
        )
        if gate.passed is False:
            raise CandidatePublicProjectionError("public model gate did not pass")
        staged_report.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
        _publish_no_replace(staged_database, settings.output_database)
        _publish_no_replace(staged_model, settings.model_output)
        _publish_no_replace(staged_report, settings.report_output)
        return report
    finally:
        staged_database.unlink(missing_ok=True)
        staged_model.unlink(missing_ok=True)
        staged_report.unlink(missing_ok=True)
