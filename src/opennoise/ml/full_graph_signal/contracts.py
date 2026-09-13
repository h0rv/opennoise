"""Typed contracts and stable hashing for the sparse graph signal."""

from __future__ import annotations

from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, model_validator

from opennoise.common import canonical_json, sha256_hex
from opennoise.models import FrozenModel

if TYPE_CHECKING:
    from pathlib import Path

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
