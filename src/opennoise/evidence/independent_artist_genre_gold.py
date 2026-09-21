"""Sealed evaluation of independently sourced artist--genre judgments.

This module deliberately has no dependency on construction evidence, historical
Every Noise material, or model artifacts.  Callers supply a narrow prediction
file after a gold set is sealed; labels are parsed and custodied before any
prediction is read.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import TYPE_CHECKING, Literal

from pydantic import Field, FiniteFloat, model_validator

from opennoise.models import FrozenModel

if TYPE_CHECKING:
    from pathlib import Path

from opennoise.types import Sha256  # noqa: TC001 - Pydantic resolves this field at runtime.

type GoldSourceKind = Literal[
    "fma_metadata_with_reviewed_identity_bridge", "other_independent_open_record", "fixture_only"
]

_REVISION: Literal["independent-artist-genre-gold-v1"] = "independent-artist-genre-gold-v1"
_SPLIT_BUCKETS = 20
_MIN_PRODUCTION_JUDGMENTS = 500
_FORBIDDEN_PROVENANCE = frozenset(
    {"every_noise", "musicbrainz", "wikidata", "listenbrainz", "model_prediction"}
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    )


def _sha256(value: object) -> Sha256:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _file_sha256(path: Path) -> Sha256:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _bucket(judgment_id: str) -> int:
    return int(hashlib.sha256(judgment_id.encode()).hexdigest(), 16) % _SPLIT_BUCKETS


class SourceCustody(FrozenModel):
    """A pinned, independently governed label source and its acquisition record."""

    source_kind: GoldSourceKind
    source_locator: str = Field(min_length=1, max_length=1_000)
    source_version: str = Field(min_length=1, max_length=200)
    source_payload_sha256: Sha256
    license_or_terms_ref: str = Field(min_length=1, max_length=1_000)
    identity_bridge_kind: Literal["reviewed_exact_external_id", "not_applicable_fixture"]
    identity_bridge_sha256: Sha256
    judgment_method: Literal["reviewed_artist_pair_from_independent_track_context", "fixture_only"]
    excluded_provenance: tuple[str, ...]

    @model_validator(mode="after")
    def require_independent_provenance(self) -> SourceCustody:
        """Reject inputs originating in construction, historical, or model data."""
        if not _FORBIDDEN_PROVENANCE.issubset(self.excluded_provenance):
            raise ValueError(
                "source custody must exclude all construction and historical provenance"
            )
        if self.source_kind == "fma_metadata_with_reviewed_identity_bridge":
            if self.identity_bridge_kind != "reviewed_exact_external_id":
                raise ValueError("FMA labels require a reviewed exact external-ID bridge")
            if self.judgment_method != "reviewed_artist_pair_from_independent_track_context":
                raise ValueError(
                    "FMA track tags cannot automatically become artist membership labels"
                )
        elif self.identity_bridge_kind != "not_applicable_fixture":
            raise ValueError("only the FMA workflow currently admits an identity bridge")
        elif self.judgment_method != "fixture_only":
            raise ValueError("fixture source custody requires the fixture-only judgment method")
        return self


class GoldSplit(FrozenModel):
    """Versioned, immutable split that is fixed before predictions are supplied."""

    revision: Literal["sha256-judgment-id-modulo-20-v1"] = "sha256-judgment-id-modulo-20-v1"
    evaluation_buckets: tuple[int, ...] = Field(min_length=1, max_length=_SPLIT_BUCKETS)
    training_buckets: tuple[int, ...] = Field(min_length=1, max_length=_SPLIT_BUCKETS)

    @model_validator(mode="after")
    def require_partition(self) -> GoldSplit:
        """Require a fixed complete partition before evaluating predictions."""
        evaluation = set(self.evaluation_buckets)
        training = set(self.training_buckets)
        universe = set(range(_SPLIT_BUCKETS))
        if evaluation & training or evaluation | training != universe:
            raise ValueError("split buckets must be a complete disjoint partition")
        if len(evaluation) != len(self.evaluation_buckets) or len(training) != len(
            self.training_buckets
        ):
            raise ValueError("split buckets must be unique")
        return self


class GoldJudgment(FrozenModel):
    """One source-cited binary decision; it is never inferred from a prediction."""

    judgment_id: str = Field(min_length=1, max_length=200)
    artist_external_id: str = Field(min_length=1, max_length=300)
    genre_external_id: str = Field(min_length=1, max_length=300)
    expected_member: bool
    source_record_sha256: Sha256
    split_bucket: int = Field(ge=0, lt=_SPLIT_BUCKETS)

    @model_validator(mode="after")
    def require_stable_split(self) -> GoldJudgment:
        """Bind the row to its deterministic split bucket."""
        if self.split_bucket != _bucket(self.judgment_id):
            raise ValueError("judgment split bucket does not match stable identifier hash")
        return self


class IndependentArtistGenreGoldSet(FrozenModel):
    """The only input accepted by the independent-gold evaluator."""

    revision: Literal["independent-artist-genre-gold-v1"] = _REVISION
    purpose: Literal["independent_artist_genre_quality_evaluation"]
    independent_public_gold_labels: bool
    production_threshold_claimed: Literal[False] = False
    threshold_policy_accepted: Literal[False] = False
    source_custody: SourceCustody
    split: GoldSplit
    judgments: tuple[GoldJudgment, ...] = Field(min_length=1, max_length=50_000)

    @model_validator(mode="after")
    def require_sealed_evaluation_slice(self) -> IndependentArtistGenreGoldSet:
        """Ensure this document is a held-out, independent or explicit fixture slice."""
        ids = tuple(row.judgment_id for row in self.judgments)
        if len(ids) != len(set(ids)):
            raise ValueError("judgment identifiers must be unique")
        evaluation = set(self.split.evaluation_buckets)
        if any(row.split_bucket not in evaluation for row in self.judgments):
            raise ValueError("gold document must contain evaluation buckets only")
        if self.independent_public_gold_labels != (
            self.source_custody.source_kind != "fixture_only"
        ):
            raise ValueError("fixture-only sources cannot claim independent public gold labels")
        return self


class Prediction(FrozenModel):
    """A model output claim supplied only after the gold set is loaded."""

    artist_external_id: str = Field(min_length=1, max_length=300)
    genre_external_id: str = Field(min_length=1, max_length=300)
    predicted_member: bool


class PredictionSet(FrozenModel):
    """Predictions evaluated against a separately loaded gold set."""

    revision: Literal["artist-genre-predictions-v1"] = "artist-genre-predictions-v1"
    predictions: tuple[Prediction, ...] = Field(max_length=250_000)

    @model_validator(mode="after")
    def require_unique_pairs(self) -> PredictionSet:
        """Reject ambiguous repeated output claims."""
        pairs = tuple((row.artist_external_id, row.genre_external_id) for row in self.predictions)
        if len(pairs) != len(set(pairs)):
            raise ValueError("predictions must not contain duplicate artist/genre pairs")
        return self


class IndependentGoldReport(FrozenModel):
    """Hash-bound scorecard with an explicit production eligibility result."""

    revision: Literal["independent-artist-genre-gold-evaluation-v1"] = (
        "independent-artist-genre-gold-evaluation-v1"
    )
    gold_file_sha256: Sha256
    gold_records_sha256: Sha256
    prediction_file_sha256: Sha256
    evaluation_sha256: Sha256
    judgment_count: int = Field(ge=0)
    true_positive: int = Field(ge=0)
    false_positive: int = Field(ge=0)
    false_negative: int = Field(ge=0)
    true_negative: int = Field(ge=0)
    precision: FiniteFloat = Field(ge=0.0, le=1.0)
    recall: FiniteFloat = Field(ge=0.0, le=1.0)
    f1: FiniteFloat = Field(ge=0.0, le=1.0)
    independently_sourced: bool
    production_threshold_met: bool
    release_quality_eligible: bool
    failures: tuple[str, ...]


def load_gold_set(path: Path) -> tuple[IndependentArtistGenreGoldSet, Sha256]:
    """Parse and byte-bind a gold document before any model output is considered."""
    gold = IndependentArtistGenreGoldSet.model_validate_json(path.read_text(encoding="utf-8"))
    return gold, _file_sha256(path)


def load_prediction_set(path: Path) -> tuple[PredictionSet, Sha256]:
    """Parse and byte-bind prediction claims without consulting the gold labels."""
    predictions = PredictionSet.model_validate_json(path.read_text(encoding="utf-8"))
    return predictions, _file_sha256(path)


def evaluate_independent_gold(
    gold: IndependentArtistGenreGoldSet,
    predictions: PredictionSet,
    *,
    gold_file_sha256: Sha256,
    prediction_file_sha256: Sha256,
) -> IndependentGoldReport:
    """Evaluate fixed gold labels with no fallback, inference, or source access."""
    indexed = {
        (row.artist_external_id, row.genre_external_id): row.predicted_member
        for row in predictions.predictions
    }
    counts: dict[str, int] = defaultdict(
        int,
        true_positive=0,
        false_positive=0,
        false_negative=0,
        true_negative=0,
    )
    for row in gold.judgments:
        predicted = indexed.get((row.artist_external_id, row.genre_external_id), False)
        if predicted and row.expected_member:
            counts["true_positive"] += 1
        elif predicted:
            counts["false_positive"] += 1
        elif row.expected_member:
            counts["false_negative"] += 1
        else:
            counts["true_negative"] += 1
    positive_predictions = counts["true_positive"] + counts["false_positive"]
    positives = counts["true_positive"] + counts["false_negative"]
    precision = counts["true_positive"] / positive_predictions if positive_predictions else 0.0
    recall = counts["true_positive"] / positives if positives else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    independently_sourced = gold.independent_public_gold_labels
    threshold_met = False
    failures: list[str] = []
    if not independently_sourced:
        failures.append("gold labels are fixture-only, not independently sourced")
    if len(gold.judgments) < _MIN_PRODUCTION_JUDGMENTS:
        failures.append(f"gold set has fewer than {_MIN_PRODUCTION_JUDGMENTS} judgments")
    failures.append(
        "production threshold policy is intentionally unaccepted: "
        "FMA missing tags are not negatives"
    )
    payload = {
        "revision": _REVISION,
        "gold_file_sha256": gold_file_sha256,
        "gold_records_sha256": _sha256([row.model_dump(mode="json") for row in gold.judgments]),
        "prediction_file_sha256": prediction_file_sha256,
        "counts": dict(sorted(counts.items())),
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }
    return IndependentGoldReport(
        gold_file_sha256=gold_file_sha256,
        gold_records_sha256=payload["gold_records_sha256"],
        prediction_file_sha256=prediction_file_sha256,
        evaluation_sha256=_sha256(payload),
        judgment_count=len(gold.judgments),
        true_positive=counts["true_positive"],
        false_positive=counts["false_positive"],
        false_negative=counts["false_negative"],
        true_negative=counts["true_negative"],
        precision=precision,
        recall=recall,
        f1=f1,
        independently_sourced=independently_sourced,
        production_threshold_met=threshold_met,
        release_quality_eligible=threshold_met and not failures,
        failures=tuple(failures),
    )
