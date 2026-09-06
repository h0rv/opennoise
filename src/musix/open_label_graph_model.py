"""Open-evidence label graph candidates with cold-label evaluation.

This module is deliberately a review layer.  It learns only from the observed
tag anchors in a sealed source artifact, keeps the raw evidence references on
every proposed identity edge, and never reads or reconstructs historical
Every Noise/H3 data.  The model is source-agnostic at the graph boundary:
labels, artists, contextual tags, and evidence references are plain stable
identifiers supplied by the source adapter.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import ijson
import numpy as np
from pydantic import Field, model_validator
from scipy.optimize import minimize

from musix.models import FrozenModel
from musix.musicbrainz_seed_targets import (
    ContextualArtistTag,
    MusicBrainzSeedTargetArtifact,
    SeedTargetCoverage,
    SeedTargetEvidence,
    SeedTargetExtractorCounters,
    SeedTargetExtractorSettings,
    artifact_sha256,
    settings_sha256,
    verify_seed_target_artifact,
)
from musix.seed_reconciliation import SeedReconciliationArtifact, verify_seed_reconciliation
from musix.storage import ObjectKey, ObjectStore, ObjectWrite

_REVISION: Final = "open-label-graph-model-v1"
_SHA: Final = r"^[0-9a-f]{64}$"
_TOKEN: Final = re.compile(r"[\w]+", re.UNICODE)
_NGRAM: Final = 3
_BINARY_CLASS_COUNT: Final = 2
_TOP_K: Final = 5

type CandidateDisposition = Literal["review_candidate"]
type AbstentionReason = Literal["no_retrievable_label", "below_calibrated_threshold"]


class OpenLabelGraphSettings(FrozenModel):
    """Laptop-safe deterministic controls for the open label graph model."""

    revision: Literal["open-label-graph-settings-v1"] = "open-label-graph-settings-v1"
    split_seed: int = Field(default=20260906, ge=0)
    calibration_fraction: float = Field(default=0.2, gt=0.0, lt=0.45)
    test_fraction: float = Field(default=0.2, gt=0.0, lt=0.45)
    hard_negatives_per_anchor: int = Field(default=8, ge=1, le=32)
    candidates_per_label: int = Field(default=5, ge=1, le=20)
    maximum_retrieval_candidates: int = Field(default=500, ge=10, le=5_000)
    maximum_vocabulary: int = Field(default=100_000, ge=1, le=250_000)
    maximum_iterations: int = Field(default=150, ge=1, le=500)
    l2_regularization: float = Field(default=0.05, gt=0.0, le=100.0)
    minimum_review_precision: float = Field(default=0.8, gt=0.0, le=1.0)
    minimum_lexical_score: float = Field(default=0.25, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _disjoint_evaluation_splits(self) -> OpenLabelGraphSettings:
        if self.calibration_fraction + self.test_fraction >= 1.0:
            raise ValueError("calibration and held-out fractions must leave training anchors")
        return self


class LabelGraphFeatures(FrozenModel):
    """Transparent lexical and optional graph components for one label edge."""

    token_jaccard: float = Field(ge=0.0, le=1.0)
    character_ngram_cosine: float = Field(ge=0.0, le=1.0)
    normalized_subword_overlap: float = Field(ge=0.0, le=1.0)
    head_modifier_relation: float = Field(ge=0.0, le=1.0)
    tag_support: float = Field(ge=0.0, le=1.0)
    artist_graph_jaccard: float = Field(ge=0.0, le=1.0)
    contextual_tag_match: float = Field(ge=0.0, le=1.0)


class LabelGraphCoefficient(FrozenModel):
    """One trained, inspectable coefficient."""

    feature_name: Literal[
        "intercept",
        "token_jaccard",
        "character_ngram_cosine",
        "normalized_subword_overlap",
        "head_modifier_relation",
        "tag_support",
        "artist_graph_jaccard",
        "contextual_tag_match",
    ]
    value: float = Field(allow_inf_nan=False)


class RecoveryMetrics(FrozenModel):
    """Anchor recovery measured only on a frozen partition."""

    anchor_count: int = Field(ge=0)
    retrievable_anchor_count: int = Field(ge=0)
    top_1_recall: float | None = Field(default=None, ge=0.0, le=1.0)
    top_5_recall: float | None = Field(default=None, ge=0.0, le=1.0)
    mean_reciprocal_rank: float | None = Field(default=None, ge=0.0, le=1.0)


class HeldoutComparison(FrozenModel):
    """Cold-label evaluation and the explicit name-only comparator."""

    heldout_anchor_count: int = Field(ge=0)
    cold_label_anchor_count: int = Field(ge=0)
    lexical_baseline: RecoveryMetrics
    label_graph_model: RecoveryMetrics
    top_1_recall_lift: float | None = None
    top_5_recall_lift: float | None = None


class OpenLabelGraphCandidate(FrozenModel):
    """A review-only proposed stable-label-to-open-tag identity edge."""

    source_item_id: str = Field(min_length=1, max_length=200)
    seed_name: str = Field(min_length=1, max_length=500)
    candidate_label_id: str = Field(min_length=1, max_length=500)
    candidate_label_name: str = Field(min_length=1, max_length=500)
    score: float = Field(ge=0.0, le=1.0)
    lexical_baseline_score: float = Field(ge=0.0, le=1.0)
    features: LabelGraphFeatures
    direct_artist_overlap_count: int = Field(ge=0)
    contextual_tag_overlap_count: int = Field(ge=0)
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=32)
    disposition: CandidateDisposition = "review_candidate"


class OpenLabelGraphAbstention(FrozenModel):
    """One unanchored label deliberately withheld from review."""

    source_item_id: str = Field(min_length=1, max_length=200)
    seed_name: str = Field(min_length=1, max_length=500)
    reason: AbstentionReason
    best_score: float | None = Field(default=None, ge=0.0, le=1.0)


class OpenLabelGraphCoverage(FrozenModel):
    """Complete accounting for anchors and truly unanchored labels."""

    seed_count: int = Field(ge=1)
    observed_anchor_count: int = Field(ge=0)
    train_anchor_count: int = Field(ge=0)
    calibration_anchor_count: int = Field(ge=0)
    heldout_anchor_count: int = Field(ge=0)
    cold_label_anchor_count: int = Field(ge=0)
    vocabulary_count: int = Field(ge=0)
    true_unanchored_label_count: int = Field(ge=0)
    proposed_unanchored_label_count: int = Field(ge=0)
    abstained_unanchored_label_count: int = Field(ge=0)
    historical_inputs_read: Literal[False] = False
    observed_identities_created: Literal[False] = False
    memberships_created: Literal[False] = False

    @model_validator(mode="after")
    def _coverage_partitions(self) -> OpenLabelGraphCoverage:
        if (
            self.train_anchor_count + self.calibration_anchor_count + self.heldout_anchor_count
            != self.observed_anchor_count
        ):
            raise ValueError("anchor partitions must account for observed anchors")
        if (
            self.proposed_unanchored_label_count + self.abstained_unanchored_label_count
            != self.true_unanchored_label_count
        ):
            raise ValueError(
                "candidate rows and abstentions must cover every truly unanchored label"
            )
        return self


class OpenLabelGraphArtifact(FrozenModel):
    """Hash-bound open-only model result with candidate provenance."""

    revision: Literal["open-label-graph-model-v1"] = _REVISION
    seed_target_output_sha256: str = Field(pattern=_SHA)
    seed_target_file_sha256: str = Field(pattern=_SHA)
    seed_reconciliation_output_sha256: str = Field(pattern=_SHA)
    seed_identity_sha256: str = Field(pattern=_SHA)
    settings: OpenLabelGraphSettings
    settings_sha256: str = Field(pattern=_SHA)
    input_sha256: str = Field(pattern=_SHA)
    vocabulary_sha256: str = Field(pattern=_SHA)
    coefficients: tuple[LabelGraphCoefficient, ...] = Field(min_length=8, max_length=8)
    calibrated_review_threshold: float = Field(ge=0.0, le=1.0)
    heldout_comparison: HeldoutComparison
    candidates: tuple[OpenLabelGraphCandidate, ...]
    abstentions: tuple[OpenLabelGraphAbstention, ...]
    coverage: OpenLabelGraphCoverage
    historical_inputs_read: Literal[False] = False
    output_sha256: str = Field(pattern=_SHA)

    @model_validator(mode="after")
    def _complete(self) -> OpenLabelGraphArtifact:
        candidate_ids = {row.source_item_id for row in self.candidates}
        abstained_ids = {row.source_item_id for row in self.abstentions}
        if candidate_ids & abstained_ids:
            raise ValueError("a label cannot be both reviewed and abstained")
        if len(candidate_ids) != self.coverage.proposed_unanchored_label_count:
            raise ValueError("candidate coverage does not match candidate rows")
        if len(abstained_ids) != self.coverage.abstained_unanchored_label_count:
            raise ValueError("abstention coverage does not match abstention rows")
        return self


class OpenLabelGraphGate(FrozenModel):
    """Fail-closed gate for the review-only model artifact."""

    artifact_output_sha256: str = Field(pattern=_SHA)
    deterministic_replay: Literal[True] = True
    heldout_labels_excluded_from_fit_and_tuning: Literal[True] = True
    cold_label_evaluation: Literal[True] = True
    name_only_baseline_compared: Literal[True] = True
    historical_construction_prohibited: Literal[True] = True
    review_only_candidates: Literal[True] = True
    no_observed_identities_or_memberships: Literal[True] = True


class OpenLabelGraphReceipt(FrozenModel):
    """Object-store receipt for a verified open label graph artifact."""

    artifact_sha256: str = Field(pattern=_SHA)
    artifact_byte_size: int = Field(ge=1)
    object_key: str = Field(min_length=1)
    logical_output_sha256: str = Field(pattern=_SHA)
    gate: OpenLabelGraphGate


@dataclass(frozen=True, slots=True)
class _Tag:
    identifier: str
    name: str
    artists: frozenset[str]
    refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Anchor:
    identifier: str
    name: str
    target: str
    artists: frozenset[str]
    context_tags: frozenset[str]


@dataclass(frozen=True, slots=True)
class _Index:
    tags: tuple[_Tag, ...]
    by_identifier: dict[str, int]
    token_rows: dict[str, tuple[int, ...]]
    ngram_rows: dict[str, tuple[int, ...]]


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(str(token) for token in _TOKEN.findall(value.casefold()))


def _ngrams(value: str) -> frozenset[str]:
    text = " ".join(_tokens(value))
    padded = f"^{text}$"
    if len(padded) <= _NGRAM:
        return frozenset((padded,))
    return frozenset(padded[index : index + _NGRAM] for index in range(len(padded) - _NGRAM + 1))


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _char_cosine(left: str, right: str) -> float:
    left_grams, right_grams = _ngrams(left), _ngrams(right)
    return (
        len(left_grams & right_grams) / math.sqrt(len(left_grams) * len(right_grams))
        if left_grams and right_grams
        else 0.0
    )


def _head_modifier(seed: str, tag: str) -> float:
    left, right = _tokens(seed), _tokens(tag)
    if not left or not right:
        return 0.0
    return (0.5 if left[-1] == right[-1] else 0.0) + 0.5 * _jaccard(
        frozenset(left[:-1]), frozenset(right[:-1])
    )


def _lexical(features: LabelGraphFeatures) -> float:
    return min(
        1.0,
        0.2 * features.token_jaccard
        + 0.45 * features.character_ngram_cosine
        + 0.25 * features.normalized_subword_overlap
        + 0.1 * features.head_modifier_relation,
    )


def _split(
    label_id: str, settings: OpenLabelGraphSettings
) -> Literal["train", "calibration", "test"]:
    """Assign every claim of one canonical target label to one split."""
    value = (
        int.from_bytes(
            hashlib.sha256(f"{settings.split_seed}\0{label_id}".encode()).digest()[:8], "big"
        )
        / 2**64
    )
    if value < settings.calibration_fraction:
        return "calibration"
    if value < settings.calibration_fraction + settings.test_fraction:
        return "test"
    return "train"


def _verify_binding(
    source: MusicBrainzSeedTargetArtifact, reconciliation: SeedReconciliationArtifact
) -> None:
    if source.seed_count != reconciliation.seed_count:
        raise ValueError("source and reconciliation seed counts do not match")
    if {row.seed_source_item_id for row in source.coverage} != {
        row.source_item_id for row in reconciliation.dispositions
    }:
        raise ValueError("source and reconciliation stable seed universes do not match")
    if (
        source.seed_source_id != reconciliation.seed_source_id
        or source.seed_source_content_sha256 != reconciliation.seed_source_content_sha256
    ):
        raise ValueError("source and reconciliation provenance does not match")


def _build_graph(
    source: MusicBrainzSeedTargetArtifact, settings: OpenLabelGraphSettings
) -> tuple[tuple[_Tag, ...], dict[str, _Anchor]]:
    tag_artists: dict[str, set[str]] = defaultdict(set)
    tag_names: dict[str, str] = {}
    tag_refs: dict[str, set[str]] = defaultdict(set)
    direct: dict[str, set[str]] = defaultdict(set)
    targets: dict[str, set[str]] = defaultdict(set)
    names = {row.seed_source_item_id: row.seed_name for row in source.coverage}
    for row in source.evidence:
        if row.facet != "tag":
            continue
        tag_artists[row.target_identity].add(row.artist_id)
        tag_names[row.target_identity] = row.target_name
        tag_refs[row.target_identity].add(row.evidence_ref)
        if row.match_kind in {"exact", "normalized"}:
            direct[row.seed_source_item_id].add(row.artist_id)
            targets[row.seed_source_item_id].add(row.target_identity)
    context: dict[str, set[str]] = defaultdict(set)
    for row in source.contextual_tags:
        tag_artists[row.tag_identity].add(row.artist_id)
        tag_names[row.tag_identity] = row.tag_name
        tag_refs[row.tag_identity].add(row.evidence_ref)
        for seed_id in row.matched_seed_source_item_ids:
            context[seed_id].add(row.tag_identity)
    if len(tag_names) > settings.maximum_vocabulary:
        raise ValueError("open label vocabulary exceeds configured bound")
    tags = tuple(
        _Tag(
            identifier,
            tag_names[identifier],
            frozenset(tag_artists[identifier]),
            tuple(sorted(tag_refs[identifier])[:32]),
        )
        for identifier in sorted(tag_names)
    )
    anchors = {
        seed_id: _Anchor(
            seed_id,
            names[seed_id],
            next(iter(target_ids)),
            frozenset(direct[seed_id]),
            frozenset(context[seed_id]),
        )
        for seed_id, target_ids in targets.items()
        if len(target_ids) == 1
    }
    return tags, anchors


def _index(tags: tuple[_Tag, ...]) -> _Index:
    token_rows: dict[str, list[int]] = defaultdict(list)
    ngram_rows: dict[str, list[int]] = defaultdict(list)
    for index, tag in enumerate(tags):
        for token in _tokens(tag.name):
            token_rows[token].append(index)
        for gram in _ngrams(tag.name):
            ngram_rows[gram].append(index)
    return _Index(
        tags,
        {tag.identifier: index for index, tag in enumerate(tags)},
        {key: tuple(value) for key, value in token_rows.items()},
        {key: tuple(value) for key, value in ngram_rows.items()},
    )


def _features(
    name: str,
    artists: frozenset[str],
    context_tags: frozenset[str],
    tag: _Tag,
    maximum_support: int,
) -> LabelGraphFeatures:
    seed_grams, tag_grams = _ngrams(name), _ngrams(tag.name)
    return LabelGraphFeatures(
        token_jaccard=_jaccard(frozenset(_tokens(name)), frozenset(_tokens(tag.name))),
        character_ngram_cosine=_char_cosine(name, tag.name),
        normalized_subword_overlap=len(seed_grams & tag_grams) / len(seed_grams)
        if seed_grams
        else 0.0,
        head_modifier_relation=_head_modifier(name, tag.name),
        tag_support=math.log1p(len(tag.artists)) / math.log1p(maximum_support)
        if maximum_support
        else 0.0,
        artist_graph_jaccard=_jaccard(artists, tag.artists),
        contextual_tag_match=1.0 if tag.identifier in context_tags else 0.0,
    )


def _vector(features: LabelGraphFeatures) -> np.ndarray:
    return np.array(
        (
            1.0,
            features.token_jaccard,
            features.character_ngram_cosine,
            features.normalized_subword_overlap,
            features.head_modifier_relation,
            features.tag_support,
            features.artist_graph_jaccard,
            features.contextual_tag_match,
        ),
        dtype=np.float64,
    )


def _retrieve(
    name: str,
    index: _Index,
    *,
    limit: int,
    include: str | None = None,
) -> tuple[int, ...]:
    """Bound label retrieval by rarest lexical postings before feature scoring."""
    rows: set[int] = set()
    postings = tuple(
        sorted(
            (
                values
                for values in (
                    *(index.token_rows.get(token, ()) for token in _tokens(name)),
                    *(index.ngram_rows.get(gram, ()) for gram in _ngrams(name)),
                )
                if values
            ),
            key=lambda values: (len(values), values),
        )
    )
    for values in postings:
        for row in values:
            if len(rows) == limit:
                break
            rows.add(row)
        if len(rows) == limit:
            break
    if include is not None:
        target_row = index.by_identifier.get(include)
        if target_row is not None:
            rows.add(target_row)
    return tuple(sorted(rows))


def _fit(
    train: tuple[_Anchor, ...], index: _Index, max_support: int, settings: OpenLabelGraphSettings
) -> np.ndarray:
    vectors: list[np.ndarray] = []
    labels: list[float] = []
    for anchor in train:
        rows = _retrieve(
            anchor.name,
            index,
            limit=settings.maximum_retrieval_candidates,
            include=anchor.target,
        )
        ranked = sorted(
            (
                (
                    _lexical(
                        _features(
                            anchor.name,
                            anchor.artists,
                            anchor.context_tags,
                            index.tags[row],
                            max_support,
                        )
                    ),
                    row,
                )
                for row in rows
                if index.tags[row].identifier != anchor.target
            ),
            reverse=True,
        )
        positive_tag = index.tags[index.by_identifier[anchor.target]]
        vectors.append(
            _vector(
                _features(
                    anchor.name, anchor.artists, anchor.context_tags, positive_tag, max_support
                )
            )
        )
        labels.append(1.0)
        for _score, row in ranked[: settings.hard_negatives_per_anchor]:
            vectors.append(
                _vector(
                    _features(
                        anchor.name,
                        anchor.artists,
                        anchor.context_tags,
                        index.tags[row],
                        max_support,
                    )
                )
            )
            labels.append(0.0)
    if not vectors or len(set(labels)) < _BINARY_CLASS_COUNT:
        return np.zeros(8, dtype=np.float64)
    matrix, outcome = np.vstack(vectors), np.array(labels, dtype=np.float64)

    def objective(weights: np.ndarray) -> tuple[float, np.ndarray]:
        logits = np.clip(matrix @ weights, -35.0, 35.0)
        probabilities = 1.0 / (1.0 + np.exp(-logits))
        loss = -float(
            np.mean(
                outcome * np.log(np.clip(probabilities, 1e-12, 1.0))
                + (1.0 - outcome) * np.log(np.clip(1.0 - probabilities, 1e-12, 1.0))
            )
        )
        penalty = settings.l2_regularization * float(weights[1:] @ weights[1:]) / 2.0
        gradient = matrix.T @ (probabilities - outcome) / len(outcome)
        gradient[1:] += settings.l2_regularization * weights[1:]
        return loss + penalty, gradient

    result = minimize(
        objective,
        np.zeros(8, dtype=np.float64),
        jac=True,
        method="L-BFGS-B",
        options={"maxiter": settings.maximum_iterations},
    )
    if (
        not result.success
        or not isinstance(result.x, np.ndarray)
        or not np.all(np.isfinite(result.x))
    ):
        raise ValueError("open label graph logistic fit did not converge")
    return result.x


def _score(weights: np.ndarray, features: LabelGraphFeatures) -> float:
    return float(1.0 / (1.0 + math.exp(-float(np.clip(weights @ _vector(features), -35.0, 35.0)))))


def _threshold(
    calibration: tuple[_Anchor, ...],
    index: _Index,
    max_support: int,
    weights: np.ndarray,
    settings: OpenLabelGraphSettings,
) -> float:
    """Tune only on calibration anchors; held-out anchors never enter this path."""
    rows: list[tuple[float, bool]] = []
    for anchor in calibration:
        for row in _retrieve(
            anchor.name,
            index,
            limit=settings.maximum_retrieval_candidates,
            include=anchor.target,
        ):
            tag = index.tags[row]
            rows.append(
                (
                    _score(
                        weights,
                        _features(
                            anchor.name, anchor.artists, anchor.context_tags, tag, max_support
                        ),
                    ),
                    tag.identifier == anchor.target,
                )
            )
    if not rows:
        return 1.0
    thresholds = sorted({score for score, _positive in rows}, reverse=True)
    selected = 1.0
    for threshold in thresholds:
        predicted = [positive for score, positive in rows if score >= threshold]
        if predicted and sum(predicted) / len(predicted) >= settings.minimum_review_precision:
            selected = threshold
    return selected


def _recovery(
    anchors: tuple[_Anchor, ...],
    index: _Index,
    max_support: int,
    weights: np.ndarray | None,
    settings: OpenLabelGraphSettings,
) -> RecoveryMetrics:
    ranks: list[int] = []
    for anchor in anchors:
        rows = _retrieve(
            anchor.name,
            index,
            limit=settings.maximum_retrieval_candidates,
            include=anchor.target,
        )
        ranked = sorted(
            (
                (
                    _score(
                        weights,
                        _features(
                            anchor.name,
                            anchor.artists,
                            anchor.context_tags,
                            index.tags[row],
                            max_support,
                        ),
                    )
                    if weights is not None
                    else _lexical(
                        _features(
                            anchor.name,
                            anchor.artists,
                            anchor.context_tags,
                            index.tags[row],
                            max_support,
                        )
                    ),
                    index.tags[row].identifier,
                )
                for row in rows
            ),
            reverse=True,
        )
        for rank, (_value, target) in enumerate(ranked, start=1):
            if target == anchor.target:
                ranks.append(rank)
                break
    evaluated = len(ranks)
    return RecoveryMetrics(
        anchor_count=len(anchors),
        retrievable_anchor_count=evaluated,
        top_1_recall=sum(rank == 1 for rank in ranks) / evaluated if evaluated else None,
        top_5_recall=sum(rank <= _TOP_K for rank in ranks) / evaluated if evaluated else None,
        mean_reciprocal_rank=sum(1.0 / rank for rank in ranks) / evaluated if evaluated else None,
    )


def _cold_evaluation_index(fit_tags: tuple[_Tag, ...], heldout_tags: tuple[_Tag, ...]) -> _Index:
    """Expose held-out names for evaluation without their direct/context graph facts."""
    stripped = tuple(_Tag(tag.identifier, tag.name, frozenset(), tag.refs) for tag in heldout_tags)
    return _index((*fit_tags, *stripped))


def _without_graph(anchor: _Anchor) -> _Anchor:
    """Remove held-out direct and contextual edges before cold-label scoring."""
    return _Anchor(anchor.identifier, anchor.name, anchor.target, frozenset(), frozenset())


def build_open_label_graph_model(
    source: MusicBrainzSeedTargetArtifact,
    reconciliation: SeedReconciliationArtifact,
    settings: OpenLabelGraphSettings | None = None,
) -> OpenLabelGraphArtifact:
    """Train from anchors, calibrate separately, then propose only unanchored review edges."""
    verify_seed_target_artifact(source)
    verify_seed_reconciliation(reconciliation)
    _verify_binding(source, reconciliation)
    resolved = settings or OpenLabelGraphSettings()
    tags, anchors_by_id = _build_graph(source, resolved)
    tags_by_id = {tag.identifier: tag for tag in tags}
    partitions: dict[str, list[_Anchor]] = {"train": [], "calibration": [], "test": []}
    for anchor in anchors_by_id.values():
        partitions[_split(anchor.target, resolved)].append(anchor)
    train, calibration, test = (
        tuple(sorted(partitions[name], key=lambda anchor: anchor.identifier))
        for name in ("train", "calibration", "test")
    )
    calibration_targets = frozenset(anchor.target for anchor in calibration)
    heldout_targets = frozenset(anchor.target for anchor in test)
    excluded_fit_targets = calibration_targets | heldout_targets
    fit_tags = tuple(tag for tag in tags if tag.identifier not in excluded_fit_targets)
    graph_index = _index(fit_tags)
    max_support = max((len(tag.artists) for tag in fit_tags), default=0)
    weights = _fit(train, graph_index, max_support, resolved)
    calibration_index = _cold_evaluation_index(
        fit_tags,
        tuple(tags_by_id[target] for target in sorted(calibration_targets)),
    )
    cold_calibration = tuple(_without_graph(anchor) for anchor in calibration)
    review_threshold = _threshold(
        cold_calibration,
        calibration_index,
        max_support,
        weights,
        resolved,
    )
    cold_index = _cold_evaluation_index(
        fit_tags,
        tuple(tags_by_id[target] for target in sorted(heldout_targets)),
    )
    cold_test = tuple(_without_graph(anchor) for anchor in test)
    lexical, model = (
        _recovery(cold_test, cold_index, max_support, None, resolved),
        _recovery(cold_test, cold_index, max_support, weights, resolved),
    )
    train_targets = {anchor.target for anchor in train}
    cold_count = sum(anchor.target not in train_targets for anchor in test)
    comparison = HeldoutComparison(
        heldout_anchor_count=len(test),
        cold_label_anchor_count=cold_count,
        lexical_baseline=lexical,
        label_graph_model=model,
        top_1_recall_lift=(
            model.top_1_recall - lexical.top_1_recall
            if model.top_1_recall is not None and lexical.top_1_recall is not None
            else None
        ),
        top_5_recall_lift=(
            model.top_5_recall - lexical.top_5_recall
            if model.top_5_recall is not None and lexical.top_5_recall is not None
            else None
        ),
    )
    unanchored = tuple(
        sorted(
            (row for row in reconciliation.dispositions if row.source_item_id not in anchors_by_id),
            key=lambda row: row.source_item_id,
        )
    )
    candidates: list[OpenLabelGraphCandidate] = []
    abstentions: list[OpenLabelGraphAbstention] = []
    for row in unanchored:
        retrieved = _retrieve(
            row.seed_name,
            graph_index,
            limit=resolved.maximum_retrieval_candidates,
        )
        ranked = sorted(
            (
                (
                    _score(
                        weights,
                        _features(
                            row.seed_name,
                            frozenset(),
                            frozenset(),
                            graph_index.tags[index],
                            max_support,
                        ),
                    ),
                    _lexical(
                        _features(
                            row.seed_name,
                            frozenset(),
                            frozenset(),
                            graph_index.tags[index],
                            max_support,
                        )
                    ),
                    graph_index.tags[index],
                    _features(
                        row.seed_name,
                        frozenset(),
                        frozenset(),
                        graph_index.tags[index],
                        max_support,
                    ),
                )
                for index in retrieved
            ),
            key=lambda candidate: (-candidate[0], -candidate[1], candidate[2].identifier),
        )
        eligible = tuple(
            candidate
            for candidate in ranked
            if candidate[0] >= review_threshold and candidate[1] >= resolved.minimum_lexical_score
        )[: resolved.candidates_per_label]
        if not eligible:
            abstentions.append(
                OpenLabelGraphAbstention(
                    source_item_id=row.source_item_id,
                    seed_name=row.seed_name,
                    reason="no_retrievable_label" if not ranked else "below_calibrated_threshold",
                    best_score=ranked[0][0] if ranked else None,
                )
            )
            continue
        for score, lexical_score, tag, features in eligible:
            candidates.append(
                OpenLabelGraphCandidate(
                    source_item_id=row.source_item_id,
                    seed_name=row.seed_name,
                    candidate_label_id=tag.identifier,
                    candidate_label_name=tag.name,
                    score=score,
                    lexical_baseline_score=lexical_score,
                    features=features,
                    direct_artist_overlap_count=0,
                    contextual_tag_overlap_count=0,
                    evidence_refs=tag.refs,
                )
            )
    coverage = OpenLabelGraphCoverage(
        seed_count=source.seed_count,
        observed_anchor_count=len(anchors_by_id),
        train_anchor_count=len(train),
        calibration_anchor_count=len(calibration),
        heldout_anchor_count=len(test),
        cold_label_anchor_count=cold_count,
        vocabulary_count=len(tags),
        true_unanchored_label_count=len(unanchored),
        proposed_unanchored_label_count=len({candidate.source_item_id for candidate in candidates}),
        abstained_unanchored_label_count=len(abstentions),
    )
    names = (
        "intercept",
        "token_jaccard",
        "character_ngram_cosine",
        "normalized_subword_overlap",
        "head_modifier_relation",
        "tag_support",
        "artist_graph_jaccard",
        "contextual_tag_match",
    )
    preliminary = OpenLabelGraphArtifact(
        seed_target_output_sha256=source.output_sha256,
        seed_target_file_sha256=_sha(source.model_dump(mode="json")),
        seed_reconciliation_output_sha256=reconciliation.output_sha256,
        seed_identity_sha256=reconciliation.seed_identity_sha256,
        settings=resolved,
        settings_sha256=_sha(resolved.model_dump(mode="json")),
        input_sha256=_sha(
            {"source": source.output_sha256, "reconciliation": reconciliation.output_sha256}
        ),
        vocabulary_sha256=_sha(
            [(tag.identifier, tag.name, sorted(tag.artists), tag.refs) for tag in tags]
        ),
        coefficients=tuple(
            LabelGraphCoefficient(feature_name=name, value=float(value))
            for name, value in zip(names, weights, strict=True)
        ),
        calibrated_review_threshold=review_threshold,
        heldout_comparison=comparison,
        candidates=tuple(candidates),
        abstentions=tuple(abstentions),
        coverage=coverage,
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(
        update={
            "output_sha256": _sha(preliminary.model_dump(mode="json", exclude={"output_sha256"}))
        }
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _declared_source_values(path: Path) -> dict[str, str]:
    """Read scalar custody values without materialising any source array."""
    wanted = {
        "output_sha256",
        "seed_input_sha256",
        "seed_source_id",
        "seed_source_content_sha256",
        "archive_sha256",
    }
    pattern = re.compile(rb'"([a-z0-9_]+)":"([^"]+)"')
    values: dict[str, str] = {}
    tail = b""
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            payload = tail + chunk
            for raw_key, raw_value in pattern.findall(payload):
                key = raw_key.decode()
                if key in wanted:
                    values[key] = raw_value.decode()
            tail = payload[-128:]
    missing = wanted - values.keys()
    if missing:
        raise ValueError(f"streamed source is missing declared custody values: {sorted(missing)}")
    return values


def _stream_compact_source(  # noqa: C901
    path: Path,
    reconciliation: SeedReconciliationArtifact,
) -> tuple[MusicBrainzSeedTargetArtifact, str, str]:
    """Build a bounded representative graph from a large immutable JSON artifact.

    The source arrays are independently streamed.  The compact artifact retains
    all seed names, every observed anchor identity, and contextual rows only
    where they attach to an observed anchor.  It is a feature cache, never a
    replacement source or a promotion mechanism.
    """
    declared = _declared_source_values(path)
    if (
        declared["seed_source_id"] != reconciliation.seed_source_id
        or declared["seed_source_content_sha256"] != reconciliation.seed_source_content_sha256
    ):
        raise ValueError("streamed source provenance does not bind reconciliation")
    with path.open("rb") as stream:
        coverage = [
            SeedTargetCoverage.model_validate(item) for item in ijson.items(stream, "coverage.item")
        ]
    if len(coverage) != reconciliation.seed_count:
        raise ValueError("streamed source coverage count does not bind reconciliation")
    coverage_ids = {row.seed_source_item_id for row in coverage}
    if coverage_ids != {row.source_item_id for row in reconciliation.dispositions}:
        raise ValueError("streamed source coverage IDs do not bind reconciliation")
    anchor_by_seed: dict[str, SeedTargetEvidence] = {}
    with path.open("rb") as stream:
        for item in ijson.items(stream, "evidence.item"):
            if not isinstance(item, dict):
                raise TypeError("streamed evidence row must be an object")
            seed_id = item.get("seed_source_item_id")
            if (
                item.get("facet") == "tag"
                and item.get("match_kind") in {"exact", "normalized"}
                and isinstance(seed_id, str)
                and seed_id not in anchor_by_seed
            ):
                anchor_by_seed[seed_id] = SeedTargetEvidence.model_validate(item)
    anchor_targets = {row.target_identity for row in anchor_by_seed.values()}
    anchor_ids = frozenset(anchor_by_seed)
    representative_context: dict[str, ContextualArtistTag] = {}
    for anchor in anchor_by_seed.values():
        representative_context[anchor.target_identity] = ContextualArtistTag(
            artist_id=anchor.artist_id,
            source_record_id=anchor.source_record_id,
            source_record_ordinal=anchor.source_record_ordinal,
            source_record_sha256=anchor.source_record_sha256,
            source_record_byte_length=anchor.source_record_byte_length,
            tag_name=anchor.target_name,
            tag_identity=anchor.target_identity,
            tag_count=1,
            matched_seed_source_item_ids=(anchor.seed_source_item_id,),
            evidence_ref=anchor.evidence_ref,
        )
    with path.open("rb") as stream:
        for item in ijson.items(stream, "contextual_tags.item"):
            if not isinstance(item, dict):
                raise TypeError("streamed contextual tag row must be an object")
            tag_identity = item.get("tag_identity")
            if not isinstance(tag_identity, str):
                raise TypeError("streamed contextual tag row must contain a tag identity")
            matched_ids = item.get("matched_seed_source_item_ids")
            if not isinstance(matched_ids, list):
                raise TypeError("streamed contextual tag row must list matched seed IDs")
            matched_anchor = tag_identity in anchor_targets and bool(set(matched_ids) & anchor_ids)
            if matched_anchor:
                item["matched_seed_source_item_ids"] = tuple(str(value) for value in matched_ids)
                representative_context[tag_identity] = ContextualArtistTag.model_validate(item)
    extractor_settings = SeedTargetExtractorSettings()
    compact = MusicBrainzSeedTargetArtifact(
        seed_input_sha256=declared["seed_input_sha256"],
        seed_source_id=declared["seed_source_id"],
        seed_source_content_sha256=declared["seed_source_content_sha256"],
        seed_count=len(coverage),
        archive_sha256=declared["archive_sha256"],
        settings=extractor_settings,
        settings_sha256=settings_sha256(extractor_settings),
        counters=SeedTargetExtractorCounters(
            archive_member_count=0,
            member_over_limit_count=0,
            malformed_member_path_count=0,
            records_seen=0,
            records_parsed=0,
            records_with_matches=0,
            records_skipped_over_limit=0,
            record_over_limit_count=0,
            malformed_json_count=0,
            malformed_shape_count=0,
            malformed_claim_count=0,
            claim_over_limit_count=0,
            duplicate_claim_count=0,
            evidence_over_limit_count=0,
            contextual_over_limit_count=0,
            positive_evidence_count=len(anchor_by_seed),
            contextual_tag_count=len(representative_context),
        ),
        coverage=tuple(coverage),
        evidence=tuple(anchor_by_seed.values()),
        contextual_tags=tuple(representative_context.values()),
        output_sha256="0" * 64,
    )
    compact = compact.model_copy(update={"output_sha256": artifact_sha256(compact)})
    return compact, declared["output_sha256"], _file_sha256(path)


def build_open_label_graph_model_from_path(
    source_path: Path,
    reconciliation: SeedReconciliationArtifact,
    settings: OpenLabelGraphSettings | None = None,
) -> OpenLabelGraphArtifact:
    """Stream a large source artifact into bounded graph state before fitting."""
    compact, declared_output_sha, file_sha = _stream_compact_source(source_path, reconciliation)
    artifact = build_open_label_graph_model(compact, reconciliation, settings)
    preliminary = artifact.model_copy(
        update={
            "seed_target_output_sha256": declared_output_sha,
            "seed_target_file_sha256": file_sha,
            "input_sha256": _sha(
                {
                    "declared_source_output_sha256": declared_output_sha,
                    "source_file_sha256": file_sha,
                    "reconciliation_output_sha256": reconciliation.output_sha256,
                }
            ),
            "output_sha256": "0" * 64,
        }
    )
    return preliminary.model_copy(
        update={
            "output_sha256": _sha(preliminary.model_dump(mode="json", exclude={"output_sha256"}))
        }
    )


def verify_open_label_graph_model(artifact: OpenLabelGraphArtifact) -> OpenLabelGraphGate:
    """Verify replayable hashes and declare the model's construction guarantees."""
    if artifact.settings_sha256 != _sha(
        artifact.settings.model_dump(mode="json")
    ) or artifact.output_sha256 != _sha(
        artifact.model_dump(mode="json", exclude={"output_sha256"})
    ):
        raise ValueError("open label graph artifact hash does not replay")
    return OpenLabelGraphGate(artifact_output_sha256=artifact.output_sha256)


def publish_open_label_graph_model(
    artifact: OpenLabelGraphArtifact, *, output_path: Path, store: ObjectStore
) -> tuple[OpenLabelGraphReceipt, ObjectWrite]:
    """Atomically write and custody one verified review-layer artifact."""
    gate = verify_open_label_graph_model(artifact)
    payload = (artifact.model_dump_json(indent=2) + "\n").encode()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.", dir=output_path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(output_path)
    finally:
        temporary.unlink(missing_ok=True)
    artifact_sha = hashlib.sha256(payload).hexdigest()
    key = ObjectKey(
        value=f"open-label-graph-model/sha256/{artifact.output_sha256}/{artifact_sha}.json"
    )
    write = store.push(output_path, key)
    if write.sha256 != artifact_sha:
        raise ValueError("object store write does not match open label graph artifact")
    return OpenLabelGraphReceipt(
        artifact_sha256=artifact_sha,
        artifact_byte_size=len(payload),
        object_key=key.value,
        logical_output_sha256=artifact.output_sha256,
        gate=gate,
    ), write
