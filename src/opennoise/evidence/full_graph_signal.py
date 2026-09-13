"""Bounded sparse membership signal over the sealed evidence graph.

This is intentionally a construction-only checkpoint.  It reads positive,
open MusicBrainz/release-support claims from the sealed SQLite graph, holds out
complete artist--seed pairs, and produces review-only metrics and containment
candidates.  It does not read historical data, coordinates, or a UI artifact.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from array import array
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, cast

import numpy as np
from pydantic import Field, model_validator
from scipy import sparse

from opennoise.checkpoints.source_neutral_certification import (
    SourceNeutralCheckpointCertification,
    verify_source_neutral_checkpoint_certification,
)
from opennoise.common import canonical_json, sha256_file, sha256_hex, write_atomic_bytes
from opennoise.evidence.graph_projection import (
    EvidenceGraphProjectionArtifact,
    verify_evidence_graph_projection,
)
from opennoise.models import FrozenModel

_REVISION: Final = "full-graph-signal-v2"
_SETTINGS_REVISION: Final = "full-graph-signal-settings-v1"
_SEED_COUNT: Final = 6_291
_SHA: Final = r"^[0-9a-f]{64}$"
_CHANNELS: Final = ("artist_direct", "release_group_support", "reviewed_alias_context")
type ModelName = Literal[
    "binary_jaccard_all_open",
    "weighted_cosine_all_open",
    "ppmi_all_open",
    "binary_jaccard_direct_only",
]
type NumericArray = array[int] | array[float]

_MODEL_NAMES: Final[tuple[ModelName, ...]] = (
    "binary_jaccard_all_open",
    "weighted_cosine_all_open",
    "ppmi_all_open",
    "binary_jaccard_direct_only",
)


class FullGraphSignalError(ValueError):
    """A sealed graph is invalid, over-bounded, or cannot replay its result."""


class FullGraphSignalSettings(FrozenModel):
    """Laptop-safe controls for the first real sparse baseline."""

    revision: Literal["full-graph-signal-settings-v1"] = _SETTINGS_REVISION
    split_seed: int = Field(default=20260913, ge=0)
    heldout_fraction: float = Field(default=0.2, gt=0.0, lt=0.5)
    maximum_pairs: int = Field(default=4_000_000, ge=1, le=10_000_000)
    maximum_cooccurrence_nnz: int = Field(default=20_000_000, ge=100_000, le=39_000_000)
    maximum_genres_per_artist_for_cooccurrence: int = Field(default=32, ge=2, le=256)
    maximum_genre_neighbors: int = Field(default=200, ge=10, le=1_000)
    maximum_evaluation_artists: int = Field(default=100_000, ge=100, le=1_000_000)
    minimum_containment_child_support: int = Field(default=3, ge=1, le=10_000)
    minimum_containment_score: float = Field(default=0.8, gt=0.0, le=1.0)
    maximum_containment_candidates: int = Field(default=10_000, ge=1, le=50_000)


class MatrixBinding(FrozenModel):
    """One train-only sparse cache keyed by sealed input and settings hashes."""

    name: str = Field(min_length=1)
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA)
    byte_count: int = Field(gt=0)
    row_count: int = Field(ge=0)
    column_count: Literal[6291] = _SEED_COUNT
    nonzero_count: int = Field(ge=0)


class MatrixCacheMetadata(FrozenModel):
    """Immutable cache manifest required before an existing matrix is reused."""

    revision: Literal["full-graph-signal-cache-v1"] = "full-graph-signal-cache-v1"
    code_revision: Literal["full-graph-signal-v2"] = _REVISION
    graph_receipt_output_sha256: str = Field(pattern=_SHA)
    construction_certificate_output_sha256: str = Field(pattern=_SHA)
    settings_sha256: str = Field(pattern=_SHA)
    pair_data_npz: MatrixBinding
    artist_ids_sha256: str = Field(pattern=_SHA)
    artist_ids_byte_count: int = Field(gt=0)
    matrices: tuple[MatrixBinding, ...] = Field(min_length=3, max_length=3)
    output_sha256: str = Field(pattern=_SHA)


class ChannelPairCounts(FrozenModel):
    """Unique pairs observed by source channel after complete claim deduplication."""

    artist_direct: int = Field(ge=0)
    release_group_support: int = Field(ge=0)
    reviewed_alias_context: int = Field(ge=0)


class PairSplitCoverage(FrozenModel):
    """Exact pair-level split accounting; claims cannot cross this boundary."""

    unique_pair_count: int = Field(ge=0)
    train_pair_count: int = Field(ge=0)
    heldout_pair_count: int = Field(ge=0)
    artist_count: int = Field(ge=0)
    observed_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    source_channel_pairs: ChannelPairCounts
    claims_streamed: int = Field(ge=0)
    heldout_complete_pairs: Literal[True] = True
    historical_inputs_read: Literal[False] = False

    @model_validator(mode="after")
    def _complete(self) -> PairSplitCoverage:
        if self.train_pair_count + self.heldout_pair_count != self.unique_pair_count:
            raise ValueError("pair split does not account for complete unique pairs")
        return self


class EvaluationPartition(FrozenModel):
    """Positive-only retrieval accounting for a label-support partition."""

    heldout_pair_count: int = Field(ge=0)
    scoreable_pair_count: int = Field(ge=0)
    abstained_pair_count: int = Field(ge=0)
    recall_at_1: float | None = Field(default=None, ge=0.0, le=1.0)
    recall_at_10: float | None = Field(default=None, ge=0.0, le=1.0)
    recall_at_25: float | None = Field(default=None, ge=0.0, le=1.0)
    score_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    cold_labels_scored: Literal[False] = False

    @model_validator(mode="after")
    def _accounted(self) -> EvaluationPartition:
        if self.scoreable_pair_count + self.abstained_pair_count != self.heldout_pair_count:
            raise ValueError("evaluation partition does not account for held-out pairs")
        return self


class MembershipModelEvaluation(FrozenModel):
    """One positive-only held-out membership result for a transparent baseline."""

    model: Literal[
        "binary_jaccard_all_open",
        "weighted_cosine_all_open",
        "ppmi_all_open",
        "binary_jaccard_direct_only",
    ]
    evaluated_artist_count: int = Field(ge=0)
    heldout_pair_count_total: int = Field(ge=0)
    evaluation_pair_count: int = Field(ge=0)
    anchored: EvaluationPartition
    split_cold: EvaluationPartition


class PeerRecovery(FrozenModel):
    """Peer retrieval induced solely from pairs held out of the open membership graph."""

    heldout_open_peer_pair_count: int = Field(ge=0)
    scoreable_peer_pair_count: int = Field(ge=0)
    abstained_peer_pair_count: int = Field(ge=0)
    recall_at_10: float | None = Field(default=None, ge=0.0, le=1.0)
    recall_at_25: float | None = Field(default=None, ge=0.0, le=1.0)


class ContainmentCandidate(FrozenModel):
    """One asymmetric, review-only parent candidate inferred from train artist sets."""

    parent_seed_id: str = Field(min_length=1)
    child_seed_id: str = Field(min_length=1)
    containment_score: float = Field(gt=0.0, le=1.0)
    shared_artist_count: int = Field(ge=1)
    child_artist_count: int = Field(ge=1)
    parent_artist_count: int = Field(ge=1)
    disposition: Literal["review_candidate"] = "review_candidate"


class ContainmentCoverage(FrozenModel):
    """Candidate summary that preserves multi-parent rather than tree semantics."""

    candidate_count: int = Field(ge=0)
    child_count: int = Field(ge=0)
    overlapping_parent_child_count: int = Field(ge=0)
    inferred_as_factual: Literal[False] = False


class SvdDecision(FrozenModel):
    """Explicit non-result for optional truncated SVD in this first bounded run."""

    attempted: Literal[False] = False
    reason: Literal["not_run_simple_sparse_baselines_are_the_checkpoint"] = (
        "not_run_simple_sparse_baselines_are_the_checkpoint"
    )
    beats_simple_baseline: None = None


class SourceScope(FrozenModel):
    """Explicitly distinguish this adapter's evidence from future overlays."""

    membership_channels: tuple[
        Literal["artist_direct", "release_group_support", "reviewed_alias_context"], ...
    ] = _CHANNELS
    factual_wikidata_hierarchy_edge_count_available: int = Field(ge=0)
    sealed_peer_score_row_count_available: int = Field(ge=0)
    listenbrainz_artist_similarity_present: Literal[False] = False
    next_adapter_inputs: tuple[str, ...] = (
        "listenbrainz_receipt_bound_artist_candidates",
        "receipt_bound_hierarchy_candidates",
        "receipt_bound_compositional_open_construction_edges",
        "receipt_bound_exact_artist_name_metadata",
    )


