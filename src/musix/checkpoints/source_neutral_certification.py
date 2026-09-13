"""Certify source-neutral checkpoint inputs and evaluate a held-out legacy reference."""

from __future__ import annotations

import hashlib
import json
from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field

from musix.common import (
    canonical_json,
    connect_readonly,
    sha256_file,
    sha256_hex,
    write_atomic_bytes,
)
from musix.evidence.graph_projection import (
    EvidenceGraphProjectionArtifact,
    verify_evidence_graph_projection,
)
from musix.models import FrozenModel
from musix.peers.audit.strength_aware_peer_audit import ConsensusMicroNeighborhoodAudit
from musix.taxonomy.relations.expansion import TaxonomyRelationExpansionArtifact

if TYPE_CHECKING:
    from pathlib import Path

_REVISION: Final = "source-neutral-checkpoint-certification-v1"
_SEED_COUNT: Final = 6_291


class CheckpointCertificationError(ValueError):
    """A checkpoint input cannot support a reproducible certification."""


class InputBinding(FrozenModel):
    """Exact byte and, when available, logical identities of one sealed input."""

    role: str = Field(min_length=1)
    bytes_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(gt=0)
    logical_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class HistoricalEvaluationNode(FrozenModel):
    """The held-out legacy node fields relevant to positive-only evaluation."""

    genre_id: str = Field(min_length=1)
    membership_count: int = Field(ge=0)


class HistoricalEvaluationNeighbor(FrozenModel):
    """One held-out legacy peer observation, never a construction input."""

    genre_id: str = Field(min_length=1)
    neighbor_genre_id: str = Field(min_length=1)


class HistoricalEvaluationArtifact(FrozenModel):
    """A narrow parsed view of the held-out historical output."""

    revision: str = Field(min_length=1)
    nodes: tuple[HistoricalEvaluationNode, ...] = Field(
        min_length=_SEED_COUNT, max_length=_SEED_COUNT
    )
    neighbors: tuple[HistoricalEvaluationNeighbor, ...]


class MembershipCertification(FrozenModel):
    """Positive-only membership coverage; absent positives are deliberately unknown."""

    certified_observed_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    certified_unknown_seed_count: int = Field(ge=0, le=_SEED_COUNT)


class PeerCertification(FrozenModel):
    """Overlap with an evaluation-only peer reference, without a parity assertion."""

    certified_stable_pair_count: int = Field(ge=0)
    eligible_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    explicit_abstention_count: int = Field(ge=0, le=_SEED_COUNT)


class HierarchyCertification(FrozenModel):
    """Exact-QID factual coverage alongside non-factual historical hierarchy coverage."""

    accepted_factual_edge_count: int = Field(ge=0)
    factual_endpoint_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    factual_isolated_seed_count: int = Field(ge=0, le=_SEED_COUNT)


class SourceNeutralCheckpointCertification(FrozenModel):
    """A deterministic construction-only certification of sealed source-neutral inputs."""

    revision: Literal["source-neutral-checkpoint-certification-v1"] = _REVISION
    historical_inputs_used_for_construction: Literal[False] = False
    inputs: tuple[InputBinding, ...] = Field(min_length=4, max_length=4)
    stable_seed_count: Literal[6291] = _SEED_COUNT
    graph_explicit_abstention_row_count: int = Field(ge=0)
    membership: MembershipCertification
    peers: PeerCertification
    hierarchy: HierarchyCertification
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class HistoricalCheckpointEvaluation(FrozenModel):
    """A separately invoked blind comparison with a historical output."""

    revision: Literal["source-neutral-checkpoint-historical-evaluation-v2"] = (
        "source-neutral-checkpoint-historical-evaluation-v2"
    )
    certification_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    historical_input: InputBinding
    historical_inputs_used_for_construction: Literal[False] = False
    historical_data_used_for_evaluation: Literal[True] = True
    historical_absence_is_negative: Literal[False] = False
    parity_claims_made: Literal[False] = False
    historical_observed_membership_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    observed_membership_seed_overlap_count: int = Field(ge=0, le=_SEED_COUNT)
    historical_observed_peer_pair_count: int = Field(ge=0)
    observed_peer_pair_overlap_count: int = Field(ge=0)
    historical_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class SourceNeutralCheckpointInputs:
    """Paths consumed only at certification, after source-neutral construction."""

    graph_database: Path
    graph_receipt: Path
    consensus_micro_neighborhoods: Path
    exact_qid_taxonomy: Path


def certification_sha256(certification: SourceNeutralCheckpointCertification) -> str:
    """Return the canonical logical checksum for a completed certification."""
    return sha256_hex(
        canonical_json(certification.model_dump(mode="json", exclude={"output_sha256"}))
    )


