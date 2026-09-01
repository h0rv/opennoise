"""Verify the sealed input boundary for the qualified Phase 3 public release."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

SHA256 = re.compile(r"^[0-9a-f]{64}$")
RELEASE_MANIFEST_NAME = "release-manifest.json"
QUALIFICATION_SELECTION_NAME = "qualification-selection.json"
QUALIFICATION_SHARD_NAMES = tuple(f"music-genres-{ordinal:02d}.rq" for ordinal in range(8))
CATALOG_SCHEMA_VERSION = 10
RELEASE_INPUT_COUNT = 62
QUALIFICATION_SELECTION_SCHEMA_VERSION = 2
QUALIFICATION_TARGET_COUNT = 746

_EXPECTED_SOURCE_GROUPS = {
    "listenbrainz_incremental_": 7,
    "listenbrainz_joint_": 1,
    "wikidata_phase3_artists_": 8,
    "wikidata_phase3_release_groups_discovery_": 8,
    "wikidata_phase3_recordings_discovery_": 8,
    "wikidata_phase3_release_group_details_": 8,
    "wikidata_phase3_recording_details_": 7,
    "wikidata_phase3_genre_discovery_": 3,
    "wikidata_phase3_genre_labels_": 4,
    "wikidata_phase3_music_genre_qualification_v3_": 8,
}


class ReleaseManifestError(ValueError):
    """Report a malformed or incomplete sealed release manifest."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise ReleaseManifestError(f"{field} must be a lowercase SHA-256")
    return value


def load_release_manifest(release_directory: Path) -> dict[str, Any]:
    """Load and structurally validate one checked-in Phase 3 release boundary."""
    payload = _read_manifest(release_directory)
    _validate_header(payload)
    inputs = _validate_inputs(payload)
    _validate_qualification(release_directory, payload, inputs)
    return payload


