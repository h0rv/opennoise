"""Audit catalog identity edges against the exact static discovery bridge."""

from __future__ import annotations

import hashlib
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, model_validator

from opennoise.common import canonical_json, sha256_json
from opennoise.deployment.static_discovery import StaticDiscoveryPayload
from opennoise.models import FrozenModel
from opennoise.serving.open.construction_graph_v2 import (
    OpenConstructionGraphV2Artifact,
    verify_open_construction_graph_v2,
)
from opennoise.types import Sha256  # noqa: TC001  # Pydantic resolves this alias at runtime.

if TYPE_CHECKING:
    from pathlib import Path


class DirectBridgeAuditError(ValueError):
    """Report malformed or mismatched audit inputs."""


_REVIEW_REVISION: Final = "direct-bridge-review-workflow-v1"
_REVIEW_POLICY_REVISION: Final = "direct-bridge-review-policy-v1"
_REVIEW_GATE_REVISION: Final = "direct-bridge-review-gate-v1"

type DirectBridgeClassification = Literal[
    "safe_exact", "safe_typography_equivalent", "conflicting_or_ambiguous", "review_only"
]
type DirectBridgeReviewDisposition = Literal["approve", "reject", "needs_evidence"]
type DirectBridgeReviewState = Literal[
    "pending_review", "needs_evidence", "rejected", "ready_for_separate_publication"
]


class DirectBridgeAuditInputs(FrozenModel):
    """Hashes of the immutable evidence used to create an audit report."""

    graph_sha256: Sha256
    discovery_sha256: Sha256
    public_database_sha256: Sha256


class DirectBridgeAuditEdge(FrozenModel):
    """One audited edge, retained as review evidence and never as a publication command."""

    edge_id: str = Field(min_length=1, max_length=500)
    legacy_id: str = Field(min_length=1, max_length=500)
    legacy_name: str = Field(min_length=1, max_length=500)
    catalog_id: str = Field(min_length=1, max_length=500)
    catalog_name: str = Field(min_length=1, max_length=500)
    classification: DirectBridgeClassification
    currently_static_catalog_genre_id: int | None = None
    catalog_genre_id: int | None = None
    direct_p136_observation_count: int = Field(ge=0)
    potential_direct_observation_lift: int = Field(ge=0)