def verify_source_neutral_checkpoint_certification(
    certification: SourceNeutralCheckpointCertification,
) -> None:
    """Fail closed when a persisted certification has been changed."""
    if certification_sha256(certification) != certification.output_sha256:
        raise CheckpointCertificationError("checkpoint certification hash does not replay")


def build_source_neutral_checkpoint_certification(
    inputs: SourceNeutralCheckpointInputs,
) -> SourceNeutralCheckpointCertification:
    """Bind final source-neutral artifacts without accepting historical evaluation data."""
    graph_receipt, graph_receipt_binding = _load_graph_receipt(inputs.graph_receipt)
    graph_seed_ids, graph_abstentions, graph_membership_ids = _load_graph_database(
        inputs.graph_database, graph_receipt
    )
    consensus, consensus_binding = _load_consensus(inputs.consensus_micro_neighborhoods)
    taxonomy, taxonomy_binding = _load_taxonomy(inputs.exact_qid_taxonomy)
    _validate_cross_artifact_bindings(graph_receipt, consensus, taxonomy)
    _validate_seed_accounting(graph_seed_ids, consensus, taxonomy)
    factual_endpoints = {
        endpoint
        for edge in taxonomy.edges
        if edge.disposition == "accepted_factual"
        for endpoint in (edge.child_seed_id, edge.parent_seed_id)
    }
    base = SourceNeutralCheckpointCertification(
        inputs=(
            _database_binding(inputs.graph_database, graph_receipt),
            graph_receipt_binding,
            consensus_binding,
            taxonomy_binding,
        ),
        graph_explicit_abstention_row_count=graph_abstentions,
        membership=MembershipCertification(
            certified_observed_seed_count=len(graph_membership_ids),
            certified_unknown_seed_count=_SEED_COUNT - len(graph_membership_ids),
        ),
        peers=PeerCertification(
            certified_stable_pair_count=consensus.stable_pair_count,
            eligible_seed_count=consensus.eligible_seed_count,
            explicit_abstention_count=consensus.abstention_count,
        ),
        hierarchy=HierarchyCertification(
            accepted_factual_edge_count=taxonomy.coverage.accepted_factual_edge_count,
            factual_endpoint_seed_count=len(factual_endpoints),
            factual_isolated_seed_count=taxonomy.coverage.factual_isolated_seed_count,
        ),
        output_sha256="0" * 64,
    )
    certification = base.model_copy(update={"output_sha256": certification_sha256(base)})
    verify_source_neutral_checkpoint_certification(certification)
    return certification


def evaluate_source_neutral_checkpoint_against_historical(
    certification: SourceNeutralCheckpointCertification,
    certified_inputs: SourceNeutralCheckpointInputs,
    historical_path: Path,
) -> HistoricalCheckpointEvaluation:
    """Read history only after a construction-only certification has been completed."""
    verify_source_neutral_checkpoint_certification(certification)
    replayed = build_source_neutral_checkpoint_certification(certified_inputs)
    if replayed.output_sha256 != certification.output_sha256:
        raise CheckpointCertificationError("provided final inputs do not replay certification")
    graph_receipt, _ = _load_graph_receipt(certified_inputs.graph_receipt)
    graph_seed_ids, _, graph_membership_ids = _load_graph_database(
        certified_inputs.graph_database, graph_receipt
    )
    consensus, _ = _load_consensus(certified_inputs.consensus_micro_neighborhoods)
    historical, historical_binding = _load_historical(historical_path)
    historical_ids = {_historical_seed_id(node.genre_id) for node in historical.nodes}
    _validate_historical_seed_universe(historical_ids, graph_seed_ids)
    historical_membership_ids = {
        _historical_seed_id(node.genre_id) for node in historical.nodes if node.membership_count > 0
    }
    historical_pairs = {
        _pair(
            _historical_seed_id(neighbor.genre_id),
            _historical_seed_id(neighbor.neighbor_genre_id),
        )
        for neighbor in historical.neighbors
    }
    _validate_historical_neighbor_endpoints(historical_pairs, historical_ids)
    consensus_pairs = {
        _pair(pair.source_genre_id, pair.target_genre_id) for pair in consensus.stable_pairs
    }
    base = HistoricalCheckpointEvaluation(
        certification_output_sha256=certification.output_sha256,
        historical_input=historical_binding,
        historical_observed_membership_seed_count=len(historical_membership_ids),
        observed_membership_seed_overlap_count=len(
            graph_membership_ids & historical_membership_ids
        ),
        historical_observed_peer_pair_count=len(historical_pairs),
        observed_peer_pair_overlap_count=len(consensus_pairs & historical_pairs),
        historical_seed_count=len(historical_ids),
        output_sha256="0" * 64,
    )
    return base.model_copy(update={"output_sha256": _evaluation_sha256(base)})


