"""Report the local-only MusicBrainz direct discovery delta.

The report is an accounting view over the verified portable custody object.  It
does not create memberships, choose display names, or write a public asset.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreClaim,
    DirectProperGenreCustodyError,
    DirectProperGenreCustodyReceipt,
    iter_verified_portable_direct_proper_genre_claims,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

_EXPECTED_STATIC_DISCOVERY_SEED_COUNT: Final = 344
_STATIC_ASSET: Final = "static_discovery"
_ATLAS_ASSET: Final = "semantic_atlas"
_REVIEW_FIELDS: Final = (
    "seed_id",
    "artist_mbid",
    "musicbrainz_genre_id",
    "source_record_id",
    "source_record_sha256",
    "source_evidence_ref",
)


class DirectDiscoveryDeltaError(ValueError):
    """The local report inputs do not prove an exact, certified comparison."""


@dataclass(frozen=True, slots=True)
class _ClaimCounts:
    observation_count: int
    distinct_seed_artist_pair_count: int
    distinct_artist_mbid_count: int
    distinct_source_record_count: int
    distinct_source_evidence_count: int


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path, *, label: str) -> object:
    try:
        return json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise DirectDiscoveryDeltaError(f"{label} is not valid JSON") from error


def _mapping(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise DirectDiscoveryDeltaError(f"{label} must be a JSON object")
    return {str(key): item for key, item in value.items()}


def _certified_asset(*, manifest_path: Path, asset_path: Path, asset_key: str) -> dict[str, object]:
    """Return an asset only when the certified manifest binds its exact bytes."""
    manifest = _mapping(_load_json(manifest_path, label="certified manifest"), label="manifest")
    assets = _mapping(manifest.get("assets"), label="manifest assets")
    record = _mapping(assets.get(asset_key), label=f"manifest asset {asset_key}")
    expected_path, expected_sha = record.get("path"), record.get("sha256")
    if not isinstance(expected_path, str) or not isinstance(expected_sha, str):
        raise DirectDiscoveryDeltaError(f"manifest asset {asset_key} lacks path or SHA-256")
    try:
        actual_relative_path = asset_path.relative_to(manifest_path.parent).as_posix()
    except ValueError as error:
        raise DirectDiscoveryDeltaError(f"{asset_key} is outside the certified site") from error
    try:
        actual_sha = _sha256(asset_path)
    except OSError as error:
        raise DirectDiscoveryDeltaError(f"{asset_key} bytes cannot be read") from error
    if actual_relative_path != expected_path or actual_sha != expected_sha:
        raise DirectDiscoveryDeltaError(f"{asset_key} bytes do not match the certified manifest")
    return _mapping(_load_json(asset_path, label=asset_key), label=asset_key)


def _node_ids(rows: object, *, field: str, label: str) -> frozenset[str]:
    if not isinstance(rows, list):
        raise DirectDiscoveryDeltaError(f"{label} must be a JSON list")
    values: list[str] = []
    for row in rows:
        value = _mapping(row, label=f"{label} entry").get(field)
        if not isinstance(value, str) or not value:
            raise DirectDiscoveryDeltaError(f"{label} entry lacks {field}")
        values.append(value)
    result = frozenset(values)
    if len(result) != len(values):
        raise DirectDiscoveryDeltaError(f"{label} repeats a node ID")
    return result


def _claim_counts(
    connection: sqlite3.Connection, *, scope: Literal["all", "shared", "candidate"]
) -> _ClaimCounts:
    match scope:
        case "all":
            metrics_sql = """
                SELECT
                    COUNT(*) AS observation_count,
                    COUNT(DISTINCT artist_mbid) AS distinct_artist_mbid_count,
                    COUNT(DISTINCT source_record_sha256) AS distinct_source_record_count,
                    COUNT(DISTINCT source_evidence_ref) AS distinct_source_evidence_count
                FROM claims
                """
            pairs_sql = """
                SELECT COUNT(*) FROM (
                    SELECT seed_id, artist_mbid FROM claims GROUP BY seed_id, artist_mbid
                )
                """
        case "shared":
            metrics_sql = """
                SELECT
                    COUNT(*) AS observation_count,
                    COUNT(DISTINCT artist_mbid) AS distinct_artist_mbid_count,
                    COUNT(DISTINCT source_record_sha256) AS distinct_source_record_count,
                    COUNT(DISTINCT source_evidence_ref) AS distinct_source_evidence_count
                FROM claims JOIN static_ids USING (seed_id)
                """
            pairs_sql = """
                SELECT COUNT(*) FROM (
                    SELECT claims.seed_id, claims.artist_mbid
                    FROM claims JOIN static_ids USING (seed_id)
                    GROUP BY claims.seed_id, claims.artist_mbid
                )
                """
        case "candidate":
            metrics_sql = """
                SELECT
                    COUNT(*) AS observation_count,
                    COUNT(DISTINCT artist_mbid) AS distinct_artist_mbid_count,
                    COUNT(DISTINCT source_record_sha256) AS distinct_source_record_count,
                    COUNT(DISTINCT source_evidence_ref) AS distinct_source_evidence_count
                FROM claims LEFT JOIN static_ids USING (seed_id)
                WHERE static_ids.seed_id IS NULL
                """
            pairs_sql = """
                SELECT COUNT(*) FROM (
                    SELECT claims.seed_id, claims.artist_mbid
                    FROM claims LEFT JOIN static_ids USING (seed_id)
                    WHERE static_ids.seed_id IS NULL
                    GROUP BY claims.seed_id, claims.artist_mbid
                )
                """
    row = connection.execute(metrics_sql).fetchone()
    pair_row = connection.execute(pairs_sql).fetchone()
    if row is None or pair_row is None:
        raise DirectDiscoveryDeltaError("custody aggregate query did not return a row")
    return _ClaimCounts(
        observation_count=int(row["observation_count"]),
        distinct_seed_artist_pair_count=int(pair_row[0]),
        distinct_artist_mbid_count=int(row["distinct_artist_mbid_count"]),
        distinct_source_record_count=int(row["distinct_source_record_count"]),
        distinct_source_evidence_count=int(row["distinct_source_evidence_count"]),
    )


def _counts_json(counts: _ClaimCounts) -> dict[str, int]:
    return {
        "observation_count": counts.observation_count,
        "distinct_seed_artist_pair_count": counts.distinct_seed_artist_pair_count,
        "distinct_artist_mbid_count": counts.distinct_artist_mbid_count,
        "distinct_source_record_count": counts.distinct_source_record_count,
        "distinct_source_evidence_count": counts.distinct_source_evidence_count,
    }


def build_musicbrainz_direct_discovery_delta(
    *,
    custody_receipt_path: Path,
    custody_object_store: Path,
    static_discovery_path: Path,
    certified_manifest_path: Path,
    certified_layout_path: Path,
) -> dict[str, object]:
    """Build a bounded review report without adding data to any public surface."""
    try:
        receipt = DirectProperGenreCustodyReceipt.model_validate_json(
            custody_receipt_path.read_bytes()
        )
    except (OSError, ValueError) as error:
        raise DirectDiscoveryDeltaError("custody receipt is invalid") from error
    if receipt.public_export_authorized:
        raise DirectDiscoveryDeltaError("custody receipt must deny public export")

    static_payload = _certified_asset(
        manifest_path=certified_manifest_path,
        asset_path=static_discovery_path,
        asset_key=_STATIC_ASSET,
    )
    static_ids = _node_ids(static_payload.get("genres"), field="node_id", label="static genres")
    if len(static_ids) != _EXPECTED_STATIC_DISCOVERY_SEED_COUNT:
        raise DirectDiscoveryDeltaError(
            "current static discovery must contain exactly 344 node IDs"
        )

    atlas_payload = _certified_asset(
        manifest_path=certified_manifest_path,
        asset_path=certified_layout_path,
        asset_key=_ATLAS_ASSET,
    )
    placed_ids = _node_ids(atlas_payload.get("nodes"), field="id", label="certified layout nodes")
    if not static_ids <= placed_ids:
        raise DirectDiscoveryDeltaError("current static discovery contains an unplaced map node")

    with tempfile.TemporaryDirectory(prefix="musicbrainz-direct-delta-") as directory:
        connection = sqlite3.connect(Path(directory) / "claims.sqlite")
        connection.row_factory = sqlite3.Row
        try:
            try:
                _stream_claims_to_sqlite(
                    connection,
                    iter_verified_portable_direct_proper_genre_claims(
                        receipt, object_store=custody_object_store
                    ),
                    static_ids=static_ids,
                    placed_ids=placed_ids,
                )
            except DirectProperGenreCustodyError as error:
                raise DirectDiscoveryDeltaError("custody object did not verify") from error
            report = _report_from_sqlite(connection, receipt=receipt)
        finally:
            connection.close()
    candidate_counts = _mapping(
        _mapping(report["evidence_counts"], label="report evidence counts").get("candidate_only"),
        label="candidate evidence counts",
    )
    review_row_count = candidate_counts.get("distinct_seed_artist_pair_count")
    if not isinstance(review_row_count, int):
        raise DirectDiscoveryDeltaError("candidate evidence counts lack distinct pair count")
    return {
        "revision": "musicbrainz-direct-discovery-delta-v1",
        "publication_scope": "local_review_only",
        "public_export_authorized": False,
        "release_gate": False,
        "name_display_coverage": {
            "status": "abstained",
            "reason": "verified custody claims have no source-bound artist-name field",
        },
        "inputs": {
            "custody_receipt_output_sha256": receipt.output_sha256,
            "custody_claims_object_sha256": receipt.claims_object_sha256,
            "static_discovery_sha256": _sha256(static_discovery_path),
            "certified_layout_sha256": _sha256(certified_layout_path),
        },
        **report,
        "review_projection": {
            "review_row_count": review_row_count,
            "source_fields": _REVIEW_FIELDS,
            "requires_artist_names": False,
            "static_ui_json_size_estimate": "abstained",
            "static_ui_reason": (
                "a public UI would need separately approved source-bound artist names or abstention"
            ),
        },
    }


def _stream_claims_to_sqlite(
    connection: sqlite3.Connection,
    claims: Iterable[DirectProperGenreClaim],
    *,
    static_ids: frozenset[str],
    placed_ids: frozenset[str],
) -> None:
    """Store only scalar claim fields while the verified custody stream is replayed."""
    connection.executescript(
        """
        CREATE TABLE claims (
            seed_id TEXT NOT NULL,
            artist_mbid TEXT NOT NULL,
            source_record_sha256 TEXT NOT NULL,
            source_evidence_ref TEXT NOT NULL
        );
        CREATE TABLE static_ids (seed_id TEXT PRIMARY KEY);
        CREATE TABLE placed_ids (seed_id TEXT PRIMARY KEY);
        """
    )
    connection.executemany("INSERT INTO static_ids VALUES (?)", ((value,) for value in static_ids))
    connection.executemany("INSERT INTO placed_ids VALUES (?)", ((value,) for value in placed_ids))
    for claim in claims:
        connection.execute(
            "INSERT INTO claims VALUES (?, ?, ?, ?)",
            (
                claim.seed_id,
                claim.artist_mbid,
                claim.source_record_sha256,
                claim.source_evidence_ref,
            ),
        )
    connection.executescript(
        """
        CREATE INDEX claims_seed_id ON claims(seed_id);
        """
    )


def _report_from_sqlite(
    connection: sqlite3.Connection, *, receipt: DirectProperGenreCustodyReceipt
) -> dict[str, object]:
    seed_rows = connection.execute(
        "SELECT DISTINCT seed_id FROM claims ORDER BY seed_id"
    ).fetchall()
    direct_ids = frozenset(str(row["seed_id"]) for row in seed_rows)
    if len(direct_ids) != receipt.seed_count:
        raise DirectDiscoveryDeltaError(
            "verified custody claims do not replay the receipt seed count"
        )
    static_count = int(connection.execute("SELECT COUNT(*) FROM static_ids").fetchone()[0])
    shared_count = int(
        connection.execute(
            "SELECT COUNT(DISTINCT claims.seed_id) FROM claims JOIN static_ids USING (seed_id)"
        ).fetchone()[0]
    )
    candidate_rows = connection.execute(
        """
        SELECT
            claims.seed_id,
            COUNT(*) AS observation_count,
            COUNT(DISTINCT claims.artist_mbid) AS distinct_seed_artist_pair_count,
            COUNT(DISTINCT claims.artist_mbid) AS distinct_artist_mbid_count,
            COUNT(DISTINCT claims.source_record_sha256) AS distinct_source_record_count,
            COUNT(DISTINCT claims.source_evidence_ref) AS distinct_source_evidence_count,
            EXISTS(SELECT 1 FROM placed_ids WHERE placed_ids.seed_id = claims.seed_id) AS placed
        FROM claims LEFT JOIN static_ids USING (seed_id)
        WHERE static_ids.seed_id IS NULL
        GROUP BY claims.seed_id
        ORDER BY claims.seed_id
        """
    ).fetchall()
    per_seed = tuple(
        {
            "seed_id": str(row["seed_id"]),
            "placement": "placed" if row["placed"] else "unplaced",
            "observation_count": int(row["observation_count"]),
            "distinct_seed_artist_pair_count": int(row["distinct_seed_artist_pair_count"]),
            "distinct_artist_mbid_count": int(row["distinct_artist_mbid_count"]),
            "distinct_source_record_count": int(row["distinct_source_record_count"]),
            "distinct_source_evidence_count": int(row["distinct_source_evidence_count"]),
        }
        for row in candidate_rows
    )
    return {
        "seed_sets": {
            "direct_seed_count": len(direct_ids),
            "current_static_discovery_seed_count": static_count,
            "shared_seed_count": shared_count,
            "candidate_only_seed_count": len(candidate_rows),
        },
        "candidate_only_placement": {
            "placed_seed_count": sum(row["placed"] for row in candidate_rows),
            "unplaced_seed_count": sum(not row["placed"] for row in candidate_rows),
        },
        "evidence_counts": {
            "all_verified_direct": _counts_json(_claim_counts(connection, scope="all")),
            "shared_with_current_static_discovery": _counts_json(
                _claim_counts(connection, scope="shared")
            ),
            "candidate_only": _counts_json(_claim_counts(connection, scope="candidate")),
        },
        "candidate_only_per_seed": per_seed,
    }


def report_json(report: dict[str, object]) -> str:
    """Serialize the local review report in a deterministic form."""
    return json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n"
