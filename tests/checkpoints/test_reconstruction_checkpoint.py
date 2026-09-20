from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from opennoise.checkpoints.reconstruction_checkpoint import (
    AxisCoverage,
    CheckpointBinding,
    ConstructionBoundary,
    MembershipTransferSummary,
    ReconstructionCheckpoint,
    ReconstructionCheckpointError,
    ReconstructionCheckpointInputs,
    _assert_construction_boundary,
    _assert_cross_artifact_bindings,
    _assert_seed_universe,
    _load_graph,
    _load_membership_transfer,
    build_reconstruction_checkpoint,
    checkpoint_sha256,
    verify_reconstruction_checkpoint,
)
from opennoise.checkpoints.source_neutral_certification import (
    HierarchyCertification,
    InputBinding,
    MembershipCertification,
    PeerCertification,
    SourceNeutralCheckpointCertification,
    certification_sha256,
)
from opennoise.common import canonical_json, sha256_file, sha256_hex
from opennoise.evidence.graph_projection import (
    ArtifactInput,
    EvidenceGraphProjectionArtifact,
    artifact_sha256,
)
from opennoise.ml.colisten_membership_transfer.contracts import (
    CoListenMembershipTransferArtifact,
    CoListenMembershipTransferReceipt,
    CoListenMembershipTransferSettings,
    TransferCoverage,
    TransferEvaluation,
)
from opennoise.ml.colisten_membership_transfer.contracts import (
    InputBinding as TransferArtifactInput,
)
from opennoise.ml.colisten_membership_transfer.contracts import (
    artifact_sha256 as transfer_artifact_sha256,
)
from opennoise.ml.colisten_membership_transfer.contracts import (
    settings_sha256 as transfer_settings_sha256,
)
from opennoise.ml.full_graph_signal.contracts import (
    FullGraphSignalArtifact,
    MatrixBinding,
    PairSplitCoverage,
)
from opennoise.ml.genre_neighborhoods.contracts import (
    ChannelCoverage,
    GenreNeighborhoodArtifact,
)
from opennoise.ml.genre_neighborhoods.contracts import (
    InputBinding as NeighborhoodArtifactInput,
)
from opennoise.ml.hierarchy_fusion.contracts import (
    HierarchyCoverage,
    HierarchyFusionArtifact,
    SeedHierarchyState,
    SourceBinding,
)
from opennoise.ml.label_alignment.contracts import (
    ColdLabelAlignmentArtifact,
    ColdLabelAlignmentCoverage,
    SeedPartitionRow,
)
from opennoise.ml.label_alignment.contracts import InputBinding as ColdArtifactInput
from opennoise.ml.semantic_layout.contracts import (
    GeometryMetrics,
    SemanticLayoutArtifact,
    UnplacedSeed,
)
from opennoise.ml.semantic_layout.contracts import InputBinding as LayoutArtifactInput