class FullGraphSignalArtifact(FrozenModel):
    """Replayable source-neutral model signal, never a map or promoted graph."""

    revision: Literal["full-graph-signal-v2"] = _REVISION
    graph_receipt_output_sha256: str = Field(pattern=_SHA)
    graph_database_sha256: str = Field(pattern=_SHA)
    construction_certificate_output_sha256: str = Field(pattern=_SHA)
    settings: FullGraphSignalSettings
    settings_sha256: str = Field(pattern=_SHA)
    input_sha256: str = Field(pattern=_SHA)
    matrix_cache_metadata_path: str = Field(min_length=1)
    matrix_cache_metadata_sha256: str = Field(pattern=_SHA)
    matrix_caches: tuple[MatrixBinding, ...] = Field(min_length=3, max_length=3)
    pair_split: PairSplitCoverage
    membership_evaluations: tuple[MembershipModelEvaluation, ...] = Field(
        min_length=4, max_length=4
    )
    peer_recovery: PeerRecovery
    containment_candidates: tuple[ContainmentCandidate, ...]
    containment_coverage: ContainmentCoverage
    svd: SvdDecision
    source_scope: SourceScope
    historical_inputs_read: Literal[False] = False
    output_sha256: str = Field(pattern=_SHA)


class FullGraphSignalReceipt(FrozenModel):
    """A small custody receipt for the JSON artifact and its bound construction inputs."""

    revision: Literal["full-graph-signal-receipt-v1"] = "full-graph-signal-receipt-v1"
    artifact_sha256: str = Field(pattern=_SHA)
    artifact_byte_count: int = Field(gt=0)
    logical_output_sha256: str = Field(pattern=_SHA)
    graph_receipt_output_sha256: str = Field(pattern=_SHA)
    construction_certificate_output_sha256: str = Field(pattern=_SHA)


