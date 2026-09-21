"""Create and verify a detached local-only binding for one historical replay candidate."""
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import os
import sqlite3
from contextlib import closing
from pathlib import Path  # noqa: TC003
from typing import Any, Literal

from pydantic import Field

from opennoise.models import FrozenModel
from opennoise.pipeline.release_manifest import load_release_manifest
from opennoise.pipeline.source_vault_replay import HistoricalDeclarationCombinedReplayReport
from opennoise.types import Sha256  # noqa: TC001

_SCHEMA_VERSION = 12
_OBJECT_COUNT = 62
_WIKIDATA_PERMISSIONS = {
    "normalize": "allow",
    "local_search": "allow",
    "display": "allow",
    "embed": "allow",
    "train": "allow",
    "export": "allow",
}
_LISTENBRAINZ_PERMISSIONS = {
    "normalize": "allow",
    "local_search": "deny",
    "display": "deny",
    "embed": "allow",
    "train": "allow",
    "export": "allow",
}


class HistoricalCandidateBindingError(ValueError):
    """Report a failed detached historical-candidate binding boundary."""


class HistoricalCandidateBinding(FrozenModel):
    """Versioned, non-certifying byte binding for one local historical candidate."""

    revision: Literal["phase3-historical-candidate-binding-v1"] = (
        "phase3-historical-candidate-binding-v1"
    )
    release_id: str = Field(min_length=1)
    release_manifest_path: Path
    release_manifest_sha256: Sha256
    replay_receipt_path: Path
    replay_receipt_sha256: Sha256
    candidate_database_path: Path
    candidate_database_sha256: Sha256
    candidate_schema_version: Literal[12] = 12
    historical_declaration_object_count: Literal[62] = 62
    source_artifact_pair_count: Literal[62] = 62
    local_experimental: Literal[True] = True
    certified_database: Literal[False] = False
    byte_identical_database_replay: Literal[False] = False
    publication_authorized: Literal[False] = False


class HistoricalCandidateBindingSettings(FrozenModel):
    """Fixed inputs and a fresh output for a detached local binding."""

    release_directory: Path
    candidate_database: Path
    replay_receipt: Path
    output: Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_pairs(manifest: dict[str, Any]) -> set[tuple[str, str]]:
    inputs = manifest.get("inputs")
    if not isinstance(inputs, list):
        raise HistoricalCandidateBindingError("release manifest inputs are invalid")
    pairs = {
        (str(item["source_key"]), str(item["artifact_sha256"]))
        for item in inputs
        if isinstance(item, dict)
    }
    if len(pairs) != _OBJECT_COUNT:
        raise HistoricalCandidateBindingError("release manifest does not contain 62 unique inputs")
    return pairs


def _load_receipt(path: Path) -> HistoricalDeclarationCombinedReplayReport:
    try:
        return HistoricalDeclarationCombinedReplayReport.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise HistoricalCandidateBindingError(
            "replay receipt is not a historical-declaration-qualified combined replay"
        ) from error


def _verify_receipt(
    receipt: HistoricalDeclarationCombinedReplayReport,
    manifest: dict[str, Any],
    manifest_sha256: str,
    candidate: Path,
) -> None:
    if receipt.manifest_sha256 != manifest_sha256 or receipt.release_id != manifest["release_id"]:
        raise HistoricalCandidateBindingError(
            "replay receipt does not bind the requested release manifest"
        )
    if receipt.database_path.resolve() != candidate:
        raise HistoricalCandidateBindingError(
            "replay receipt does not bind the requested candidate database"
        )
    if receipt.database_schema_version != _SCHEMA_VERSION:
        raise HistoricalCandidateBindingError("replay receipt is not for a schema-12 candidate")
    expected_pairs = _manifest_pairs(manifest)
    expected_declarations = {
        str(item["source_key"]): str(item["source_manifest_sha256"])
        for item in manifest["inputs"]
        if isinstance(item, dict)
    }
    declarations = {
        item.source_key: (item.expected_sha256, item.replayed_sha256)
        for item in receipt.historical_declarations.objects
    }
    if (
        receipt.historical_declarations.object_count != _OBJECT_COUNT
        or len(declarations) != _OBJECT_COUNT
    ):
        raise HistoricalCandidateBindingError(
            "historical declaration receipt does not cover all 62 inputs"
        )
    if set(declarations) != set(expected_declarations) or any(
        declarations[key] != (digest, digest) for key, digest in expected_declarations.items()
    ):
        raise HistoricalCandidateBindingError(
            "historical declaration hashes do not match the release manifest"
        )
    receipt_pairs = (
        {(item.source_key, item.artifact_sha256) for item in receipt.wikidata_objects}
        | {(item.source_key, item.artifact_sha256) for item in receipt.listenbrainz_daily_objects}
        | {("listenbrainz_joint_20260824_20260830", receipt.sealed_joint_artifact_sha256)}
    )
    if receipt_pairs != expected_pairs:
        raise HistoricalCandidateBindingError(
            "replay receipt source/artifact pairs do not match manifest"
        )