def write_source_neutral_checkpoint_certification(
    path: Path, certification: SourceNeutralCheckpointCertification
) -> None:
    """Atomically persist a certification after replaying its logical digest."""
    verify_source_neutral_checkpoint_certification(certification)
    write_atomic_bytes(path, certification.model_dump_json(indent=2).encode() + b"\n")


def write_historical_checkpoint_evaluation(
    path: Path, evaluation: HistoricalCheckpointEvaluation
) -> None:
    """Atomically persist the separately generated historical evaluation."""
    if _evaluation_sha256(evaluation) != evaluation.output_sha256:
        raise CheckpointCertificationError("historical checkpoint evaluation hash does not replay")
    write_atomic_bytes(path, evaluation.model_dump_json(indent=2).encode() + b"\n")


def _load_graph_receipt(path: Path) -> tuple[EvidenceGraphProjectionArtifact, InputBinding]:
    raw = path.read_bytes()
    try:
        receipt = EvidenceGraphProjectionArtifact.model_validate_json(raw)
        verify_evidence_graph_projection(receipt)
    except (OSError, ValueError) as error:
        raise CheckpointCertificationError("invalid evidence graph receipt") from error
    return receipt, _binding("evidence_graph_receipt", path, receipt.output_sha256)


def _load_graph_database(
    path: Path, receipt: EvidenceGraphProjectionArtifact
) -> tuple[set[str], int, set[str]]:
    digest, size = sha256_file(path)
    if (digest, size) != (receipt.database_sha256, receipt.database_bytes):
        raise CheckpointCertificationError("evidence graph database does not match receipt")
    try:
        with closing(connect_readonly(path)) as database:
            if database.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise CheckpointCertificationError("evidence graph database integrity check failed")
            database_inputs = tuple(
                database.execute(
                    "SELECT role, path, byte_sha256, byte_count, logical_sha256 "
                    "FROM artifact_input ORDER BY role"
                )
            )
            receipt_inputs = tuple(
                (item.role, item.path, item.byte_sha256, item.byte_count, item.logical_sha256)
                for item in sorted(receipt.inputs, key=lambda item: item.role)
            )
            if database_inputs != receipt_inputs:
                raise CheckpointCertificationError(
                    "evidence graph database input bindings differ from receipt"
                )
            seed_ids = {
                str(row[0])
                for row in database.execute(
                    "SELECT identifier FROM identity WHERE namespace = 'stable_seed'"
                )
            }
            abstentions = int(database.execute("SELECT count(*) FROM abstention").fetchone()[0])
            membership_ids = {
                str(row[0])
                for row in database.execute(
                    "SELECT DISTINCT object_identifier FROM claim "
                    "WHERE predicate = 'artist_membership' AND object_namespace = 'stable_seed'"
                )
            }
    except (OSError, ValueError) as error:
        raise CheckpointCertificationError("invalid evidence graph database") from error
    if len(seed_ids) != _SEED_COUNT or not membership_ids <= seed_ids:
        raise CheckpointCertificationError(
            "evidence graph does not contain the complete seed universe"
        )
    return seed_ids, abstentions, membership_ids


def _load_consensus(path: Path) -> tuple[ConsensusMicroNeighborhoodAudit, InputBinding]:
    raw = path.read_bytes()
    try:
        value = ConsensusMicroNeighborhoodAudit.model_validate_json(raw)
        declared = _logical_sha256(raw)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise CheckpointCertificationError(
            "invalid consensus micro-neighborhood artifact"
        ) from error
    if declared != value.output_sha256:
        raise CheckpointCertificationError("consensus micro-neighborhood hash does not replay")
    return value, _binding("consensus_micro_neighborhoods", path, value.output_sha256)


def _load_taxonomy(path: Path) -> tuple[TaxonomyRelationExpansionArtifact, InputBinding]:
    raw = path.read_bytes()
    try:
        value = TaxonomyRelationExpansionArtifact.model_validate_json(raw)
    except (OSError, ValueError) as error:
        raise CheckpointCertificationError("invalid exact-QID taxonomy artifact") from error
    return value, _binding("exact_qid_factual_taxonomy", path, value.output_sha256)


def _load_historical(path: Path) -> tuple[HistoricalEvaluationArtifact, InputBinding]:
    raw = path.read_bytes()
    try:
        value = HistoricalEvaluationArtifact.model_validate_json(raw)
    except (OSError, ValueError) as error:
        raise CheckpointCertificationError(
            "invalid held-out historical evaluation artifact"
        ) from error
    return value, _binding("held_out_historical_evaluation", path, None)


