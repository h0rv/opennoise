"""Project a receipt-bound schema-12 replay candidate into local-only serving rows."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from pydantic import Field

from opennoise.db import Database
from opennoise.ml.public_graph import build_public_model
from opennoise.ml.public_model_gate import PublicModelGateReport, require_public_model_gate
from opennoise.ml.publish import PublicModelPublishSummary, publish_public_model
from opennoise.ml.repository import PublicInputLoadSettings, PublicModelRepository
from opennoise.models import FrozenModel
from opennoise.models.modeling import PublicModelArtifact, PublicModelSettings
from opennoise.pipeline.historical_candidate_binding import (
    HistoricalCandidateBindingError,
    verify_historical_candidate_binding,
)
from opennoise.pipeline.public_release import _release_policy_id
from opennoise.pipeline.release_manifest import load_release_manifest
from opennoise.pipeline.source_vault_replay import HistoricalDeclarationCombinedReplayReport
from opennoise.types import Sha256  # noqa: TC001

_CANDIDATE_SCHEMA_VERSION = 12
_SOURCE_ARTIFACT_COUNT = 62
_V2_RECEIPT_REVISION = "phase3-candidate-public-projection-v2"
_EXPECTED_LAYOUT_POINTS = {
    "public": 468,
    "public-direct": 468,
    "public-community": 468,
    "public-taxonomy": 598,
}
_EXPECTED_REPRESENTATIVE_ITEMS = 3_344
_EXPECTED_PROFILE_MEMBERSHIPS = 26_525
_EXPECTED_NEIGHBOR_ROWS = 34_348
_HISTORICAL_WIKIDATA_PERMISSIONS = {
    "normalize": "allow",
    "local_search": "allow",
    "display": "allow",
    "embed": "allow",
    "train": "allow",
    "export": "allow",
}
_HISTORICAL_LISTENBRAINZ_PERMISSIONS = {
    "normalize": "allow",
    "local_search": "deny",
    "display": "deny",
    "embed": "allow",
    "train": "allow",
    "export": "allow",
}


class CandidatePublicProjectionError(RuntimeError):
    """Report a candidate projection boundary or output failure."""


class CandidatePublicProjectionSettings(FrozenModel):
    """All explicit inputs and fresh destinations for a local-only projection."""

    release_directory: Path
    candidate_database: Path
    replay_receipt: Path
    historical_candidate_binding: Path
    expected_candidate_sha256: Sha256
    expected_replay_receipt_sha256: Sha256
    expected_historical_candidate_binding_sha256: Sha256
    output_database: Path
    model_output: Path
    report_output: Path


class CandidatePublicProjectionReport(FrozenModel):
    """Uncertified receipt for one independently writable candidate projection."""

    revision: str = "phase3-candidate-public-projection-v1"
    release_id: str
    manifest_sha256: Sha256
    historical_candidate_binding_sha256: Sha256
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


class CandidatePublicProjectionV2Settings(FrozenModel):
    """Inputs and fresh local destinations for the source-artifact v2 experiment."""

    release_directory: Path
    candidate_database: Path
    replay_receipt: Path
    historical_candidate_binding: Path
    expected_candidate_sha256: Sha256
    expected_replay_receipt_sha256: Sha256
    expected_historical_candidate_binding_sha256: Sha256
    output_database: Path
    model_output: Path
    report_output: Path


class CandidatePublicProjectionV2Report(FrozenModel):
    """Logical receipt for an uncertified, local-only source-artifact-v2 projection."""

    revision: Literal["phase3-candidate-public-projection-v2"] = _V2_RECEIPT_REVISION
    release_id: str
    manifest_sha256: Sha256
    historical_candidate_binding_sha256: Sha256
    replay_receipt_sha256: Sha256
    candidate_sha256: Sha256
    candidate_schema_version: Literal[12] = 12
    source_artifact_count: Literal[62] = 62
    source_artifact_set_sha256: Sha256
    input_load_settings: dict[str, Any]
    input_load_settings_sha256: Sha256
    model_settings: dict[str, Any]
    model_input_sha256: Sha256
    model_settings_sha256: Sha256
    model_logical_sha256: Sha256
    model_file_sha256: Sha256
    graph_v2_evidence_refs: int = Field(ge=0)
    gate: PublicModelGateReport
    serving_database_sha256: Sha256
    serving_database_schema_version: int = Field(ge=1)
    certified_database: Literal[False] = False
    byte_identical_database_replay: Literal[False] = False
    receipt_logical_sha256: Sha256


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _logical_sha256(value: object) -> Sha256:
    """Hash a JSON-shaped logical receipt payload independent of file formatting."""
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
        ).encode()
    ).hexdigest()


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


def _load_receipt(path: Path, expected_sha256: Sha256) -> HistoricalDeclarationCombinedReplayReport:
    """Load only the declaration-qualified replay receipt.

    The older combined receipt describes a deliberately local-only replay.  It
    is not evidence that the reconstructed candidate carries the historical
    source declarations required at this public projection boundary.
    """
    actual_sha256 = _sha256(path)
    if actual_sha256 != expected_sha256:
        raise CandidatePublicProjectionError(
            "replay receipt hash does not match the requested input"
        )
    try:
        return HistoricalDeclarationCombinedReplayReport.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise CandidatePublicProjectionError(
            "replay receipt is not a historical-declaration-qualified combined replay"
        ) from error


def _manifest_source_artifacts(manifest: dict[str, Any]) -> set[tuple[str, str]]:
    inputs = manifest["inputs"]
    if not isinstance(inputs, list):  # guarded by load_release_manifest
        raise CandidatePublicProjectionError("release manifest inputs are invalid")
    return {
        (str(item["source_key"]), str(item["artifact_sha256"]))
        for item in inputs
        if isinstance(item, dict)
    }


def _receipt_artifact_hashes(receipt: HistoricalDeclarationCombinedReplayReport) -> set[str]:
    return {
        *(item.artifact_sha256 for item in receipt.wikidata_objects),
        *(item.artifact_sha256 for item in receipt.listenbrainz_daily_objects),
        receipt.sealed_joint_artifact_sha256,
    }


def _verify_historical_declarations(
    manifest: dict[str, Any], receipt: HistoricalDeclarationCombinedReplayReport
) -> None:
    """Require a complete exact replay of each manifest declaration digest."""
    expected = {
        str(item["source_key"]): str(item["source_manifest_sha256"])
        for item in manifest["inputs"]
        if isinstance(item, dict)
    }
    declarations = receipt.historical_declarations
    actual = {
        item.source_key: (item.expected_sha256, item.replayed_sha256)
        for item in declarations.objects
    }
    if declarations.object_count != len(expected) or len(actual) != len(expected):
        raise CandidatePublicProjectionError(
            "historical declaration receipt does not cover all 62 manifest inputs"
        )
    if set(actual) != set(expected):
        raise CandidatePublicProjectionError(
            "historical declaration receipt source keys do not match the release manifest"
        )
    if any(actual[key] != (digest, digest) for key, digest in expected.items()):
        raise CandidatePublicProjectionError(
            "historical declaration hashes do not match the release manifest"
        )


def _expected_historical_permissions(source_key: str) -> dict[str, str]:
    if source_key.startswith("wikidata_phase3_"):
        return _HISTORICAL_WIKIDATA_PERMISSIONS
    if source_key.startswith("listenbrainz_"):
        return _HISTORICAL_LISTENBRAINZ_PERMISSIONS
    raise CandidatePublicProjectionError("manifest has an unsupported historical source policy")


def _verify_candidate_policy_provenance(
    connection: sqlite3.Connection, manifest: dict[str, Any]
) -> None:
    """Verify that each source's sealed historical policy owns its provenance.

    The receipt proves declarations, but cannot itself make a candidate's
    mutable database policy public.  Check the source, snapshot, artifact, and
    provenance links against the historical constructor's policy contract.
    """
    expected_artifacts = {
        str(item["source_key"]): str(item["artifact_sha256"])
        for item in manifest["inputs"]
        if isinstance(item, dict)
    }
    rows = tuple(
        connection.execute(
            """SELECT source.source_key, source.default_policy_id, source.acquisition_kind,
                      policy.id, policy.policy_key, policy.policy_version, policy.classification,
                      policy.local_only,
                      snapshot.id, snapshot.policy_id, snapshot.snapshot_ref,
                      artifact.policy_id, artifact.sha256
               FROM data_sources AS source
               JOIN rights_policies AS policy ON policy.id = source.default_policy_id
               JOIN rights_policy_seals AS seal ON seal.policy_id = policy.id
               JOIN source_snapshots AS snapshot ON snapshot.source_id = source.id
               JOIN source_artifacts AS artifact ON artifact.snapshot_id = snapshot.id"""
        )
    )
    by_source = {str(row[0]): row for row in rows}
    if len(rows) != len(expected_artifacts) or set(by_source) != set(expected_artifacts):
        raise CandidatePublicProjectionError("candidate source policy boundary is incomplete")
    expected_provenance: set[tuple[str, int, str, str]] = set()
    for row in rows:
        source_key = str(row[0])
        default_policy_id, acquisition_kind = int(row[1]), str(row[2])
        policy_id, policy_key, policy_version, classification, local_only = (
            int(row[3]),
            str(row[4]),
            int(row[5]),
            str(row[6]),
            int(row[7]),
        )
        snapshot_policy_id, snapshot_ref = int(row[9]), str(row[10])
        artifact_policy_id, artifact_sha256 = int(row[11]), str(row[12])
        if (
            artifact_sha256 != expected_artifacts[source_key]
            or policy_key != f"manifest:{source_key}:{artifact_sha256}"
            or (default_policy_id, snapshot_policy_id, artifact_policy_id)
            != (
                policy_id,
                policy_id,
                policy_id,
            )
            or (policy_version, acquisition_kind, classification, local_only)
            != (1, "public_download", "public_domain", 0)
        ):
            raise CandidatePublicProjectionError(
                "candidate source policy is not the historical public policy"
            )
        permissions = {
            str(permission[0]): str(permission[1])
            for permission in connection.execute(
                "SELECT use_kind, decision FROM active_rights_policy_permissions "
                "WHERE policy_id = ?",
                (policy_id,),
            )
        }
        if permissions != _expected_historical_permissions(source_key):
            raise CandidatePublicProjectionError(
                "candidate source policy permissions do not match historical declarations"
            )
        expected_provenance.add((source_key, policy_id, snapshot_ref, artifact_sha256))
    actual_provenance = {
        (str(row[0]), int(row[1]), str(row[2]), str(row[3]))
        for row in connection.execute(
            """SELECT source.source_key, provenance.policy_id, provenance.snapshot_ref,
                      provenance.artifact_sha256
               FROM provenance_records AS provenance
               JOIN data_sources AS source ON source.id = provenance.source_id"""
        )
    }
    if actual_provenance != expected_provenance:
        raise CandidatePublicProjectionError(
            "candidate provenance does not match its historical source policies"
        )


def _verify_candidate_boundary(
    settings: CandidatePublicProjectionSettings,
) -> tuple[dict[str, Any], HistoricalDeclarationCombinedReplayReport, str, str]:
    try:
        verify_historical_candidate_binding(
            settings.historical_candidate_binding,
            settings.expected_historical_candidate_binding_sha256,
            release_directory=settings.release_directory,
            candidate_database=settings.candidate_database,
            replay_receipt=settings.replay_receipt,
        )
    except HistoricalCandidateBindingError as error:
        raise CandidatePublicProjectionError(
            f"historical candidate binding verification failed: {error}"
        ) from error
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
    _verify_historical_declarations(manifest, receipt)
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
        _verify_candidate_policy_provenance(connection, manifest)
    if integrity is None or integrity[0] != "ok":
        raise CandidatePublicProjectionError("candidate database integrity check failed")
    if version is None or int(version[0]) != _CANDIDATE_SCHEMA_VERSION:
        raise CandidatePublicProjectionError("candidate database is not schema 12")
    if actual_source_artifacts != manifest_source_artifacts:
        raise CandidatePublicProjectionError(
            "candidate source-key/artifact hashes do not match the release manifest"
        )
    return manifest, receipt, manifest_sha256, candidate_sha256


def _v2_source_artifacts(manifest: dict[str, Any]) -> set[tuple[str, str, str]]:
    """Return the complete release source identity required by the v2 graph."""
    inputs = manifest.get("inputs")
    if not isinstance(inputs, list):
        raise CandidatePublicProjectionError("release manifest inputs are invalid")
    result = {
        (str(item["source_key"]), str(item["snapshot_ref"]), str(item["artifact_sha256"]))
        for item in inputs
        if isinstance(item, dict)
    }
    if len(result) != _SOURCE_ARTIFACT_COUNT:
        raise CandidatePublicProjectionError(
            "release manifest does not contain 62 source artifacts"
        )
    return result


def _verify_v2_database_source_attestation(database: Path, manifest: dict[str, Any]) -> Sha256:
    """Bind all 62 release source/snapshot/artifact identities before graph loading."""
    expected = _v2_source_artifacts(manifest)
    with closing(
        sqlite3.connect(f"file:{database.as_posix()}?mode=ro&immutable=1", uri=True)
    ) as connection:
        rows = tuple(
            connection.execute(
                """SELECT source.source_key, snapshot.snapshot_ref, artifact.sha256
                   FROM data_sources AS source
                   JOIN source_snapshots AS snapshot ON snapshot.source_id = source.id
                   JOIN source_artifacts AS artifact ON artifact.snapshot_id = snapshot.id"""
            )
        )
        actual = {(str(row[0]), str(row[1]), str(row[2])) for row in rows}
    if len(rows) != _SOURCE_ARTIFACT_COUNT or actual != expected:
        raise CandidatePublicProjectionError(
            "candidate source/snapshot/artifact identities do not match all 62 release inputs"
        )
    return _logical_sha256(sorted(expected))


def _v2_settings() -> tuple[PublicInputLoadSettings, PublicModelSettings]:
    """Freeze the modest release bounds and opt into stable source-artifact refs."""
    load = PublicInputLoadSettings(
        max_direct_memberships=100_000,
        max_artist_pairs=250_000,
        artist_pair_evidence_ref_version="source_artifacts_v2",
    )
    model = PublicModelSettings(
        max_direct_memberships=100_000,
        max_artist_pairs=250_000,
        neighbors_per_genre=25,
    )
    return load, model


def _build_model_v2(
    database: Path,
) -> tuple[bytes, PublicModelArtifact, PublicInputLoadSettings, PublicModelSettings]:
    """Build only with the explicit source-artifact-v2 evidence reference contract."""
    load_settings, model_settings = _v2_settings()
    with closing(
        sqlite3.connect(f"file:{database.as_posix()}?mode=ro&immutable=1", uri=True)
    ) as connection:
        connection.row_factory = sqlite3.Row
        inputs = PublicModelRepository(connection, connection).load(load_settings)
    artifact = build_public_model(inputs, model_settings)
    return artifact.model_dump_json().encode(), artifact, load_settings, model_settings


def _v2_evidence_reference(source_key: str, snapshot_ref: str, artifact_sha256: str) -> str:
    return (
        "listenbrainz:v2:source_key="
        f"{quote(source_key, safe='')}&snapshot_ref={quote(snapshot_ref, safe='')}"
        f"&artifact_sha256={artifact_sha256}"
    )


def _v2_direct_evidence_refs(database: Path, manifest: dict[str, Any]) -> set[str]:
    """Return only direct seed refs backed by an attested catalog provenance row."""
    expected = _v2_source_artifacts(manifest)
    refs: set[str] = set()
    with closing(
        sqlite3.connect(f"file:{database.as_posix()}?mode=ro&immutable=1", uri=True)
    ) as connection:
        for (
            evidence_id,
            source_record_id,
            source_key,
            snapshot_ref,
            artifact_sha256,
        ) in connection.execute(
            """SELECT evidence.id, evidence.source_record_id,
                          source.source_key, snapshot.snapshot_ref, artifact.sha256
                   FROM normalizable_artist_genre_evidence AS evidence
                   JOIN provenance_records AS provenance ON provenance.id = evidence.provenance_id
                   JOIN data_sources AS source ON source.id = provenance.source_id
                   JOIN source_snapshots AS snapshot
                     ON snapshot.source_id = source.id
                    AND snapshot.snapshot_ref = provenance.snapshot_ref
                   JOIN source_artifacts AS artifact
                     ON artifact.snapshot_id = snapshot.id
                    AND artifact.sha256 = provenance.artifact_sha256
                   JOIN active_rights_policy_permissions AS embed_permission
                     ON embed_permission.policy_id = evidence.policy_id
                    AND embed_permission.use_kind = 'embed'
                    AND embed_permission.decision = 'allow'
                   WHERE evidence.evidence_kind = 'direct_source_claim'
                     AND evidence.method_key IN (
                       'direct_musicbrainz_artist_genre',
                       'musicbrainz_artist_genre', 'wikidata_p136'
                     )"""
        ):
            if (str(source_key), str(snapshot_ref), str(artifact_sha256)) in expected:
                refs.add(f"catalog:artist-genre:{int(evidence_id)}:{source_record_id!s}")
    return refs


def _verify_v2_graph_attestation(
    artifact: PublicModelArtifact, manifest: dict[str, Any], database: Path
) -> int:
    """Require the model's artifacts and one-hop graph references to name release inputs."""
    expected = _v2_source_artifacts(manifest)
    # rpartition returns (source_key, separator, declared_hash); source_key and the
    # content hash are independently checked so a malformed key cannot be hidden.
    actual = {
        (item.artifact_key.rpartition(":")[0], item.snapshot, item.content_sha256)
        for item in artifact.artifacts
        if item.artifact_key.rpartition(":")[1] == ":"
        and item.artifact_key.rpartition(":")[2] == item.content_sha256
    }
    if actual != expected or len(artifact.artifacts) != _SOURCE_ARTIFACT_COUNT:
        raise CandidatePublicProjectionError(
            "model artifacts do not exactly attest all 62 release source artifacts"
        )

    allowed_refs = {_v2_evidence_reference(*item) for item in expected}
    direct_refs = _v2_direct_evidence_refs(database, manifest) & {
        reference
        for profile in artifact.profiles
        if profile.profile_kind == "direct"
        for membership in profile.memberships
        for reference in membership.evidence_refs
        if reference.startswith("catalog:artist-genre:")
    }
    reference_count = 0
    for profile in artifact.profiles:
        if profile.profile_kind != "one_hop":
            continue
        for membership in profile.memberships:
            if {component.component_kind for component in membership.components} != {
                "listenbrainz_one_hop"
            }:
                raise CandidatePublicProjectionError("one-hop graph has an unexpected component")
            references = {
                reference
                for component in membership.components
                if component.component_kind == "listenbrainz_one_hop"
                for reference in component.evidence_refs
            }
            if references != set(membership.evidence_refs):
                raise CandidatePublicProjectionError(
                    "one-hop component refs do not match membership refs"
                )
            v2_references = {
                reference for reference in references if reference.startswith("listenbrainz:v2:")
            }
            if not v2_references:
                raise CandidatePublicProjectionError(
                    "one-hop graph lacks source_artifacts_v2 evidence"
                )
            if not v2_references <= allowed_refs or references - v2_references - direct_refs:
                raise CandidatePublicProjectionError(
                    "one-hop graph evidence is outside the release source attestation"
                )
            reference_count += len(v2_references)
    if reference_count == 0:
        raise CandidatePublicProjectionError("v2 graph contains no source_artifacts_v2 evidence")
    return reference_count