def _verify_database(candidate: Path, manifest: dict[str, Any]) -> None:
    expected_pairs = _manifest_pairs(manifest)
    with closing(
        sqlite3.connect(f"file:{candidate.as_posix()}?mode=ro&immutable=1", uri=True)
    ) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()
        foreign_keys = tuple(db.execute("PRAGMA foreign_key_check"))
        version = db.execute("PRAGMA user_version").fetchone()
        pairs = {
            (str(row[0]), str(row[1]))
            for row in db.execute(
                """SELECT source.source_key, artifact.sha256 FROM data_sources AS source
                   JOIN source_snapshots AS snapshot ON snapshot.source_id = source.id
                   JOIN source_artifacts AS artifact ON artifact.snapshot_id = snapshot.id"""
            )
        }
        policy_rows = tuple(
            db.execute(
                """SELECT source.source_key, source.default_policy_id, source.acquisition_kind,
                          policy.id, policy.policy_key, policy.policy_version, policy.classification,
                          policy.local_only, snapshot.policy_id, snapshot.snapshot_ref,
                          artifact.policy_id, artifact.sha256
                   FROM data_sources AS source JOIN rights_policies AS policy
                     ON policy.id = source.default_policy_id JOIN rights_policy_seals AS seal
                     ON seal.policy_id = policy.id JOIN source_snapshots AS snapshot
                     ON snapshot.source_id = source.id JOIN source_artifacts AS artifact
                     ON artifact.snapshot_id = snapshot.id"""
            )
        )
        provenance = {
            (str(row[0]), int(row[1]), str(row[2]), str(row[3]))
            for row in db.execute(
                """SELECT source.source_key, provenance.policy_id, provenance.snapshot_ref,
                          provenance.artifact_sha256 FROM provenance_records AS provenance
                   JOIN data_sources AS source ON source.id = provenance.source_id"""
            )
        }
        permissions = {
            int(row[3]): {
                str(item[0]): str(item[1])
                for item in db.execute(
                    "SELECT use_kind, decision FROM active_rights_policy_permissions WHERE policy_id = ?",
                    (int(row[3]),),
                )
            }
            for row in policy_rows
        }
    if integrity is None or integrity[0] != "ok" or foreign_keys:
        raise HistoricalCandidateBindingError(
            "candidate database integrity or foreign-key check failed"
        )
    if version is None or int(version[0]) != _SCHEMA_VERSION:
        raise HistoricalCandidateBindingError("candidate database is not schema 12")
    if pairs != expected_pairs:
        raise HistoricalCandidateBindingError(
            "candidate source/artifact pairs do not match manifest"
        )
    expected_provenance: set[tuple[str, int, str, str]] = set()
    if len(policy_rows) != _OBJECT_COUNT:
        raise HistoricalCandidateBindingError("candidate source policy boundary is incomplete")
    for row in policy_rows:
        (
            source_key,
            default_id,
            acquisition,
            policy_id,
            key,
            policy_version,
            classification,
            local,
        ) = row[:8]
        snapshot_id, snapshot_ref, artifact_id, artifact_sha = row[8:]
        expected_sha = dict(expected_pairs).get(str(source_key))
        if (
            expected_sha != str(artifact_sha)
            or str(key) != f"manifest:{source_key}:{artifact_sha}"
            or (int(default_id), int(snapshot_id), int(artifact_id)) != (int(policy_id),) * 3
            or (int(policy_version), str(acquisition), str(classification), int(local))
            != (1, "public_download", "public_domain", 0)
        ):
            raise HistoricalCandidateBindingError(
                "candidate policy state is not historical public state"
            )
        required_permissions = (
            _WIKIDATA_PERMISSIONS
            if str(source_key).startswith("wikidata_phase3_")
            else _LISTENBRAINZ_PERMISSIONS
        )
        if permissions[int(policy_id)] != required_permissions:
            raise HistoricalCandidateBindingError(
                "candidate policy permissions do not match historical state"
            )
        expected_provenance.add(
            (str(source_key), int(policy_id), str(snapshot_ref), str(artifact_sha))
        )
    if provenance != expected_provenance:
        raise HistoricalCandidateBindingError(
            "candidate provenance does not match historical policy state"
        )