class ReconstructionCheckpointTests(unittest.TestCase):
    def test_axis_requires_historical_denominator_when_measured(self) -> None:
        with self.assertRaises(ValidationError):
            AxisCoverage(
                status="measured",
                candidate_observation_count=1,
                note="missing denominator",
            )

    def test_not_evaluable_axis_cannot_smuggle_historical_metrics(self) -> None:
        with self.assertRaises(ValidationError):
            AxisCoverage(
                status="not_evaluable",
                candidate_observation_count=1,
                historical_observation_count=2,
                note="not measured",
            )

    def test_checkpoint_hash_and_historical_boundary_replay(self) -> None:
        checkpoint = _checkpoint()
        self.assertEqual(checkpoint.output_sha256, checkpoint_sha256(checkpoint))
        verify_reconstruction_checkpoint(checkpoint)
        with self.assertRaises(ReconstructionCheckpointError):
            verify_reconstruction_checkpoint(
                checkpoint.model_copy(update={"historical_data_used_for_evaluation": True})
            )

    def test_checkpoint_locators_must_be_relative(self) -> None:
        with self.assertRaises(ValidationError):
            CheckpointBinding(
                role="input",
                locator="/absolute/path.json",
                bytes_sha256="a" * 64,
                byte_count=1,
                logical_sha256="b" * 64,
            )

    def test_build_fixture_binds_sqlite_receipt_and_all_seed_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database, receipt, certificate = _graph_fixture(root)
            inputs = _inputs(root, database, receipt, certificate)
            fakes = _signal_fixtures()
            graph, graph_bindings, _ = _load_graph(database, receipt, root)
            certificate_model = SourceNeutralCheckpointCertification.model_validate_json(
                certificate.read_bytes()
            )
            fakes = _bind_signal_fixtures(fakes, graph, graph_bindings, certificate_model)
            with (
                patch(
                    "opennoise.checkpoints.reconstruction_checkpoint._load_full_graph",
                    return_value=(
                        fakes.full,
                        (fakes.full_binding, fakes.full_binding),
                    ),
                ),
                patch(
                    "opennoise.checkpoints.reconstruction_checkpoint._load_cold",
                    return_value=(fakes.cold, (fakes.cold_binding,)),
                ),
                patch(
                    "opennoise.checkpoints.reconstruction_checkpoint._load_neighborhood",
                    return_value=(
                        fakes.neighborhood,
                        (
                            fakes.neighborhood_binding,
                            fakes.neighborhood_binding,
                            fakes.neighborhood_binding,
                        ),
                        fakes.seed_hash,
                    ),
                ),
                patch(
                    "opennoise.checkpoints.reconstruction_checkpoint._load_hierarchy",
                    return_value=(fakes.hierarchy, (fakes.hierarchy_binding,), fakes.seed_hash),
                ),
                patch(
                    "opennoise.checkpoints.reconstruction_checkpoint._load_layout",
                    return_value=(fakes.layout, fakes.layout_binding),
                ),
                patch(
                    "opennoise.checkpoints.reconstruction_checkpoint._load_membership_transfer",
                    return_value=(
                        fakes.transfer,
                        (fakes.transfer_binding, fakes.transfer_binding),
                    ),
                ),
            ):
                checkpoint = build_reconstruction_checkpoint(inputs)
            self.assertEqual(checkpoint.stable_seed_count, 6291)
            self.assertEqual(checkpoint.seed_identity_sha256, fakes.seed_hash)
            self.assertFalse(checkpoint.historical_data_used_for_evaluation)

    def test_build_fixture_rejects_receipt_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database, receipt, _ = _graph_fixture(root)
            original = EvidenceGraphProjectionArtifact.model_validate_json(receipt.read_bytes())
            tampered = original.model_copy(update={"database_sha256": "f" * 64})
            receipt.write_bytes(
                tampered.model_copy(update={"output_sha256": artifact_sha256(tampered)})
                .model_dump_json()
                .encode()
            )
            with self.assertRaises(ReconstructionCheckpointError):
                _load_graph(database, receipt, root)

    def test_build_fixture_rejects_seed_universe_mismatch(self) -> None:
        fakes = _signal_fixtures()
        with self.assertRaises(ReconstructionCheckpointError):
            _assert_seed_universe(
                fakes.seed_hash,
                fakes.full,
                fakes.cold,
                fakes.neighborhood,
                sha256_hex(canonical_json(tuple(fakes.seed_ids[:-1]))),
                fakes.hierarchy,
                fakes.seed_hash,
                fakes.layout,
            )

    def test_build_fixture_rejects_cross_signal_graph_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database, receipt, certificate_path = _graph_fixture(root)
            graph, graph_bindings, _ = _load_graph(database, receipt, root)
            certificate = SourceNeutralCheckpointCertification.model_validate_json(
                certificate_path.read_bytes()
            )
            fakes = _bind_signal_fixtures(_signal_fixtures(), graph, graph_bindings, certificate)
            bad_full = fakes.full.model_copy(update={"graph_database_sha256": "e" * 64})
            with self.assertRaises(ReconstructionCheckpointError):
                _assert_cross_artifact_bindings(
                    graph,
                    graph_bindings,
                    certificate,
                    bad_full,
                    (fakes.full_binding, fakes.full_binding),
                    fakes.cold,
                    fakes.neighborhood,
                    (
                        fakes.neighborhood_binding,
                        fakes.neighborhood_binding,
                        fakes.neighborhood_binding,
                    ),
                    fakes.hierarchy,
                    (fakes.hierarchy_binding,),
                    fakes.layout,
                    fakes.transfer,
                )
            with self.assertRaises(ReconstructionCheckpointError):
                _assert_cross_artifact_bindings(
                    graph,
                    graph_bindings,
                    certificate,
                    fakes.full,
                    (fakes.full_binding, fakes.full_binding),
                    fakes.cold,
                    fakes.neighborhood,
                    (
                        fakes.neighborhood_binding,
                        fakes.neighborhood_binding,
                        fakes.neighborhood_binding,
                    ),
                    fakes.hierarchy,
                    (fakes.hierarchy_binding,),
                    fakes.layout,
                    fakes.transfer.model_copy(update={"graph_receipt_output_sha256": "f" * 64}),
                )

    def test_membership_transfer_receipt_tamper_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact, receipt = _transfer_fixture(root)
            value = json.loads(receipt.read_bytes())
            value["logical_output_sha256"] = "f" * 64
            receipt.write_text(json.dumps(value))
            with self.assertRaises(ReconstructionCheckpointError):
                _load_membership_transfer(artifact, receipt, root)

    def test_build_fixture_rejects_historical_construction_flag(self) -> None:
        fakes = _signal_fixtures()
        with self.assertRaises(ReconstructionCheckpointError):
            certificate = SourceNeutralCheckpointCertification.model_construct(
                historical_inputs_used_for_construction=False
            )
            _assert_construction_boundary(
                (),
                certificate,
                FullGraphSignalArtifact.model_construct(historical_inputs_read=True),
                fakes.cold,
                fakes.neighborhood,
                fakes.hierarchy,
                fakes.layout,
                fakes.transfer,
            )

    def test_build_fixture_rejects_transfer_boundary_flag(self) -> None:
        fakes = _signal_fixtures()
        certificate = SourceNeutralCheckpointCertification.model_construct(
            historical_inputs_used_for_construction=False
        )
        with self.assertRaises(ReconstructionCheckpointError):
            _assert_construction_boundary(
                (),
                certificate,
                FullGraphSignalArtifact.model_construct(historical_inputs_read=False),
                fakes.cold,
                fakes.neighborhood,
                fakes.hierarchy,
                fakes.layout,
                fakes.transfer.model_copy(update={"audio_read_for_construction": True}),
            )