class FullGraphSignalRunReport(FrozenModel):
    """Operational facts intentionally kept outside the logical artifact hash."""

    revision: Literal["full-graph-signal-run-report-v1"] = "full-graph-signal-run-report-v1"
    logical_output_sha256: str = Field(pattern=_SHA)
    elapsed_seconds: float = Field(ge=0.0)
    peak_rss_kib: int = Field(ge=0)
    memory_measurement: Literal["process_ru_maxrss_kib"] = "process_ru_maxrss_kib"


@dataclass(frozen=True, slots=True)
class FullGraphSignalInputs:
    """Exactly the sealed graph/certificate pair plus new local destinations."""

    graph_database: Path
    graph_receipt: Path
    construction_certificate: Path
    cache_directory: Path


@dataclass(frozen=True, slots=True)
class _PairData:
    rows: NumericArray
    columns: NumericArray
    full_weights: NumericArray
    direct_weights: NumericArray
    support_weights: NumericArray
    heldout_rows: NumericArray
    heldout_columns: NumericArray
    artist_ids: tuple[str, ...]
    seed_ids: tuple[str, ...]
    claims_streamed: int
    channel_pairs: ChannelPairCounts


def _sha(value: object) -> str:
    return sha256_hex(canonical_json(value))


def full_graph_signal_settings_sha256(settings: FullGraphSignalSettings) -> str:
    """Return the deterministic cache key component for all numerical controls."""
    return _sha(settings.model_dump(mode="json"))


def full_graph_signal_artifact_sha256(artifact: FullGraphSignalArtifact) -> str:
    """Return the logical digest excluding the artifact's self hash."""
    return _sha(artifact.model_dump(mode="json", exclude={"output_sha256"}))


def _cache_metadata_sha256(metadata: MatrixCacheMetadata) -> str:
    return _sha(metadata.model_dump(mode="json", exclude={"output_sha256"}))


def _load_cache_metadata(
    path: Path,
    graph_receipt: EvidenceGraphProjectionArtifact,
    certificate: SourceNeutralCheckpointCertification,
    settings: FullGraphSignalSettings,
) -> MatrixCacheMetadata:
    """Validate every cache binding before either pair or matrix bytes are reused."""
    try:
        metadata = MatrixCacheMetadata.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise FullGraphSignalError("matrix cache metadata is invalid") from error
    if (
        metadata.output_sha256 != _cache_metadata_sha256(metadata)
        or metadata.graph_receipt_output_sha256 != graph_receipt.output_sha256
        or metadata.construction_certificate_output_sha256 != certificate.output_sha256
        or metadata.settings_sha256 != full_graph_signal_settings_sha256(settings)
    ):
        raise FullGraphSignalError("matrix cache metadata does not bind current inputs")
    return metadata


def _split_pair(artist_id: str, seed_id: str, settings: FullGraphSignalSettings) -> bool:
    value = int(
        hashlib.sha256(f"{settings.split_seed}:{artist_id}:{seed_id}".encode()).hexdigest()[:16], 16
    )
    return value / (2**64) < settings.heldout_fraction


def _load_inputs(
    inputs: FullGraphSignalInputs,
) -> tuple[EvidenceGraphProjectionArtifact, SourceNeutralCheckpointCertification]:
    try:
        receipt = EvidenceGraphProjectionArtifact.model_validate_json(
            inputs.graph_receipt.read_bytes()
        )
        verify_evidence_graph_projection(receipt)
        certificate = SourceNeutralCheckpointCertification.model_validate_json(
            inputs.construction_certificate.read_bytes()
        )
        verify_source_neutral_checkpoint_certification(certificate)
    except (OSError, ValueError) as error:
        raise FullGraphSignalError(
            "sealed receipt or construction certificate is invalid"
        ) from error
    database_sha, database_size = sha256_file(inputs.graph_database)
    if (database_sha, database_size) != (receipt.database_sha256, receipt.database_bytes):
        raise FullGraphSignalError("evidence graph database does not bind its receipt")
    database_binding = next(
        (binding for binding in certificate.inputs if binding.role == "evidence_graph_database"),
        None,
    )
    receipt_binding = next(
        (binding for binding in certificate.inputs if binding.role == "evidence_graph_receipt"),
        None,
    )
    if (
        database_binding is None
        or receipt_binding is None
        or (
            database_binding.bytes_sha256 != database_sha
            or receipt_binding.logical_sha256 != receipt.output_sha256
        )
    ):
        raise FullGraphSignalError(
            "construction certificate does not bind graph receipt and database"
        )
    if (
        certificate.membership.certified_observed_seed_count
        + certificate.membership.certified_unknown_seed_count
        != _SEED_COUNT
    ):
        raise FullGraphSignalError("construction certificate seed accounting is incomplete")
    return receipt, certificate


