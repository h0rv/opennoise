"""Transparent learned tag-label alignment candidates for unresolved genre seeds.

This is a review-only experiment. It learns from exact or normalized
MusicBrainz tag identities observed in the full seed-target artifact, never
creates an observed identity or artist membership, and never reads historical
inputs.
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

import numpy as np
from pydantic import Field, model_validator
from scipy.optimize import minimize

from opennoise.ingest.musicbrainz.seed_targets import (
    MusicBrainzSeedTargetArtifact,
    verify_seed_target_artifact,
)
from opennoise.models import FrozenModel
from opennoise.storage import ObjectKey, ObjectStore, ObjectWrite
from opennoise.taxonomy.seeds.reconciliation import (
    SeedReconciliationArtifact,
    verify_seed_reconciliation,
)

_REVISION: Final = "learned-label-alignment-v1"
_SHA256: Final = r"^[0-9a-f]{64}$"
_TOKEN: Final = re.compile(r"[\w]+", re.UNICODE)
_NGRAM_SIZE: Final = 3
_BINARY_CLASS_COUNT: Final = 2

type AlignmentDisposition = Literal["review_candidate", "abstained"]
type AbstentionReason = Literal[
    "no_contextual_tag_vocabulary",
    "no_lexically_plausible_candidate",
    "below_review_threshold",
]


class LearnedLabelAlignmentSettings(FrozenModel):
    """Bounded, deterministic controls for the linear review model."""

    revision: Literal["learned-label-alignment-settings-v1"] = "learned-label-alignment-settings-v1"
    validation_seed_fraction: float = Field(default=0.2, gt=0.0, lt=1.0)
    split_seed: int = Field(default=20260905, ge=0)
    hard_negatives_per_positive: int = Field(default=4, ge=1, le=32)
    candidates_per_unresolved_seed: int = Field(default=20, ge=1, le=100)
    maximum_tag_vocabulary: int = Field(default=200_000, ge=1, le=1_000_000)
    l2_regularization: float = Field(default=1.0, gt=0.0, le=1_000_000)
    maximum_iterations: int = Field(default=200, ge=1, le=2_000)
    review_score_threshold: float = Field(default=0.5, ge=0.0, le=1.0)


class AlignmentFeatureComponents(FrozenModel):
    """Bounded, inspectable score inputs for a seed-to-tag comparison."""

    normalized_token_overlap: float = Field(ge=0.0, le=1.0)
    character_ngram_cosine: float = Field(ge=0.0, le=1.0)
    head_modifier_relation: float = Field(ge=0.0, le=1.0)
    normalized_tag_support: float = Field(ge=0.0, le=1.0)
    contextual_tag_overlap: float = Field(ge=0.0, le=1.0)


class AlignmentCoefficient(FrozenModel):
    """One learned coefficient named after its transparent feature."""

    feature_name: Literal[
        "intercept",
        "normalized_token_overlap",
        "character_ngram_cosine",
        "head_modifier_relation",
        "normalized_tag_support",
        "contextual_tag_overlap",
    ]
    value: float = Field(allow_inf_nan=False)


class AlignmentSplitMetrics(FrozenModel):
    """Per split label accounting and thresholded review behavior."""

    seed_count: int = Field(ge=0)
    positive_count: int = Field(ge=0)
    hard_negative_count: int = Field(ge=0)
    average_log_loss: float | None = Field(default=None, ge=0.0)
    review_prediction_count: int = Field(ge=0)
    review_precision: float | None = Field(default=None, ge=0.0, le=1.0)
    review_positive_recall: float | None = Field(default=None, ge=0.0, le=1.0)


class LearnedAlignmentCandidate(FrozenModel):
    """A score for review, explicitly not an observed identity claim."""

    source_item_id: str = Field(min_length=1, max_length=200)
    seed_name: str = Field(min_length=1, max_length=500)
    tag_identity: str = Field(min_length=1, max_length=500)
    tag_name: str = Field(min_length=1, max_length=500)
    score: float = Field(ge=0.0, le=1.0)
    components: AlignmentFeatureComponents
    direct_tag_artist_count: int = Field(ge=0)
    contextual_tag_artist_count: int = Field(ge=0)
    evidence_refs: tuple[str, ...] = Field(max_length=32)
    disposition: Literal["review_candidate"] = "review_candidate"


class LearnedAlignmentAbstention(FrozenModel):
    """One unresolved seed with no candidate promoted for review."""

    source_item_id: str = Field(min_length=1, max_length=200)
    seed_name: str = Field(min_length=1, max_length=500)
    reason: AbstentionReason
    best_score: float | None = Field(default=None, ge=0.0, le=1.0)


class LearnedLabelAlignmentCoverage(FrozenModel):
    """Coverage is explicit: candidate rows plus abstentions cover unresolved seeds."""

    seed_count: int = Field(ge=1)
    known_supervision_seed_count: int = Field(ge=0)
    positive_supervision_count: int = Field(ge=0)
    hard_negative_count: int = Field(ge=0)
    train_seed_count: int = Field(ge=0)
    validation_seed_count: int = Field(ge=0)
    reconciliation_unresolved_seed_count: int = Field(ge=0)
    observed_tag_anchor_seed_count: int = Field(ge=0)
    unresolved_seed_count: int = Field(ge=0)
    unresolved_seed_with_review_candidate_count: int = Field(ge=0)
    unresolved_seed_abstention_count: int = Field(ge=0)
    contextual_tag_vocabulary_count: int = Field(ge=0)
    historical_inputs_read: Literal[False] = False
    observed_identities_created: Literal[False] = False
    memberships_created: Literal[False] = False

    @model_validator(mode="after")
    def _account_unresolved(self) -> LearnedLabelAlignmentCoverage:
        if (
            self.unresolved_seed_with_review_candidate_count + self.unresolved_seed_abstention_count
            != self.unresolved_seed_count
        ):
            raise ValueError("review candidates and abstentions must account for unresolved seeds")
        return self


class LearnedLabelAlignmentArtifact(FrozenModel):
    """A sealed learned alignment experiment with review-only output."""

    revision: Literal["learned-label-alignment-v1"] = _REVISION
    seed_target_output_sha256: str = Field(pattern=_SHA256)
    seed_reconciliation_output_sha256: str = Field(pattern=_SHA256)
    target_seed_input_sha256: str = Field(pattern=_SHA256)
    reconciliation_seed_input_sha256: str = Field(pattern=_SHA256)
    seed_source_id: str = Field(min_length=1)
    seed_source_content_sha256: str = Field(pattern=_SHA256)
    seed_identity_fingerprint: str = Field(pattern=_SHA256)
    settings: LearnedLabelAlignmentSettings
    settings_sha256: str = Field(pattern=_SHA256)
    input_sha256: str = Field(pattern=_SHA256)
    vocabulary_sha256: str = Field(pattern=_SHA256)
    coefficients: tuple[AlignmentCoefficient, ...] = Field(min_length=6, max_length=6)
    train_metrics: AlignmentSplitMetrics
    validation_metrics: AlignmentSplitMetrics
    candidates: tuple[LearnedAlignmentCandidate, ...]
    abstentions: tuple[LearnedAlignmentAbstention, ...]
    coverage: LearnedLabelAlignmentCoverage
    historical_inputs_read: Literal[False] = False
    output_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _complete(self) -> LearnedLabelAlignmentArtifact:
        candidate_seeds = {row.source_item_id for row in self.candidates}
        abstention_seeds = {row.source_item_id for row in self.abstentions}
        if candidate_seeds & abstention_seeds:
            raise ValueError("an unresolved seed cannot be both a candidate and an abstention")
        if len(candidate_seeds) != self.coverage.unresolved_seed_with_review_candidate_count:
            raise ValueError("review candidate seed coverage does not match candidates")
        if len(abstention_seeds) != self.coverage.unresolved_seed_abstention_count:
            raise ValueError("abstention seed coverage does not match abstentions")
        return self


class LearnedLabelAlignmentGate(FrozenModel):
    """Fail-closed custody gate for review-only learned candidates."""

    artifact_output_sha256: str = Field(pattern=_SHA256)
    deterministic_replay: Literal[True] = True
    stable_seed_validation_split: Literal[True] = True
    historical_data_prohibited: Literal[True] = True
    review_only_candidates: Literal[True] = True
    no_observed_identities_or_memberships: Literal[True] = True


class LearnedLabelAlignmentReceipt(FrozenModel):
    """Object-store receipt for a sealed alignment experiment."""

    artifact_sha256: str = Field(pattern=_SHA256)
    artifact_byte_size: int = Field(ge=1)
    object_key: str = Field(min_length=1)
    logical_output_sha256: str = Field(pattern=_SHA256)
    gate: LearnedLabelAlignmentGate


@dataclass(frozen=True, slots=True)
class _TagRecord:
    identity: str
    name: str
    direct_artists: frozenset[str]
    contextual_artists: frozenset[str]
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _LabeledPair:
    seed_id: str
    seed_name: str
    tag: _TagRecord
    label: float
    features: AlignmentFeatureComponents


@dataclass(frozen=True, slots=True)
class _LexicalTagIndex:
    """Deterministic inverted index for bounded, plausible tag retrieval."""

    vocabulary: tuple[_TagRecord, ...]
    by_identity: dict[str, int]
    by_token: dict[str, tuple[int, ...]]
    by_ngram: dict[str, tuple[int, ...]]


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(str(token) for token in _TOKEN.findall(value.casefold()))


def _ngrams(value: str) -> frozenset[str]:
    normalized = " ".join(_tokens(value))
    padded = f"^{normalized}$"
    if len(padded) < _NGRAM_SIZE:
        return frozenset({padded})
    return frozenset(padded[index : index + _NGRAM_SIZE] for index in range(len(padded) - 2))


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _char_cosine(left: str, right: str) -> float:
    left_grams, right_grams = _ngrams(left), _ngrams(right)
    if not left_grams or not right_grams:
        return 0.0
    return len(left_grams & right_grams) / math.sqrt(len(left_grams) * len(right_grams))


def _head_modifier_relation(seed_name: str, tag_name: str) -> float:
    seed_tokens, tag_tokens = _tokens(seed_name), _tokens(tag_name)
    if not seed_tokens or not tag_tokens:
        return 0.0
    head_score = 0.5 if seed_tokens[-1] == tag_tokens[-1] else 0.0
    return head_score + 0.5 * _jaccard(frozenset(seed_tokens[:-1]), frozenset(tag_tokens[:-1]))


def _stable_validation_seed(seed_id: str, settings: LearnedLabelAlignmentSettings) -> bool:
    digest = hashlib.sha256(f"{settings.split_seed}\0{seed_id}".encode()).digest()
    value = int.from_bytes(digest[:8], "big") / 2**64
    return value < settings.validation_seed_fraction


def _build_tag_vocabulary(
    source: MusicBrainzSeedTargetArtifact, settings: LearnedLabelAlignmentSettings
) -> tuple[_TagRecord, ...]:
    direct_artists: dict[str, set[str]] = defaultdict(set)
    contextual_artists: dict[str, set[str]] = defaultdict(set)
    names: dict[str, str] = {}
    refs: dict[str, set[str]] = defaultdict(set)
    for evidence in source.evidence:
        if evidence.facet == "tag":
            direct_artists[evidence.target_identity].add(evidence.artist_id)
            names[evidence.target_identity] = evidence.target_name
            refs[evidence.target_identity].add(evidence.evidence_ref)
    for row in source.contextual_tags:
        contextual_artists[row.tag_identity].add(row.artist_id)
        names[row.tag_identity] = row.tag_name
        refs[row.tag_identity].add(row.evidence_ref)
    identities = tuple(sorted(names))
    if len(identities) > settings.maximum_tag_vocabulary:
        raise ValueError("contextual tag vocabulary exceeds configured bound")
    return tuple(
        _TagRecord(
            identity=identity,
            name=names[identity],
            direct_artists=frozenset(direct_artists[identity]),
            contextual_artists=frozenset(contextual_artists[identity]),
            evidence_refs=tuple(sorted(refs[identity])[:32]),
        )
        for identity in identities
    )


def _seed_contexts(source: MusicBrainzSeedTargetArtifact) -> dict[str, frozenset[str]]:
    contexts: dict[str, set[str]] = defaultdict(set)
    for row in source.contextual_tags:
        for seed_id in row.matched_seed_source_item_ids:
            contexts[seed_id].add(row.tag_identity)
    return {seed_id: frozenset(tags) for seed_id, tags in contexts.items()}


def _features(
    seed_name: str,
    tag: _TagRecord,
    seed_context: frozenset[str],
    largest_support: int,
) -> AlignmentFeatureComponents:
    support = len(tag.direct_artists | tag.contextual_artists)
    normalized_support = (
        math.log1p(support) / math.log1p(largest_support) if largest_support else 0.0
    )
    return AlignmentFeatureComponents(
        normalized_token_overlap=_jaccard(
            frozenset(_tokens(seed_name)), frozenset(_tokens(tag.name))
        ),
        character_ngram_cosine=_char_cosine(seed_name, tag.name),
        head_modifier_relation=_head_modifier_relation(seed_name, tag.name),
        normalized_tag_support=normalized_support,
        contextual_tag_overlap=_jaccard(seed_context, frozenset({tag.identity})),
    )


def _feature_vector(components: AlignmentFeatureComponents) -> np.ndarray:
    return np.array(
        [
            1.0,
            components.normalized_token_overlap,
            components.character_ngram_cosine,
            components.head_modifier_relation,
            components.normalized_tag_support,
            components.contextual_tag_overlap,
        ],
        dtype=np.float64,
    )


def _build_lexical_tag_index(vocabulary: tuple[_TagRecord, ...]) -> _LexicalTagIndex:
    """Index only transparent lexical features used by the review model."""
    token_rows: dict[str, list[int]] = defaultdict(list)
    ngram_rows: dict[str, list[int]] = defaultdict(list)
    for index, tag in enumerate(vocabulary):
        for token in frozenset(_tokens(tag.name)):
            token_rows[token].append(index)
        for ngram in _ngrams(tag.name):
            ngram_rows[ngram].append(index)
    return _LexicalTagIndex(
        vocabulary=vocabulary,
        by_identity={tag.identity: index for index, tag in enumerate(vocabulary)},
        by_token={key: tuple(value) for key, value in token_rows.items()},
        by_ngram={key: tuple(value) for key, value in ngram_rows.items()},
    )


def _rank_tags(
    seed_name: str,
    index: _LexicalTagIndex,
    seed_context: frozenset[str],
    largest_support: int,
) -> tuple[tuple[_TagRecord, AlignmentFeatureComponents], ...]:
    """Rank only tags with lexical or contextual evidence for this seed.

    This avoids a full vocabulary sort for every seed.  The old exhaustive
    rank also treated arbitrary zero-feature tags as "lexically plausible",
    making the abstention state unreachable whenever the vocabulary existed.
    """
    candidate_rows: set[int] = set()
    for token in _tokens(seed_name):
        candidate_rows.update(index.by_token.get(token, ()))
    for ngram in _ngrams(seed_name):
        candidate_rows.update(index.by_ngram.get(ngram, ()))
    for tag_identity in seed_context:
        tag_index = index.by_identity.get(tag_identity)
        if tag_index is not None:
            candidate_rows.add(tag_index)
    return tuple(
        sorted(
            (
                (
                    index.vocabulary[tag_index],
                    _features(
                        seed_name,
                        index.vocabulary[tag_index],
                        seed_context,
                        largest_support,
                    ),
                )
                for tag_index in candidate_rows
            ),
            key=lambda pair: (
                -pair[1].normalized_token_overlap,
                -pair[1].character_ngram_cosine,
                pair[0].identity,
            ),
        )
    )


def _target_seed_identity_fingerprint(source: MusicBrainzSeedTargetArtifact) -> str:
    """Fingerprint stable seed IDs, external IDs, and names independent of wrappers."""
    return _sha(
        [
            {
                "source_item_id": row.seed_source_item_id,
                "source_external_id": row.seed_source_external_id,
                "name": row.seed_name,
            }
            for row in sorted(source.coverage, key=lambda item: item.seed_source_item_id)
        ]
    )


def _reconciliation_seed_identity_fingerprint(reconciliation: SeedReconciliationArtifact) -> str:
    """Fingerprint the reconciliation-side stable seed join universe."""
    return _sha(
        [
            {
                "source_item_id": row.source_item_id,
                "source_external_id": row.source_external_id,
                "name": row.seed_name,
            }
            for row in sorted(reconciliation.dispositions, key=lambda item: item.source_item_id)
        ]
    )


def _observed_tag_pairs(source: MusicBrainzSeedTargetArtifact) -> frozenset[tuple[str, str]]:
    """Return directly observed, lexical tag anchors from the full target corpus."""
    return frozenset(
        (row.seed_source_item_id, row.target_identity)
        for row in source.evidence
        if row.facet == "tag" and row.match_kind in {"exact", "normalized"}
    )


def _verify_seed_binding(
    source: MusicBrainzSeedTargetArtifact, reconciliation: SeedReconciliationArtifact
) -> str:
    """Verify the shared stable seed universe while retaining producer hashes."""
    if source.seed_count != reconciliation.seed_count:
        raise ValueError("seed target and reconciliation seed counts do not match")
    source_ids = {row.seed_source_item_id for row in source.coverage}
    reconciliation_ids = {row.source_item_id for row in reconciliation.dispositions}
    if source_ids != reconciliation_ids:
        raise ValueError("seed target coverage does not bind reconciliation seeds")
    if source.seed_source_id != reconciliation.seed_source_id:
        raise ValueError("seed target and reconciliation source IDs do not match")
    if source.seed_source_content_sha256 != reconciliation.seed_source_content_sha256:
        raise ValueError("seed target and reconciliation source content hashes do not match")
    target_fingerprint = _target_seed_identity_fingerprint(source)
    if target_fingerprint != _reconciliation_seed_identity_fingerprint(reconciliation):
        raise ValueError("seed target and reconciliation seed identities do not match")
    if target_fingerprint != reconciliation.seed_identity_sha256:
        raise ValueError("reconciliation stable seed identity hash does not match seed target")
    return target_fingerprint


def _positive_pairs(
    reconciliation: SeedReconciliationArtifact,
    vocabulary_by_id: dict[str, _TagRecord],
    seed_contexts: dict[str, frozenset[str]],
    largest_support: int,
    observed_tag_pairs: frozenset[tuple[str, str]],
) -> tuple[_LabeledPair, ...]:
    names = {row.source_item_id: row.seed_name for row in reconciliation.dispositions}
    pairs: list[_LabeledPair] = []
    for seed_id, tag_id in sorted(observed_tag_pairs):
        tag = vocabulary_by_id.get(tag_id)
        if tag is None:
            continue
        pairs.append(
            _LabeledPair(
                seed_id=seed_id,
                seed_name=names[seed_id],
                tag=tag,
                label=1.0,
                features=_features(
                    names[seed_id],
                    tag,
                    seed_contexts.get(seed_id, frozenset()),
                    largest_support,
                ),
            )
        )
    return tuple(sorted(pairs, key=lambda pair: (pair.seed_id, pair.tag.identity)))


def _labeled_examples(
    positives: tuple[_LabeledPair, ...],
    index: _LexicalTagIndex,
    seed_contexts: dict[str, frozenset[str]],
    largest_support: int,
    settings: LearnedLabelAlignmentSettings,
) -> tuple[_LabeledPair, ...]:
    known_by_seed: dict[str, set[str]] = defaultdict(set)
    for pair in positives:
        known_by_seed[pair.seed_id].add(pair.tag.identity)
    examples = list(positives)
    for positive in positives:
        ranked = _rank_tags(
            positive.seed_name,
            index,
            seed_contexts.get(positive.seed_id, frozenset()),
            largest_support,
        )
        negatives = tuple(
            (tag, components)
            for tag, components in ranked
            if tag.identity not in known_by_seed[positive.seed_id]
        )[: settings.hard_negatives_per_positive]
        # A tiny vocabulary can have fewer lexical alternatives than the
        # configured hard-negative count.  Complete the requested bounded
        # training set with deterministic zero-lexical candidates, just as an
        # exhaustive rank would after its plausible candidates.  This path is
        # normally irrelevant on the full vocabulary and avoids weakening the
        # negative-accounting contract on small fixtures.
        if len(negatives) < settings.hard_negatives_per_positive:
            selected = {tag.identity for tag, _components in negatives}
            fallback: list[tuple[_TagRecord, AlignmentFeatureComponents]] = []
            for tag in index.vocabulary:
                if tag.identity in known_by_seed[positive.seed_id] or tag.identity in selected:
                    continue
                fallback.append(
                    (
                        tag,
                        _features(
                            positive.seed_name,
                            tag,
                            seed_contexts.get(positive.seed_id, frozenset()),
                            largest_support,
                        ),
                    )
                )
                if len(negatives) + len(fallback) == settings.hard_negatives_per_positive:
                    break
            negatives = negatives + tuple(fallback)
        examples.extend(
            _LabeledPair(
                seed_id=positive.seed_id,
                seed_name=positive.seed_name,
                tag=tag,
                label=0.0,
                features=components,
            )
            for tag, components in negatives
        )
    return tuple(sorted(examples, key=lambda pair: (pair.seed_id, -pair.label, pair.tag.identity)))


def _fit_coefficients(
    examples: tuple[_LabeledPair, ...], settings: LearnedLabelAlignmentSettings
) -> np.ndarray:
    if not examples or len({pair.label for pair in examples}) < _BINARY_CLASS_COUNT:
        return np.zeros(6, dtype=np.float64)
    matrix = np.vstack(tuple(_feature_vector(pair.features) for pair in examples))
    labels = np.array([pair.label for pair in examples], dtype=np.float64)

    def objective(weights: np.ndarray) -> tuple[float, np.ndarray]:
        logits = np.clip(matrix @ weights, -40.0, 40.0)
        probabilities = 1.0 / (1.0 + np.exp(-logits))
        loss = -np.mean(
            labels * np.log(np.clip(probabilities, 1e-12, 1.0))
            + (1.0 - labels) * np.log(np.clip(1.0 - probabilities, 1e-12, 1.0))
        )
        penalty = settings.l2_regularization * float(weights[1:] @ weights[1:]) / 2.0
        gradient = matrix.T @ (probabilities - labels) / len(labels)
        gradient[1:] += settings.l2_regularization * weights[1:]
        return float(loss + penalty), gradient

    result = minimize(
        objective,
        np.zeros(matrix.shape[1], dtype=np.float64),
        jac=True,
        method="L-BFGS-B",
        options={"maxiter": settings.maximum_iterations},
    )
    if (
        not result.success
        or not isinstance(result.x, np.ndarray)
        or not np.all(np.isfinite(result.x))
    ):
        raise ValueError("L2 logistic alignment fit did not converge")
    return result.x


def _score(weights: np.ndarray, components: AlignmentFeatureComponents) -> float:
    return float(
        1.0 / (1.0 + math.exp(-float(np.clip(weights @ _feature_vector(components), -40.0, 40.0))))
    )


def _metrics(
    examples: tuple[_LabeledPair, ...], weights: np.ndarray, threshold: float
) -> AlignmentSplitMetrics:
    seeds = {pair.seed_id for pair in examples}
    positives = sum(pair.label == 1.0 for pair in examples)
    negatives = len(examples) - positives
    if not examples:
        return AlignmentSplitMetrics(
            seed_count=0,
            positive_count=0,
            hard_negative_count=0,
            review_prediction_count=0,
        )
    scores = tuple(_score(weights, pair.features) for pair in examples)
    labels = tuple(pair.label for pair in examples)
    review_indices = tuple(index for index, score in enumerate(scores) if score >= threshold)
    review_true_positive = sum(labels[index] == 1.0 for index in review_indices)
    return AlignmentSplitMetrics(
        seed_count=len(seeds),
        positive_count=positives,
        hard_negative_count=negatives,
        average_log_loss=-sum(
            label * math.log(max(score, 1e-12)) + (1.0 - label) * math.log(max(1.0 - score, 1e-12))
            for label, score in zip(labels, scores, strict=True)
        )
        / len(labels),
        review_prediction_count=len(review_indices),
        review_precision=review_true_positive / len(review_indices) if review_indices else None,
        review_positive_recall=review_true_positive / positives if positives else None,
    )


def build_learned_label_alignment(
    source: MusicBrainzSeedTargetArtifact,
    reconciliation: SeedReconciliationArtifact,
    settings: LearnedLabelAlignmentSettings | None = None,
) -> LearnedLabelAlignmentArtifact:
    """Fit a compact review model and score only unresolved seed-tag candidates."""
    verify_seed_target_artifact(source)
    verify_seed_reconciliation(reconciliation)
    resolved = settings or LearnedLabelAlignmentSettings()
    target_fingerprint = _verify_seed_binding(source, reconciliation)
    vocabulary = _build_tag_vocabulary(source, resolved)
    lexical_index = _build_lexical_tag_index(vocabulary)
    vocabulary_by_id = {tag.identity: tag for tag in vocabulary}
    seed_contexts = _seed_contexts(source)
    observed_tag_pairs = _observed_tag_pairs(source)
    largest_support = max(
        (len(tag.direct_artists | tag.contextual_artists) for tag in vocabulary), default=0
    )
    positives = _positive_pairs(
        reconciliation,
        vocabulary_by_id,
        seed_contexts,
        largest_support,
        observed_tag_pairs,
    )
    examples = _labeled_examples(positives, lexical_index, seed_contexts, largest_support, resolved)
    train_examples = tuple(
        pair for pair in examples if not _stable_validation_seed(pair.seed_id, resolved)
    )
    validation_examples = tuple(
        pair for pair in examples if _stable_validation_seed(pair.seed_id, resolved)
    )
    weights = _fit_coefficients(train_examples, resolved)
    observed_tag_seed_ids = {seed_id for seed_id, _tag_id in observed_tag_pairs}
    reconciliation_unresolved = tuple(
        row for row in reconciliation.dispositions if row.disposition == "unresolved"
    )
    unresolved = tuple(
        row for row in reconciliation_unresolved if row.source_item_id not in observed_tag_seed_ids
    )
    candidates: list[LearnedAlignmentCandidate] = []
    abstentions: list[LearnedAlignmentAbstention] = []
    for row in unresolved:
        if not vocabulary:
            abstentions.append(
                LearnedAlignmentAbstention(
                    source_item_id=row.source_item_id,
                    seed_name=row.seed_name,
                    reason="no_contextual_tag_vocabulary",
                )
            )
            continue
        ranked = _rank_tags(
            row.seed_name,
            lexical_index,
            seed_contexts.get(row.source_item_id, frozenset()),
            largest_support,
        )[: resolved.candidates_per_unresolved_seed]
        if not ranked:
            abstentions.append(
                LearnedAlignmentAbstention(
                    source_item_id=row.source_item_id,
                    seed_name=row.seed_name,
                    reason="no_lexically_plausible_candidate",
                )
            )
            continue
        scored = tuple((tag, components, _score(weights, components)) for tag, components in ranked)
        review_rows = tuple(item for item in scored if item[2] >= resolved.review_score_threshold)
        if not review_rows:
            abstentions.append(
                LearnedAlignmentAbstention(
                    source_item_id=row.source_item_id,
                    seed_name=row.seed_name,
                    reason="below_review_threshold",
                    best_score=scored[0][2],
                )
            )
            continue
        candidates.extend(
            LearnedAlignmentCandidate(
                source_item_id=row.source_item_id,
                seed_name=row.seed_name,
                tag_identity=tag.identity,
                tag_name=tag.name,
                score=score,
                components=components,
                direct_tag_artist_count=len(tag.direct_artists),
                contextual_tag_artist_count=len(tag.contextual_artists),
                evidence_refs=tag.evidence_refs,
            )
            for tag, components, score in review_rows
        )
    coefficients = tuple(
        AlignmentCoefficient(feature_name=name, value=float(value))
        for name, value in zip(
            (
                "intercept",
                "normalized_token_overlap",
                "character_ngram_cosine",
                "head_modifier_relation",
                "normalized_tag_support",
                "contextual_tag_overlap",
            ),
            weights,
            strict=True,
        )
    )
    coverage = LearnedLabelAlignmentCoverage(
        seed_count=reconciliation.seed_count,
        known_supervision_seed_count=len({pair.seed_id for pair in positives}),
        positive_supervision_count=len(positives),
        hard_negative_count=sum(pair.label == 0.0 for pair in examples),
        train_seed_count=len({pair.seed_id for pair in train_examples}),
        validation_seed_count=len({pair.seed_id for pair in validation_examples}),
        reconciliation_unresolved_seed_count=len(reconciliation_unresolved),
        observed_tag_anchor_seed_count=len(observed_tag_seed_ids),
        unresolved_seed_count=len(unresolved),
        unresolved_seed_with_review_candidate_count=len({row.source_item_id for row in candidates}),
        unresolved_seed_abstention_count=len(abstentions),
        contextual_tag_vocabulary_count=len(vocabulary),
    )
    preliminary = LearnedLabelAlignmentArtifact(
        seed_target_output_sha256=source.output_sha256,
        seed_reconciliation_output_sha256=reconciliation.output_sha256,
        target_seed_input_sha256=source.seed_input_sha256,
        reconciliation_seed_input_sha256=reconciliation.seed_input_sha256,
        seed_source_id=source.seed_source_id,
        seed_source_content_sha256=source.seed_source_content_sha256,
        seed_identity_fingerprint=target_fingerprint,
        settings=resolved,
        settings_sha256=_sha(resolved.model_dump(mode="json")),
        input_sha256=_sha(
            {
                "seed_target_output_sha256": source.output_sha256,
                "seed_reconciliation_output_sha256": reconciliation.output_sha256,
                "target_seed_input_sha256": source.seed_input_sha256,
                "reconciliation_seed_input_sha256": reconciliation.seed_input_sha256,
                "seed_identity_fingerprint": target_fingerprint,
            }
        ),
        vocabulary_sha256=_sha(
            tuple(
                (
                    tag.identity,
                    tag.name,
                    tuple(sorted(tag.direct_artists)),
                    tuple(sorted(tag.contextual_artists)),
                    tag.evidence_refs,
                )
                for tag in vocabulary
            )
        ),
        coefficients=coefficients,
        train_metrics=_metrics(train_examples, weights, resolved.review_score_threshold),
        validation_metrics=_metrics(validation_examples, weights, resolved.review_score_threshold),
        candidates=tuple(
            sorted(
                candidates,
                key=lambda candidate: (
                    -candidate.score,
                    candidate.source_item_id,
                    candidate.tag_identity,
                ),
            )
        ),
        abstentions=tuple(sorted(abstentions, key=lambda abstention: abstention.source_item_id)),
        coverage=coverage,
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(
        update={
            "output_sha256": _sha(preliminary.model_dump(mode="json", exclude={"output_sha256"}))
        }
    )


def verify_learned_label_alignment(
    artifact: LearnedLabelAlignmentArtifact,
) -> LearnedLabelAlignmentGate:
    """Replay all hashes and enforce the review-only safety declaration."""
    if artifact.settings_sha256 != _sha(artifact.settings.model_dump(mode="json")):
        raise ValueError("alignment settings hash does not replay")
    if artifact.output_sha256 != _sha(artifact.model_dump(mode="json", exclude={"output_sha256"})):
        raise ValueError("alignment output hash does not replay")
    return LearnedLabelAlignmentGate(artifact_output_sha256=artifact.output_sha256)


def publish_learned_label_alignment(
    artifact: LearnedLabelAlignmentArtifact, *, output_path: Path, store: ObjectStore
) -> tuple[LearnedLabelAlignmentReceipt, ObjectWrite]:
    """Atomically write and publish a verified learned alignment artifact."""
    gate = verify_learned_label_alignment(artifact)
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
    key = ObjectKey(value=f"learned-label-alignment/{artifact.output_sha256}/{artifact_sha}.json")
    write = store.push(output_path, key)
    if write.sha256 != artifact_sha or write.byte_size != len(payload):
        raise ValueError("object store write does not match learned alignment artifact")
    return LearnedLabelAlignmentReceipt(
        artifact_sha256=artifact_sha,
        artifact_byte_size=len(payload),
        object_key=key.value,
        logical_output_sha256=artifact.output_sha256,
        gate=gate,
    ), write
