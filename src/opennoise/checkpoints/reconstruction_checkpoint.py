"""Build one deterministic status manifest for the open reconstruction signals.

The manifest is intentionally a small index, not a second copy of any model
artifact.  It binds the current construction artifacts by bytes and logical
hash, checks their complete 6,291-seed accounting, and keeps historical
comparison reports in a separate evaluation-only section.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, model_validator

from opennoise.checkpoints.source_neutral_certification import (
    HistoricalCheckpointEvaluation,
    SourceNeutralCheckpointCertification,
    verify_source_neutral_checkpoint_certification,
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
from opennoise.ml.colisten_membership_transfer import (
    CoListenMembershipTransferArtifact,
    verify_colisten_membership_transfer,
)
from opennoise.ml.colisten_membership_transfer.contracts import CoListenMembershipTransferReceipt
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
from opennoise.ml.label_alignment import ColdLabelAlignmentArtifact, verify_cold_label_alignment
from opennoise.ml.label_alignment.contracts import ColdLabelAlignmentReceipt
from opennoise.ml.label_alignment.release_group_vocabulary import (
    ReleaseGroupVocabularyArtifact,
    ReleaseGroupVocabularyReceipt,
    verify_release_group_vocabulary,
)
from opennoise.ml.semantic_layout import SemanticLayoutArtifact, verify_semantic_map_layout
from opennoise.models import FrozenModel

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from opennoise.ml.colisten_membership_transfer.contracts import (
        InputBinding as TransferInputBinding,
    )
    from opennoise.ml.genre_neighborhoods.contracts import InputBinding as NeighborhoodInputBinding
    from opennoise.ml.hierarchy_fusion.contracts import SourceBinding as HierarchySourceBinding
    from opennoise.ml.label_alignment.contracts import InputBinding as ColdInputBinding
    from opennoise.ml.semantic_layout.contracts import InputBinding as LayoutInputBinding

_SEED_COUNT: Final = 6_291
_SHA: Final = r"^[0-9a-f]{64}$"
_HISTORICAL_TERMS: Final = ("historical", "everynoise", "enao-legacy", "h3")


class ReconstructionCheckpointError(ValueError):
    """A construction or evaluation artifact cannot be admitted to the manifest."""


@dataclass(frozen=True, slots=True)
class ReconstructionCheckpointInputs:
    """Explicit construction artifacts and their custody receipts."""

    root: Path
    graph_database: Path
    graph_receipt: Path
    construction_certificate: Path
    full_graph: Path
    full_graph_receipt: Path
    cold_alignment: Path
    cold_alignment_receipt: Path
    neighborhoods: Path
    neighborhoods_receipt: Path
    neighborhoods_database: Path
    hierarchy: Path
    hierarchy_receipt: Path | None
    layout: Path
    membership_transfer: Path
    membership_transfer_receipt: Path
    vocabulary_artifact: Path | None = None
    vocabulary_receipt: Path | None = None


class CheckpointBinding(FrozenModel):
    """A path-independent byte and logical binding for one input artifact."""

    role: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    bytes_sha256: str = Field(pattern=_SHA)
    byte_count: int = Field(gt=0)
    logical_sha256: str = Field(pattern=_SHA)

    @model_validator(mode="after")
    def _relative_locator(self) -> CheckpointBinding:
        if self.locator.startswith(("/", "\\")) or ":\\" in self.locator:
            raise ValueError("checkpoint locators must be relative")
        return self


class HierarchyFusionReceipt(FrozenModel):
    """Byte and logical custody fields for an optional hierarchy receipt."""

    artifact_sha256: str = Field(pattern=_SHA)
    artifact_byte_count: int = Field(gt=0)
    logical_output_sha256: str = Field(pattern=_SHA)


class AxisCoverage(FrozenModel):
    """Coverage for one axis, preserving unavailable historical denominators."""

    status: Literal["measured", "not_evaluable"]
    candidate_observation_count: int = Field(ge=0)
    historical_observation_count: int | None = Field(default=None, ge=0)
    overlap_count: int | None = Field(default=None, ge=0)
    overlap_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    note: str = Field(min_length=1)

    @model_validator(mode="after")
    def _status_matches_denominator(self) -> AxisCoverage:
        if self.status == "measured":
            if self.historical_observation_count is None or self.overlap_count is None:
                raise ValueError("measured coverage requires a historical denominator and overlap")
            if self.overlap_count > self.historical_observation_count:
                raise ValueError("overlap cannot exceed historical observations")
            if self.overlap_fraction is None:
                raise ValueError("measured coverage requires an overlap fraction")
        elif any(
            value is not None
            for value in (
                self.historical_observation_count,
                self.overlap_count,
                self.overlap_fraction,
            )
        ):
            raise ValueError("not-evaluable coverage cannot carry historical metrics")
        return self


class MembershipTransferSummary(FrozenModel):
    """Review-only cold-artist transfer coverage, separate from observed memberships."""

    stable_seed_count: Literal[6291] = _SEED_COUNT
    colisten_artist_count: int = Field(ge=0)
    review_candidate_count: int = Field(ge=0)
    eligible_cold_artist_count: int = Field(ge=0)
    abstained_cold_artist_count: int = Field(ge=0)
    heldout_direct_positive_count: int = Field(ge=0)
    heldout_eligible_artist_count: int = Field(ge=0)
    heldout_recall_at_10: float | None = Field(default=None, ge=0.0, le=1.0)
    heldout_recall_at_25: float | None = Field(default=None, ge=0.0, le=1.0)
    train_only_popularity_recall_at_10: float | None = Field(default=None, ge=0.0, le=1.0)
    train_only_popularity_recall_at_25: float | None = Field(default=None, ge=0.0, le=1.0)
    note: str = (
        "Review candidates are not factual memberships and are excluded from the observed "
        "membership/support denominator."
    )


class ConstructionBoundary(FrozenModel):
    """The explicit boundary that makes history terminal rather than a feature."""

    historical_inputs_used_for_construction: Literal[False] = False
    historical_flags_checked: tuple[str, ...] = Field(min_length=1)
    forbidden_historical_construction_inputs: Literal[0] = 0


class ReconstructionCheckpoint(FrozenModel):
    """A compact, replayable index over the full source-neutral checkpoint."""

    revision: Literal["source-neutral-reconstruction-checkpoint-v1"] = (
        "source-neutral-reconstruction-checkpoint-v1"
    )
    stable_seed_count: Literal[6291] = _SEED_COUNT
    seed_identity_sha256: str = Field(pattern=_SHA)
    inputs: tuple[CheckpointBinding, ...] = Field(min_length=1)
    evaluation_inputs: tuple[CheckpointBinding, ...] = ()
    construction_boundary: ConstructionBoundary
    identities: AxisCoverage
    memberships: AxisCoverage
    neighborhoods: AxisCoverage
    hierarchy: AxisCoverage
    coordinates: AxisCoverage
    membership_transfer: MembershipTransferSummary
    historical_data_used_for_evaluation: bool = False
    output_sha256: str = Field(pattern=_SHA)


def checkpoint_sha256(checkpoint: ReconstructionCheckpoint) -> str:
    """Return the canonical logical digest excluding only the self hash."""
    return sha256_hex(canonical_json(checkpoint.model_dump(mode="json", exclude={"output_sha256"})))


def verify_reconstruction_checkpoint(checkpoint: ReconstructionCheckpoint) -> None:
    """Fail closed when the manifest was edited or its boundary was weakened."""
    if checkpoint.output_sha256 != checkpoint_sha256(checkpoint):
        raise ReconstructionCheckpointError("reconstruction checkpoint hash does not replay")
    if checkpoint.construction_boundary.historical_inputs_used_for_construction:
        raise ReconstructionCheckpointError("historical data crossed the construction boundary")
    if checkpoint.historical_data_used_for_evaluation != bool(checkpoint.evaluation_inputs):
        raise ReconstructionCheckpointError("historical evaluation flag does not match inputs")


def write_reconstruction_checkpoint(path: Path, checkpoint: ReconstructionCheckpoint) -> None:
    """Atomically persist a verified, deterministic manifest."""
    verify_reconstruction_checkpoint(checkpoint)
    write_atomic_bytes(path, canonical_json(checkpoint.model_dump(mode="json")) + b"\n")


def build_reconstruction_checkpoint(
    inputs: ReconstructionCheckpointInputs,
    historical_evaluation: Path | None = None,
) -> ReconstructionCheckpoint:
    """Validate sealed signals and build a status-only checkpoint manifest."""
    root = inputs.root.resolve()
    graph, graph_bindings, graph_seed_hash = _load_graph(
        inputs.graph_database, inputs.graph_receipt, root
    )
    certificate, certificate_binding = _load_certificate(inputs.construction_certificate, root)
    _bind_certificate_inputs(certificate, inputs.graph_database, inputs.graph_receipt, root, graph)
    full, full_bindings = _load_full_graph(inputs.full_graph, inputs.full_graph_receipt, root)
    cold, cold_bindings = _load_cold(
        inputs.cold_alignment,
        inputs.cold_alignment_receipt,
        inputs.vocabulary_artifact,
        inputs.vocabulary_receipt,
        root,
    )
    neighborhood, neighborhood_bindings, neighborhood_seed_hash = _load_neighborhood(
        inputs.neighborhoods, inputs.neighborhoods_receipt, inputs.neighborhoods_database, root
    )
    hierarchy_data, hierarchy_bindings, hierarchy_seed_hash = _load_hierarchy(
        inputs.hierarchy, inputs.hierarchy_receipt, root
    )
    layout_data, layout_binding = _load_layout(inputs.layout, root)
    transfer, transfer_bindings = _load_membership_transfer(
        inputs.membership_transfer,
        inputs.membership_transfer_receipt,
        root,
    )
    _assert_cross_artifact_bindings(
        graph,
        graph_bindings,
        certificate,
        full,
        full_bindings,
        cold,
        neighborhood,
        neighborhood_bindings,
        hierarchy_data,
        hierarchy_bindings,
        layout_data,
        transfer,
    )
    construction_bindings = (
        *graph_bindings,
        certificate_binding,
        *full_bindings,
        *cold_bindings,
        *neighborhood_bindings,
        *hierarchy_bindings,
        layout_binding,
        *transfer_bindings,
    )
    _assert_construction_boundary(
        construction_bindings,
        certificate,
        full,
        cold,
        neighborhood,
        hierarchy_data,
        layout_data,
        transfer,
    )
    seed_identity_sha256 = _assert_seed_universe(
        graph_seed_hash,
        full,
        cold,
        neighborhood,
        neighborhood_seed_hash,
        hierarchy_data,
        hierarchy_seed_hash,
        layout_data,
    )

    evaluation_bindings: tuple[CheckpointBinding, ...] = ()
    if historical_evaluation is not None:
        _, historical_binding = _load_historical_evaluation(historical_evaluation, root)
        evaluation_bindings = (historical_binding,)

    membership_candidate_count = full.pair_split.unique_pair_count
    neighborhood_candidate_count = sum(
        channel.retained_neighbor_count for channel in neighborhood.channels
    )
    hierarchy_candidate_count = (
        hierarchy_data.coverage.factual_source_edge_count
        + hierarchy_data.coverage.review_edge_count
    )
    placed_seed_count = layout_data.metrics.placed_seed_count

    base = ReconstructionCheckpoint(
        inputs=construction_bindings,
        evaluation_inputs=evaluation_bindings,
        seed_identity_sha256=seed_identity_sha256,
        construction_boundary=ConstructionBoundary(
            historical_flags_checked=(
                "source_neutral_certificate",
                "full_graph_signal",
                "cold_label_alignment",
                "genre_neighborhoods",
                "hierarchy_fusion",
                "semantic_layout",
                "membership_transfer",
            )
        ),
        identities=AxisCoverage(
            status="not_evaluable",
            candidate_observation_count=(
                cold.coverage.existing_open_identity_accepted_seed_count
                + cold.coverage.inferred_unique_normalized_accepted_seed_count
            ),
            note=(
                "No historical artist or open-identity reference is available; "
                "cold-label masked recovery is construction-only calibration. "
                f"The source vocabulary contains {cold.coverage.open_identity_count} identities; "
                "this count reports only grounded accepted target seeds."
            ),
        ),
        memberships=AxisCoverage(
            status="not_evaluable",
            candidate_observation_count=membership_candidate_count,
            note=(
                "A terminal historical report may be bound separately, but its legacy "
                "candidate hashes do not match this full-graph signal."
            ),
        ),
        neighborhoods=AxisCoverage(
            status="not_evaluable",
            candidate_observation_count=neighborhood_candidate_count,
            note=(
                "A terminal historical report may be bound separately, but its legacy "
                "candidate hashes do not match this co-listen artifact."
            ),
        ),
        hierarchy=AxisCoverage(
            status="not_evaluable",
            candidate_observation_count=hierarchy_candidate_count,
            note=(
                "No historical hierarchy ground truth is bound to this checkpoint; "
                "factual holdout recovery remains open-source calibration only."
            ),
        ),
        coordinates=AxisCoverage(
            status="not_evaluable",
            candidate_observation_count=placed_seed_count,
            note=(
                "Historical coordinates are intentionally absent from construction "
                "and no coordinate holdout is available."
            ),
        ),
        membership_transfer=MembershipTransferSummary(
            colisten_artist_count=transfer.coverage.colisten_artist_count,
            review_candidate_count=transfer.coverage.candidate_count,
            eligible_cold_artist_count=transfer.coverage.eligible_cold_artist_count,
            abstained_cold_artist_count=transfer.coverage.abstained_cold_artist_count,
            heldout_direct_positive_count=transfer.heldout_evaluation.heldout_direct_positive_count,
            heldout_eligible_artist_count=transfer.heldout_evaluation.eligible_heldout_artist_count,
            heldout_recall_at_10=transfer.heldout_evaluation.recall_at_10,
            heldout_recall_at_25=transfer.heldout_evaluation.recall_at_25,
            train_only_popularity_recall_at_10=transfer.train_only_global_popularity_baseline.recall_at_10,
            train_only_popularity_recall_at_25=transfer.train_only_global_popularity_baseline.recall_at_25,
        ),
        historical_data_used_for_evaluation=bool(evaluation_bindings),
        output_sha256="0" * 64,
    )
    checkpoint = base.model_copy(update={"output_sha256": checkpoint_sha256(base)})
    verify_reconstruction_checkpoint(checkpoint)
    return checkpoint


def _load_graph(
    path: Path, receipt_path: Path, root: Path
) -> tuple[EvidenceGraphProjectionArtifact, tuple[CheckpointBinding, CheckpointBinding], str]:
    try:
        receipt = EvidenceGraphProjectionArtifact.model_validate_json(receipt_path.read_bytes())
        verify_evidence_graph_projection(receipt)
        digest, size = sha256_file(path)
    except (OSError, ValueError) as error:
        raise ReconstructionCheckpointError("invalid evidence graph input") from error
    if (digest, size) != (receipt.database_sha256, receipt.database_bytes):
        raise ReconstructionCheckpointError("evidence graph database does not match receipt")
    with closing(connect_readonly(path)) as database:
        seed_ids = {
            str(row[0])
            for row in database.execute(
                "SELECT identifier FROM identity WHERE namespace = 'stable_seed'"
            )
        }
    return (
        receipt,
        (
            _binding("evidence_graph_database", path, root, receipt.database_sha256),
            _binding("evidence_graph_receipt", receipt_path, root, receipt.output_sha256),
        ),
        _seed_hash(seed_ids),
    )


def _load_certificate(
    path: Path, root: Path
) -> tuple[SourceNeutralCheckpointCertification, CheckpointBinding]:
    try:
        certificate = SourceNeutralCheckpointCertification.model_validate_json(path.read_bytes())
        verify_source_neutral_checkpoint_certification(certificate)
    except (OSError, ValueError) as error:
        raise ReconstructionCheckpointError(
            "invalid source-neutral construction certificate"
        ) from error
    return certificate, _binding(
        "source_neutral_construction_certificate", path, root, certificate.output_sha256
    )


def _load_full_graph(
    path: Path, receipt_path: Path, root: Path
) -> tuple[FullGraphSignalArtifact, tuple[CheckpointBinding, CheckpointBinding]]:
    try:
        artifact = FullGraphSignalArtifact.model_validate_json(path.read_bytes())
        verify_full_graph_signal(artifact)
        receipt = FullGraphSignalReceipt.model_validate_json(receipt_path.read_bytes())
        digest, size = sha256_file(path)
    except (OSError, ValueError) as error:
        raise ReconstructionCheckpointError("invalid full-graph signal input") from error
    _check_receipt(
        receipt.artifact_sha256,
        receipt.artifact_byte_count,
        digest,
        size,
        receipt.logical_output_sha256,
        artifact.output_sha256,
        "full graph",
    )
    return artifact, (
        _binding("full_graph_signal", path, root, artifact.output_sha256),
        _binding("full_graph_signal_receipt", receipt_path, root, artifact.output_sha256),
    )


def _load_cold(
    path: Path,
    receipt_path: Path,
    vocabulary_path: Path | None,
    vocabulary_receipt_path: Path | None,
    root: Path,
) -> tuple[ColdLabelAlignmentArtifact, tuple[CheckpointBinding, ...]]:
    try:
        artifact = ColdLabelAlignmentArtifact.model_validate_json(path.read_bytes())
        verify_cold_label_alignment(artifact)
        receipt = ColdLabelAlignmentReceipt.model_validate_json(receipt_path.read_bytes())
        digest, size = sha256_file(path)
    except (OSError, ValueError) as error:
        raise ReconstructionCheckpointError("invalid cold-label alignment input") from error
    _check_receipt(
        receipt.artifact_sha256,
        receipt.artifact_byte_count,
        digest,
        size,
        receipt.logical_output_sha256,
        artifact.output_sha256,
        "cold label",
    )
    bindings: list[CheckpointBinding] = [
        _binding("cold_label_alignment", path, root, artifact.output_sha256),
        _binding("cold_label_alignment_receipt", receipt_path, root, artifact.output_sha256),
    ]
    vocabulary_roles = {
        item.role
        for item in artifact.inputs
        if item.role.startswith("musicbrainz_release_group_vocabulary_")
    }
    if vocabulary_roles:
        if vocabulary_path is None or vocabulary_receipt_path is None:
            raise ReconstructionCheckpointError("cold alignment vocabulary bindings are missing")
        vocabulary, vocabulary_binding, vocabulary_receipt_binding = _load_vocabulary(
            vocabulary_path, vocabulary_receipt_path, root
        )
        declared_logicals = {
            item.logical_sha256
            for item in artifact.inputs
            if item.role == "musicbrainz_release_group_vocabulary_artifact"
        }
        if vocabulary.output_sha256 not in declared_logicals:
            raise ReconstructionCheckpointError(
                "cold alignment vocabulary artifact hash does not match its input binding"
            )
        bindings.extend((vocabulary_binding, vocabulary_receipt_binding))
    elif vocabulary_path is not None or vocabulary_receipt_path is not None:
        raise ReconstructionCheckpointError(
            "vocabulary supplied for alignment without vocabulary inputs"
        )
    return artifact, tuple(bindings)


def _load_neighborhood(
    path: Path, receipt_path: Path, database_path: Path, root: Path
) -> tuple[
    GenreNeighborhoodArtifact,
    tuple[CheckpointBinding, CheckpointBinding, CheckpointBinding],
    str,
]:
    try:
        artifact = GenreNeighborhoodArtifact.model_validate_json(path.read_bytes())
        verify_genre_neighborhood_artifact(artifact)
        receipt = GenreNeighborhoodReceipt.model_validate_json(receipt_path.read_bytes())
        digest, size = sha256_file(path)
    except (OSError, ValueError) as error:
        raise ReconstructionCheckpointError("invalid genre-neighborhood input") from error
    _check_receipt(
        receipt.artifact_sha256,
        receipt.artifact_byte_count,
        digest,
        size,
        receipt.logical_output_sha256,
        artifact.output_sha256,
        "genre neighborhoods",
    )
    db_digest, db_size = sha256_file(database_path)
    if (db_digest, db_size) != (artifact.cache_database_sha256, artifact.cache_database_byte_count):
        raise ReconstructionCheckpointError("genre-neighborhood cache does not match artifact")
    with closing(connect_readonly(database_path)) as database:
        seed_ids = {
            str(row[0]) for row in database.execute("SELECT DISTINCT seed_id FROM genre_state")
        }
    return (
        artifact,
        (
            _binding("genre_neighborhoods", path, root, artifact.output_sha256),
            _binding("genre_neighborhoods_receipt", receipt_path, root, artifact.output_sha256),
            _binding(
                "genre_neighborhoods_database", database_path, root, artifact.cache_database_sha256
            ),
        ),
        _seed_hash(seed_ids),
    )


def _load_vocabulary(
    path: Path, receipt_path: Path, root: Path
) -> tuple[
    ReleaseGroupVocabularyArtifact,
    CheckpointBinding,
    CheckpointBinding,
]:
    try:
        artifact = ReleaseGroupVocabularyArtifact.model_validate_json(path.read_bytes())
        verify_release_group_vocabulary(artifact)
        receipt = ReleaseGroupVocabularyReceipt.model_validate_json(receipt_path.read_bytes())
        digest, size = sha256_file(path)
    except (OSError, ValueError) as error:
        raise ReconstructionCheckpointError("invalid release-group vocabulary input") from error
    _check_receipt(
        receipt.artifact_sha256,
        receipt.artifact_byte_count,
        digest,
        size,
        receipt.logical_output_sha256,
        artifact.output_sha256,
        "release-group vocabulary",
    )
    return (
        artifact,
        _binding(
            "musicbrainz_release_group_vocabulary_artifact", path, root, artifact.output_sha256
        ),
        _binding(
            "musicbrainz_release_group_vocabulary_receipt",
            receipt_path,
            root,
            artifact.output_sha256,
        ),
    )


def _load_hierarchy(
    path: Path, receipt_path: Path | None, root: Path
) -> tuple[HierarchyFusionArtifact, tuple[CheckpointBinding, ...], str]:
    try:
        data = HierarchyFusionArtifact.model_validate_json(path.read_bytes())
        verify_hierarchy_fusion(data)
    except (OSError, ValueError) as error:
        raise ReconstructionCheckpointError("invalid hierarchy fusion input") from error
    logical = data.output_sha256
    bindings: list[CheckpointBinding] = [_binding("hierarchy_fusion", path, root, logical)]
    if receipt_path is not None:
        try:
            receipt = HierarchyFusionReceipt.model_validate_json(receipt_path.read_bytes())
            digest, size = sha256_file(path)
        except (OSError, ValueError) as error:
            raise ReconstructionCheckpointError("invalid hierarchy fusion receipt") from error
        _check_receipt(
            receipt.artifact_sha256,
            receipt.artifact_byte_count,
            digest,
            size,
            receipt.logical_output_sha256,
            logical,
            "hierarchy fusion",
        )
        bindings.append(_binding("hierarchy_fusion_receipt", receipt_path, root, logical))
    seed_ids = (row.seed_id for row in data.seed_states)
    return data, tuple(bindings), _seed_hash(seed_ids)


def _load_layout(path: Path, root: Path) -> tuple[SemanticLayoutArtifact, CheckpointBinding]:
    try:
        artifact = SemanticLayoutArtifact.model_validate_json(path.read_bytes())
        verify_semantic_map_layout(artifact)
    except (OSError, ValueError) as error:
        raise ReconstructionCheckpointError("invalid semantic layout input") from error
    return artifact, _binding("semantic_layout", path, root, artifact.output_sha256)


def _load_membership_transfer(
    path: Path,
    receipt_path: Path,
    root: Path,
) -> tuple[CoListenMembershipTransferArtifact, tuple[CheckpointBinding, CheckpointBinding]]:
    try:
        artifact = CoListenMembershipTransferArtifact.model_validate_json(path.read_bytes())
        verify_colisten_membership_transfer(artifact)
        receipt = CoListenMembershipTransferReceipt.model_validate_json(receipt_path.read_bytes())
        digest, size = sha256_file(path)
    except (OSError, ValueError) as error:
        raise ReconstructionCheckpointError(
            "invalid co-listen membership transfer input"
        ) from error
    _check_receipt(
        receipt.artifact_sha256,
        receipt.artifact_byte_count,
        digest,
        size,
        receipt.logical_output_sha256,
        artifact.output_sha256,
        "co-listen membership transfer",
    )
    bindings = (
        _binding("colisten_membership_transfer", path, root, artifact.output_sha256),
        _binding(
            "colisten_membership_transfer_receipt", receipt_path, root, artifact.output_sha256
        ),
    )
    return artifact, bindings


def _load_historical_evaluation(
    path: Path, root: Path
) -> tuple[HistoricalCheckpointEvaluation, CheckpointBinding]:
    try:
        evaluation = HistoricalCheckpointEvaluation.model_validate_json(path.read_bytes())
        expected = sha256_hex(
            canonical_json(evaluation.model_dump(mode="json", exclude={"output_sha256"}))
        )
    except (OSError, ValueError) as error:
        raise ReconstructionCheckpointError("invalid terminal historical evaluation") from error
    if evaluation.output_sha256 != expected or not evaluation.historical_data_used_for_evaluation:
        raise ReconstructionCheckpointError(
            "historical evaluation hash or boundary does not replay"
        )
    return evaluation, _binding(
        "terminal_historical_evaluation", path, root, evaluation.output_sha256
    )


def _binding(role: str, path: Path, root: Path, logical: str) -> CheckpointBinding:
    resolved = path.resolve()
    try:
        locator = resolved.relative_to(root).as_posix()
    except ValueError as error:
        raise ReconstructionCheckpointError(f"{role} is outside checkpoint root") from error
    digest, size = sha256_file(resolved)
    return CheckpointBinding(
        role=role,
        locator=locator,
        bytes_sha256=digest,
        byte_count=size,
        logical_sha256=logical,
    )


def _check_receipt(  # noqa: PLR0913, PLR0917 - one explicit custody tuple is clearer.
    expected_digest: str,
    expected_size: int,
    digest: str,
    size: int,
    expected_logical: str,
    logical: str,
    label: str,
) -> None:
    if (expected_digest, expected_size) != (digest, size) or expected_logical != logical:
        raise ReconstructionCheckpointError(f"{label} artifact does not match custody receipt")


def _bind_certificate_inputs(
    certificate: SourceNeutralCheckpointCertification,
    graph_database: Path,
    graph_receipt: Path,
    root: Path,
    graph: EvidenceGraphProjectionArtifact,
) -> None:
    by_role = {item.role: item for item in certificate.inputs}
    graph_db = by_role.get("evidence_graph_database")
    graph_receipt_binding = by_role.get("evidence_graph_receipt")
    if graph_db is None or graph_receipt_binding is None:
        raise ReconstructionCheckpointError("construction certificate lacks graph bindings")
    for path, binding in ((graph_database, graph_db), (graph_receipt, graph_receipt_binding)):
        current = _binding(binding.role, path, root, binding.logical_sha256 or binding.bytes_sha256)
        if current.bytes_sha256 != binding.bytes_sha256 or current.byte_count != binding.byte_count:
            raise ReconstructionCheckpointError(
                "construction certificate input bytes do not replay"
            )
    if graph_db.logical_sha256 != graph.database_sha256:
        raise ReconstructionCheckpointError(
            "construction certificate graph database logical hash does not match"
        )
    if graph_receipt_binding.logical_sha256 != graph.output_sha256:
        raise ReconstructionCheckpointError(
            "construction certificate graph receipt logical hash does not match"
        )


def _assert_cross_artifact_bindings(  # noqa: PLR0913, PLR0917 - all sealed inputs are compared.
    graph: EvidenceGraphProjectionArtifact,
    graph_bindings: tuple[CheckpointBinding, CheckpointBinding],
    certificate: SourceNeutralCheckpointCertification,
    full: FullGraphSignalArtifact,
    full_bindings: tuple[CheckpointBinding, CheckpointBinding],
    cold: ColdLabelAlignmentArtifact,
    neighborhood: GenreNeighborhoodArtifact,
    neighborhood_bindings: tuple[CheckpointBinding, ...],
    hierarchy: HierarchyFusionArtifact,
    hierarchy_bindings: tuple[CheckpointBinding, ...],
    layout: SemanticLayoutArtifact,
    transfer: CoListenMembershipTransferArtifact,
) -> None:
    """Require every admitted signal to name this exact graph and certificate."""
    if (
        full.graph_database_sha256 != graph.database_sha256
        or full.graph_receipt_output_sha256 != graph.output_sha256
        or full.construction_certificate_output_sha256 != certificate.output_sha256
    ):
        raise ReconstructionCheckpointError(
            "full-graph signal lineage does not match graph certificate"
        )
    graph_database, graph_receipt = graph_bindings
    _assert_shared_source_binding(
        cold.inputs,
        "source_neutral_evidence_graph_database",
        graph_database,
        expected_logical=graph.output_sha256,
    )
    _assert_shared_source_binding(
        cold.inputs,
        "source_neutral_evidence_graph_receipt",
        graph_receipt,
        expected_logical=graph.output_sha256,
    )
    _assert_shared_source_binding(
        neighborhood.inputs,
        "graph_database",
        graph_database,
        expected_logical=graph.output_sha256,
    )
    _assert_shared_source_binding(
        neighborhood.inputs,
        "graph_receipt",
        graph_receipt,
        expected_logical=graph.output_sha256,
    )
    if neighborhood.graph_receipt_output_sha256 != graph.output_sha256:
        raise ReconstructionCheckpointError("neighborhood graph receipt does not match graph")
    full_artifact, full_receipt = full_bindings
    hierarchy_source = {item.role: item for item in hierarchy.inputs}
    _assert_hierarchy_source_binding(
        hierarchy_source.values(),
        "evidence_graph_database",
        graph_database,
        expected_logical=graph.output_sha256,
    )
    _assert_hierarchy_source_binding(
        hierarchy_source.values(),
        "evidence_graph_receipt",
        graph_receipt,
        expected_logical=graph.output_sha256,
    )
    _assert_hierarchy_source_binding(
        hierarchy_source.values(),
        "full_graph_containment",
        full_artifact,
        expected_logical=full.output_sha256,
    )
    _assert_hierarchy_source_binding(
        hierarchy_source.values(),
        "full_graph_containment_receipt",
        full_receipt,
        expected_logical=full.output_sha256,
    )
    neighborhood_artifact, _, neighborhood_database = neighborhood_bindings
    layout_source = {item.role: item for item in layout.inputs}
    _assert_shared_source_binding(
        layout_source.values(), "hierarchy_artifact", hierarchy_bindings[0]
    )
    _assert_shared_source_binding(
        layout_source.values(), "colisten_artifact", neighborhood_artifact
    )
    _assert_shared_source_binding(layout_source.values(), "colisten_cache", neighborhood_database)
    _assert_shared_source_binding(transfer.inputs, "graph_database", graph_database)
    _assert_shared_source_binding(transfer.inputs, "graph_receipt", graph_receipt)
    if transfer.graph_receipt_output_sha256 != graph.output_sha256:
        raise ReconstructionCheckpointError(
            "membership transfer graph receipt does not match graph"
        )
    if transfer.coverage.stable_seed_count != _SEED_COUNT:
        raise ReconstructionCheckpointError("membership transfer does not cover 6,291 seeds")
    if (
        transfer.historical_inputs_read_for_construction
        or transfer.audio_read_for_construction
        or transfer.listener_identifiers_read_for_construction
        or transfer.factual_memberships_written
    ):
        raise ReconstructionCheckpointError("membership transfer crossed the construction boundary")


def _assert_shared_source_binding(
    bindings: Iterable[
        ColdInputBinding | NeighborhoodInputBinding | LayoutInputBinding | TransferInputBinding
    ],
    role: str,
    expected: CheckpointBinding,
    *,
    expected_logical: str | None = None,
) -> None:
    """Compare a typed shared input row with one admitted checkpoint binding."""
    candidates = [item for item in bindings if item.role == role]
    if len(candidates) != 1 or candidates[0] is None:
        raise ReconstructionCheckpointError(f"missing cross-artifact binding for {role}")
    binding = candidates[0]
    if (
        binding.byte_sha256 != expected.bytes_sha256
        or binding.byte_count != expected.byte_count
        or binding.logical_sha256 != (expected_logical or expected.logical_sha256)
    ):
        raise ReconstructionCheckpointError(f"cross-artifact binding does not match for {role}")


def _assert_hierarchy_source_binding(
    bindings: Iterable[HierarchySourceBinding],
    role: str,
    expected: CheckpointBinding,
    *,
    expected_logical: str | None = None,
) -> None:
    """Compare one hierarchy source binding with an admitted checkpoint binding."""
    candidates = [item for item in bindings if item.role == role]
    if len(candidates) != 1:
        raise ReconstructionCheckpointError(f"missing cross-artifact binding for {role}")
    binding = candidates[0]
    if (
        binding.sha256 != expected.bytes_sha256
        or binding.byte_count != expected.byte_count
        or binding.logical_sha256 != (expected_logical or expected.logical_sha256)
    ):
        raise ReconstructionCheckpointError(f"cross-artifact binding does not match for {role}")


def _assert_construction_boundary(  # noqa: PLR0913, PLR0917 - all flags are checked together.
    bindings: tuple[CheckpointBinding, ...],
    certificate: SourceNeutralCheckpointCertification,
    full: FullGraphSignalArtifact,
    cold: ColdLabelAlignmentArtifact,
    neighborhood: GenreNeighborhoodArtifact,
    hierarchy: HierarchyFusionArtifact,
    layout: SemanticLayoutArtifact,
    transfer: CoListenMembershipTransferArtifact,
) -> None:
    if certificate.historical_inputs_used_for_construction:
        raise ReconstructionCheckpointError("construction certificate admits historical data")
    flags = (
        full.historical_inputs_read,
        cold.historical_inputs_read,
        neighborhood.historical_inputs_read_for_construction,
        hierarchy.historical_inputs_used_for_construction,
        layout.historical_inputs_read_for_construction,
        transfer.historical_inputs_read_for_construction,
        transfer.audio_read_for_construction,
        transfer.listener_identifiers_read_for_construction,
        transfer.factual_memberships_written,
    )
    if any(flags):
        raise ReconstructionCheckpointError("a construction artifact declares historical input")
    if any(
        any(term in f"{item.role}/{item.locator}".casefold() for term in _HISTORICAL_TERMS)
        for item in bindings
    ):
        raise ReconstructionCheckpointError("historical-looking path entered construction bindings")


def _assert_seed_universe(  # noqa: PLR0913, PLR0917 - all sealed signals are compared together.
    graph_seed_hash: str,
    full: FullGraphSignalArtifact,
    cold: ColdLabelAlignmentArtifact,
    neighborhood: GenreNeighborhoodArtifact,
    neighborhood_seed_hash: str,
    hierarchy: HierarchyFusionArtifact,
    hierarchy_seed_hash: str,
    layout: SemanticLayoutArtifact,
) -> str:
    if cold.coverage.seed_count != _SEED_COUNT or neighborhood.stable_seed_count != _SEED_COUNT:
        raise ReconstructionCheckpointError("construction artifacts do not cover 6,291 seeds")
    if tuple(cache.column_count for cache in full.matrix_caches) != (_SEED_COUNT,) * 3:
        raise ReconstructionCheckpointError("full graph matrices do not cover 6,291 seeds")
    if hierarchy.coverage.seed_count != _SEED_COUNT:
        raise ReconstructionCheckpointError("hierarchy does not cover 6,291 seeds")
    if layout.stable_seed_count != _SEED_COUNT:
        raise ReconstructionCheckpointError("layout does not cover 6,291 seeds")
    cold_seed_hash = _seed_hash(row.source_item_id for row in cold.seed_partition)
    layout_seed_hash = _seed_hash(
        tuple(item.seed_id for item in layout.coordinates)
        + tuple(item.seed_id for item in layout.unplaced)
    )
    if (
        len(
            {
                graph_seed_hash,
                cold_seed_hash,
                neighborhood_seed_hash,
                hierarchy_seed_hash,
                layout_seed_hash,
            }
        )
        != 1
    ):
        raise ReconstructionCheckpointError(
            "construction artifacts do not share one seed identity universe"
        )
    return cold_seed_hash


def _seed_hash(seed_ids: Iterable[object]) -> str:
    """Hash the exact sorted stable-seed universe, independent of row order."""
    try:
        ordered = tuple(sorted(str(seed_id) for seed_id in seed_ids))
    except TypeError as error:
        raise ReconstructionCheckpointError("seed universe is not iterable") from error
    if len(ordered) != len(set(ordered)):
        raise ReconstructionCheckpointError("seed universe contains duplicate identities")
    return sha256_hex(canonical_json(ordered))