def _read_manifest(release_directory: Path) -> dict[str, Any]:
    try:
        payload = json.loads((release_directory / RELEASE_MANIFEST_NAME).read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseManifestError("release manifest cannot be read") from error
    if not isinstance(payload, dict):
        raise ReleaseManifestError("release manifest must be an object")
    return payload


def _validate_header(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != 1:
        raise ReleaseManifestError("unsupported release manifest schema")
    if payload.get("catalog_schema_version") != CATALOG_SCHEMA_VERSION:
        raise ReleaseManifestError("release is not sealed against schema 10")


def _validate_inputs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    inputs = payload.get("inputs")
    if not isinstance(inputs, list) or len(inputs) != RELEASE_INPUT_COUNT:
        raise ReleaseManifestError("release must contain exactly 62 source artifacts")
    source_keys: list[str] = []
    artifact_hashes: list[str] = []
    groups: Counter[str] = Counter()
    for ordinal, item in enumerate(inputs):
        source_key, artifact_hash, group = _validate_input(item, ordinal)
        source_keys.append(source_key)
        artifact_hashes.append(artifact_hash)
        groups[group] += 1
    if len(set(source_keys)) != len(source_keys):
        raise ReleaseManifestError("source keys and artifact hashes must each be unique")
    if len(set(artifact_hashes)) != len(artifact_hashes):
        raise ReleaseManifestError("source keys and artifact hashes must each be unique")
    if dict(groups) != _EXPECTED_SOURCE_GROUPS:
        raise ReleaseManifestError("release source groups are incomplete or overbroad")
    return inputs


def _validate_input(item: object, ordinal: int) -> tuple[str, str, str]:
    if not isinstance(item, dict):
        raise ReleaseManifestError(f"input {ordinal} must be an object")
    source_key = item.get("source_key")
    if not isinstance(source_key, str):
        raise ReleaseManifestError(f"input {ordinal} has no source key")
    artifact_hash = _require_sha256(item.get("artifact_sha256"), field="artifact_sha256")
    _require_sha256(item.get("source_manifest_sha256"), field="source_manifest_sha256")
    if not isinstance(item.get("byte_size"), int) or item["byte_size"] < 0:
        raise ReleaseManifestError(f"input {ordinal} has an invalid byte size")
    if item.get("classification") != "public_domain":
        raise ReleaseManifestError(f"input {ordinal} is not public-domain metadata")
    matching_groups = [
        prefix for prefix in _EXPECTED_SOURCE_GROUPS if source_key.startswith(prefix)
    ]
    if len(matching_groups) != 1:
        raise ReleaseManifestError(f"input {ordinal} has an unexpected source key")
    return source_key, artifact_hash, matching_groups[0]


def _validate_qualification(
    release_directory: Path, payload: dict[str, Any], inputs: list[dict[str, Any]]
) -> None:
    qualification = payload.get("qualification")
    if not isinstance(qualification, dict):
        raise ReleaseManifestError("release has no qualification boundary")
    selection_sha = _require_sha256(
        qualification.get("canonical_selection_sha256"), field="canonical_selection_sha256"
    )
    if _sha256(release_directory / QUALIFICATION_SELECTION_NAME) != selection_sha:
        raise ReleaseManifestError("qualification selection does not match its sealed hash")
    selection = json.loads((release_directory / QUALIFICATION_SELECTION_NAME).read_text())
    if selection.get("schema_version") != QUALIFICATION_SELECTION_SCHEMA_VERSION:
        raise ReleaseManifestError("qualification selection is not the v3 schema")
    if len(selection.get("targets", [])) != QUALIFICATION_TARGET_COUNT:
        raise ReleaseManifestError("qualification selection is not the 746-QID v3 boundary")
    if selection.get("root_qids") != ["Q188451"]:
        raise ReleaseManifestError("qualification selection has the wrong music-genre root")
    if selection.get("excluded_direct_parent_qids") != ["Q25379"]:
        raise ReleaseManifestError("qualification selection has the wrong exclusion")
    qualification_inputs = {
        item["query_sha256"]
        for item in inputs
        if str(item["source_key"]).startswith("wikidata_phase3_music_genre_qualification_v3_")
    }
    try:
        shard_hashes = {_sha256(release_directory / name) for name in QUALIFICATION_SHARD_NAMES}
    except OSError as error:
        raise ReleaseManifestError("qualification query shard is missing") from error
    if qualification_inputs != shard_hashes:
        raise ReleaseManifestError("qualification query shards do not match the recorded inputs")


def verify_manifest_against_database(release_directory: Path, database: Path) -> dict[str, Any]:
    """Confirm that a local cache-backed database has the sealed source boundary.

    This is intentionally an offline verification. It never reacquires a live query result and
    therefore cannot silently turn a historical release into a newer graph.
    """
    manifest = load_release_manifest(release_directory)
    expected = {
        (item["source_key"], item["artifact_sha256"], item["source_manifest_sha256"])
        for item in manifest["inputs"]
    }
    with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        version = connection.execute("PRAGMA user_version").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise ReleaseManifestError("database integrity check failed")
        if version is None or version[0] != manifest["catalog_schema_version"]:
            raise ReleaseManifestError("database schema version does not match the release")
        actual = {
            (str(row[0]), str(row[1]), str(row[2]))
            for row in connection.execute(
                """SELECT source.source_key, artifact.sha256, snapshot.manifest_sha256
                   FROM data_sources AS source
                   JOIN source_snapshots AS snapshot ON snapshot.source_id = source.id
                   JOIN source_artifacts AS artifact ON artifact.snapshot_id = snapshot.id"""
            )
        }
    if actual != expected:
        missing = len(expected - actual)
        unexpected = len(actual - expected)
        raise ReleaseManifestError(
            f"database source boundary differs (missing={missing}, unexpected={unexpected})"
        )
    return {
        "release_id": manifest["release_id"],
        "schema_version": manifest["catalog_schema_version"],
        "input_artifacts": len(expected),
        "integrity_check": "ok",
    }