def _readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)


def _load_pairs(database_path: Path, settings: FullGraphSignalSettings) -> _PairData:  # noqa: C901, PLR0915
    """Stream sorted claims and deduplicate full pairs before assigning a split."""
    with closing(_readonly(database_path)) as database:
        seeds = tuple(
            str(row[0])
            for row in database.execute(
                "SELECT identifier FROM identity WHERE namespace = 'stable_seed' "
                "ORDER BY identifier"
            )
        )
        if len(seeds) != _SEED_COUNT:
            raise FullGraphSignalError("graph lacks the complete stable seed universe")
        seed_index = {seed_id: index for index, seed_id in enumerate(seeds)}
        cursor = database.execute(
            "SELECT subject_identifier, object_identifier, evidence_kind, release_group_id "
            "FROM claim WHERE subject_namespace = 'musicbrainz_artist' "
            "AND predicate = 'artist_membership' AND object_namespace = 'stable_seed' "
            "ORDER BY subject_identifier, object_identifier, evidence_kind, release_group_id"
        )
        artist_index: dict[str, int] = {}
        artist_ids: list[str] = []
        rows, columns = array("I"), array("I")
        full_weights, direct_weights, support_weights = array("f"), array("f"), array("f")
        heldout_rows, heldout_columns = array("I"), array("I")
        channel_counts: dict[str, int] = dict.fromkeys(_CHANNELS, 0)
        current: tuple[str, str] | None = None
        has_direct = has_alias = False
        support_groups: set[str] = set()
        claims_streamed = unique_pairs = 0

        def finish() -> None:
            nonlocal unique_pairs, has_direct, has_alias
            if current is None:
                return
            artist_id, seed_id = current
            artist_row = artist_index.setdefault(artist_id, len(artist_ids))
            if artist_row == len(artist_ids):
                artist_ids.append(artist_id)
            if has_direct:
                channel_counts["artist_direct"] += 1
            if support_groups:
                channel_counts["release_group_support"] += 1
            if has_alias:
                channel_counts["reviewed_alias_context"] += 1
            unique_pairs += 1
            if unique_pairs > settings.maximum_pairs:
                raise FullGraphSignalError("unique membership pair bound exceeded")
            if _split_pair(artist_id, seed_id, settings):
                heldout_rows.append(artist_row)
                heldout_columns.append(seed_index[seed_id])
            else:
                rows.append(artist_row)
                columns.append(seed_index[seed_id])
                direct = 1.0 if has_direct else 0.0
                support = math.log1p(len(support_groups)) + (1.0 if has_alias else 0.0)
                direct_weights.append(direct)
                support_weights.append(support)
                full_weights.append(3.0 * direct + support if direct or support else 1.0)
            has_direct = has_alias = False
            support_groups.clear()

        for artist_id, seed_id, evidence_kind, release_group_id in cursor:
            claims_streamed += 1
            pair = str(artist_id), str(seed_id)
            if pair != current:
                finish()
                current = pair
            if evidence_kind == "artist_direct":
                has_direct = True
            elif evidence_kind == "release_group_support" and release_group_id:
                support_groups.add(str(release_group_id))
            elif evidence_kind == "reviewed_alias_context":
                has_alias = True
        finish()
    return _PairData(
        rows=rows,
        columns=columns,
        full_weights=full_weights,
        direct_weights=direct_weights,
        support_weights=support_weights,
        heldout_rows=heldout_rows,
        heldout_columns=heldout_columns,
        artist_ids=tuple(artist_ids),
        seed_ids=seeds,
        claims_streamed=claims_streamed,
        channel_pairs=ChannelPairCounts(**channel_counts),
    )


def _csr(
    rows: NumericArray, columns: NumericArray, values: NumericArray, shape: tuple[int, int]
) -> sparse.csr_matrix:
    matrix = sparse.csr_matrix(
        (
            np.frombuffer(values, dtype=np.float32),
            (np.frombuffer(rows, dtype=np.uint32), np.frombuffer(columns, dtype=np.uint32)),
        ),
        shape=shape,
        dtype=np.float32,
    )
    matrix.sum_duplicates()
    matrix.eliminate_zeros()
    return matrix


def _save_matrix(path: Path, matrix: sparse.csr_matrix, name: str) -> MatrixBinding:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".partial.npz")
    sparse.save_npz(temporary, matrix, compressed=True)
    temporary.replace(path)
    digest, size = sha256_file(path)
    return MatrixBinding(
        name=name,
        path=path.name,
        sha256=digest,
        byte_count=size,
        row_count=matrix.shape[0],
        nonzero_count=matrix.nnz,
    )


