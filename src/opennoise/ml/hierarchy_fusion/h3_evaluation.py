"""Read-only H3 co-assignment diagnostics for a completed fusion artifact."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from opennoise.common import canonical_json, sha256_file, sha256_hex
from opennoise.models import FrozenModel
from opennoise.models.historical_signal import HistoricalSignalArtifact

from .contracts import HierarchyFusionArtifact, HierarchyFusionError

if TYPE_CHECKING:
    from pathlib import Path

    from opennoise.models.historical_signal import HistoricalSignalNode

    from .contracts import FusedHierarchyEdge


class H3RelationOverlap(FrozenModel):
    """H3 co-assignment counts and ratios for one fusion edge disposition."""

    included_dag_edge_count: int = Field(ge=0)
    edges_with_both_h3_nodes: int = Field(ge=0)
    same_umbrella_count: int = Field(ge=0)
    same_umbrella_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    same_subcommunity_count: int = Field(ge=0)
    same_subcommunity_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    same_microgenre_count: int = Field(ge=0)
    same_microgenre_ratio: float | None = Field(default=None, ge=0.0, le=1.0)


class H3OverlapReport(FrozenModel):
    """Evaluation-only agreement with an independently-built H3 neighborhood map.

    This report never feeds construction or calibration.  Co-assignment is a
    descriptive overlap measure, not a claim that the H3 neighborhoods are
    hierarchy labels.
    """

    revision: str = "hierarchy-fusion-h3-overlap-v1"
    construction_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    h3_claimed_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    h3_claimed_artifact_sha256_replays: Literal[False] = False
    h3_evaluation_byte_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    h3_evaluation_byte_count: int = Field(gt=0)
    h3_nodes_count: int = Field(ge=0)
    factual: H3RelationOverlap
    review: H3RelationOverlap
    combined: H3RelationOverlap
    h3_evaluation_only: Literal[True] = True
    historical_data_used_for_construction: Literal[False] = False
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def h3_overlap_output_sha256(report: H3OverlapReport) -> str:
    """Hash the complete diagnostic while excluding its self hash."""
    return sha256_hex(canonical_json(report.model_dump(mode="json", exclude={"output_sha256"})))


def verify_h3_overlap(report: H3OverlapReport) -> None:
    """Reject a report whose construction or evaluation-only boundary drifted."""
    if report.output_sha256 != h3_overlap_output_sha256(report):
        raise HierarchyFusionError("H3 overlap report hash does not replay")
    if not report.h3_evaluation_only or report.historical_data_used_for_construction:
        raise HierarchyFusionError("H3 overlap report crossed its evaluation-only boundary")


def _relation_overlap(
    edges: list[FusedHierarchyEdge], nodes: dict[str, HistoricalSignalNode]
) -> H3RelationOverlap:
    """Keep per-disposition H3 co-assignment separate for interpretation."""
    counts: Counter[str] = Counter()
    for edge in edges:
        child = nodes.get(edge.child_seed_id)
        parent = nodes.get(edge.parent_seed_id)
        if child is None or parent is None:
            continue
        counts["both"] += 1
        counts["umbrella"] += child.umbrella_id == parent.umbrella_id
        counts["subcommunity"] += child.subcommunity_id == parent.subcommunity_id
        counts["microgenre"] += child.microgenre_id == parent.microgenre_id
    denominator = counts["both"]
    return H3RelationOverlap(
        included_dag_edge_count=len(edges),
        edges_with_both_h3_nodes=denominator,
        same_umbrella_count=counts["umbrella"],
        same_umbrella_ratio=counts["umbrella"] / denominator if denominator else None,
        same_subcommunity_count=counts["subcommunity"],
        same_subcommunity_ratio=counts["subcommunity"] / denominator if denominator else None,
        same_microgenre_count=counts["microgenre"],
        same_microgenre_ratio=counts["microgenre"] / denominator if denominator else None,
    )


def evaluate_h3_overlap(
    artifact: HierarchyFusionArtifact, h3_path: Path
) -> H3OverlapReport:
    """Compare accepted DAG links to H3 neighborhood co-assignment after build."""
    try:
        h3 = HistoricalSignalArtifact.model_validate_json(h3_path.read_bytes())
    except (OSError, ValueError) as error:
        raise HierarchyFusionError("H3 evaluation artifact is invalid") from error
    # This cache artifact has structural Pydantic validation, but its claimed
    # `quality.artifact_sha256` does not currently replay under the producer's
    # canonical hash function. Do not bless that stale claim: the report binds
    # exact bytes and declares this evaluation-only limitation explicitly.
    claimed_h3_sha = h3.quality.artifact_sha256
    byte_sha, byte_count = sha256_file(h3_path)
    nodes = {
        node.genre_id.removeprefix("enao-legacy:"): node
        for node in h3.nodes
        if node.genre_id.startswith("enao-legacy:")
    }
    if len(nodes) != len(h3.nodes):
        raise HierarchyFusionError("H3 evaluation artifact has unsupported genre identifiers")
    factual = [edge for edge in artifact.edges if edge.disposition == "factual"]
    review = [edge for edge in artifact.edges if edge.disposition == "review"]
    preliminary = H3OverlapReport(
        construction_output_sha256=artifact.output_sha256,
        h3_claimed_artifact_sha256=claimed_h3_sha,
        h3_evaluation_byte_sha256=byte_sha,
        h3_evaluation_byte_count=byte_count,
        h3_nodes_count=len(nodes),
        factual=_relation_overlap(factual, nodes),
        review=_relation_overlap(review, nodes),
        combined=_relation_overlap([*factual, *review], nodes),
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(update={"output_sha256": h3_overlap_output_sha256(preliminary)})
