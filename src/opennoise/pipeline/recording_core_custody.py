"""Register retained MusicBrainz core artifacts during an explicit fresh replay.

These are verified safe metadata projections, not original HTTP response bodies.
The replay time is local custody time; no upstream acquisition time is invented.
Legacy replay callers and sealed catalogs are unchanged.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from opennoise.common import canonical_json
from opennoise.deployment.musicbrainz_credit_portable_release import PortableMusicBrainzCreditSource
from opennoise.pipeline.artist_identity_replay import CORE_SHA

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path


@dataclass(frozen=True)
class RecordingCoreInventory:
    """Exact local artifact bytes and a manifest bound to the approved portable source."""

    hydration: bytes
    credits: bytes
    manifest: bytes
    acquired_at: str


def prepare_core_inventory(
    source_path: Path, source: PortableMusicBrainzCreditSource, *, replayed_at: str
) -> RecordingCoreInventory:
    """Revalidate the physical approved source before describing its embedded artifacts."""
    raw = source_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CORE_SHA:
        raise ValueError("Core custody source differs from the approved portable bytes")
    if PortableMusicBrainzCreditSource.model_validate_json(raw) != source:
        raise ValueError("Core custody source differs from the replayed projection")
    hydration = source.hydration_artifact_json.encode("utf-8")
    credit_bytes = source.credit_artifact_json.encode("utf-8")
    manifest = canonical_json(
        {
            "revision": "musicbrainz-recording-core-inventory-v1",
            "portable_source_sha256": CORE_SHA,
            "custody": "retained_safe_core_projections_not_original_http_bodies",
            "replayed_at": replayed_at,
            "license": "CC0-1.0",
            "attribution": "MusicBrainz contributors",
            "license_url": "https://musicbrainz.org/doc/About/Data_License",
            "content_policy": source.content_policy,
            "artifacts": {
                "core-hydration.json": {
                    "sha256": source.hydration_artifact_sha256,
                    "bytes": len(hydration),
                },
                "core-credits.json": {
                    "sha256": source.credit_artifact_sha256,
                    "bytes": len(credit_bytes),
                },
            },
        }
    )
    return RecordingCoreInventory(hydration, credit_bytes, manifest, replayed_at)


def _register_one(  # noqa: PLR0913 -- Exact source and artifact identity, not generic options.
    connection: sqlite3.Connection,
    inventory: RecordingCoreInventory,
    *,
    source_key: str,
    snapshot_prefix: str,
    artifact_ref: str,
    artifact: bytes,
) -> None:
    """Validate the existing approved declaration and register one exact artifact atomically."""
    rows = connection.execute(
        """SELECT s.id,s.default_policy_id,s.homepage_url,s.license_name,s.license_url,
                  s.acquisition_kind,r.policy_key,r.policy_version,r.classification,
                  r.local_only,r.expires_at
           FROM data_sources s JOIN rights_policies r ON r.id=s.default_policy_id
           WHERE s.source_key=? AND EXISTS(
               SELECT 1 FROM rights_policy_seals seal WHERE seal.policy_id=r.id)""",
        (source_key,),
    ).fetchall()
    if len(rows) != 1:
        raise ValueError("Core custody source declaration is missing or ambiguous")
    row = rows[0]
    expected = (
        "https://musicbrainz.org/",
        "https://musicbrainz.org/doc/About/Data_License",
        "public_api",
        "musicbrainz-core-metadata-hydration",
        1,
        "public_domain",
        0,
        None,
    )
    if (row[2], *tuple(row)[4:]) != expected or row[3] not in ("CC0", "CC0-1.0"):
        raise ValueError("Core custody source declaration differs from approved core metadata")
    source_id, policy_id = int(row[0]), int(row[1])
    permissions = set(
        connection.execute(
            "SELECT use_kind,decision FROM active_rights_policy_permissions WHERE policy_id=?",
            (policy_id,),
        ).fetchall()
    )
    if {tuple(p) for p in permissions} != {
        (use, "allow")
        for use in ("normalize", "local_search", "display", "embed", "train", "export")
    }:
        raise ValueError("Core custody registration cannot replace restricted permissions")
    artifact_sha = hashlib.sha256(artifact).hexdigest()
    snapshot_ref = snapshot_prefix + artifact_sha
    provenance = connection.execute(
        """SELECT source_id,policy_id,artifact_sha256 FROM provenance_records
           WHERE source_id=? AND snapshot_ref=?""",
        (source_id, snapshot_ref),
    ).fetchall()
    if not provenance or any(tuple(p) != (source_id, policy_id, artifact_sha) for p in provenance):
        raise ValueError("Core custody artifact does not match native projection provenance")
    manifest_sha = hashlib.sha256(inventory.manifest).hexdigest()
    expected_snapshot = (
        source_id,
        "single_artifact",
        None,
        manifest_sha,
        inventory.acquired_at,
        policy_id,
    )
    existing = connection.execute(
        """SELECT id,source_id,snapshot_kind,upstream_version,manifest_sha256,acquired_at,policy_id
           FROM source_snapshots WHERE snapshot_ref=?""",
        (snapshot_ref,),
    ).fetchone()
    if existing is not None:
        if tuple(existing)[1:] != expected_snapshot:
            raise ValueError("Registered core snapshot differs from exact replay custody")
        snapshot_id = int(existing[0])
    else:
        cursor = connection.execute(
            """INSERT INTO source_snapshots(source_id,snapshot_ref,snapshot_kind,upstream_version,
                   manifest_sha256,acquired_at,policy_id)
                   VALUES(?,?,'single_artifact',NULL,?,?,?)""",
            (source_id, snapshot_ref, manifest_sha, inventory.acquired_at, policy_id),
        )
        if cursor.lastrowid is None:
            raise RuntimeError("Core snapshot registration produced no ID")
        snapshot_id = cursor.lastrowid
    expected_artifact = (
        artifact_ref,
        "Retained safe MusicBrainz core projection",
        "application/json",
        len(artifact),
        artifact_sha,
        artifact_sha,
        policy_id,
    )
    existing_artifacts = connection.execute(
        """SELECT artifact_ref,logical_name,media_type,byte_size,sha256,vault_key,policy_id
           FROM source_artifacts WHERE snapshot_id=?""",
        (snapshot_id,),
    ).fetchall()
    if existing_artifacts:
        if [tuple(a) for a in existing_artifacts] != [expected_artifact]:
            raise ValueError("Registered core artifact inventory differs")
    else:
        connection.execute(
            """INSERT INTO source_artifacts(snapshot_id,artifact_ref,logical_name,media_type,
                   byte_size,sha256,vault_key,policy_id) VALUES(?,?,?,?,?,?,?,?)""",
            (snapshot_id, *expected_artifact),
        )
    # This fresh-build opt-in canonicalizes the spelling, not the policy or permissions.
    connection.execute("UPDATE data_sources SET license_name='CC0-1.0' WHERE id=?", (source_id,))


def register_core_inventory(
    connection: sqlite3.Connection, inventory: RecordingCoreInventory
) -> None:
    """Register both real artifacts or roll back the complete registration; never commit."""
    if not connection.in_transaction:
        connection.execute("BEGIN")
    connection.execute("SAVEPOINT recording_core_custody")
    try:
        for key, prefix, ref, body in (
            (
                "musicbrainz_public_core_release_hydration",
                "hydration:",
                "core-hydration.json",
                inventory.hydration,
            ),
            (
                "musicbrainz_public_artist_credit_refresh",
                "artist-credit:",
                "core-credits.json",
                inventory.credits,
            ),
        ):
            _register_one(
                connection,
                inventory,
                source_key=key,
                snapshot_prefix=prefix,
                artifact_ref=ref,
                artifact=body,
            )
    except BaseException:
        connection.execute("ROLLBACK TO recording_core_custody")
        connection.execute("RELEASE recording_core_custody")
        raise
    connection.execute("RELEASE recording_core_custody")