class DirectBridgeAuditReport(FrozenModel):
    """The typed, hashable review boundary for a direct-bridge audit report."""

    revision: Literal["direct-bridge-audit-v1"] = "direct-bridge-audit-v1"
    inputs: DirectBridgeAuditInputs
    edge_count: int = Field(ge=1)
    classification_counts: dict[DirectBridgeClassification, int]
    current_static_bridge_count: int = Field(ge=0)
    potential_direct_observation_lift: int = Field(ge=0)
    edges: tuple[DirectBridgeAuditEdge, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _complete_edge_accounting(self) -> DirectBridgeAuditReport:
        edge_ids = tuple(edge.edge_id for edge in self.edges)
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("audit edge IDs must be unique")
        if self.edge_count != len(self.edges):
            raise ValueError("audit edge count does not match edges")
        counts = dict(sorted(Counter(edge.classification for edge in self.edges).items()))
        if self.classification_counts != counts:
            raise ValueError("audit classification counts do not match edges")
        return self


class DirectBridgeReviewDecision(FrozenModel):
    """One append-only human decision about an audited identity edge."""

    decision_id: str = Field(min_length=1, max_length=300)
    edge_id: str = Field(min_length=1, max_length=500)
    reviewer_ref: str = Field(min_length=1, max_length=300)
    review_revision: str = Field(min_length=1, max_length=120)
    disposition: DirectBridgeReviewDisposition
    rationale: str = Field(min_length=1, max_length=2_000)


class DirectBridgeReviewPolicy(FrozenModel):
    """Bounded, versioned policy for a sealed direct-bridge review ledger."""

    revision: Literal["direct-bridge-review-policy-v1"] = _REVIEW_POLICY_REVISION
    maximum_edges: int = Field(default=10_000, ge=1, le=100_000)
    maximum_review_decisions: int = Field(default=30_000, ge=0, le=150_000)
    required_independent_approvals: int = Field(default=2, ge=1, le=10)
    required_rejections: int = Field(default=1, ge=1, le=10)


class DirectBridgeReviewRow(FrozenModel):
    """Derived review state for one edge; it has no serving or catalog effect."""

    edge_id: str = Field(min_length=1, max_length=500)
    state: DirectBridgeReviewState
    approval_count: int = Field(default=0, ge=0)
    rejection_count: int = Field(default=0, ge=0)
    needs_evidence_count: int = Field(default=0, ge=0)


class DirectBridgeReviewCoverage(FrozenModel):
    """Complete accounting for review states in an audit-bound ledger."""

    edge_count: int = Field(ge=1)
    review_decision_count: int = Field(ge=0)
    pending_review_count: int = Field(ge=0)
    needs_evidence_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    ready_for_separate_publication_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _edge_partition(self) -> DirectBridgeReviewCoverage:
        if self.edge_count != (
            self.pending_review_count
            + self.needs_evidence_count
            + self.rejected_count
            + self.ready_for_separate_publication_count
        ):
            raise ValueError("direct bridge review states must partition audit edges")
        return self


class DirectBridgeReviewArtifact(FrozenModel):
    """A sealed, append-only review ledger with no static-publication authority."""

    revision: Literal["direct-bridge-review-workflow-v1"] = _REVIEW_REVISION
    policy: DirectBridgeReviewPolicy
    policy_sha256: Sha256
    source_audit_sha256: Sha256
    audit_edges_sha256: Sha256
    review_decisions_sha256: Sha256
    predecessor_output_sha256: Sha256 | None = None
    audit: DirectBridgeAuditReport
    review_decisions: tuple[DirectBridgeReviewDecision, ...]
    review_rows: tuple[DirectBridgeReviewRow, ...]
    coverage: DirectBridgeReviewCoverage
    catalog_mutated: Literal[False] = False
    static_discovery_mutated: Literal[False] = False
    static_bridge_published: Literal[False] = False
    output_sha256: Sha256

    @model_validator(mode="after")
    def _hashes_and_complete_coverage(self) -> DirectBridgeReviewArtifact:
        if self.policy_sha256 != sha256_json(self.policy.model_dump(mode="json")):
            raise ValueError("direct bridge review policy hash does not replay")
        if self.source_audit_sha256 != direct_bridge_audit_sha256(self.audit):
            raise ValueError("source audit hash does not replay")
        if self.audit_edges_sha256 != sha256_json(
            [edge.model_dump(mode="json") for edge in self.audit.edges]
        ):
            raise ValueError("audit edge hash does not replay")
        if self.review_decisions_sha256 != sha256_json(
            [decision.model_dump(mode="json") for decision in self.review_decisions]
        ):
            raise ValueError("direct bridge review decision hash does not replay")
        row_ids = tuple(row.edge_id for row in self.review_rows)
        audit_edge_ids = tuple(edge.edge_id for edge in self.audit.edges)
        if len(row_ids) != len(set(row_ids)) or set(row_ids) != set(audit_edge_ids):
            raise ValueError("review rows must cover every audit edge exactly once")
        if self.coverage.edge_count != len(self.audit.edges):
            raise ValueError("review coverage edge count does not match audit")
        if self.coverage.review_decision_count != len(self.review_decisions):
            raise ValueError("review decision count does not match coverage")
        return self


class DirectBridgeReviewGate(FrozenModel):
    """Verification result that deliberately stops before any bridge publication."""

    revision: Literal["direct-bridge-review-gate-v1"] = _REVIEW_GATE_REVISION
    artifact_output_sha256: Sha256
    edge_count: int = Field(ge=1)
    deterministic_replay: Literal[True] = True
    catalog_not_mutated: Literal[True] = True
    static_discovery_not_mutated: Literal[True] = True
    static_bridge_not_published: Literal[True] = True
    approved_edges_require_separate_publication: Literal[True] = True


@dataclass(frozen=True, slots=True)
class BridgeEdge:
    """One claimed catalog identity edge from the open construction graph."""

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
    by_catalog: dict[str, list[BridgeEdge]] = {}
    for edge in edges:
        by_legacy.setdefault(edge.legacy_id, []).append(edge)
        by_catalog.setdefault(edge.catalog_id, []).append(edge)

    counts: Counter[str] = Counter()
    rows: list[dict[str, object]] = []
    static_bridge_count = 0
    potential_observation_lift = 0
    for edge in edges:
        static = discovery.get(edge.legacy_id.removeprefix("legacy:"))
        static_catalog_id = static[0] if static else None
        catalog_genre_id = genre_ids.get(edge.catalog_id.removeprefix("wikidata:genre:"))
        same_name = _norm(edge.legacy_name) == _norm(edge.catalog_name)
        one_to_one = len(by_legacy[edge.legacy_id]) == 1 and len(by_catalog[edge.catalog_id]) == 1
        if not one_to_one or static_catalog_id not in (None, catalog_genre_id):
            classification = "conflicting_or_ambiguous"
        elif same_name and _casefold_space(edge.legacy_name) == _casefold_space(edge.catalog_name):
            classification = "safe_exact"
        elif same_name:
            classification = "safe_typography_equivalent"
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


def parse_direct_bridge_audit_report(report: object) -> DirectBridgeAuditReport:
    """Parse one untrusted audit-report payload into its immutable review boundary."""
    return DirectBridgeAuditReport.model_validate_json(canonical_json(report))


def direct_bridge_audit_sha256(report: DirectBridgeAuditReport) -> Sha256:
    """Return the deterministic logical hash of a typed direct-bridge audit."""
    return sha256_json(report.model_dump(mode="json"))


def _direct_bridge_review_state(
    edge_id: str,
    decisions: tuple[DirectBridgeReviewDecision, ...],
    policy: DirectBridgeReviewPolicy,
) -> DirectBridgeReviewRow:
    """Resolve an edge review state without treating any state as publication."""
    counts = Counter(decision.disposition for decision in decisions)
    if counts["reject"] >= policy.required_rejections:
        state: DirectBridgeReviewState = "rejected"
    elif counts["approve"] >= policy.required_independent_approvals:
        state = "ready_for_separate_publication"
    elif counts["needs_evidence"]:
        state = "needs_evidence"
    else:
        state = "pending_review"
    return DirectBridgeReviewRow(
        edge_id=edge_id,
        state=state,
        approval_count=counts["approve"],
        rejection_count=counts["reject"],
        needs_evidence_count=counts["needs_evidence"],
    )


def _validated_review_decisions(
    audit: DirectBridgeAuditReport,
    decisions: tuple[DirectBridgeReviewDecision, ...],
    policy: DirectBridgeReviewPolicy,
) -> dict[str, list[DirectBridgeReviewDecision]]:
    """Validate the append-only event set and group it by its audited edge."""
    if len(audit.edges) > policy.maximum_edges:
        raise ValueError("audit edge count exceeds workflow policy bound")
    if len(decisions) > policy.maximum_review_decisions:
        raise ValueError("review decision count exceeds workflow policy bound")
    known_edge_ids = {edge.edge_id for edge in audit.edges}
    grouped: dict[str, list[DirectBridgeReviewDecision]] = defaultdict(list)
    decision_ids: set[str] = set()
    reviewer_edge_pairs: set[tuple[str, str]] = set()
    for decision in decisions:
        if decision.edge_id not in known_edge_ids:
            raise ValueError("review decision references an unknown audit edge")
        if decision.decision_id in decision_ids:
            raise ValueError("review decision IDs must be unique")
        decision_ids.add(decision.decision_id)
        reviewer_edge_pair = (decision.edge_id, decision.reviewer_ref)
        if reviewer_edge_pair in reviewer_edge_pairs:
            raise ValueError("a reviewer may record only one decision per audit edge")
        reviewer_edge_pairs.add(reviewer_edge_pair)
        grouped[decision.edge_id].append(decision)
    return grouped


def direct_bridge_review_output_sha256(artifact: DirectBridgeReviewArtifact) -> Sha256:
    """Recompute the logical hash of a sealed direct-bridge review artifact."""
    return sha256_json(artifact.model_dump(mode="json", exclude={"output_sha256"}))


def build_direct_bridge_review_artifact(
    audit: DirectBridgeAuditReport,
    review_decisions: tuple[DirectBridgeReviewDecision, ...],
    policy: DirectBridgeReviewPolicy | None = None,
    predecessor: DirectBridgeReviewArtifact | None = None,
) -> DirectBridgeReviewArtifact:
    """Seal review decisions for one audit without mutating or publishing a bridge.

    When a predecessor is supplied, the new decision sequence must retain its
    complete prefix and add at least one event. This makes a successor ledger
    append-only rather than a replacement interpretation of earlier reviews.
    """
    resolved = policy or DirectBridgeReviewPolicy()
    if predecessor is None:
        predecessor_output_sha256: Sha256 | None = None
    else:
        if predecessor.output_sha256 != direct_bridge_review_output_sha256(predecessor):
            raise ValueError("predecessor review artifact output hash does not replay")
        if direct_bridge_audit_sha256(audit) != predecessor.source_audit_sha256:
            raise ValueError("predecessor references a different audit")
        if resolved != predecessor.policy:
            raise ValueError("successor review policy must match the predecessor policy")
        prior_decisions = predecessor.review_decisions
        if (
            len(review_decisions) <= len(prior_decisions)
            or review_decisions[: len(prior_decisions)] != prior_decisions
        ):
            raise ValueError("successor review decisions must append to the predecessor ledger")
        predecessor_output_sha256 = predecessor.output_sha256
    grouped = _validated_review_decisions(audit, review_decisions, resolved)
    rows = tuple(
        _direct_bridge_review_state(edge.edge_id, tuple(grouped[edge.edge_id]), resolved)
        if grouped[edge.edge_id]
        else DirectBridgeReviewRow(edge_id=edge.edge_id, state="pending_review")
        for edge in audit.edges
    )
    coverage = DirectBridgeReviewCoverage(
        edge_count=len(audit.edges),
        review_decision_count=len(review_decisions),
        pending_review_count=sum(row.state == "pending_review" for row in rows),
        needs_evidence_count=sum(row.state == "needs_evidence" for row in rows),
        rejected_count=sum(row.state == "rejected" for row in rows),
        ready_for_separate_publication_count=sum(
            row.state == "ready_for_separate_publication" for row in rows
        ),
    )
    base = DirectBridgeReviewArtifact(
        policy=resolved,
        policy_sha256=sha256_json(resolved.model_dump(mode="json")),
        source_audit_sha256=direct_bridge_audit_sha256(audit),
        audit_edges_sha256=sha256_json([edge.model_dump(mode="json") for edge in audit.edges]),
        review_decisions_sha256=sha256_json(
            [decision.model_dump(mode="json") for decision in review_decisions]
        ),
        predecessor_output_sha256=predecessor_output_sha256,
        audit=audit,
        review_decisions=review_decisions,
        review_rows=rows,
        coverage=coverage,
        output_sha256="0" * 64,
    )
    return base.model_copy(update={"output_sha256": direct_bridge_review_output_sha256(base)})


def verify_direct_bridge_review_artifact(
    artifact: DirectBridgeReviewArtifact,
) -> DirectBridgeReviewGate:
    """Verify a review-only artifact and return no authority to publish it."""
    if artifact.output_sha256 != direct_bridge_review_output_sha256(artifact):
        raise ValueError("direct bridge review artifact output hash does not replay")
    _validated_review_decisions(artifact.audit, artifact.review_decisions, artifact.policy)
    return DirectBridgeReviewGate(
        artifact_output_sha256=artifact.output_sha256,
        edge_count=artifact.coverage.edge_count,
    )
