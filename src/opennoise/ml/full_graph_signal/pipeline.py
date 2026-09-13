"""Orchestration and artifact persistence for the sparse graph signal."""

from __future__ import annotations

from array import array
from typing import TYPE_CHECKING

from opennoise.common import sha256_file, write_atomic_bytes

from .contracts import (
    _MODEL_NAMES,
    _REVISION,
    _SEED_COUNT,
    FullGraphSignalArtifact,
    FullGraphSignalError,
    FullGraphSignalInputs,
    FullGraphSignalReceipt,
    FullGraphSignalSettings,
    PairSplitCoverage,
    SourceScope,
    SvdDecision,
    _sha,
    full_graph_signal_artifact_sha256,
    full_graph_signal_settings_sha256,
)
from .evaluation import (
    _containment_candidates,
    _evaluate_membership,
    _heldout_by_artist,
    _peer_recovery,
)
from .input_cache import _load_inputs, _load_or_stream_pair_data, _load_or_write_matrices
from .sparse_baselines import (
    _cooccurrence,
    _cosine_neighbors,
    _csr,
    _jaccard_neighbors,
    _ppmi_neighbors,
)

if TYPE_CHECKING:
    from pathlib import Path


def build_full_graph_signal(
    inputs: FullGraphSignalInputs, settings: FullGraphSignalSettings | None = None
) -> FullGraphSignalArtifact:
    """Build a bounded real sparse baseline from a receipt-bound SQLite graph."""
    resolved = settings or FullGraphSignalSettings()
    graph_receipt, certificate = _load_inputs(inputs)
    cache_key = _sha(
        {
            "code_revision": _REVISION,
            "graph_receipt": graph_receipt.output_sha256,
            "certificate": certificate.output_sha256,
            "settings": full_graph_signal_settings_sha256(resolved),
        }
    )
    pair_data, pair_binding, artist_ids_sha, artist_ids_size = _load_or_stream_pair_data(
        inputs.cache_directory,
        cache_key,
        graph_receipt,
        certificate,
        resolved,
        inputs.graph_database,
    )
    shape = len(pair_data.artist_ids), _SEED_COUNT
    binary_values = array("f", (1.0 for _ in pair_data.rows))
    binary = _csr(pair_data.rows, pair_data.columns, binary_values, shape)
    weighted = _csr(pair_data.rows, pair_data.columns, pair_data.full_weights, shape)
    direct = _csr(pair_data.rows, pair_data.columns, pair_data.direct_weights, shape)
    matrix_caches, matrices, metadata_path, metadata_sha = _load_or_write_matrices(
        inputs.cache_directory,
        cache_key,
        graph_receipt,
        certificate,
        resolved,
        pair_binding,
        artist_ids_sha,
        artist_ids_size,
        binary,
        weighted,
        direct,
    )
    binary, weighted, direct = matrices
    raw_binary_cooccurrence = _cooccurrence(binary, resolved)
    jaccard = _jaccard_neighbors(binary, raw_binary_cooccurrence, resolved)
    cosine = _cosine_neighbors(weighted, resolved)
    ppmi = _ppmi_neighbors(binary, raw_binary_cooccurrence, resolved)
    direct_jaccard = _jaccard_neighbors(direct, _cooccurrence(direct, resolved), resolved)
    heldout = _heldout_by_artist(pair_data)
    evaluations = (
        _evaluate_membership(_MODEL_NAMES[0], binary, jaccard, heldout, resolved),
        _evaluate_membership(_MODEL_NAMES[1], weighted, cosine, heldout, resolved),
        _evaluate_membership(_MODEL_NAMES[2], binary, ppmi, heldout, resolved),
        _evaluate_membership(_MODEL_NAMES[3], direct, direct_jaccard, heldout, resolved),
    )
    containment_candidates, containment_coverage = _containment_candidates(
        binary, raw_binary_cooccurrence, pair_data, resolved
    )
    preliminary = FullGraphSignalArtifact(
        graph_receipt_output_sha256=graph_receipt.output_sha256,
        graph_database_sha256=graph_receipt.database_sha256,
        construction_certificate_output_sha256=certificate.output_sha256,
        settings=resolved,
        settings_sha256=full_graph_signal_settings_sha256(resolved),
        input_sha256=cache_key,
        matrix_cache_metadata_path=metadata_path.name,
        matrix_cache_metadata_sha256=metadata_sha,
        matrix_caches=matrix_caches,
        pair_split=PairSplitCoverage(
            unique_pair_count=len(pair_data.rows) + len(pair_data.heldout_rows),
            train_pair_count=len(pair_data.rows),
            heldout_pair_count=len(pair_data.heldout_rows),
            artist_count=len(pair_data.artist_ids),
            observed_seed_count=int(binary.getnnz(axis=0).astype(bool).sum()),
            source_channel_pairs=pair_data.channel_pairs,
            claims_streamed=pair_data.claims_streamed,
        ),
        membership_evaluations=evaluations,
        peer_recovery=_peer_recovery(jaccard, heldout, resolved),
        containment_candidates=containment_candidates,
        containment_coverage=containment_coverage,
        svd=SvdDecision(),
        source_scope=SourceScope(
            factual_wikidata_hierarchy_edge_count_available=certificate.hierarchy.accepted_factual_edge_count,
            sealed_peer_score_row_count_available=graph_receipt.candidate_relation_score_count,
        ),
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(
        update={"output_sha256": full_graph_signal_artifact_sha256(preliminary)}
    )


def verify_full_graph_signal(artifact: FullGraphSignalArtifact) -> None:
    """Fail closed when a persisted logical artifact or settings hash has changed."""
    if artifact.settings_sha256 != full_graph_signal_settings_sha256(artifact.settings):
        raise FullGraphSignalError("full graph signal settings hash does not replay")
    if artifact.output_sha256 != full_graph_signal_artifact_sha256(artifact):
        raise FullGraphSignalError("full graph signal artifact hash does not replay")


def write_full_graph_signal(
    output: Path, receipt_path: Path, artifact: FullGraphSignalArtifact
) -> FullGraphSignalReceipt:
    """Write a checked artifact and small custody receipt atomically."""
    verify_full_graph_signal(artifact)
    payload = artifact.model_dump_json(indent=2).encode() + b"\n"
    write_atomic_bytes(output, payload)
    artifact_sha, artifact_size = sha256_file(output)
    receipt = FullGraphSignalReceipt(
        artifact_sha256=artifact_sha,
        artifact_byte_count=artifact_size,
        logical_output_sha256=artifact.output_sha256,
        graph_receipt_output_sha256=artifact.graph_receipt_output_sha256,
        construction_certificate_output_sha256=artifact.construction_certificate_output_sha256,
    )
    write_atomic_bytes(receipt_path, receipt.model_dump_json(indent=2).encode() + b"\n")
    return receipt