def _save_pair_data(path: Path, data: _PairData) -> MatrixBinding:
    """Atomically persist the complete deduplicated split as typed primitive arrays."""
    temporary = path.with_suffix(".partial.npz")
    np.savez_compressed(
        temporary,
        rows=np.frombuffer(data.rows, dtype=np.uint32),
        columns=np.frombuffer(data.columns, dtype=np.uint32),
        full_weights=np.frombuffer(data.full_weights, dtype=np.float32),
        direct_weights=np.frombuffer(data.direct_weights, dtype=np.float32),
        support_weights=np.frombuffer(data.support_weights, dtype=np.float32),
        heldout_rows=np.frombuffer(data.heldout_rows, dtype=np.uint32),
        heldout_columns=np.frombuffer(data.heldout_columns, dtype=np.uint32),
        claims_streamed=np.asarray([data.claims_streamed], dtype=np.uint64),
        channel_pairs=np.asarray(
            [
                data.channel_pairs.artist_direct,
                data.channel_pairs.release_group_support,
                data.channel_pairs.reviewed_alias_context,
            ],
            dtype=np.uint64,
        ),
    )
    temporary.replace(path)
    digest, size = sha256_file(path)
    return MatrixBinding(
        name="deduplicated_complete_pair_split",
        path=path.name,
        sha256=digest,
        byte_count=size,
        row_count=len(data.artist_ids),
        nonzero_count=len(data.rows) + len(data.heldout_rows),
    )


def _save_artist_ids(path: Path, data: _PairData) -> tuple[str, int]:
    """Persist row/column identity sidecar separately from numeric sparse arrays."""
    payload = canonical_json({"artist_ids": data.artist_ids, "seed_ids": data.seed_ids}) + b"\n"
    write_atomic_bytes(path, payload)
    return sha256_file(path)


def _load_pair_data(
    cache_directory: Path, binding: MatrixBinding, artist_ids_sha: str, artist_ids_size: int
) -> _PairData:
    """Reload a fully verified pair/index sidecar without touching the claim table."""
    if Path(binding.path).is_absolute():
        raise FullGraphSignalError("cache paths must be relative to the configured cache root")
    pair_path = cache_directory / binding.path
    identities_path = (
        cache_directory
        / f"artist-ids-{binding.path.removeprefix('pairs-').removesuffix('.npz')}.json"
    )
    if sha256_file(pair_path) != (binding.sha256, binding.byte_count) or sha256_file(
        identities_path
    ) != (artist_ids_sha, artist_ids_size):
        raise FullGraphSignalError("pair cache bytes do not replay")
    identities = json.loads(identities_path.read_text(encoding="utf-8"))
    with np.load(pair_path, allow_pickle=False) as arrays:

        def values(name: str, code: str, dtype: np.dtype[np.generic]) -> NumericArray:
            source = arrays[name]
            if source.dtype != dtype or source.ndim != 1:
                raise FullGraphSignalError("pair cache array has an unexpected primitive dtype")
            output = array(code)
            output.frombytes(np.ascontiguousarray(source).tobytes())
            return cast("NumericArray", output)

        channels = arrays["channel_pairs"]
        if channels.dtype != np.dtype(np.uint64) or channels.shape != (3,):
            raise FullGraphSignalError(
                "pair cache channel counts have an unexpected primitive dtype"
            )
        return _PairData(
            rows=values("rows", "I", np.dtype(np.uint32)),
            columns=values("columns", "I", np.dtype(np.uint32)),
            full_weights=values("full_weights", "f", np.dtype(np.float32)),
            direct_weights=values("direct_weights", "f", np.dtype(np.float32)),
            support_weights=values("support_weights", "f", np.dtype(np.float32)),
            heldout_rows=values("heldout_rows", "I", np.dtype(np.uint32)),
            heldout_columns=values("heldout_columns", "I", np.dtype(np.uint32)),
            artist_ids=tuple(str(value) for value in identities["artist_ids"]),
            seed_ids=tuple(str(value) for value in identities["seed_ids"]),
            claims_streamed=int(arrays["claims_streamed"][0]),
            channel_pairs=ChannelPairCounts(
                artist_direct=int(channels[0]),
                release_group_support=int(channels[1]),
                reviewed_alias_context=int(channels[2]),
            ),
        )