def _graph_fixture(root: Path) -> tuple[Path, Path, Path]:
    database = root / "graph.sqlite"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("CREATE TABLE identity (namespace TEXT, identifier TEXT)")
        connection.executemany(
            "INSERT INTO identity VALUES ('stable_seed', ?)",
            ((f"seed-{index:04d}",) for index in range(6291)),
        )
    database_sha, database_bytes = sha256_file(database)
    receipt_base = EvidenceGraphProjectionArtifact(
        inputs=tuple(
            ArtifactInput(
                role=f"fixture-{index}",
                path=f"fixture-{index}",
                byte_sha256="a" * 64,
                byte_count=1,
                logical_sha256="b" * 64,
            )
            for index in range(8)
        ),
        database_sha256=database_sha,
        database_bytes=database_bytes,
        identity_count=6291,
        total_identity_count=6291,
        claim_count=0,
        abstention_count=0,
        factual_relation_count=0,
        candidate_relation_score_count=0,
        output_sha256="0" * 64,
    )
    receipt = root / "graph.receipt.json"
    receipt.write_bytes(
        receipt_base.model_copy(update={"output_sha256": artifact_sha256(receipt_base)})
        .model_dump_json()
        .encode()
    )
    receipt_model = EvidenceGraphProjectionArtifact.model_validate_json(receipt.read_bytes())
    receipt_sha, receipt_bytes = sha256_file(receipt)
    certificate_base = SourceNeutralCheckpointCertification(
        inputs=(
            InputBinding(
                role="evidence_graph_database",
                bytes_sha256=database_sha,
                byte_count=database_bytes,
                logical_sha256=database_sha,
            ),
            InputBinding(
                role="evidence_graph_receipt",
                bytes_sha256=receipt_sha,
                byte_count=receipt_bytes,
                logical_sha256=receipt_model.output_sha256,
            ),
            InputBinding(
                role="fixture-consensus",
                bytes_sha256="a" * 64,
                byte_count=1,
                logical_sha256="b" * 64,
            ),
            InputBinding(
                role="fixture-taxonomy",
                bytes_sha256="c" * 64,
                byte_count=1,
                logical_sha256="d" * 64,
            ),
        ),
        graph_explicit_abstention_row_count=0,
        membership=MembershipCertification(
            certified_observed_seed_count=6291, certified_unknown_seed_count=0
        ),
        peers=PeerCertification(
            certified_stable_pair_count=0,
            eligible_seed_count=6291,
            explicit_abstention_count=0,
        ),
        hierarchy=HierarchyCertification(
            accepted_factual_edge_count=0,
            factual_endpoint_seed_count=0,
            factual_isolated_seed_count=6291,
        ),
        output_sha256="0" * 64,
    )
    certificate = root / "construction.json"
    certificate.write_bytes(
        certificate_base.model_copy(
            update={"output_sha256": certification_sha256(certificate_base)}
        )
        .model_dump_json()
        .encode()
    )
    return database, receipt, certificate


