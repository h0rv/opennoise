"""Sparse contextual-tag genre prototypes and held-out weak-supervision evaluation."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import numpy as np
from pydantic import Field, model_validator
from scipy.sparse import csr_matrix, diags

from musix.ingest.musicbrainz.musicbrainz_seed_targets import (
    MusicBrainzSeedTargetArtifact,
    verify_seed_target_artifact,
)
from musix.models import FrozenModel
from musix.storage import ObjectKey, ObjectStore, ObjectWrite

_REVISION: Final = "sparse-genre-prototype-v1"
_SHA: Final = r"^[0-9a-f]{64}$"


class SparsePrototypeSettings(FrozenModel):
    """Bounded deterministic controls for the non-historical baseline."""

    revision: Literal["sparse-genre-prototype-settings-v1"] = "sparse-genre-prototype-settings-v1"
    holdout_fraction: float = Field(default=0.2, gt=0.0, lt=1.0)
    holdout_seed: int = Field(default=20260905, ge=0)
    retrieval_k: int = Field(default=25, ge=1, le=100)
    neighbors_per_seed: int = Field(default=25, ge=1, le=100)
    minimum_train_artists: int = Field(default=1, ge=1, le=1000)


class PrototypeSimilarityCandidate(FrozenModel):
    """A symmetric seed-prototype candidate, not a direct artist-overlap peer."""

    left_source_item_id: str = Field(min_length=1)
    right_source_item_id: str = Field(min_length=1)
    cosine_similarity: float = Field(gt=0.0, le=1.0)
    shared_context_tag_count: int = Field(gt=0)

    @model_validator(mode="after")
    def _canonical(self) -> PrototypeSimilarityCandidate:
        if self.left_source_item_id >= self.right_source_item_id:
            raise ValueError("prototype candidates require ascending distinct seed IDs")
        return self


class PrototypeHeldoutResult(FrozenModel):
    """Positive-only retrieval evaluation; absent candidates are abstentions."""

    heldout_positive_count: int = Field(ge=0)
    evaluated_positive_count: int = Field(ge=0)
    retrieval_recall_at_k: float | None = Field(default=None, ge=0.0, le=1.0)
    mean_reciprocal_rank: float | None = Field(default=None, ge=0.0, le=1.0)
    abstained_positive_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _account(self) -> PrototypeHeldoutResult:
        if (
            self.evaluated_positive_count + self.abstained_positive_count
            != self.heldout_positive_count
        ):
            raise ValueError("heldout evaluation must explicitly account for every positive")
        return self


class SparsePrototypeCoverage(FrozenModel):
    """Explicit sparse feature and supervision coverage."""

    seed_count: int = Field(ge=1)
    contextual_artist_count: int = Field(ge=0)
    contextual_tag_count: int = Field(ge=0)
    direct_positive_count: int = Field(ge=0)
    train_positive_count: int = Field(ge=0)
    seed_prototype_count: int = Field(ge=0)
    prototype_candidate_count: int = Field(ge=0)
    historical_inputs_read: Literal[False] = False
    direct_target_features_used: Literal[False] = False


class SparseGenrePrototypeArtifact(FrozenModel):
    """Hash-bound sparse baseline with direct evidence reserved for labels only."""

    revision: Literal["sparse-genre-prototype-v1"] = _REVISION
    source_artifact_sha256: str = Field(pattern=_SHA)
    settings: SparsePrototypeSettings
    settings_sha256: str = Field(pattern=_SHA)
    input_sha256: str = Field(pattern=_SHA)
    candidates: tuple[PrototypeSimilarityCandidate, ...]
    heldout_evaluation: PrototypeHeldoutResult
    coverage: SparsePrototypeCoverage
    output_sha256: str = Field(pattern=_SHA)

    @model_validator(mode="after")
    def _safe(self) -> SparseGenrePrototypeArtifact:
        pairs = {(item.left_source_item_id, item.right_source_item_id) for item in self.candidates}
        if len(pairs) != len(self.candidates):
            raise ValueError("prototype candidates must be unique")
        return self


class SparsePrototypeGate(FrozenModel):
    """Fail-closed baseline gate."""

    artifact_output_sha256: str = Field(pattern=_SHA)
    deterministic_replay: Literal[True] = True
    historical_data_prohibited: Literal[True] = True
    direct_evidence_kept_out_of_features: Literal[True] = True
    positive_only_evaluation: Literal[True] = True


class SparsePrototypeReceipt(FrozenModel):
    """Object-store receipt for one sparse baseline artifact."""

    artifact_sha256: str = Field(pattern=_SHA)
    artifact_byte_size: int = Field(ge=1)
    object_key: str = Field(min_length=1)
    logical_output_sha256: str = Field(pattern=_SHA)
    gate: SparsePrototypeGate


@dataclass(frozen=True, slots=True)
class _HeldoutRetrievalInputs:
    """Sparse retrieval matrices and their deterministic row labels."""

    prototypes: csr_matrix
    artist_matrix: csr_matrix
    seeds: tuple[str, ...]
    artists: dict[str, int]


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _select_holdout(seed_id: str, artist_id: str, settings: SparsePrototypeSettings) -> float:
    digest = hashlib.sha256(f"{settings.holdout_seed}\0{seed_id}\0{artist_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def _direct_pairs(artifact: MusicBrainzSeedTargetArtifact) -> dict[str, tuple[str, ...]]:
    pairs: dict[str, set[str]] = defaultdict(set)
    for evidence in artifact.evidence:
        pairs[evidence.seed_source_item_id].add(evidence.artist_id)
    return {seed: tuple(sorted(artists)) for seed, artists in pairs.items()}


def _split_train_holdout(
    pairs: dict[str, tuple[str, ...]], settings: SparsePrototypeSettings
) -> tuple[dict[str, tuple[str, ...]], tuple[tuple[str, str], ...]]:
    train: dict[str, tuple[str, ...]] = {}
    heldout: list[tuple[str, str]] = []
    for seed, artists in pairs.items():
        chosen = tuple(
            artist
            for artist in artists
            if _select_holdout(seed, artist, settings) < settings.holdout_fraction
        )
        if len(chosen) == len(artists):
            chosen = chosen[:-1]
        heldout.extend((seed, artist) for artist in chosen)
        train[seed] = tuple(artist for artist in artists if artist not in set(chosen))
    return train, tuple(sorted(heldout))


def _context_matrix(artifact: MusicBrainzSeedTargetArtifact) -> tuple[tuple[str, ...], csr_matrix]:
    artists = tuple(sorted({row.artist_id for row in artifact.contextual_tags}))
    tags = tuple(sorted({row.tag_identity for row in artifact.contextual_tags}))
    artist_index, tag_index = (
        {key: index for index, key in enumerate(artists)},
        {key: index for index, key in enumerate(tags)},
    )
    rows = [artist_index[row.artist_id] for row in artifact.contextual_tags]
    columns = [tag_index[row.tag_identity] for row in artifact.contextual_tags]
    values = [float(row.tag_count or 1) for row in artifact.contextual_tags]
    raw = csr_matrix((values, (rows, columns)), shape=(len(artists), len(tags)))
    document_frequency = np.asarray((raw > 0).sum(axis=0)).ravel()
    inverse_document_frequency = np.log((1 + len(artists)) / (1 + document_frequency)) + 1
    weighted = raw @ diags(inverse_document_frequency)
    return artists, _normalize_rows(weighted.tocsr())


def _normalize_rows(matrix: csr_matrix) -> csr_matrix:
    norms = np.sqrt(matrix.multiply(matrix).sum(axis=1)).A1
    inverse = np.divide(1.0, norms, out=np.zeros_like(norms), where=norms > 0.0)
    normalized = (diags(inverse) @ matrix).tocsr()
    if not isinstance(normalized, csr_matrix):
        raise TypeError("sparse row normalization did not produce CSR storage")
    return normalized


def _bounded_cosine(value: float) -> float:
    """Keep harmless sparse floating-point overshoot within cosine bounds."""
    return min(1.0, max(0.0, value))


def _evaluate_heldout_retrieval(
    inputs: _HeldoutRetrievalInputs,
    heldout: tuple[tuple[str, str], ...],
    settings: SparsePrototypeSettings,
) -> PrototypeHeldoutResult:
    """Evaluate only scored sparse retrieval candidates for held-out edges."""
    retrieval = (inputs.prototypes @ inputs.artist_matrix.T).tocsr()
    seed_index = {seed: index for index, seed in enumerate(inputs.seeds)}
    heldout_by_seed: dict[str, list[str]] = defaultdict(list)
    for seed, artist in heldout:
        heldout_by_seed[seed].append(artist)
    evaluated = 0
    hits = 0
    reciprocal = 0.0
    for seed, heldout_artists in heldout_by_seed.items():
        row_index = seed_index.get(seed)
        if row_index is None:
            continue
        scores = retrieval.getrow(row_index)
        scores.sort_indices()
        # Search only non-zero candidates.  A held-out artist with no sparse
        # retrieval score has no candidate and is explicitly an abstention;
        # treating the implicit zero as rank one would inflate the metric.
        for artist in heldout_artists:
            artist_column = inputs.artists.get(artist)
            if artist_column is None:
                continue
            position = int(np.searchsorted(scores.indices, artist_column))
            if position == len(scores.indices) or scores.indices[position] != artist_column:
                continue
            target_score = float(scores.data[position])
            if target_score <= 0.0:
                continue
            rank = int(np.count_nonzero(scores.data > target_score) + 1)
            evaluated += 1
            hits += rank <= settings.retrieval_k
            reciprocal += 1.0 / rank
    return PrototypeHeldoutResult(
        heldout_positive_count=len(heldout),
        evaluated_positive_count=evaluated,
        retrieval_recall_at_k=hits / evaluated if evaluated else None,
        mean_reciprocal_rank=reciprocal / evaluated if evaluated else None,
        abstained_positive_count=len(heldout) - evaluated,
    )


def build_sparse_genre_prototype(
    artifact: MusicBrainzSeedTargetArtifact, settings: SparsePrototypeSettings | None = None
) -> SparseGenrePrototypeArtifact:
    """Build tag-only seed prototypes and positive-only heldout artist retrieval."""
    verify_seed_target_artifact(artifact)
    resolved = settings or SparsePrototypeSettings()
    pairs = _direct_pairs(artifact)
    train, heldout = _split_train_holdout(pairs, resolved)
    artists, matrix = _context_matrix(artifact)
    artist_index = {artist: index for index, artist in enumerate(artists)}
    seeds = tuple(
        sorted(
            seed
            for seed, ids in train.items()
            if sum(artist in artist_index for artist in ids) >= resolved.minimum_train_artists
        )
    )
    seed_rows, columns, values = [], [], []
    for row_index, seed in enumerate(seeds):
        for artist in train[seed]:
            if artist in artist_index:
                seed_rows.append(row_index)
                columns.append(artist_index[artist])
                values.append(1.0)
    assignments = csr_matrix((values, (seed_rows, columns)), shape=(len(seeds), len(artists)))
    prototypes = _normalize_rows((assignments @ matrix).tocsr())
    similarities = (prototypes @ prototypes.T).tocsr()
    candidates: list[PrototypeSimilarityCandidate] = []
    for left in range(len(seeds)):
        ranked = sorted(
            (
                (float(score), right)
                for right, score in zip(
                    similarities[left].indices, similarities[left].data, strict=True
                )
                if right != left and score > 0.0
            ),
            reverse=True,
        )[: resolved.neighbors_per_seed]
        for score, right in ranked:
            if seeds[left] < seeds[right]:
                shared = int(prototypes[left].multiply(prototypes[right]).count_nonzero())
                candidates.append(
                    PrototypeSimilarityCandidate(
                        left_source_item_id=seeds[left],
                        right_source_item_id=seeds[right],
                        cosine_similarity=_bounded_cosine(score),
                        shared_context_tag_count=shared,
                    )
                )
    unique = {(item.left_source_item_id, item.right_source_item_id): item for item in candidates}
    ordered_candidates = tuple(
        sorted(
            unique.values(), key=lambda item: (item.left_source_item_id, item.right_source_item_id)
        )
    )
    evaluation = _evaluate_heldout_retrieval(
        _HeldoutRetrievalInputs(prototypes, matrix, seeds, artist_index), heldout, resolved
    )
    coverage = SparsePrototypeCoverage(
        seed_count=artifact.seed_count,
        contextual_artist_count=len(artists),
        contextual_tag_count=matrix.shape[1],
        direct_positive_count=sum(len(ids) for ids in pairs.values()),
        train_positive_count=sum(len(ids) for ids in train.values()),
        seed_prototype_count=len(seeds),
        prototype_candidate_count=len(ordered_candidates),
    )
    preliminary = SparseGenrePrototypeArtifact(
        source_artifact_sha256=artifact.output_sha256,
        settings=resolved,
        settings_sha256=_hash(resolved.model_dump(mode="json")),
        input_sha256=_hash(artifact.model_dump(mode="json")),
        candidates=ordered_candidates,
        heldout_evaluation=evaluation,
        coverage=coverage,
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(
        update={
            "output_sha256": _hash(preliminary.model_dump(mode="json", exclude={"output_sha256"}))
        }
    )


def verify_sparse_genre_prototype(artifact: SparseGenrePrototypeArtifact) -> SparsePrototypeGate:
    """Verify deterministic hashes and evidence-separation declarations."""
    if artifact.settings_sha256 != _hash(
        artifact.settings.model_dump(mode="json")
    ) or artifact.output_sha256 != _hash(
        artifact.model_dump(mode="json", exclude={"output_sha256"})
    ):
        raise ValueError("sparse prototype hash does not replay")
    return SparsePrototypeGate(artifact_output_sha256=artifact.output_sha256)


def publish_sparse_genre_prototype(
    artifact: SparseGenrePrototypeArtifact, *, output_path: Path, store: ObjectStore
) -> tuple[SparsePrototypeReceipt, ObjectWrite]:
    """Write and custody one verified prototype artifact."""
    gate = verify_sparse_genre_prototype(artifact)
    payload = (artifact.model_dump_json(indent=2) + "\n").encode()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(prefix=f".{output_path.name}.", dir=output_path.parent)
    temporary = Path(raw_path)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(output_path)
    finally:
        temporary.unlink(missing_ok=True)
    artifact_sha = hashlib.sha256(payload).hexdigest()
    key = ObjectKey(value=f"sparse-genre-prototype/{artifact.output_sha256}/{artifact_sha}.json")
    write = store.push(output_path, key)
    if write.sha256 != artifact_sha:
        raise ValueError("object store write does not match sparse prototype")
    return SparsePrototypeReceipt(
        artifact_sha256=artifact_sha,
        artifact_byte_size=len(payload),
        object_key=key.value,
        logical_output_sha256=artifact.output_sha256,
        gate=gate,
    ), write