def _validate_cross_artifact_bindings(
    receipt: EvidenceGraphProjectionArtifact,
    consensus: ConsensusMicroNeighborhoodAudit,
    taxonomy: TaxonomyRelationExpansionArtifact,
) -> None:
    bindings = {item.role: item for item in receipt.inputs}
    direct = bindings.get("direct_peer")
    support = bindings.get("support_peer")
    hierarchy = bindings.get("wikidata_factual_hierarchy")
    if direct is None or support is None or hierarchy is None:
        raise CheckpointCertificationError(
            "evidence graph receipt lacks a required source-neutral input"
        )
    if (direct.byte_sha256, direct.logical_sha256) != (
        consensus.direct_input.artifact_bytes_sha256,
        consensus.direct_input.artifact_logical_sha256,
    ) or (support.byte_sha256, support.logical_sha256) != (
        consensus.support_input.artifact_bytes_sha256,
        consensus.support_input.artifact_logical_sha256,
    ):
        raise CheckpointCertificationError(
            "consensus channel bindings do not match evidence graph inputs"
        )
    if hierarchy.logical_sha256 != taxonomy.output_sha256:
        raise CheckpointCertificationError("taxonomy binding does not match evidence graph input")
    if taxonomy.historical_data_used_for_construction:
        raise CheckpointCertificationError("taxonomy construction must exclude historical data")


def _validate_seed_accounting(
    graph_seed_ids: set[str],
    consensus: ConsensusMicroNeighborhoodAudit,
    taxonomy: TaxonomyRelationExpansionArtifact,
) -> None:
    eligible = {row.genre_id for row in consensus.ego_affiliations}
    abstained = {row.genre_id for row in consensus.abstentions}
    if (
        len(eligible) != consensus.eligible_seed_count
        or len(abstained) != consensus.abstention_count
    ):
        raise CheckpointCertificationError("consensus seed counts do not match explicit rows")
    if eligible & abstained or eligible | abstained != graph_seed_ids:
        raise CheckpointCertificationError(
            "consensus does not explicitly account for every graph seed"
        )
    if taxonomy.coverage.seed_count != _SEED_COUNT:
        raise CheckpointCertificationError("taxonomy does not bind the complete seed universe")
    taxonomy_endpoints = {
        endpoint
        for edge in taxonomy.edges
        for endpoint in (edge.child_seed_id, edge.parent_seed_id)
    }
    if not taxonomy_endpoints <= graph_seed_ids:
        raise CheckpointCertificationError(
            "taxonomy contains endpoints outside the graph seed universe"
        )


def _binding(role: str, path: Path, logical_sha256: str | None) -> InputBinding:
    digest, size = sha256_file(path)
    return InputBinding(
        role=role, bytes_sha256=digest, byte_count=size, logical_sha256=logical_sha256
    )


def _database_binding(path: Path, receipt: EvidenceGraphProjectionArtifact) -> InputBinding:
    binding = _binding("evidence_graph_database", path, receipt.database_sha256)
    if (binding.bytes_sha256, binding.byte_count) != (
        receipt.database_sha256,
        receipt.database_bytes,
    ):
        raise CheckpointCertificationError("evidence graph database binding does not replay")
    return binding


def _logical_sha256(raw: bytes) -> str:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise TypeError("artifact must be a JSON object")
    payload = {key: item for key, item in value.items() if key != "output_sha256"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _evaluation_sha256(evaluation: HistoricalCheckpointEvaluation) -> str:
    return sha256_hex(canonical_json(evaluation.model_dump(mode="json", exclude={"output_sha256"})))


def _pair(left: str, right: str) -> tuple[str, str]:
    return (left, right) if left <= right else (right, left)


def _historical_seed_id(value: str) -> str:
    """Bridge the sole declared historical namespace into stable seed IDs."""
    prefix = "enao-legacy:"
    if not value.startswith(prefix):
        raise CheckpointCertificationError("historical evaluation ID lacks enao-legacy namespace")
    stable_id = value.removeprefix(prefix)
    if not stable_id or stable_id.startswith(prefix):
        raise CheckpointCertificationError("historical evaluation ID is malformed")
    return stable_id


def _validate_historical_seed_universe(historical_ids: set[str], graph_seed_ids: set[str]) -> None:
    """Require a one-to-one historical namespace bridge, not just equal cardinality."""
    if historical_ids != graph_seed_ids:
        raise CheckpointCertificationError(
            "historical evaluation artifact does not match the graph seed universe"
        )


def _validate_historical_neighbor_endpoints(
    historical_pairs: set[tuple[str, str]], historical_ids: set[str]
) -> None:
    """Reject historical neighbor rows outside the validated bridged universe."""
    if any(endpoint not in historical_ids for pair in historical_pairs for endpoint in pair):
        raise CheckpointCertificationError("historical evaluation has a dangling neighbor endpoint")