def _transfer_fixture(root: Path) -> tuple[Path, Path]:
    settings = CoListenMembershipTransferSettings()
    empty_evaluation = TransferEvaluation(
        heldout_direct_positive_count=0,
        eligible_heldout_artist_count=0,
        abstained_no_colisten_or_support_artist_count=0,
        scoreable_direct_positive_count=0,
        recovered_at_10_count=0,
        recovered_at_25_count=0,
        recall_at_10=None,
        recall_at_25=None,
    )
    artifact_base = CoListenMembershipTransferArtifact(
        inputs=tuple(
            TransferArtifactInput(
                role=role,
                byte_sha256="a" * 64,
                byte_count=1,
                logical_sha256="b" * 64,
            )
            for role in ("graph_database", "graph_receipt", "colisten_database", "colisten_receipt")
        ),
        graph_receipt_output_sha256="b" * 64,
        colisten_receipt_output_sha256="b" * 64,
        settings=settings,
        settings_sha256=transfer_settings_sha256(settings),
        coverage=TransferCoverage(
            colisten_artist_count=0,
            direct_labeled_colisten_artist_count=0,
            direct_cold_colisten_artist_count=0,
            eligible_cold_artist_count=0,
            abstained_cold_artist_count=0,
            candidate_count=0,
        ),
        candidates=(),
        heldout_evaluation=empty_evaluation,
        train_only_global_popularity_baseline=empty_evaluation,
        direct_only_no_colisten_ablation=empty_evaluation,
        output_sha256="0" * 64,
    )
    artifact = artifact_base.model_copy(
        update={"output_sha256": transfer_artifact_sha256(artifact_base)}
    )
    artifact_path = root / "transfer.json"
    artifact_path.write_bytes(canonical_json(artifact.model_dump(mode="json")) + b"\n")
    digest, byte_count = sha256_file(artifact_path)
    receipt = CoListenMembershipTransferReceipt(
        artifact_sha256=digest,
        artifact_byte_count=byte_count,
        logical_output_sha256=artifact.output_sha256,
    )
    receipt_path = root / "transfer.receipt.json"
    receipt_path.write_bytes(canonical_json(receipt.model_dump(mode="json")) + b"\n")
    return artifact_path, receipt_path


def _inputs(
    root: Path, database: Path, receipt: Path, certificate: Path
) -> ReconstructionCheckpointInputs:
    placeholder = root / "placeholder.json"
    placeholder.write_text("{}")
    return ReconstructionCheckpointInputs(
        root=root,
        graph_database=database,
        graph_receipt=receipt,
        construction_certificate=certificate,
        full_graph=placeholder,
        full_graph_receipt=placeholder,
        cold_alignment=placeholder,
        cold_alignment_receipt=placeholder,
        neighborhoods=placeholder,
        neighborhoods_receipt=placeholder,
        neighborhoods_database=placeholder,
        hierarchy=placeholder,
        hierarchy_receipt=None,
        layout=placeholder,
        membership_transfer=placeholder,
        membership_transfer_receipt=placeholder,
    )


@dataclass(frozen=True, slots=True)
class FixtureSignals:
    seed_ids: tuple[str, ...]
    seed_hash: str
    full: FullGraphSignalArtifact
    cold: ColdLabelAlignmentArtifact
    neighborhood: GenreNeighborhoodArtifact
    hierarchy: HierarchyFusionArtifact
    layout: SemanticLayoutArtifact
    full_binding: CheckpointBinding
    cold_binding: CheckpointBinding
    neighborhood_binding: CheckpointBinding
    hierarchy_binding: CheckpointBinding
    layout_binding: CheckpointBinding
    transfer: CoListenMembershipTransferArtifact
    transfer_binding: CheckpointBinding