def _load_or_write_matrices(  # noqa: PLR0913, PLR0917
    cache_directory: Path,
    cache_key: str,
    graph_receipt: EvidenceGraphProjectionArtifact,
    certificate: SourceNeutralCheckpointCertification,
    settings: FullGraphSignalSettings,
    pair_binding: MatrixBinding,
    artist_ids_sha: str,
    artist_ids_size: int,
    binary: sparse.csr_matrix,
    weighted: sparse.csr_matrix,
    direct: sparse.csr_matrix,
) -> tuple[
    tuple[MatrixBinding, ...],
    tuple[sparse.csr_matrix, sparse.csr_matrix, sparse.csr_matrix],
    Path,
    str,
]:
    """Reuse only a hash-bound cache; otherwise atomically replace all matrices."""
    cache_directory.mkdir(parents=True, exist_ok=True)
    metadata_path = cache_directory / f"cache-{cache_key}.json"
    if metadata_path.exists():
        try:
            metadata = _load_cache_metadata(metadata_path, graph_receipt, certificate, settings)
            loaded: list[sparse.csr_matrix] = []
            for binding in metadata.matrices:
                if Path(binding.path).is_absolute():
                    raise FullGraphSignalError("matrix cache paths must be relative")
                path = cache_directory / binding.path
                digest, size = sha256_file(path)
                if (digest, size) != (binding.sha256, binding.byte_count):
                    raise FullGraphSignalError("matrix cache bytes do not match metadata")
                matrix = sparse.load_npz(path).tocsr().astype(np.float32)
                if matrix.shape != binary.shape or matrix.nnz != binding.nonzero_count:
                    raise FullGraphSignalError("matrix cache shape does not match current graph")
                loaded.append(matrix)
            if tuple(binding.name for binding in metadata.matrices) != (
                "binary_all_open",
                "weighted_all_open",
                "binary_direct_only",
            ):
                raise FullGraphSignalError("matrix cache has an unknown matrix set")
            return (
                metadata.matrices,
                (loaded[0], loaded[1], loaded[2]),
                metadata_path,
                metadata.output_sha256,
            )
        except (OSError, ValueError) as error:
            raise FullGraphSignalError("matrix cache exists but cannot be safely reused") from error
    bindings = (
        _save_matrix(cache_directory / f"binary-{cache_key}.npz", binary, "binary_all_open"),
        _save_matrix(cache_directory / f"weighted-{cache_key}.npz", weighted, "weighted_all_open"),
        _save_matrix(cache_directory / f"direct-{cache_key}.npz", direct, "binary_direct_only"),
    )
    preliminary = MatrixCacheMetadata(
        graph_receipt_output_sha256=graph_receipt.output_sha256,
        construction_certificate_output_sha256=certificate.output_sha256,
        settings_sha256=full_graph_signal_settings_sha256(settings),
        pair_data_npz=pair_binding,
        artist_ids_sha256=artist_ids_sha,
        artist_ids_byte_count=artist_ids_size,
        matrices=bindings,
        output_sha256="0" * 64,
    )
    metadata = preliminary.model_copy(update={"output_sha256": _cache_metadata_sha256(preliminary)})
    write_atomic_bytes(metadata_path, metadata.model_dump_json(indent=2).encode() + b"\n")
    return bindings, (binary, weighted, direct), metadata_path, metadata.output_sha256


def _load_or_stream_pair_data(  # noqa: PLR0913, PLR0917
    cache_directory: Path,
    cache_key: str,
    graph_receipt: EvidenceGraphProjectionArtifact,
    certificate: SourceNeutralCheckpointCertification,
    settings: FullGraphSignalSettings,
    database_path: Path,
) -> tuple[_PairData, MatrixBinding, str, int]:
    """Bypass the claim scan entirely when a verified pair/index sidecar exists."""
    cache_directory.mkdir(parents=True, exist_ok=True)
    metadata_path = cache_directory / f"cache-{cache_key}.json"
    if metadata_path.exists():
        metadata = _load_cache_metadata(metadata_path, graph_receipt, certificate, settings)
        data = _load_pair_data(
            cache_directory,
            metadata.pair_data_npz,
            metadata.artist_ids_sha256,
            metadata.artist_ids_byte_count,
        )
        return (
            data,
            metadata.pair_data_npz,
            metadata.artist_ids_sha256,
            metadata.artist_ids_byte_count,
        )
    data = _load_pairs(database_path, settings)
    pair_binding = _save_pair_data(cache_directory / f"pairs-{cache_key}.npz", data)
    artist_ids_sha, artist_ids_size = _save_artist_ids(
        cache_directory / f"artist-ids-{cache_key}.json", data
    )
    return data, pair_binding, artist_ids_sha, artist_ids_size


def _trim_rows(matrix: sparse.csr_matrix, limit: int) -> sparse.csr_matrix:
    """Keep deterministic top overlap neighbors per seed to bound ranking work."""
    output_rows: list[np.ndarray] = []
    output_columns: list[np.ndarray] = []
    output_values: list[np.ndarray] = []
    for row in range(matrix.shape[0]):
        start, end = matrix.indptr[row], matrix.indptr[row + 1]
        values, columns = matrix.data[start:end], matrix.indices[start:end]
        if len(values) > limit:
            selected = np.argpartition(values, -limit)[-limit:]
            selected = selected[np.lexsort((columns[selected], -values[selected]))]
            values, columns = values[selected], columns[selected]
        if len(values):
            output_rows.append(np.full(len(values), row, dtype=np.uint32))
            output_columns.append(columns.astype(np.uint32, copy=False))
            output_values.append(values.astype(np.float32, copy=False))
    if not output_rows:
        return sparse.csr_matrix(matrix.shape, dtype=np.float32)
    return sparse.csr_matrix(
        (
            np.concatenate(output_values),
            (np.concatenate(output_rows), np.concatenate(output_columns)),
        ),
        shape=matrix.shape,
        dtype=np.float32,
    )


