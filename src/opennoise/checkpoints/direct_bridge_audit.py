"""Audit catalog identity edges against the exact static discovery bridge."""

from __future__ import annotations

import hashlib
import sqlite3
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from opennoise.deployment.static_discovery import StaticDiscoveryPayload
from opennoise.serving.open.construction_graph_v2 import (
    OpenConstructionGraphV2Artifact,
    verify_open_construction_graph_v2,
)

if TYPE_CHECKING:
    from pathlib import Path


class DirectBridgeAuditError(ValueError):
    """Report malformed or mismatched audit inputs."""


@dataclass(frozen=True, slots=True)
class BridgeEdge:
    """One factual catalog identity edge from the open construction graph."""

    edge_id: str
    legacy_id: str
    legacy_name: str
    catalog_id: str
    catalog_name: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _norm(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _casefold_space(value: str) -> str:
    return " ".join(value.casefold().split())


def _load_edges(path: Path, database_sha256: str) -> tuple[str, tuple[BridgeEdge, ...]]:
    artifact = OpenConstructionGraphV2Artifact.model_validate_json(path.read_text(encoding="utf-8"))
    verify_open_construction_graph_v2(artifact)
    nodes = {item.node_id: item for item in artifact.nodes}
    edges = []
    for item in artifact.edges:
        if item.kind != "canonical_catalog_identity":
            continue
        source = nodes[item.source_node_id]
        target = nodes[item.target_node_id]
        if not source.node_id.startswith("legacy:") or target.catalog_id is None:
            raise DirectBridgeAuditError("canonical edge has an invalid endpoint")
        public_hash = item.evidence.public_catalog_sha256
        if public_hash != database_sha256:
            raise DirectBridgeAuditError("canonical edge targets a different public catalog")
        edges.append(
            BridgeEdge(
                edge_id=item.edge_id,
                legacy_id=source.node_id,
                legacy_name=source.name,
                catalog_id=target.catalog_id,
                catalog_name=target.name,
            )
        )
    if not edges:
        raise DirectBridgeAuditError("graph has no canonical catalog identity edges")
    return _sha256(path), tuple(sorted(edges, key=lambda edge: edge.edge_id))


def _load_discovery(
    path: Path, database_sha256: str
) -> tuple[str, dict[str, tuple[int, str, int]]]:
    payload = StaticDiscoveryPayload.model_validate_json(path.read_bytes())
    if payload.availability != "ready" or payload.source is None:
        raise DirectBridgeAuditError("static discovery is not ready")
    if payload.source.database_sha256 != database_sha256:
        raise DirectBridgeAuditError("static discovery targets a different public catalog")
    result: dict[str, tuple[int, str, int]] = {
        item.node_id: (item.catalog_genre_id, item.catalog_genre_name, len(item.artist_ids))
        for item in payload.genres
    }
    return _sha256(path), result


def _genre_ids_and_direct_counts(database: Path) -> tuple[dict[str, int], dict[int, int]]:
    database_uri = f"file:{database.resolve(strict=True).as_posix()}?mode=ro"
    with sqlite3.connect(database_uri, uri=True) as db:
        genre_ids = {
            str(value): int(genre_id)
            for genre_id, value in db.execute(
                """SELECT genres.id, identifiers.value
                   FROM genres
                   JOIN entity_identifiers AS identifiers ON identifiers.entity_id = genres.id
                   WHERE identifiers.namespace = 'wikidata'"""
            )
        }
        genre_id_values = set(genre_ids.values())
        counts = Counter(
            int(row[0])
            for row in db.execute(
                """SELECT evidence.genre_id
                   FROM displayable_artist_genre_evidence AS evidence
                   JOIN provenance_records AS provenance
                     ON provenance.id = evidence.provenance_id
                   JOIN active_rights_policy_permissions AS export_permission
                     ON export_permission.policy_id = provenance.policy_id
                    AND export_permission.use_kind = 'export'
                    AND export_permission.decision = 'allow'
                   JOIN active_rights_policy_permissions AS display_permission
                     ON display_permission.policy_id = provenance.policy_id
                    AND display_permission.use_kind = 'display'
                    AND display_permission.decision = 'allow'
                   WHERE evidence.evidence_kind = 'direct_source_claim'"""
            )
            if int(row[0]) in genre_id_values
        )
    return genre_ids, dict(counts)


def audit_direct_bridges(
    graph_path: Path, discovery_path: Path, database_path: Path
) -> dict[str, object]:
    """Return a deterministic, non-publishing comparison report."""
    database_sha256 = _sha256(database_path)
    graph_sha256, edges = _load_edges(graph_path, database_sha256)
    discovery_sha256, discovery = _load_discovery(discovery_path, database_sha256)
    genre_ids, direct_counts = _genre_ids_and_direct_counts(database_path)
    by_legacy: dict[str, list[BridgeEdge]] = {}
    for edge in edges:
        by_legacy.setdefault(edge.legacy_id, []).append(edge)

    counts: Counter[str] = Counter()
    rows: list[dict[str, object]] = []
    static_bridge_count = 0
    potential_observation_lift = 0
    for edge in edges:
        static = discovery.get(edge.legacy_id.removeprefix("legacy:"))
        static_catalog_id = static[0] if static else None
        catalog_genre_id = genre_ids.get(edge.catalog_id.removeprefix("wikidata:genre:"))
        same_name = _norm(edge.legacy_name) == _norm(edge.catalog_name)
        if same_name and _casefold_space(edge.legacy_name) == _casefold_space(edge.catalog_name):
            classification = "safe_exact"
        elif same_name:
            classification = "safe_typography_equivalent"
        elif len(by_legacy[edge.legacy_id]) > 1 or static_catalog_id not in (
            None,
            catalog_genre_id,
        ):
            classification = "conflicting_or_ambiguous"
        else:
            classification = "review_only"
        counts[classification] += 1
        genre_id = catalog_genre_id
        lift = 0 if static_catalog_id == genre_id else direct_counts.get(genre_id, 0)
        if static_catalog_id is not None:
            static_bridge_count += 1
        potential_observation_lift += lift
        rows.append(
            {
                "edge_id": edge.edge_id,
                "legacy_id": edge.legacy_id,
                "legacy_name": edge.legacy_name,
                "catalog_id": edge.catalog_id,
                "catalog_name": edge.catalog_name,
                "classification": classification,
                "currently_static_catalog_genre_id": static_catalog_id,
                "catalog_genre_id": genre_id,
                "direct_p136_observation_count": direct_counts.get(genre_id, 0),
                "potential_direct_observation_lift": lift,
            }
        )
    return {
        "revision": "direct-bridge-audit-v1",
        "inputs": {
            "graph_sha256": graph_sha256,
            "discovery_sha256": discovery_sha256,
            "public_database_sha256": database_sha256,
        },
        "edge_count": len(edges),
        "classification_counts": dict(sorted(counts.items())),
        "current_static_bridge_count": static_bridge_count,
        "potential_direct_observation_lift": potential_observation_lift,
        "edges": rows,
    }