def _database_schema_version(path: Path) -> int:
    with closing(
        sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)
    ) as connection:
        row = connection.execute("PRAGMA user_version").fetchone()
    if row is None:
        raise CandidatePublicProjectionError("projected database has no schema version")
    return int(row[0])


def _v2_receipt_logical_sha256(report: CandidatePublicProjectionV2Report) -> Sha256:
    return _logical_sha256(report.model_dump(mode="json", exclude={"receipt_logical_sha256"}))


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
            historical_candidate_binding_sha256=(
                settings.expected_historical_candidate_binding_sha256
            ),
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


def project_candidate_public_model_v2(
    settings: CandidatePublicProjectionV2Settings,
) -> CandidatePublicProjectionV2Report:
    """Project an independently attested source-artifact-v2 model into fresh local files.

    Unlike the sealed v1 replay, this experiment records its newly computed
    hashes.  It never compares them with the Phase 3 manifest model boundary.
    """
    legacy_settings = CandidatePublicProjectionSettings(**settings.model_dump())
    _require_fresh_outputs(legacy_settings)
    manifest, receipt, manifest_sha256, candidate_sha256 = _verify_candidate_boundary(
        legacy_settings
    )
    source_artifact_set_sha256 = _verify_v2_database_source_attestation(
        settings.candidate_database.resolve(strict=True), manifest
    )
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
        model_payload, artifact, load_settings, model_settings = _build_model_v2(staged_database)
        _verify_v2_graph_attestation(artifact, manifest, staged_database)
        staged_model.write_bytes(model_payload)
        gate = require_public_model_gate(
            artifact,
            artifact_file_sha256=_sha256(staged_model),
            artifact_byte_size=len(model_payload),
        )
        if gate.passed is False:
            raise CandidatePublicProjectionError("public model gate did not pass")
        with Database(staged_database).connect() as connection, connection:
            policy_id = _release_policy_id(connection, receipt.release_id)
        summary = publish_public_model(staged_database, staged_model, policy_id=policy_id)
        if (
            summary.output_sha256 != artifact.output_sha256
            or summary.profile_memberships
            != sum(len(profile.memberships) for profile in artifact.profiles)
            or summary.neighbor_rows != len(artifact.neighbors)
        ):
            raise CandidatePublicProjectionError("persisted graph does not match the v2 model")
        _checkpoint_database(staged_database)
        _verify_projected_database(staged_database)
        report = CandidatePublicProjectionV2Report(
            release_id=receipt.release_id,
            manifest_sha256=manifest_sha256,
            historical_candidate_binding_sha256=settings.expected_historical_candidate_binding_sha256,
            replay_receipt_sha256=settings.expected_replay_receipt_sha256,
            candidate_sha256=candidate_sha256,
            source_artifact_set_sha256=source_artifact_set_sha256,
            input_load_settings=load_settings.model_dump(mode="json"),
            input_load_settings_sha256=_logical_sha256(load_settings.model_dump(mode="json")),
            model_settings=model_settings.model_dump(mode="json"),
            model_input_sha256=artifact.input_sha256,
            model_settings_sha256=artifact.settings_sha256,
            model_logical_sha256=artifact.output_sha256,
            model_file_sha256=_sha256(staged_model),
            graph_v2_evidence_refs=_verify_v2_graph_attestation(
                artifact, manifest, staged_database
            ),
            gate=gate,
            serving_database_sha256=_sha256(staged_database),
            serving_database_schema_version=_database_schema_version(staged_database),
            receipt_logical_sha256="0" * 64,
        )
        report = report.model_copy(
            update={"receipt_logical_sha256": _v2_receipt_logical_sha256(report)}
        )
        staged_report.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
        _publish_no_replace(staged_database, settings.output_database)
        _publish_no_replace(staged_model, settings.model_output)
        _publish_no_replace(staged_report, settings.report_output)
        return report
    finally:
        staged_database.unlink(missing_ok=True)
        staged_model.unlink(missing_ok=True)
        staged_report.unlink(missing_ok=True)