def _cap_artist_rows(
    matrix: sparse.csr_matrix, settings: FullGraphSignalSettings
) -> sparse.csr_matrix:
    """Bound feature expansion while retaining the complete deduplicated pair matrix on disk."""
    return _trim_rows(matrix, settings.maximum_genres_per_artist_for_cooccurrence)


def _cooccurrence(
    matrix: sparse.csr_matrix, settings: FullGraphSignalSettings
) -> sparse.csr_matrix:
    bounded = _cap_artist_rows(matrix, settings)
    cooccurrence = cast("sparse.csr_matrix", (bounded.T @ bounded).tocsr().astype(np.float32))
    cooccurrence.setdiag(0.0)
    cooccurrence.eliminate_zeros()
    if cooccurrence.nnz > settings.maximum_cooccurrence_nnz:
        raise FullGraphSignalError("raw sparse cooccurrence bound exceeded")
    return cooccurrence


def _jaccard_neighbors(
    binary: sparse.csr_matrix,
    cooccurrence: sparse.csr_matrix,
    settings: FullGraphSignalSettings,
) -> sparse.csr_matrix:
    cooccurrence = cast("sparse.csr_matrix", cooccurrence.copy())
    counts = np.asarray(binary.sum(axis=0)).ravel()
    rows = np.repeat(np.arange(cooccurrence.shape[0]), np.diff(cooccurrence.indptr))
    cooccurrence.data /= counts[rows] + counts[cooccurrence.indices] - cooccurrence.data
    return _trim_rows(cooccurrence, settings.maximum_genre_neighbors)


def _cosine_neighbors(
    weighted: sparse.csr_matrix, settings: FullGraphSignalSettings
) -> sparse.csr_matrix:
    cooccurrence = _cooccurrence(weighted, settings)
    norms = np.sqrt(np.asarray(weighted.multiply(weighted).sum(axis=0)).ravel())
    rows = np.repeat(np.arange(cooccurrence.shape[0]), np.diff(cooccurrence.indptr))
    denominator = norms[rows] * norms[cooccurrence.indices]
    cooccurrence.data = np.divide(
        cooccurrence.data, denominator, out=np.zeros_like(cooccurrence.data), where=denominator > 0
    )
    cooccurrence.eliminate_zeros()
    return _trim_rows(cooccurrence, settings.maximum_genre_neighbors)


def _ppmi_neighbors(
    binary: sparse.csr_matrix,
    cooccurrence: sparse.csr_matrix,
    settings: FullGraphSignalSettings,
) -> sparse.csr_matrix:
    cooccurrence = cast("sparse.csr_matrix", cooccurrence.copy())
    counts = np.asarray(binary.sum(axis=0)).ravel()
    rows = np.repeat(np.arange(cooccurrence.shape[0]), np.diff(cooccurrence.indptr))
    numerator = cooccurrence.data * binary.shape[0]
    denominator = counts[rows] * counts[cooccurrence.indices]
    cooccurrence.data = np.maximum(0.0, np.log(np.divide(numerator, denominator)))
    cooccurrence.eliminate_zeros()
    return _trim_rows(cooccurrence, settings.maximum_genre_neighbors)


def _heldout_by_artist(data: _PairData) -> dict[int, set[int]]:
    heldout: dict[int, set[int]] = defaultdict(set)
    for row, column in zip(data.heldout_rows, data.heldout_columns, strict=True):
        heldout[int(row)].add(int(column))
    return heldout


def _sampled_artists(heldout: dict[int, set[int]], settings: FullGraphSignalSettings) -> list[int]:
    """Use one deterministic bounded artist sample across membership and peer metrics."""
    return sorted(
        heldout,
        key=lambda artist: hashlib.sha256(f"{settings.split_seed}:{artist}".encode()).hexdigest(),
    )[: settings.maximum_evaluation_artists]


def _partition(
    values: dict[str, int], scoreable: dict[str, int], hits: dict[str, int]
) -> EvaluationPartition:
    total = values["count"]
    return EvaluationPartition(
        heldout_pair_count=total,
        scoreable_pair_count=scoreable["count"],
        abstained_pair_count=total - scoreable["count"],
        recall_at_1=hits["one"] / total if total else None,
        recall_at_10=hits["ten"] / total if total else None,
        recall_at_25=hits["twenty_five"] / total if total else None,
        score_coverage=scoreable["count"] / total if total else None,
    )


