"""Terminal, exact-lineage comparison of sealed reconstruction signals with history.

This module is deliberately downstream of ``build_reconstruction_checkpoint``.  It
replays the construction manifest without opening the historical file, then reads
the held-out historical signal only for positive-only comparison.  Missing historical
positives are unknown and are never treated as negative labels.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, model_validator

from opennoise.checkpoints.reconstruction_checkpoint import (
    CheckpointBinding,
    ReconstructionCheckpoint,
    checkpoint_sha256,
    verify_reconstruction_checkpoint,
)
from opennoise.common import (
    canonical_json,
    connect_readonly,
    sha256_file,
    sha256_hex,
    write_atomic_bytes,
)
from opennoise.evidence.graph_projection import (
    EvidenceGraphProjectionArtifact,
    verify_evidence_graph_projection,
)
from opennoise.ml.full_graph_signal import (
    FullGraphSignalArtifact,
    FullGraphSignalReceipt,
    verify_full_graph_signal,
)
from opennoise.ml.genre_neighborhoods.contracts import (
    GenreNeighborhoodArtifact,
    GenreNeighborhoodReceipt,
)
from opennoise.ml.genre_neighborhoods.contracts import (
    verify_artifact as verify_genre_neighborhood_artifact,
)
from opennoise.ml.hierarchy_fusion import HierarchyFusionArtifact, verify_hierarchy_fusion
from opennoise.ml.hierarchy_fusion.h3_evaluation import H3RelationOverlap, evaluate_h3_overlap
from opennoise.models import FrozenModel
from opennoise.models.historical_signal import HistoricalSignalArtifact

if TYPE_CHECKING:
    from pathlib import Path


_SEED_COUNT: Final = 6_291
_SHA: Final = r"^[0-9a-f]{64}$"


class CurrentLineageEvaluationError(ValueError):
    """The sealed candidate or terminal evaluation input cannot be replayed."""


class PositiveOverlapAxis(FrozenModel):
    """Positive-only overlap with both observed denominators made explicit."""

    candidate_observation_count: int = Field(ge=0)
    mapped_candidate_observation_count: int = Field(ge=0)
    historical_positive_observation_count: int = Field(ge=0)
    overlap_count: int = Field(ge=0)
    historical_positive_recall: float | None = Field(default=None, ge=0.0, le=1.0)
    candidate_precision: None = None
    denominator_note: str = Field(min_length=1)

    @model_validator(mode="after")
    def _counts_replay(self) -> PositiveOverlapAxis:
        if self.mapped_candidate_observation_count > self.candidate_observation_count:
            raise ValueError("mapped candidates cannot exceed candidate observations")
        if self.overlap_count > min(
            self.mapped_candidate_observation_count, self.historical_positive_observation_count
        ):
            raise ValueError("overlap cannot exceed either positive observation set")
        expected = (
            self.overlap_count / self.historical_positive_observation_count
            if self.historical_positive_observation_count
            else None
        )
        if self.historical_positive_recall != expected:
            raise ValueError("historical positive recall does not replay its denominator")
        return self


class UnavailableAxis(FrozenModel):
    """An axis whose historical denominator is not present in the reference."""

    candidate_observation_count: int = Field(ge=0)
    historical_positive_observation_count: None = None
    overlap_count: None = None
    denominator_available: Literal[False] = False
    note: str = Field(min_length=1)


class HierarchyTerminalEvaluation(FrozenModel):
    """H3 co-assignment diagnostics over mapped current hierarchy edges."""

    included_dag_edge_count: int = Field(ge=0)
    edges_with_mapped_historical_nodes: int = Field(ge=0)
    historical_directed_parent_denominator: None = None
    factual: H3RelationOverlap
    review: H3RelationOverlap
    combined: H3RelationOverlap
    denominator_note: str = Field(min_length=1)

    @model_validator(mode="after")
    def _mapped_edges_replay(self) -> HierarchyTerminalEvaluation:
        if self.edges_with_mapped_historical_nodes > self.included_dag_edge_count:
            raise ValueError("mapped hierarchy edges cannot exceed included edges")
        if self.combined.edges_with_both_h3_nodes != self.edges_with_mapped_historical_nodes:
            raise ValueError("hierarchy H3 denominator does not replay mapped edges")
        return self


class CurrentLineageHistoricalEvaluation(FrozenModel):
    """A terminal report bound to the exact sealed current candidate lineage."""

    revision: Literal["source-neutral-current-lineage-historical-evaluation-v1"] = (
        "source-neutral-current-lineage-historical-evaluation-v1"
    )
    construction_checkpoint: CheckpointBinding
    current_inputs: tuple[CheckpointBinding, ...] = Field(min_length=7)
    historical_input: CheckpointBinding
    stable_seed_count: Literal[6291] = _SEED_COUNT
    seed_identity_sha256: str = Field(pattern=_SHA)
    construction_replayed_without_historical: Literal[True] = True
    historical_inputs_used_for_construction: Literal[False] = False
    historical_data_used_for_evaluation: Literal[True] = True
    historical_absence_is_negative: Literal[False] = False
    parity_claims_made: Literal[False] = False
    full_graph_pair_split_observed_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    full_graph_unique_pair_count: int = Field(ge=0)
    membership_seed_presence: PositiveOverlapAxis
    neighborhoods: PositiveOverlapAxis
    hierarchy: HierarchyTerminalEvaluation
    coordinates: UnavailableAxis
    output_sha256: str = Field(pattern=_SHA)

    @model_validator(mode="after")
    def _current_roles_are_exact(self) -> CurrentLineageHistoricalEvaluation:
        expected = {
            "evidence_graph_database",
            "evidence_graph_receipt",
            "full_graph_signal",
            "full_graph_signal_receipt",
            "genre_neighborhoods",
            "genre_neighborhoods_receipt",
            "genre_neighborhoods_database",
            "hierarchy_fusion",
        }
        if {item.role for item in self.current_inputs} != expected:
            raise ValueError("terminal evaluation current inputs do not have exact roles")
        if self.historical_input.role != "held_out_historical_signal":
            raise ValueError("terminal evaluation historical role is invalid")
        return self


class CurrentLineageHistoricalEvaluationReceipt(FrozenModel):
    """Custody receipt for the terminal report bytes and logical output."""

    revision: Literal["source-neutral-current-lineage-historical-evaluation-receipt-v1"] = (
        "source-neutral-current-lineage-historical-evaluation-receipt-v1"
    )
    artifact_sha256: str = Field(pattern=_SHA)
    artifact_byte_count: int = Field(gt=0)
    logical_output_sha256: str = Field(pattern=_SHA)


@dataclass(frozen=True, slots=True)
class CurrentLineageEvaluationInputs:
    """Explicit paths for sealed candidates and the terminal held-out reference."""

    root: Path
    construction_checkpoint: Path
    graph_database: Path
    graph_receipt: Path
    full_graph: Path
    full_graph_receipt: Path
    neighborhoods: Path
    neighborhoods_receipt: Path
    neighborhoods_database: Path
    hierarchy: Path
    historical_reference: Path


@dataclass(frozen=True, slots=True)
class _ReceiptExpectation:
    """Receipt fields expected for one logical JSON artifact."""

    digest: str
    byte_count: int
    logical_sha256: str


def current_lineage_evaluation_sha256(report: CurrentLineageHistoricalEvaluation) -> str:
    """Return the deterministic report digest excluding only its self hash."""
    return sha256_hex(canonical_json(report.model_dump(mode="json", exclude={"output_sha256"})))


def verify_current_lineage_evaluation(report: CurrentLineageHistoricalEvaluation) -> None:
    """Fail closed when a terminal report or its boundary was edited."""
    if report.output_sha256 != current_lineage_evaluation_sha256(report):
        raise CurrentLineageEvaluationError("current-lineage evaluation hash does not replay")
    if report.historical_inputs_used_for_construction:
        raise CurrentLineageEvaluationError("historical data crossed the construction boundary")


def write_current_lineage_historical_evaluation(
    path: Path,
    receipt_path: Path,
    report: CurrentLineageHistoricalEvaluation,
) -> CurrentLineageHistoricalEvaluationReceipt:
    """Write the terminal report and a receipt binding its exact bytes."""
    verify_current_lineage_evaluation(report)
    payload = report.model_dump_json(indent=2).encode() + b"\n"
    write_atomic_bytes(path, payload)
    digest, size = sha256_file(path)
    receipt = CurrentLineageHistoricalEvaluationReceipt(
        artifact_sha256=digest,
        artifact_byte_count=size,
        logical_output_sha256=report.output_sha256,
    )
    write_atomic_bytes(receipt_path, receipt.model_dump_json(indent=2).encode() + b"\n")
    return receipt


def verify_current_lineage_historical_evaluation_receipt(
    path: Path,
    receipt: CurrentLineageHistoricalEvaluationReceipt,
    report: CurrentLineageHistoricalEvaluation,
) -> None:
    """Verify report bytes, logical output, and receipt fields together."""
    verify_current_lineage_evaluation(report)
    digest, size = sha256_file(path)
    if (digest, size, report.output_sha256) != (
        receipt.artifact_sha256,
        receipt.artifact_byte_count,
        receipt.logical_output_sha256,
    ):
        raise CurrentLineageEvaluationError("terminal evaluation receipt does not replay")


def build_current_lineage_historical_evaluation(
    inputs: CurrentLineageEvaluationInputs,
) -> CurrentLineageHistoricalEvaluation:
    """Replay construction first, then compare exact current candidates to history."""
    root = inputs.root.resolve()
    checkpoint = _load_checkpoint(inputs.construction_checkpoint)
    if checkpoint.historical_data_used_for_evaluation or checkpoint.evaluation_inputs:
        raise CurrentLineageEvaluationError(
            "terminal evaluation requires a construction-only checkpoint without history"
        )
    graph = _load_graph(inputs.graph_database, inputs.graph_receipt)
    full = _load_full_graph(inputs.full_graph, inputs.full_graph_receipt, graph)
    neighborhood, current_pairs = _load_neighborhood(
        inputs.neighborhoods,
        inputs.neighborhoods_receipt,
        inputs.neighborhoods_database,
        graph,
    )
    hierarchy = _load_hierarchy(inputs.hierarchy)

    checkpoint_bindings = {item.role: item for item in checkpoint.inputs}
    for role, path, logical in (
        ("evidence_graph_database", inputs.graph_database, graph.database_sha256),
        ("evidence_graph_receipt", inputs.graph_receipt, graph.output_sha256),
        ("full_graph_signal", inputs.full_graph, full.output_sha256),
        ("full_graph_signal_receipt", inputs.full_graph_receipt, full.output_sha256),
        ("genre_neighborhoods", inputs.neighborhoods, neighborhood.output_sha256),
        ("genre_neighborhoods_receipt", inputs.neighborhoods_receipt, neighborhood.output_sha256),
        (
            "genre_neighborhoods_database",
            inputs.neighborhoods_database,
            neighborhood.cache_database_sha256,
        ),
        ("hierarchy_fusion", inputs.hierarchy, hierarchy.output_sha256),
    ):
        _assert_checkpoint_binding(checkpoint_bindings, role, path, root, logical)

    current_seed_ids = {row.seed_id for row in hierarchy.seed_states}
    if len(current_seed_ids) != _SEED_COUNT:
        raise CurrentLineageEvaluationError("current hierarchy does not contain 6,291 seed IDs")
    seed_hash = sha256_hex(canonical_json(tuple(sorted(current_seed_ids))))
    if checkpoint.seed_identity_sha256 != seed_hash:
        raise CurrentLineageEvaluationError("checkpoint seed identity hash does not replay")

    current_membership_ids = _load_current_membership_ids(inputs.graph_database)
    if not current_membership_ids <= current_seed_ids:
        raise CurrentLineageEvaluationError("current membership has a dangling seed endpoint")
    if any(endpoint not in current_seed_ids for pair in current_pairs for endpoint in pair):
        raise CurrentLineageEvaluationError("current neighborhood has a dangling seed endpoint")

    # This is the terminal boundary: all current lineage and seed accounting has
    # passed before the held-out file is opened.
    historical, historical_binding = _load_historical(inputs.historical_reference, root)
    historical_seed_ids = {node.genre_id.removeprefix("enao-legacy:") for node in historical.nodes}
    if current_seed_ids != historical_seed_ids:
        raise CurrentLineageEvaluationError(
            "current and historical seed identities do not form the same 6,291-seed universe"
        )
    historical_membership_ids = {
        node.genre_id.removeprefix("enao-legacy:")
        for node in historical.nodes
        if node.membership_count > 0
    }
    historical_pairs = {
        _canonical_pair(
            neighbor.genre_id.removeprefix("enao-legacy:"),
            neighbor.neighbor_genre_id.removeprefix("enao-legacy:"),
        )
        for neighbor in historical.neighbors
    }
    if any(endpoint not in historical_seed_ids for pair in historical_pairs for endpoint in pair):
        raise CurrentLineageEvaluationError("historical neighbor has a dangling seed endpoint")
    hierarchy_report = evaluate_h3_overlap(hierarchy, inputs.historical_reference)
    mapped_hierarchy_edges = sum(
        edge.included_in_dag
        and edge.child_seed_id in historical_seed_ids
        and edge.parent_seed_id in historical_seed_ids
        for edge in hierarchy.edges
    )
    if hierarchy_report.combined.edges_with_both_h3_nodes != mapped_hierarchy_edges:
        raise CurrentLineageEvaluationError("hierarchy H3 mapping does not replay")

    base = CurrentLineageHistoricalEvaluation(
        construction_checkpoint=_binding(
            "construction_checkpoint",
            inputs.construction_checkpoint,
            root,
            checkpoint.output_sha256,
        ),
        current_inputs=(
            _binding("evidence_graph_database", inputs.graph_database, root, graph.database_sha256),
            _binding("evidence_graph_receipt", inputs.graph_receipt, root, graph.output_sha256),
            _binding("full_graph_signal", inputs.full_graph, root, full.output_sha256),
            _binding(
                "full_graph_signal_receipt",
                inputs.full_graph_receipt,
                root,
                full.output_sha256,
            ),
            _binding("genre_neighborhoods", inputs.neighborhoods, root, neighborhood.output_sha256),
            _binding(
                "genre_neighborhoods_receipt",
                inputs.neighborhoods_receipt,
                root,
                neighborhood.output_sha256,
            ),
            _binding(
                "genre_neighborhoods_database",
                inputs.neighborhoods_database,
                root,
                neighborhood.cache_database_sha256,
            ),
            _binding("hierarchy_fusion", inputs.hierarchy, root, hierarchy.output_sha256),
        ),
        historical_input=historical_binding,
        seed_identity_sha256=seed_hash,
        full_graph_pair_split_observed_seed_count=full.pair_split.observed_seed_count,
        full_graph_unique_pair_count=full.pair_split.unique_pair_count,
        membership_seed_presence=_overlap_axis(
            candidate_observation_count=len(current_membership_ids),
            mapped_candidate_observation_count=len(current_membership_ids & historical_seed_ids),
            historical_positive_observation_count=len(historical_membership_ids),
            overlap_count=len(current_membership_ids & historical_membership_ids),
            denominator_note=(
                "Historical positive membership is the node membership_count>0 set. "
                f"The graph-backed candidate set is {len(current_membership_ids)} seeds; "
                "the full signal's pair-level split observes "
                f"{full.pair_split.observed_seed_count} "
                "seeds. Absence is unknown, so candidate precision and negative recall are "
                "unavailable."
            ),
        ),
        neighborhoods=_overlap_axis(
            candidate_observation_count=len(current_pairs),
            mapped_candidate_observation_count=len(
                current_pairs
                & {
                    pair
                    for pair in current_pairs
                    if pair[0] in historical_seed_ids and pair[1] in historical_seed_ids
                }
            ),
            historical_positive_observation_count=len(historical_pairs),
            overlap_count=len(current_pairs & historical_pairs),
            denominator_note=(
                "Canonical undirected co-listen pairs are compared to historical positive "
                "neighbor pairs. Missing historical pairs are not negatives."
            ),
        ),
        hierarchy=HierarchyTerminalEvaluation(
            included_dag_edge_count=sum(edge.included_in_dag for edge in hierarchy.edges),
            edges_with_mapped_historical_nodes=mapped_hierarchy_edges,
            factual=hierarchy_report.factual,
            review=hierarchy_report.review,
            combined=hierarchy_report.combined,
            denominator_note=(
                "Historical hierarchy exposes node co-assignment, not directed parent-child "
                "labels. Ratios use mapped current DAG edges; a historical directed-parent "
                "denominator and hierarchy precision are unavailable."
            ),
        ),
        coordinates=UnavailableAxis(
            candidate_observation_count=checkpoint.coordinates.candidate_observation_count,
            note=(
                "The held-out historical reference has coordinates, but this terminal report "
                "does not claim coordinate parity or a comparable coordinate denominator."
            ),
        ),
        output_sha256="0" * 64,
    )
    report = base.model_copy(update={"output_sha256": current_lineage_evaluation_sha256(base)})
    verify_current_lineage_evaluation(report)
    return report


def _load_checkpoint(path: Path) -> ReconstructionCheckpoint:
    try:
        checkpoint = ReconstructionCheckpoint.model_validate_json(path.read_bytes())
        verify_reconstruction_checkpoint(checkpoint)
    except (OSError, ValueError) as error:
        raise CurrentLineageEvaluationError("invalid construction checkpoint") from error
    if checkpoint_sha256(checkpoint) != checkpoint.output_sha256:
        raise CurrentLineageEvaluationError("construction checkpoint hash does not replay")
    return checkpoint


def _load_graph(path: Path, receipt_path: Path) -> EvidenceGraphProjectionArtifact:
    try:
        graph = EvidenceGraphProjectionArtifact.model_validate_json(receipt_path.read_bytes())
        verify_evidence_graph_projection(graph)
        digest, size = sha256_file(path)
    except (OSError, ValueError) as error:
        raise CurrentLineageEvaluationError("invalid evidence graph lineage") from error
    if (digest, size) != (graph.database_sha256, graph.database_bytes):
        raise CurrentLineageEvaluationError("evidence graph database does not match receipt")
    return graph


def _load_current_membership_ids(path: Path) -> set[str]:
    try:
        with closing(connect_readonly(path)) as database:
            return {
                str(row[0])
                for row in database.execute(
                    "SELECT DISTINCT object_identifier FROM claim "
                    "WHERE predicate = 'artist_membership' AND object_namespace = 'stable_seed'"
                )
            }
    except (OSError, ValueError) as error:
        raise CurrentLineageEvaluationError("cannot read current membership candidates") from error


def _load_full_graph(
    path: Path, receipt_path: Path, graph: EvidenceGraphProjectionArtifact
) -> FullGraphSignalArtifact:
    try:
        artifact = FullGraphSignalArtifact.model_validate_json(path.read_bytes())
        verify_full_graph_signal(artifact)
        receipt = FullGraphSignalReceipt.model_validate_json(receipt_path.read_bytes())
        digest, size = sha256_file(path)
    except (OSError, ValueError) as error:
        raise CurrentLineageEvaluationError("invalid full-graph candidate") from error
    _check_receipt(
        _ReceiptExpectation(
            receipt.artifact_sha256,
            receipt.artifact_byte_count,
            receipt.logical_output_sha256,
        ),
        digest,
        size,
        artifact.output_sha256,
        "full graph",
    )
    if (
        artifact.graph_database_sha256 != graph.database_sha256
        or artifact.graph_receipt_output_sha256 != graph.output_sha256
    ):
        raise CurrentLineageEvaluationError("full graph does not bind the admitted graph lineage")
    return artifact


def _load_neighborhood(
    path: Path,
    receipt_path: Path,
    database_path: Path,
    graph: EvidenceGraphProjectionArtifact,
) -> tuple[GenreNeighborhoodArtifact, set[tuple[str, str]]]:
    try:
        artifact = GenreNeighborhoodArtifact.model_validate_json(path.read_bytes())
        verify_genre_neighborhood_artifact(artifact)
        receipt = GenreNeighborhoodReceipt.model_validate_json(receipt_path.read_bytes())
        digest, size = sha256_file(path)
        database_digest, database_size = sha256_file(database_path)
    except (OSError, ValueError) as error:
        raise CurrentLineageEvaluationError("invalid co-listen neighborhood candidate") from error
    _check_receipt(
        _ReceiptExpectation(
            receipt.artifact_sha256,
            receipt.artifact_byte_count,
            receipt.logical_output_sha256,
        ),
        digest,
        size,
        artifact.output_sha256,
        "co-listen neighborhoods",
    )
    if (
        artifact.graph_receipt_output_sha256 != graph.output_sha256
        or (database_digest, database_size)
        != (artifact.cache_database_sha256, artifact.cache_database_byte_count)
        or receipt.cache_database_sha256 != database_digest
    ):
        raise CurrentLineageEvaluationError("co-listen candidate does not bind the graph lineage")
    try:
        with closing(connect_readonly(database_path)) as database:
            pairs = {
                _canonical_pair(str(row[0]), str(row[1]))
                for row in database.execute(
                    "SELECT seed_id, neighbor_seed_id FROM neighbor "
                    "WHERE relation_kind = 'peer_not_parent_child'"
                )
            }
    except (OSError, ValueError) as error:
        raise CurrentLineageEvaluationError("cannot read co-listen neighborhood cache") from error
    return artifact, pairs


def _load_hierarchy(path: Path) -> HierarchyFusionArtifact:
    try:
        artifact = HierarchyFusionArtifact.model_validate_json(path.read_bytes())
        verify_hierarchy_fusion(artifact)
    except (OSError, ValueError) as error:
        raise CurrentLineageEvaluationError("invalid hierarchy candidate") from error
    return artifact


def _load_historical(path: Path, root: Path) -> tuple[HistoricalSignalArtifact, CheckpointBinding]:
    try:
        raw = path.read_bytes()
        artifact = HistoricalSignalArtifact.model_validate_json(raw)
        logical = sha256_hex(canonical_json(artifact.model_dump(mode="json")))
    except (OSError, ValueError) as error:
        raise CurrentLineageEvaluationError("invalid held-out historical reference") from error
    return artifact, _binding("held_out_historical_signal", path, root, logical)


def _overlap_axis(
    *,
    candidate_observation_count: int,
    mapped_candidate_observation_count: int,
    historical_positive_observation_count: int,
    overlap_count: int,
    denominator_note: str,
) -> PositiveOverlapAxis:
    recall = (
        overlap_count / historical_positive_observation_count
        if historical_positive_observation_count
        else None
    )
    return PositiveOverlapAxis(
        candidate_observation_count=candidate_observation_count,
        mapped_candidate_observation_count=mapped_candidate_observation_count,
        historical_positive_observation_count=historical_positive_observation_count,
        overlap_count=overlap_count,
        historical_positive_recall=recall,
        denominator_note=denominator_note,
    )


def _binding(role: str, path: Path, root: Path, logical: str) -> CheckpointBinding:
    resolved = path.resolve()
    try:
        locator = resolved.relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise CurrentLineageEvaluationError(f"{role} is outside the report root") from error
    digest, size = sha256_file(resolved)
    return CheckpointBinding(
        role=role,
        locator=locator,
        bytes_sha256=digest,
        byte_count=size,
        logical_sha256=logical,
    )


def _assert_checkpoint_binding(
    bindings: dict[str, CheckpointBinding],
    role: str,
    path: Path,
    root: Path,
    logical: str,
) -> None:
    expected = bindings.get(role)
    if expected is None:
        raise CurrentLineageEvaluationError(f"construction checkpoint lacks {role}")
    current = _binding(role, path, root, logical)
    if current != expected:
        raise CurrentLineageEvaluationError(f"current {role} does not match sealed checkpoint")


def _check_receipt(
    expected: _ReceiptExpectation,
    digest: str,
    size: int,
    logical: str,
    label: str,
) -> None:
    if (expected.digest, expected.byte_count, expected.logical_sha256) != (
        digest,
        size,
        logical,
    ):
        raise CurrentLineageEvaluationError(f"{label} receipt does not replay")


def _canonical_pair(left: str, right: str) -> tuple[str, str]:
    return (left, right) if left <= right else (right, left)


__all__ = [
    "CurrentLineageEvaluationError",
    "CurrentLineageEvaluationInputs",
    "CurrentLineageHistoricalEvaluation",
    "CurrentLineageHistoricalEvaluationReceipt",
    "build_current_lineage_historical_evaluation",
    "current_lineage_evaluation_sha256",
    "verify_current_lineage_evaluation",
    "verify_current_lineage_historical_evaluation_receipt",
    "write_current_lineage_historical_evaluation",
]
