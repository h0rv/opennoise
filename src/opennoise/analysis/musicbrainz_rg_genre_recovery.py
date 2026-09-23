"""Local feasibility holdout for exact MusicBrainz release-group genre labels.

Uses the retained 10,000-record source-bound sample, not the unindexed 3.2 GB
support database. Community tags are never converted into target labels.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from opennoise.ingest.musicbrainz.release_group_native_artist_support import (
    NativeReleaseGroupFact,
    ReleaseGroupNativeArtistSupportReport,
    verify_release_group_native_artist_support,
)
from opennoise.taxonomy.seeds.universe import normalize_label

_HOLDOUT_MODULUS: Final = 5
_SEED_COUNT: Final = 6_291
_RECONCILIATION_SHA256: Final = "a9db9fb5d7a8dc1fdeae8e311b7e1d4556d98947a7d600ef4c331a86eba5bef0"

if TYPE_CHECKING:
    from pathlib import Path


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class RecoveryMetric(_FrozenModel):
    """Top-one correctness with coverage and abstention denominators."""

    correct: int = Field(ge=0)
    scoreable_denominator: int = Field(ge=0)
    target_group_denominator: int = Field(ge=0)
    abstentions: int = Field(ge=0)
    accuracy: float = Field(ge=0.0, le=1.0)
    coverage_adjusted_accuracy: float = Field(ge=0.0, le=1.0)


class MusicBrainzRgGenreRecoveryReport(_FrozenModel):
    """Deterministic local-only scorecard with its bounded denominator."""

    revision: Literal["musicbrainz-rg-genre-recovery-feasibility-v1"] = (
        "musicbrainz-rg-genre-recovery-feasibility-v1"
    )
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    model_input_allowed: Literal[False] = False
    population_quality_claimed: Literal[False] = False
    target_definition: str = (
        "positive native proper-genre name, exact normalized match to seed vocabulary"
    )
    tag_evidence_used: bool = False
    source_archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    native_sample_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reconciliation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    holdout_rule: str
    source_sample_group_count: int = Field(ge=0)
    labeled_group_count: int = Field(ge=0)
    heldout_labeled_group_count: int = Field(ge=0)
    heldout_seed_label_pair_count: int = Field(ge=0)
    train_labeled_group_count: int = Field(ge=0)
    train_seed_label_count: int = Field(ge=0)
    heldout_seed_label_count: int = Field(ge=0)
    heldout_seed_labels_without_train_support: int = Field(ge=0)
    artist_transfer_macro_recall_by_seed: float = Field(ge=0.0, le=1.0)
    train_popularity_macro_recall_by_seed: float = Field(ge=0.0, le=1.0)
    warm_artist_group_count: int = Field(ge=0)
    cold_artist_group_count: int = Field(ge=0)
    artist_transfer_top1: RecoveryMetric
    train_popularity_top1: RecoveryMetric
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class _HoldoutScore:
    transfer_correct: int
    transfer_abstentions: int
    popularity_correct: int
    warm_groups: int
    label_pairs: int
    label_count: int
    labels_without_train_support: int
    train_label_count: int
    transfer_macro_recall: float
    popularity_macro_recall: float


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _finish(payload: dict[str, object]) -> MusicBrainzRgGenreRecoveryReport:
    complete: dict[str, object] = {
        "revision": "musicbrainz-rg-genre-recovery-feasibility-v1",
        "local_only": True,
        "export_allowed": False,
        "serving_allowed": False,
        "model_input_allowed": False,
        "population_quality_claimed": False,
        "target_definition": (
            "positive native proper-genre name, exact normalized match to seed vocabulary"
        ),
        "tag_evidence_used": False,
        **payload,
    }
    placeholder = MusicBrainzRgGenreRecoveryReport.model_validate(
        {**complete, "output_sha256": "0" * 64}
    )
    output_sha256 = hashlib.sha256(
        _canonical(placeholder.model_dump(mode="json", exclude={"output_sha256"}))
    ).hexdigest()
    serialized = placeholder.model_dump(mode="json")
    serialized["output_sha256"] = output_sha256
    return MusicBrainzRgGenreRecoveryReport.model_validate(serialized)


def _heldout(group_id: str) -> bool:
    bucket = int.from_bytes(hashlib.sha256(group_id.encode()).digest()[:8], "big")
    return bucket % _HOLDOUT_MODULUS == 0


def _native_seed_labels(fact: NativeReleaseGroupFact, seed_names: set[str]) -> frozenset[str]:
    """Return only positive proper-genre labels; tags are a separate field/type."""
    return frozenset(
        normalize_label(genre.name)
        for genre in fact.proper_genres
        if genre.vote_count is not None
        and genre.vote_count > 0
        and normalize_label(genre.name) in seed_names
    )


def _partition_groups[T](
    groups: dict[str, T],
) -> tuple[dict[str, T], dict[str, T]]:
    """Partition exact group IDs once so no release group enters both sides."""
    train = {key: row for key, row in groups.items() if not _heldout(key)}
    test = {key: row for key, row in groups.items() if _heldout(key)}
    return train, test


def _score_holdout(
    train: dict[str, tuple[frozenset[str], frozenset[str]]],
    test: dict[str, tuple[frozenset[str], frozenset[str]]],
) -> _HoldoutScore:
    """Fit on train group-label pairs and score each disjoint test group once."""
    if train.keys() & test.keys():
        raise ValueError("a release-group ID occurs in both train and test")
    artist_labels: dict[str, Counter[str]] = defaultdict(Counter)
    popularity: Counter[str] = Counter()
    for labels, artists in train.values():
        popularity.update(labels)
        for artist in artists:
            artist_labels[artist].update(labels)
    popular_label = popularity.most_common(1)[0][0] if popularity else None

    transfer_correct = transfer_abstentions = popularity_correct = label_pairs = 0
    test_label_groups: Counter[str] = Counter()
    transfer_label_hits: Counter[str] = Counter()
    popularity_label_hits: Counter[str] = Counter()
    for labels, artists in test.values():
        label_pairs += len(labels)
        test_label_groups.update(labels)
        votes: Counter[str] = Counter()
        for artist in artists:
            votes.update(artist_labels.get(artist, {}))
        prediction = min(votes, key=lambda label: (-votes[label], label)) if votes else None
        if prediction is None:
            transfer_abstentions += 1
        elif prediction in labels:
            transfer_correct += 1
            transfer_label_hits[prediction] += 1
        if popular_label is not None and popular_label in labels:
            popularity_correct += 1
            popularity_label_hits[popular_label] += 1
    label_count = len(test_label_groups)

    def macro_recall(hits: Counter[str]) -> float:
        return (
            sum(hits[label] / count for label, count in test_label_groups.items()) / label_count
            if label_count
            else 0.0
        )

    return _HoldoutScore(
        transfer_correct=transfer_correct,
        transfer_abstentions=transfer_abstentions,
        popularity_correct=popularity_correct,
        warm_groups=len(test) - transfer_abstentions,
        label_pairs=label_pairs,
        label_count=label_count,
        labels_without_train_support=sum(label not in popularity for label in test_label_groups),
        train_label_count=len(popularity),
        transfer_macro_recall=macro_recall(transfer_label_hits),
        popularity_macro_recall=macro_recall(popularity_label_hits),
    )


def evaluate_musicbrainz_rg_genre_recovery(
    *, native_artist_support_path: Path, seed_reconciliation_path: Path
) -> MusicBrainzRgGenreRecoveryReport:
    """Compare warm-artist transfer and train-only popularity on held-out RG IDs."""
    sample_bytes = native_artist_support_path.read_bytes()
    sample = ReleaseGroupNativeArtistSupportReport.model_validate_json(sample_bytes)
    verify_release_group_native_artist_support(sample)
    reconciliation_bytes = seed_reconciliation_path.read_bytes()
    reconciliation_hash = hashlib.sha256(reconciliation_bytes).hexdigest()
    if reconciliation_hash != _RECONCILIATION_SHA256:
        raise ValueError("seed reconciliation does not match the pinned 6,291-name scope")
    reconciliation = json.loads(reconciliation_bytes)
    dispositions = reconciliation.get("dispositions")
    if not isinstance(dispositions, list):
        raise TypeError("seed reconciliation has no dispositions")
    seed_names = {
        normalize_label(item["normalized_name"])
        for item in dispositions
        if isinstance(item, dict) and isinstance(item.get("normalized_name"), str)
    }
    if len(seed_names) != _SEED_COUNT:
        raise ValueError("seed reconciliation does not contain the fixed 6,291-name scope")

    # Only positive proper genres with an exact normalized seed-name match qualify.
    groups: dict[str, tuple[frozenset[str], frozenset[str]]] = {}
    for fact in sample.release_group_facts:
        labels = _native_seed_labels(fact, seed_names)
        if labels:
            groups[fact.release_group_mbid] = (
                labels,
                frozenset(credit.artist_mbid for credit in fact.artist_credit),
            )

    train, test = _partition_groups(groups)
    score = _score_holdout(train, test)
    denominator = len(test)

    def metric(
        correct: int, scoreable_denominator: int, abstentions: int
    ) -> dict[str, int | float]:
        return {
            "correct": correct,
            "scoreable_denominator": scoreable_denominator,
            "target_group_denominator": denominator,
            "abstentions": abstentions,
            "accuracy": correct / scoreable_denominator if scoreable_denominator else 0.0,
            "coverage_adjusted_accuracy": correct / denominator if denominator else 0.0,
        }

    return _finish(
        {
            "source_archive_sha256": sample.source_archive_sha256,
            "native_sample_report_sha256": hashlib.sha256(sample_bytes).hexdigest(),
            "reconciliation_sha256": reconciliation_hash,
            "holdout_rule": (
                "sha256(release_group_mbid) first_u64 modulo 5 equals 0; whole release "
                "groups held out; artists may overlap by design for transfer"
            ),
            "source_sample_group_count": len(sample.release_group_facts),
            "labeled_group_count": len(groups),
            "heldout_labeled_group_count": denominator,
            "heldout_seed_label_pair_count": score.label_pairs,
            "train_labeled_group_count": len(train),
            "train_seed_label_count": score.train_label_count,
            "heldout_seed_label_count": score.label_count,
            "heldout_seed_labels_without_train_support": score.labels_without_train_support,
            "artist_transfer_macro_recall_by_seed": score.transfer_macro_recall,
            "train_popularity_macro_recall_by_seed": score.popularity_macro_recall,
            "warm_artist_group_count": score.warm_groups,
            "cold_artist_group_count": score.transfer_abstentions,
            "artist_transfer_top1": metric(
                score.transfer_correct, score.warm_groups, score.transfer_abstentions
            ),
            "train_popularity_top1": metric(score.popularity_correct, denominator, 0),
            "output_sha256": "0" * 64,
        }
    )