def _evaluate_membership(
    name: ModelName,
    train: sparse.csr_matrix,
    neighbors: sparse.csr_matrix,
    heldout: dict[int, set[int]],
    settings: FullGraphSignalSettings,
) -> MembershipModelEvaluation:
    ordered_artists = _sampled_artists(heldout, settings)
    anchored_values = {"count": 0}
    cold_values = {"count": 0}
    anchored_scoreable = {"count": 0}
    cold_scoreable = {"count": 0}
    anchored_hits = {"one": 0, "ten": 0, "twenty_five": 0}
    cold_hits = {"one": 0, "ten": 0, "twenty_five": 0}
    seed_train_counts = np.asarray(train.getnnz(axis=0)).ravel()
    for artist in ordered_artists:
        targets = heldout[artist]
        train_genres = train.indices[train.indptr[artist] : train.indptr[artist + 1]]
        scores: dict[int, float] = defaultdict(float)
        for genre in train_genres:
            start, end = neighbors.indptr[genre], neighbors.indptr[genre + 1]
            for candidate, value in zip(
                neighbors.indices[start:end], neighbors.data[start:end], strict=True
            ):
                if candidate not in train_genres:
                    scores[int(candidate)] += float(value)
        ranked = [
            candidate
            for candidate, _ in sorted(scores.items(), key=lambda row: (-row[1], row[0]))[:25]
        ]
        for target in targets:
            values, scoreable, hits = (
                (anchored_values, anchored_scoreable, anchored_hits)
                if seed_train_counts[target] > 0
                else (cold_values, cold_scoreable, cold_hits)
            )
            values["count"] += 1
            if seed_train_counts[target] > 0 and ranked:
                scoreable["count"] += 1
                if target in ranked[:1]:
                    hits["one"] += 1
                if target in ranked[:10]:
                    hits["ten"] += 1
                if target in ranked[:25]:
                    hits["twenty_five"] += 1
    return MembershipModelEvaluation(
        model=name,
        evaluated_artist_count=len(ordered_artists),
        heldout_pair_count_total=sum(len(targets) for targets in heldout.values()),
        evaluation_pair_count=anchored_values["count"] + cold_values["count"],
        anchored=_partition(anchored_values, anchored_scoreable, anchored_hits),
        split_cold=_partition(cold_values, cold_scoreable, cold_hits),
    )


def _peer_recovery(
    neighbors: sparse.csr_matrix, heldout: dict[int, set[int]], settings: FullGraphSignalSettings
) -> PeerRecovery:
    pairs: set[tuple[int, int]] = set()
    for artist in _sampled_artists(heldout, settings):
        labels = sorted(heldout[artist])[:20]
        for index, left in enumerate(labels):
            pairs.update((left, right) for right in labels[index + 1 :])
    scoreable = hits_ten = hits_twenty_five = 0
    for left, right in pairs:
        start, end = neighbors.indptr[left], neighbors.indptr[left + 1]
        ranked = [
            candidate
            for candidate, _ in sorted(
                zip(neighbors.indices[start:end], neighbors.data[start:end], strict=True),
                key=lambda row: (-row[1], row[0]),
            )
        ]
        if ranked:
            scoreable += 1
            hits_ten += right in ranked[:10]
            hits_twenty_five += right in ranked[:25]
    return PeerRecovery(
        heldout_open_peer_pair_count=len(pairs),
        scoreable_peer_pair_count=scoreable,
        abstained_peer_pair_count=len(pairs) - scoreable,
        recall_at_10=hits_ten / len(pairs) if pairs else None,
        recall_at_25=hits_twenty_five / len(pairs) if pairs else None,
    )


def _containment_candidates(
    binary: sparse.csr_matrix,
    raw_cooccurrence: sparse.csr_matrix,
    data: _PairData,
    settings: FullGraphSignalSettings,
) -> tuple[tuple[ContainmentCandidate, ...], ContainmentCoverage]:
    counts = np.asarray(binary.getnnz(axis=0)).ravel()
    candidates: list[ContainmentCandidate] = []
    columns = raw_cooccurrence.tocsc()
    for child, child_count in enumerate(counts):
        if child_count < settings.minimum_containment_child_support:
            continue
        start, end = columns.indptr[child], columns.indptr[child + 1]
        child_rows, shared = columns.indices[start:end], columns.data[start:end]
        eligible = sorted(
            (
                (float(value) / child_count, int(parent), int(value))
                for parent, value in zip(child_rows, shared, strict=True)
                if counts[parent] > child_count
                and value / child_count >= settings.minimum_containment_score
            ),
            key=lambda row: (-row[0], row[1]),
        )[:3]
        candidates.extend(
            ContainmentCandidate(
                parent_seed_id=data.seed_ids[parent],
                child_seed_id=data.seed_ids[child],
                containment_score=score,
                shared_artist_count=shared_count,
                child_artist_count=int(child_count),
                parent_artist_count=int(counts[parent]),
            )
            for score, parent, shared_count in eligible
        )
    candidates = sorted(
        candidates,
        key=lambda item: (-item.containment_score, item.child_seed_id, item.parent_seed_id),
    )[: settings.maximum_containment_candidates]
    parents: dict[str, set[str]] = defaultdict(set)
    for candidate in candidates:
        parents[candidate.child_seed_id].add(candidate.parent_seed_id)
    return tuple(candidates), ContainmentCoverage(
        candidate_count=len(candidates),
        child_count=len(parents),
        overlapping_parent_child_count=sum(len(values) > 1 for values in parents.values()),
    )


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