def _bind_signal_fixtures(
    fakes: FixtureSignals,
    graph: EvidenceGraphProjectionArtifact,
    graph_bindings: tuple[CheckpointBinding, CheckpointBinding],
    certificate: SourceNeutralCheckpointCertification,
) -> FixtureSignals:
    graph_database, graph_receipt = graph_bindings
    shared_cold = (
        ColdArtifactInput.model_construct(
            role="source_neutral_evidence_graph_database",
            byte_sha256=graph_database.bytes_sha256,
            byte_count=graph_database.byte_count,
            logical_sha256=graph.output_sha256,
        ),
        ColdArtifactInput.model_construct(
            role="source_neutral_evidence_graph_receipt",
            byte_sha256=graph_receipt.bytes_sha256,
            byte_count=graph_receipt.byte_count,
            logical_sha256=graph.output_sha256,
        ),
    )
    neighborhood_inputs = (
        NeighborhoodArtifactInput.model_construct(
            role="graph_database",
            byte_sha256=graph_database.bytes_sha256,
            byte_count=graph_database.byte_count,
            logical_sha256=graph.output_sha256,
        ),
        NeighborhoodArtifactInput.model_construct(
            role="graph_receipt",
            byte_sha256=graph_receipt.bytes_sha256,
            byte_count=graph_receipt.byte_count,
            logical_sha256=graph.output_sha256,
        ),
    )
    hierarchy_inputs = tuple(
        SourceBinding(
            role=role,
            locator=role,
            sha256=binding.bytes_sha256,
            byte_count=binding.byte_count,
            logical_sha256=(graph.output_sha256 if role.startswith("evidence_graph") else "b" * 64),
        )
        for role, binding in (
            ("evidence_graph_database", graph_database),
            ("evidence_graph_receipt", graph_receipt),
            ("full_graph_containment", fakes.full_binding),
            ("full_graph_containment_receipt", fakes.full_binding),
        )
    )
    layout_inputs = tuple(
        LayoutArtifactInput.model_construct(
            role=role,
            byte_sha256=binding.bytes_sha256,
            byte_count=binding.byte_count,
            logical_sha256=binding.logical_sha256,
        )
        for role, binding in (
            ("hierarchy_artifact", fakes.hierarchy_binding),
            ("colisten_artifact", fakes.neighborhood_binding),
            ("colisten_cache", fakes.neighborhood_binding),
        )
    )
    return replace(
        fakes,
        full=fakes.full.model_copy(
            update={
                "output_sha256": "b" * 64,
                "graph_database_sha256": graph.database_sha256,
                "graph_receipt_output_sha256": graph.output_sha256,
                "construction_certificate_output_sha256": certificate.output_sha256,
            }
        ),
        cold=fakes.cold.model_copy(update={"inputs": shared_cold}),
        neighborhood=fakes.neighborhood.model_copy(
            update={
                "inputs": neighborhood_inputs,
                "graph_receipt_output_sha256": graph.output_sha256,
            }
        ),
        hierarchy=fakes.hierarchy.model_copy(update={"inputs": hierarchy_inputs}),
        layout=fakes.layout.model_copy(update={"inputs": layout_inputs}),
        transfer=fakes.transfer.model_copy(
            update={
                "inputs": (
                    TransferArtifactInput.model_construct(
                        role="graph_database",
                        byte_sha256=graph_database.bytes_sha256,
                        byte_count=graph_database.byte_count,
                        logical_sha256=graph.database_sha256,
                    ),
                    TransferArtifactInput.model_construct(
                        role="graph_receipt",
                        byte_sha256=graph_receipt.bytes_sha256,
                        byte_count=graph_receipt.byte_count,
                        logical_sha256=graph.output_sha256,
                    ),
                    TransferArtifactInput.model_construct(
                        role="colisten_database",
                        byte_sha256="a" * 64,
                        byte_count=1,
                        logical_sha256="b" * 64,
                    ),
                    TransferArtifactInput.model_construct(
                        role="colisten_receipt",
                        byte_sha256="a" * 64,
                        byte_count=1,
                        logical_sha256="b" * 64,
                    ),
                ),
                "graph_receipt_output_sha256": graph.output_sha256,
            }
        ),
    )


