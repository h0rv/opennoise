"""Receipt-bound low-rank genre retrieval benchmark over the open artist-membership graph."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

import numpy as np
from pydantic import Field, model_validator
from scipy import sparse
from scipy.sparse.linalg import svds

from opennoise.common import canonical_json, sha256_file, sha256_hex, write_atomic_bytes
from opennoise.ml.full_graph_signal import (
    FullGraphSignalArtifact,
    FullGraphSignalReceipt,
    FullGraphSignalSettings,
    verify_full_graph_signal,
)
from opennoise.ml.full_graph_signal.contracts import MatrixCacheMetadata, _cache_metadata_sha256
from opennoise.ml.full_graph_signal.sparse_baselines import _cooccurrence, _jaccard_neighbors
from opennoise.models import FrozenModel

if TYPE_CHECKING:
    from pathlib import Path

_SEED_COUNT: Final = 6_291
_SHA: Final = r"^[0-9a-f]{64}$"
type InputRole = Literal[
    "full_graph_artifact",
    "full_graph_receipt",
    "matrix_cache_metadata",
    "binary_train_matrix",
    "pair_split",
]
_INPUT_ROLES: Final[frozenset[InputRole]] = frozenset(
    (
        "full_graph_artifact",
        "full_graph_receipt",
        "matrix_cache_metadata",
        "binary_train_matrix",
        "pair_split",
    )
)


class LatentGenreSimilarityError(ValueError):
    """A bound full-graph cache or deterministic latent benchmark is invalid."""


class LatentGenreSimilaritySettings(FrozenModel):
    """CPU-safe fixed controls; no held-out values select rank or thresholds."""

    revision: Literal["latent-genre-similarity-settings-v1"] = "latent-genre-similarity-settings-v1"
    rank: int = Field(default=16, ge=2, le=64)
    random_seed: int = Field(default=20260920, ge=0)
    maximum_evaluation_artists: int = Field(default=5_000, ge=100, le=20_000)
    evaluation_batch_size: int = Field(default=128, ge=1, le=1_000)
    maximum_genre_neighbors: int = Field(default=200, ge=10, le=1_000)
    maximum_cooccurrence_nnz: int = Field(default=20_000_000, ge=100_000, le=39_000_000)


class InputBinding(FrozenModel):
    """One immutable byte source and its logical source identity."""

    role: InputRole
    byte_sha256: str = Field(pattern=_SHA)
    byte_count: int = Field(gt=0)
    logical_sha256: str = Field(pattern=_SHA)


class RetrievalMetric(FrozenModel):
    """Positive-only, same-split retrieval result; missing pairs are never negatives."""

    model: Literal["latent_svd", "binary_jaccard", "train_only_popularity", "direct_only"]
    eligible_artist_count: int = Field(ge=0)
    heldout_positive_count: int = Field(ge=0)
    scoreable_positive_count: int = Field(ge=0)
    abstained_positive_count: int = Field(ge=0)
    recovered_at_10_count: int = Field(ge=0)
    recovered_at_25_count: int = Field(ge=0)
    recall_at_10: float | None = Field(default=None, ge=0, le=1)
    recall_at_25: float | None = Field(default=None, ge=0, le=1)
    absence_is_negative: Literal[False] = False
    precision_claimed: Literal[False] = False

    @model_validator(mode="after")
    def replay_counts(self) -> RetrievalMetric:
        """Require complete held-out positive accounting and exact ratios."""
        if (
            self.scoreable_positive_count + self.abstained_positive_count
            != self.heldout_positive_count
        ):
            raise ValueError("retrieval accounting is incomplete")
        if self.recovered_at_10_count > self.recovered_at_25_count:
            raise ValueError("recall at 10 exceeds recall at 25")
        if self.recovered_at_25_count > self.scoreable_positive_count:
            raise ValueError("recovered count exceeds scoreable positives")
        if self.heldout_positive_count:
            if self.recall_at_10 != self.recovered_at_10_count / self.heldout_positive_count:
                raise ValueError("recall at 10 does not replay")
            if self.recall_at_25 != self.recovered_at_25_count / self.heldout_positive_count:
                raise ValueError("recall at 25 does not replay")
        elif self.recall_at_10 is not None or self.recall_at_25 is not None:
            raise ValueError("an empty cohort has no recall fraction")
        return self


class LatentGenreSimilarityArtifact(FrozenModel):
    """Review-only model benchmark, never an artist-membership or serving artifact."""

    revision: Literal["latent-genre-similarity-v1"] = "latent-genre-similarity-v1"
    inputs: tuple[InputBinding, ...] = Field(min_length=5, max_length=5)
    settings: LatentGenreSimilaritySettings
    settings_sha256: str = Field(pattern=_SHA)
    stable_seed_count: Literal[6291] = _SEED_COUNT
    train_pair_count: int = Field(ge=0)
    heldout_pair_count: int = Field(ge=0)
    evaluated_artist_count: int = Field(ge=0)
    latent: RetrievalMetric
    binary_jaccard: RetrievalMetric
    train_only_popularity: RetrievalMetric
    direct_only: RetrievalMetric
    historical_inputs_read_for_construction: Literal[False] = False
    audio_read_for_construction: Literal[False] = False
    listener_identifiers_read_for_construction: Literal[False] = False
    review_only_not_promoted: Literal[True] = True
    output_sha256: str = Field(pattern=_SHA)

    @model_validator(mode="after")
    def same_cohort(self) -> LatentGenreSimilarityArtifact:
        """Require every comparison to use exactly one bounded held-out cohort."""
        metrics = (self.latent, self.binary_jaccard, self.train_only_popularity, self.direct_only)
        if {item.heldout_positive_count for item in metrics} != {
            self.latent.heldout_positive_count
        }:
            raise ValueError("baselines do not share the latent held-out cohort")
        if {item.eligible_artist_count for item in metrics} != {self.evaluated_artist_count}:
            raise ValueError("baselines do not share the latent eligible artist cohort")
        if {item.role for item in self.inputs} != _INPUT_ROLES:
            raise ValueError("latent inputs must have one binding for every required role")
        return self


class LatentGenreSimilarityReceipt(FrozenModel):
    """Byte custody for the compact benchmark report."""

    artifact_sha256: str = Field(pattern=_SHA)
    artifact_byte_count: int = Field(gt=0)
    logical_output_sha256: str = Field(pattern=_SHA)


@dataclass(frozen=True, slots=True)
class LatentGenreSimilarityInputs:
    """One sealed sparse baseline and its immutable cache directory."""

    full_graph_artifact: Path
    full_graph_receipt: Path
    cache_directory: Path


def _settings_sha256(settings: LatentGenreSimilaritySettings) -> str:
    return sha256_hex(canonical_json(settings.model_dump(mode="json")))


def _artifact_sha256(artifact: LatentGenreSimilarityArtifact) -> str:
    return sha256_hex(canonical_json(artifact.model_dump(mode="json", exclude={"output_sha256"})))


def verify_latent_genre_similarity(artifact: LatentGenreSimilarityArtifact) -> None:
    """Fail closed unless settings and artifact logical hashes replay."""
    if artifact.settings_sha256 != _settings_sha256(artifact.settings):
        raise LatentGenreSimilarityError("latent settings hash does not replay")
    if artifact.output_sha256 != _artifact_sha256(artifact):
        raise LatentGenreSimilarityError("latent artifact hash does not replay")


def _binding(role: InputRole, path: Path, logical: str) -> InputBinding:
    digest, count = sha256_file(path)
    return InputBinding(role=role, byte_sha256=digest, byte_count=count, logical_sha256=logical)


def _load(
    inputs: LatentGenreSimilarityInputs,
) -> tuple[
    FullGraphSignalArtifact, sparse.csr_matrix, dict[str, np.ndarray], tuple[InputBinding, ...]
]:
    """Load verified train/heldout cache data without rereading source claims."""
    try:
        artifact = FullGraphSignalArtifact.model_validate_json(
            inputs.full_graph_artifact.read_bytes()
        )
        receipt = FullGraphSignalReceipt.model_validate_json(inputs.full_graph_receipt.read_bytes())
        verify_full_graph_signal(artifact)
        artifact_digest, artifact_count = sha256_file(inputs.full_graph_artifact)
        if (
            receipt.logical_output_sha256 != artifact.output_sha256
            or receipt.artifact_sha256 != artifact_digest
            or receipt.artifact_byte_count != artifact_count
            or receipt.graph_receipt_output_sha256 != artifact.graph_receipt_output_sha256
            or receipt.construction_certificate_output_sha256
            != artifact.construction_certificate_output_sha256
        ):
            raise LatentGenreSimilarityError("full graph receipt does not bind artifact")
        metadata_path = inputs.cache_directory / artifact.matrix_cache_metadata_path
        metadata = MatrixCacheMetadata.model_validate_json(metadata_path.read_bytes())
    except (OSError, ValueError) as error:
        raise LatentGenreSimilarityError(
            "full graph artifact or matrix cache is invalid"
        ) from error
    if (
        metadata.output_sha256 != _cache_metadata_sha256(metadata)
        or metadata.output_sha256 != artifact.matrix_cache_metadata_sha256
    ):
        raise LatentGenreSimilarityError("matrix cache metadata hash does not replay")
    if (
        metadata.graph_receipt_output_sha256 != artifact.graph_receipt_output_sha256
        or metadata.construction_certificate_output_sha256
        != artifact.construction_certificate_output_sha256
        or metadata.settings_sha256 != artifact.settings_sha256
    ):
        raise LatentGenreSimilarityError("matrix cache metadata does not bind full graph inputs")
    binary_binding = next((row for row in metadata.matrices if row.name == "binary_all_open"), None)
    if binary_binding is None:
        raise LatentGenreSimilarityError("full graph cache lacks binary matrix")
    binary_path = inputs.cache_directory / binary_binding.path
    if sha256_file(binary_path) != (binary_binding.sha256, binary_binding.byte_count):
        raise LatentGenreSimilarityError("binary matrix does not bind cache metadata")
    pair_path = inputs.cache_directory / metadata.pair_data_npz.path
    if sha256_file(pair_path) != (metadata.pair_data_npz.sha256, metadata.pair_data_npz.byte_count):
        raise LatentGenreSimilarityError("pair split does not bind cache metadata")
    with np.load(pair_path) as pairs:
        values = {
            name: np.asarray(pairs[name])
            for name in ("rows", "columns", "heldout_rows", "heldout_columns")
        }
    matrix = sparse.load_npz(binary_path).tocsr().astype(np.float32)
    if (
        matrix.shape != (binary_binding.row_count, _SEED_COUNT)
        or matrix.nnz != binary_binding.nonzero_count
    ):
        raise LatentGenreSimilarityError("binary matrix does not preserve the seed universe")
    _validate_pair_indices(
        values,
        matrix.shape[0],
        artifact.pair_split.train_pair_count,
        artifact.pair_split.heldout_pair_count,
    )
    bindings = (
        _binding("full_graph_artifact", inputs.full_graph_artifact, artifact.output_sha256),
        _binding("full_graph_receipt", inputs.full_graph_receipt, artifact.output_sha256),
        _binding("matrix_cache_metadata", metadata_path, metadata.output_sha256),
        _binding("binary_train_matrix", binary_path, binary_binding.sha256),
        _binding("pair_split", pair_path, metadata.pair_data_npz.sha256),
    )
    return artifact, matrix, values, bindings


def _validate_pair_indices(
    values: dict[str, np.ndarray],
    row_count: int,
    train_pair_count: int,
    heldout_pair_count: int,
) -> None:
    """Require complete one-dimensional train and held-out coordinates within matrix bounds."""
    rows = values["rows"]
    columns = values["columns"]
    heldout_rows = values["heldout_rows"]
    heldout_columns = values["heldout_columns"]
    if (
        any(value.ndim != 1 for value in values.values())
        or len(rows) != train_pair_count
        or len(heldout_rows) != heldout_pair_count
        or len(columns) != len(rows)
        or len(heldout_columns) != len(heldout_rows)
        or np.any(rows < 0)
        or np.any(rows >= row_count)
        or np.any(heldout_rows < 0)
        or np.any(heldout_rows >= row_count)
        or np.any(columns < 0)
        or np.any(columns >= _SEED_COUNT)
        or np.any(heldout_columns < 0)
        or np.any(heldout_columns >= _SEED_COUNT)
    ):
        raise LatentGenreSimilarityError("pair split does not preserve exact matrix coordinates")


def _sampled(heldout_rows: np.ndarray, seed: int, maximum: int) -> list[int]:
    return sorted(
        {int(row) for row in heldout_rows},
        key=lambda row: hashlib.sha256(f"{seed}:{row}".encode()).hexdigest(),
    )[:maximum]


def _targets(rows: np.ndarray, columns: np.ndarray, artists: list[int]) -> dict[int, set[int]]:
    selected = set(artists)
    output: dict[int, set[int]] = defaultdict(set)
    for row, column in zip(rows, columns, strict=True):
        if int(row) in selected:
            output[int(row)].add(int(column))
    return dict(output)


def _metric(
    name: Literal["latent_svd", "binary_jaccard", "train_only_popularity", "direct_only"],
    targets: dict[int, set[int]],
    rankings: dict[int, np.ndarray],
    eligible_artist_count: int,
) -> RetrievalMetric:
    total = sum(len(values) for values in targets.values())
    scoreable = hits10 = hits25 = 0
    for artist, positives in targets.items():
        ranked = rankings.get(artist)
        if ranked is None or not len(ranked):
            continue
        scoreable += len(positives)
        hits10 += sum(int(seed) in ranked[:10] for seed in positives)
        hits25 += sum(int(seed) in ranked[:25] for seed in positives)
    return RetrievalMetric(
        model=name,
        eligible_artist_count=eligible_artist_count,
        heldout_positive_count=total,
        scoreable_positive_count=scoreable,
        abstained_positive_count=total - scoreable,
        recovered_at_10_count=hits10,
        recovered_at_25_count=hits25,
        recall_at_10=hits10 / total if total else None,
        recall_at_25=hits25 / total if total else None,
    )


def _rank_latent(
    matrix: sparse.csr_matrix, artists: list[int], settings: LatentGenreSimilaritySettings
) -> dict[int, np.ndarray]:
    """Fit fixed-rank SVD to training pairs and score only bounded heldout artists in batches."""
    if settings.rank >= min(matrix.shape):
        raise LatentGenreSimilarityError("latent rank exceeds matrix dimensions")
    _left, _singular, right = svds(
        matrix,
        k=settings.rank,
        which="LM",
        solver="arpack",
        random_state=settings.random_seed,
        return_singular_vectors="vh",
    )
    vectors = np.asarray(right, dtype=np.float32).T
    output: dict[int, np.ndarray] = {}
    for start in range(0, len(artists), settings.evaluation_batch_size):
        batch = artists[start : start + settings.evaluation_batch_size]
        projected = np.asarray(matrix[batch] @ vectors)
        scores = projected @ vectors.T
        for offset, artist in enumerate(batch):
            train = matrix.indices[matrix.indptr[artist] : matrix.indptr[artist + 1]]
            if (
                not len(train)
                or not np.all(np.isfinite(projected[offset]))
                or not np.any(projected[offset])
            ):
                output[artist] = np.asarray([], dtype=np.int32)
                continue
            scores[offset, train] = -np.inf
            ordered = np.argsort(-scores[offset], kind="stable")
            output[artist] = ordered[np.isfinite(scores[offset, ordered])][:25]
    return output


def _rank_jaccard(
    matrix: sparse.csr_matrix, artists: list[int], settings: LatentGenreSimilaritySettings
) -> dict[int, np.ndarray]:
    baseline = FullGraphSignalSettings(
        maximum_genre_neighbors=settings.maximum_genre_neighbors,
        maximum_cooccurrence_nnz=settings.maximum_cooccurrence_nnz,
        maximum_evaluation_artists=settings.maximum_evaluation_artists,
    )
    neighbors = _jaccard_neighbors(matrix, _cooccurrence(matrix, baseline), baseline)
    output: dict[int, np.ndarray] = {}
    for artist in artists:
        scores: dict[int, float] = defaultdict(float)
        train = matrix.indices[matrix.indptr[artist] : matrix.indptr[artist + 1]]
        for genre in train:
            begin, end = neighbors.indptr[genre], neighbors.indptr[genre + 1]
            for candidate, value in zip(
                neighbors.indices[begin:end], neighbors.data[begin:end], strict=True
            ):
                if candidate not in train:
                    scores[int(candidate)] += float(value)
        output[artist] = np.asarray(
            [key for key, _ in sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:25]],
            dtype=np.int32,
        )
    return output


def _rank_popularity(matrix: sparse.csr_matrix, artists: list[int]) -> dict[int, np.ndarray]:
    ranked = np.argsort(-np.asarray(matrix.getnnz(axis=0)).ravel(), kind="stable")[:25]
    return dict.fromkeys(artists, ranked)


def build_latent_genre_similarity(
    inputs: LatentGenreSimilarityInputs, settings: LatentGenreSimilaritySettings | None = None
) -> LatentGenreSimilarityArtifact:
    """Benchmark fixed-rank latent retrieval against same-split sparse and popularity baselines."""
    resolved = settings or LatentGenreSimilaritySettings()
    source, matrix, pairs, bindings = _load(inputs)
    artists = _sampled(
        pairs["heldout_rows"], source.settings.split_seed, resolved.maximum_evaluation_artists
    )
    targets = _targets(pairs["heldout_rows"], pairs["heldout_columns"], artists)
    latent = _metric("latent_svd", targets, _rank_latent(matrix, artists, resolved), len(artists))
    jaccard = _metric(
        "binary_jaccard", targets, _rank_jaccard(matrix, artists, resolved), len(artists)
    )
    popularity = _metric(
        "train_only_popularity", targets, _rank_popularity(matrix, artists), len(artists)
    )
    direct = _metric("direct_only", targets, {}, len(artists))
    preliminary = LatentGenreSimilarityArtifact(
        inputs=bindings,
        settings=resolved,
        settings_sha256=_settings_sha256(resolved),
        train_pair_count=len(pairs["rows"]),
        heldout_pair_count=len(pairs["heldout_rows"]),
        evaluated_artist_count=len(artists),
        latent=latent,
        binary_jaccard=jaccard,
        train_only_popularity=popularity,
        direct_only=direct,
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(update={"output_sha256": _artifact_sha256(preliminary)})


def write_latent_genre_similarity(
    output: Path, receipt_path: Path, artifact: LatentGenreSimilarityArtifact
) -> LatentGenreSimilarityReceipt:
    """Persist the review-only benchmark with exact byte custody."""
    verify_latent_genre_similarity(artifact)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json(artifact.model_dump(mode="json")) + b"\n"
    write_atomic_bytes(output, payload)
    digest, count = sha256_file(output)
    receipt = LatentGenreSimilarityReceipt(
        artifact_sha256=digest,
        artifact_byte_count=count,
        logical_output_sha256=artifact.output_sha256,
    )
    write_atomic_bytes(receipt_path, canonical_json(receipt.model_dump(mode="json")) + b"\n")
    return receipt