def create_historical_candidate_binding(
    settings: HistoricalCandidateBindingSettings,
) -> HistoricalCandidateBinding:
    """Rehash and attest one completed historical candidate without replaying sources."""
    if settings.output.exists() or settings.output.is_symlink():
        raise HistoricalCandidateBindingError(f"binding output already exists: {settings.output}")
    if not settings.output.parent.is_dir():
        raise HistoricalCandidateBindingError(
            f"binding output parent does not exist: {settings.output.parent}"
        )
    candidate = settings.candidate_database.resolve(strict=True)
    receipt_path = settings.replay_receipt.resolve(strict=True)
    manifest_path = settings.release_directory.resolve(strict=True) / "release-manifest.json"
    manifest = load_release_manifest(settings.release_directory)
    manifest_sha256 = _sha256(manifest_path)
    receipt = _load_receipt(receipt_path)
    _verify_receipt(receipt, manifest, manifest_sha256, candidate)
    _verify_database(candidate, manifest)
    binding = HistoricalCandidateBinding(
        release_id=receipt.release_id,
        release_manifest_path=manifest_path,
        release_manifest_sha256=manifest_sha256,
        replay_receipt_path=receipt_path,
        replay_receipt_sha256=_sha256(receipt_path),
        candidate_database_path=candidate,
        candidate_database_sha256=_sha256(candidate),
    )
    payload = binding.model_dump_json(indent=2).encode() + b"\n"
    try:
        descriptor = os.open(settings.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise HistoricalCandidateBindingError(
            f"binding output already exists: {settings.output}"
        ) from error
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    return binding


def verify_historical_candidate_binding(
    binding_path: Path,
    expected_sha256: Sha256,
    *,
    release_directory: Path,
    candidate_database: Path,
    replay_receipt: Path,
) -> HistoricalCandidateBinding:
    """Fail closed unless the detached binding and all current inputs still agree."""
    try:
        binding_path = binding_path.resolve(strict=True)
    except OSError as error:
        raise HistoricalCandidateBindingError("historical candidate binding is invalid") from error
    if _sha256(binding_path) != expected_sha256:
        raise HistoricalCandidateBindingError("historical candidate binding hash does not match")
    try:
        binding = HistoricalCandidateBinding.model_validate_json(binding_path.read_bytes())
    except (OSError, ValueError) as error:
        raise HistoricalCandidateBindingError("historical candidate binding is invalid") from error
    candidate = candidate_database.resolve(strict=True)
    receipt = replay_receipt.resolve(strict=True)
    manifest = release_directory.resolve(strict=True) / "release-manifest.json"
    if (
        binding.candidate_database_path != candidate
        or binding.replay_receipt_path != receipt
        or binding.release_manifest_path != manifest
        or binding.candidate_database_sha256 != _sha256(candidate)
        or binding.replay_receipt_sha256 != _sha256(receipt)
        or binding.release_manifest_sha256 != _sha256(manifest)
    ):
        raise HistoricalCandidateBindingError(
            "historical candidate binding does not match current inputs"
        )
    return binding