def _signal_fixtures() -> FixtureSignals:
    seed_ids = tuple(f"seed-{index:04d}" for index in range(6291))
    seed_hash = sha256_hex(canonical_json(seed_ids))
    fake_binding = CheckpointBinding(
        role="fixture",
        locator="fixture.json",
        bytes_sha256="a" * 64,
        byte_count=1,
        logical_sha256="b" * 64,
    )
    full = FullGraphSignalArtifact.model_construct(
        historical_inputs_read=False,
        matrix_caches=(MatrixBinding.model_construct(column_count=6291),) * 3,
        pair_split=PairSplitCoverage.model_construct(unique_pair_count=1),
    )
    cold = ColdLabelAlignmentArtifact.model_construct(
        historical_inputs_read=False,
        coverage=ColdLabelAlignmentCoverage.model_construct(
            seed_count=6291,
            open_identity_count=1,
            existing_open_identity_accepted_seed_count=1,
            inferred_unique_normalized_accepted_seed_count=0,
        ),
        seed_partition=tuple(
            SeedPartitionRow.model_construct(source_item_id=seed_id) for seed_id in seed_ids
        ),
    )
    neighborhood = GenreNeighborhoodArtifact.model_construct(
        historical_inputs_read_for_construction=False,
        stable_seed_count=6291,
        channels=(ChannelCoverage.model_construct(retained_neighbor_count=1),) * 2,
    )
    hierarchy = HierarchyFusionArtifact.model_construct(
        historical_inputs_used_for_construction=False,
        coverage=HierarchyCoverage.model_construct(
            seed_count=6291, factual_source_edge_count=1, review_edge_count=1
        ),
        seed_states=tuple(
            SeedHierarchyState.model_construct(seed_id=seed_id) for seed_id in seed_ids
        ),
    )
    layout = SemanticLayoutArtifact.model_construct(
        historical_inputs_read_for_construction=False,
        stable_seed_count=6291,
        metrics=GeometryMetrics.model_construct(placed_seed_count=0),
        coordinates=(),
        unplaced=tuple(UnplacedSeed.model_construct(seed_id=seed_id) for seed_id in seed_ids),
    )
    transfer = CoListenMembershipTransferArtifact.model_construct(
        historical_inputs_read_for_construction=False,
        audio_read_for_construction=False,
        listener_identifiers_read_for_construction=False,
        factual_memberships_written=False,
        graph_receipt_output_sha256="b" * 64,
        coverage=TransferCoverage.model_construct(
            stable_seed_count=6291,
            colisten_artist_count=1,
            direct_labeled_colisten_artist_count=1,
            direct_cold_colisten_artist_count=0,
            eligible_cold_artist_count=0,
            abstained_cold_artist_count=0,
            candidate_count=0,
        ),
        candidates=(),
        heldout_evaluation=TransferEvaluation.model_construct(
            heldout_direct_positive_count=0,
            eligible_heldout_artist_count=0,
            recall_at_10=None,
            recall_at_25=None,
        ),
        train_only_global_popularity_baseline=TransferEvaluation.model_construct(
            heldout_direct_positive_count=0,
            eligible_heldout_artist_count=0,
            recall_at_10=None,
            recall_at_25=None,
        ),
    )
    return FixtureSignals(
        seed_ids=seed_ids,
        seed_hash=seed_hash,
        full=full,
        cold=cold,
        neighborhood=neighborhood,
        hierarchy=hierarchy,
        layout=layout,
        full_binding=fake_binding,
        cold_binding=fake_binding,
        neighborhood_binding=fake_binding,
        hierarchy_binding=fake_binding,
        layout_binding=fake_binding,
        transfer=transfer,
        transfer_binding=fake_binding,
    )


def _checkpoint() -> ReconstructionCheckpoint:
    axis = AxisCoverage(
        status="not_evaluable",
        candidate_observation_count=0,
        note="No independent reference.",
    )
    base = ReconstructionCheckpoint(
        seed_identity_sha256="c" * 64,
        inputs=(
            CheckpointBinding(
                role="construction",
                locator=".cache/input.json",
                bytes_sha256="a" * 64,
                byte_count=1,
                logical_sha256="b" * 64,
            ),
        ),
        construction_boundary=ConstructionBoundary(
            historical_flags_checked=("fixture",),
        ),
        identities=axis,
        memberships=axis,
        neighborhoods=axis,
        hierarchy=axis,
        coordinates=axis,
        membership_transfer=MembershipTransferSummary(
            colisten_artist_count=0,
            review_candidate_count=0,
            eligible_cold_artist_count=0,
            abstained_cold_artist_count=0,
            heldout_direct_positive_count=0,
            heldout_eligible_artist_count=0,
        ),
        output_sha256="0" * 64,
    )
    return base.model_copy(update={"output_sha256": checkpoint_sha256(base)})


if __name__ == "__main__":
    unittest.main()
