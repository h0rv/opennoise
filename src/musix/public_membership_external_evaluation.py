"""Local-only, post-seal comparison of a public model with MusicBrainz tags.

This evaluator is deliberately outside every public-model construction and
publication path.  It reads a sealed public serving database and a separate
local MusicBrainz research database in read-only mode, then produces a
deterministic research report.  MusicBrainz tag absence is an *unobserved
noisy reference*, not ground truth and never becomes a model input.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import Field, FiniteFloat, model_validator

from musix.models import FrozenModel
from musix.types import Sha256  # noqa: TC001

if TYPE_CHECKING:
    from pathlib import Path

type ProfileKind = Literal["direct", "one_hop"]
type ErrorKind = Literal["false_positive", "false_negative"]

_REVISION: Literal["public-membership-external-evaluation-v1"] = (
    "public-membership-external-evaluation-v1"
)
_RESEARCH_SOURCE_KEY = "musicbrainz_json_artist_research_20260829"
_THRESHOLDS = (1.0, 3.0, 5.0)
_CALIBRATION_BOUNDS = (0.0, 0.25, 0.5, 0.75, 1.0)
_MAX_ERROR_SAMPLES = 12


def _canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    )


def _sha256(value: object) -> Sha256:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> Sha256:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_name(value: str) -> str:
    """Use only reversible-ish Unicode/case/whitespace normalization, never fuzzy matching."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


class ExternalEvaluationInput(FrozenModel):
    """Hash-addressed inputs and the selected already-published public model."""

    public_database_sha256: Sha256
    musicbrainz_research_database_sha256: Sha256
    public_model_run_id: int = Field(gt=0)
    public_model_output_sha256: Sha256
    public_model_artifact_sha256: Sha256
    public_model_published_at: str = Field(min_length=1)
    musicbrainz_research_source_key: Literal["musicbrainz_json_artist_research_20260829"] = (
        _RESEARCH_SOURCE_KEY
    )


class ProhibitedInputChecks(FrozenModel):
    """Fail-closed assertions proving the research input was not a public input."""

    post_seal_only: Literal[True] = True
    public_database_opened_read_only: Literal[True] = True
    research_database_opened_read_only: Literal[True] = True
    databases_are_distinct: Literal[True] = True
    selected_public_model_is_exportable: Literal[True] = True
    selected_public_model_has_derived_output: Literal[True] = True
    research_source_absent_from_public_database: Literal[True] = True
    public_model_or_release_modified: Literal[False] = False
    research_tags_used_for_construction: Literal[False] = False
    research_tags_used_for_ranking: Literal[False] = False
    research_tags_used_for_layout: Literal[False] = False
    research_tags_used_for_exportable_release: Literal[False] = False


class MatchingCoverage(FrozenModel):
    """Explain exactly which public predictions entered the local comparison."""

    profile_kind: ProfileKind
    public_prediction_count: int = Field(ge=0)
    artist_id_matched_prediction_count: int = Field(ge=0)
    genre_name_matched_prediction_count: int = Field(ge=0)
    evaluated_prediction_count: int = Field(ge=0)
    unmatched_artist_prediction_count: int = Field(ge=0)
    unmatched_genre_prediction_count: int = Field(ge=0)
    ambiguous_genre_prediction_count: int = Field(ge=0)
    reference_positive_pair_count: int = Field(ge=0)
    reference_only_positive_pair_count: int = Field(ge=0)
    reference_only_abstention_rate: FiniteFloat = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def require_prediction_partition(self) -> MatchingCoverage:
        if self.public_prediction_count != (
            self.evaluated_prediction_count
            + self.unmatched_artist_prediction_count
            + self.unmatched_genre_prediction_count
            + self.ambiguous_genre_prediction_count
        ):
            raise ValueError("matching coverage does not partition public predictions")
        if self.artist_id_matched_prediction_count < self.evaluated_prediction_count:
            raise ValueError("evaluated predictions must have exact artist identifiers")
        if self.genre_name_matched_prediction_count < self.evaluated_prediction_count:
            raise ValueError("evaluated predictions must have unambiguous genre matches")
        return self


class BinaryMetrics(FrozenModel):
    """One thresholded confusion matrix over the union of predictions and references."""

    candidate_pair_count: int = Field(ge=0)
    prediction_count: int = Field(ge=0)
    reference_positive_count: int = Field(ge=0)
    true_positive: int = Field(ge=0)
    false_positive: int = Field(ge=0)
    false_negative: int = Field(ge=0)
    true_negative: int = Field(ge=0)
    abstention_count: int = Field(ge=0)
    precision: FiniteFloat = Field(ge=0.0, le=1.0)
    recall: FiniteFloat = Field(ge=0.0, le=1.0)
    f1: FiniteFloat = Field(ge=0.0, le=1.0)
    reference_weight_total: FiniteFloat = Field(ge=0.0)
    true_positive_reference_weight: FiniteFloat = Field(ge=0.0)
    weighted_reference_recall: FiniteFloat = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def require_consistent_counts(self) -> BinaryMetrics:
        if (
            self.candidate_pair_count
            != self.true_positive + self.false_positive + self.false_negative + self.true_negative
        ):
            raise ValueError("confusion matrix does not sum to candidate pairs")
        if self.prediction_count != self.true_positive + self.false_positive:
            raise ValueError("prediction count does not match positive predictions")
        if self.reference_positive_count != self.true_positive + self.false_negative:
            raise ValueError("reference count does not match positives")
        if self.abstention_count != self.false_negative:
            raise ValueError("abstentions are reference-positive pairs without a prediction")
        return self


class PerGenreSupport(FrozenModel):
    """Per-genre denominator and thresholded result used for macro averages."""

    public_genre_id: str
    public_genre_name: str
    musicbrainz_genre_name: str
    metrics: BinaryMetrics


class CalibrationBin(FrozenModel):
    lower_inclusive: FiniteFloat = Field(ge=0.0, le=1.0)
    upper_inclusive: FiniteFloat = Field(ge=0.0, le=1.0)
    prediction_count: int = Field(ge=0)
    mean_model_score: FiniteFloat = Field(ge=0.0, le=1.0)
    musicbrainz_reference_rate: FiniteFloat = Field(ge=0.0, le=1.0)


class ConfidenceCalibration(FrozenModel):
    """Descriptive calibration only; public scores are not claimed probabilities."""

    scored_prediction_count: int = Field(ge=0)
    brier_score: FiniteFloat = Field(ge=0.0, le=1.0)
    expected_calibration_error: FiniteFloat = Field(ge=0.0, le=1.0)
    bins: tuple[CalibrationBin, ...] = Field(min_length=5, max_length=5)


class ErrorSample(FrozenModel):
    error_kind: ErrorKind
    artist_id: str
    artist_name: str
    public_genre_id: str
    public_genre_name: str
    musicbrainz_genre_name: str
    model_score: FiniteFloat | None = Field(default=None, ge=0.0, le=1.0)
    musicbrainz_tag_weight: FiniteFloat = Field(ge=0.0)


class ProfileThresholdEvaluation(FrozenModel):
    profile_kind: ProfileKind
    coverage: MatchingCoverage
    micro: BinaryMetrics
    macro_precision: FiniteFloat = Field(ge=0.0, le=1.0)
    macro_recall: FiniteFloat = Field(ge=0.0, le=1.0)
    macro_f1: FiniteFloat = Field(ge=0.0, le=1.0)
    per_genre_support: tuple[PerGenreSupport, ...] = Field(max_length=1_000)
    calibration: ConfidenceCalibration
    error_samples: tuple[ErrorSample, ...] = Field(max_length=2 * _MAX_ERROR_SAMPLES)


class ThresholdSensitivity(FrozenModel):
    """One transparent interpretation of an MB weighted tag as a positive reference."""

    musicbrainz_tag_weight_threshold: FiniteFloat = Field(gt=0.0)
    direct: ProfileThresholdEvaluation
    one_hop: ProfileThresholdEvaluation


class ReplayStability(FrozenModel):
    exact_replay: bool
    initial_evaluation_sha256: Sha256
    replay_evaluation_sha256: Sha256


class PublicMembershipExternalEvaluationReport(FrozenModel):
    """A retained local-research report, explicitly not a public quality certificate."""

    revision: Literal["public-membership-external-evaluation-v1"] = _REVISION
    evaluation_scope: Literal["local_research_only_post_seal_external_comparison"] = (
        "local_research_only_post_seal_external_comparison"
    )
    independent_public_gold_labels: Literal[False] = False
    musicbrainz_tags_are_noisy_reference_not_gold: Literal[True] = True
    public_release_quality_eligible: Literal[False] = False
    input: ExternalEvaluationInput
    prohibited_input_checks: ProhibitedInputChecks
    genre_matching_rule: Literal[
        "unique_exact_nfkc_casefold_whitespace_name_only_no_fuzzy_or_taxonomy_mapping"
    ] = "unique_exact_nfkc_casefold_whitespace_name_only_no_fuzzy_or_taxonomy_mapping"
    artist_matching_rule: Literal["exact_musicbrainz_artist_identifier_only"] = (
        "exact_musicbrainz_artist_identifier_only"
    )
    source_dependence_caveats: tuple[str, ...] = Field(min_length=4, max_length=12)
    sensitivity: tuple[ThresholdSensitivity, ...] = Field(min_length=1, max_length=12)
    evaluation_sha256: Sha256
    stability: ReplayStability


@dataclass(frozen=True, slots=True)
class _Prediction:
    profile_kind: ProfileKind
    artist_ref: str
    artist_mbid: str
    genre_id: int
    genre_ref: str
    genre_name: str
    score: float


@dataclass(frozen=True, slots=True)
class _Reference:
    artist_mbid: str
    artist_name: str
    genre_name: str
    weight: float


@dataclass(frozen=True, slots=True)
class _ResolvedPrediction:
    profile_kind: ProfileKind
    artist_mbid: str
    artist_name: str
    genre_ref: str
    genre_name: str
    musicbrainz_genre_name: str
    score: float


def _readonly_connection(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)


def _current_public_model(connection: sqlite3.Connection) -> tuple[int, str, str, str]:
    row = connection.execute(
        """SELECT run.id, run.output_sha256, run.artifact_sha256, run.published_at
           FROM current_public_models AS current
           JOIN public_model_runs AS run ON run.id = current.model_run_id
           WHERE current.model_key = 'public-graph'
             AND run.export_allowed = 1
             AND run.derived_output_id IS NOT NULL"""
    ).fetchone()
    if row is None:
        raise ValueError("public database has no selected, exportable, derived public-graph model")
    return int(row[0]), str(row[1]), str(row[2]), str(row[3])


def _ensure_post_seal_inputs(
    public: Path, research: Path
) -> tuple[ExternalEvaluationInput, ProhibitedInputChecks]:
    if public.resolve() == research.resolve():
        raise ValueError("public and MusicBrainz research databases must be distinct")
    with _readonly_connection(public) as public_connection:
        model_run_id, output_sha, artifact_sha, published_at = _current_public_model(
            public_connection
        )
        research_source_seen = public_connection.execute(
            "SELECT 1 FROM data_sources WHERE source_key = ? LIMIT 1", (_RESEARCH_SOURCE_KEY,)
        ).fetchone()
    if research_source_seen is not None:
        raise ValueError("MusicBrainz research source is present in public database")
    with _readonly_connection(research) as research_connection:
        tag_count = research_connection.execute(
            """SELECT COUNT(*) FROM artist_genre_evidence
               WHERE evidence_kind = 'direct_source_claim' AND source_key = ?""",
            (_RESEARCH_SOURCE_KEY,),
        ).fetchone()
    if tag_count is None or int(tag_count[0]) == 0:
        raise ValueError("research database has no expected MusicBrainz direct tag evidence")
    return (
        ExternalEvaluationInput(
            public_database_sha256=_file_sha256(public),
            musicbrainz_research_database_sha256=_file_sha256(research),
            public_model_run_id=model_run_id,
            public_model_output_sha256=output_sha,
            public_model_artifact_sha256=artifact_sha,
            public_model_published_at=published_at,
        ),
        ProhibitedInputChecks(),
    )


def _profile_kind(value: object) -> ProfileKind:
    if value == "direct":
        return "direct"
    if value == "one_hop":
        return "one_hop"
    raise ValueError(f"unsupported public profile kind: {value!r}")


def _artist_mbid(reference: str) -> str | None:
    prefix = "musicbrainz:artist:"
    value = reference.casefold()
    return (
        value.removeprefix(prefix)
        if value.startswith(prefix) and len(value) > len(prefix)
        else None
    )


def _public_predictions(
    connection: sqlite3.Connection, model_run_id: int
) -> tuple[_Prediction, ...]:
    rows = connection.execute(
        """SELECT membership.profile_kind, membership.source_artist_ref, membership.genre_id,
                  genre.name, membership.score
           FROM public_genre_profile_memberships AS membership
           JOIN genres AS genre ON genre.id = membership.genre_id
           WHERE membership.model_run_id = ?
           ORDER BY membership.profile_kind, membership.source_artist_ref, membership.genre_id""",
        (model_run_id,),
    ).fetchall()
    predictions: list[_Prediction] = []
    for profile_kind, artist_ref, genre_id, genre_name, score in rows:
        parsed = _artist_mbid(str(artist_ref))
        if parsed is None:
            continue
        predictions.append(
            _Prediction(
                profile_kind=_profile_kind(profile_kind),
                artist_ref=str(artist_ref),
                artist_mbid=parsed,
                genre_id=int(genre_id),
                genre_ref=f"public:genre:{int(genre_id)}",
                genre_name=str(genre_name),
                score=float(score),
            )
        )
    return tuple(predictions)


def _research_references(connection: sqlite3.Connection) -> tuple[_Reference, ...]:
    rows = connection.execute(
        """SELECT artist_identifier.normalized_value, artist_name.name, genre.name,
                  SUM(evidence.evidence_value)
           FROM artist_genre_evidence AS evidence
           JOIN entity_identifiers AS artist_identifier
             ON artist_identifier.entity_id = evidence.artist_id
           JOIN entity_names AS artist_name ON artist_name.entity_id = evidence.artist_id
             AND artist_name.name_kind = 'primary'
           JOIN genres AS genre ON genre.id = evidence.genre_id
           WHERE evidence.evidence_kind = 'direct_source_claim'
             AND evidence.source_key = ?
             AND artist_identifier.namespace = 'musicbrainz'
           GROUP BY artist_identifier.normalized_value, artist_name.name, genre.name
           ORDER BY artist_identifier.normalized_value, genre.name""",
        (_RESEARCH_SOURCE_KEY,),
    ).fetchall()
    return tuple(_Reference(str(row[0]), str(row[1]), str(row[2]), float(row[3])) for row in rows)


def _unique_name_map(names: list[tuple[str, str]]) -> dict[str, str | None]:
    matched: dict[str, str | None] = {}
    for identifier, name in names:
        key = _normalized_name(name)
        previous = matched.get(key)
        if previous is None and key not in matched:
            matched[key] = identifier
        elif previous != identifier:
            matched[key] = None
    return matched


def _metrics(
    candidate: set[tuple[str, str]],
    predicted: dict[tuple[str, str], _ResolvedPrediction],
    references: dict[tuple[str, str], _Reference],
    threshold: float,
) -> BinaryMetrics:
    tp = fp = fn = tn = 0
    weight_total = matched_weight = 0.0
    for key in candidate:
        predicted_present = key in predicted
        reference = references.get(key)
        positive = reference is not None and reference.weight >= threshold
        if positive:
            weight_total += reference.weight
        if predicted_present and positive:
            tp += 1
            matched_weight += reference.weight
        elif predicted_present:
            fp += 1
        elif positive:
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return BinaryMetrics(
        candidate_pair_count=len(candidate),
        prediction_count=tp + fp,
        reference_positive_count=tp + fn,
        true_positive=tp,
        false_positive=fp,
        false_negative=fn,
        true_negative=tn,
        abstention_count=fn,
        precision=precision,
        recall=recall,
        f1=f1,
        reference_weight_total=weight_total,
        true_positive_reference_weight=matched_weight,
        weighted_reference_recall=matched_weight / weight_total if weight_total else 0.0,
    )


def _calibration(
    predictions: dict[tuple[str, str], _ResolvedPrediction],
    references: dict[tuple[str, str], _Reference],
    threshold: float,
) -> ConfidenceCalibration:
    values = sorted(
        (item.score, int(references.get(key, _Reference("", "", "", 0.0)).weight >= threshold))
        for key, item in predictions.items()
    )
    bins: list[CalibrationBin] = []
    total_brier = total_ece = 0.0
    for index, lower in enumerate(_CALIBRATION_BOUNDS):
        upper = _CALIBRATION_BOUNDS[index + 1] if index + 1 < len(_CALIBRATION_BOUNDS) else 1.0
        members = [
            (score, target)
            for score, target in values
            if (lower <= score < upper or (upper == 1.0 and lower <= score <= upper))
        ]
        count = len(members)
        mean_score = sum(score for score, _ in members) / count if count else 0.0
        rate = sum(target for _, target in members) / count if count else 0.0
        total_brier += sum((score - target) ** 2 for score, target in members)
        total_ece += count * abs(mean_score - rate)
        bins.append(
            CalibrationBin(
                lower_inclusive=lower,
                upper_inclusive=upper,
                prediction_count=count,
                mean_model_score=mean_score,
                musicbrainz_reference_rate=rate,
            )
        )
    count = len(values)
    return ConfidenceCalibration(
        scored_prediction_count=count,
        brier_score=total_brier / count if count else 0.0,
        expected_calibration_error=total_ece / count if count else 0.0,
        bins=tuple(bins),
    )


def _profile_threshold_evaluation(
    profile_kind: ProfileKind,
    resolved: tuple[_ResolvedPrediction, ...],
    references: dict[tuple[str, str], _Reference],
    threshold: float,
    coverage: MatchingCoverage,
) -> ProfileThresholdEvaluation:
    predicted = {(item.artist_mbid, item.genre_ref): item for item in resolved}
    relevant_artists = {item.artist_mbid for item in resolved}
    relevant_genres = {item.genre_ref for item in resolved}
    reference_subset = {
        key: value
        for key, value in references.items()
        if key[0] in relevant_artists and key[1] in relevant_genres
    }
    candidate = set(predicted) | set(reference_subset)
    micro = _metrics(candidate, predicted, reference_subset, threshold)
    by_genre: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for artist, genre in candidate:
        by_genre[genre].add((artist, genre))
    genre_labels = {
        item.genre_ref: (item.genre_name, item.musicbrainz_genre_name) for item in resolved
    }
    support = tuple(
        PerGenreSupport(
            public_genre_id=genre,
            public_genre_name=genre_labels[genre][0],
            musicbrainz_genre_name=genre_labels[genre][1],
            metrics=_metrics(rows, predicted, reference_subset, threshold),
        )
        for genre, rows in sorted(by_genre.items())
    )
    fp = [
        ErrorSample(
            error_kind="false_positive",
            artist_id=item.artist_mbid,
            artist_name=item.artist_name,
            public_genre_id=item.genre_ref,
            public_genre_name=item.genre_name,
            musicbrainz_genre_name=item.musicbrainz_genre_name,
            model_score=item.score,
            musicbrainz_tag_weight=reference_subset.get(key, _Reference("", "", "", 0.0)).weight,
        )
        for key, item in predicted.items()
        if reference_subset.get(key, _Reference("", "", "", 0.0)).weight < threshold
    ]
    fn = [
        ErrorSample(
            error_kind="false_negative",
            artist_id=reference.artist_mbid,
            artist_name=reference.artist_name,
            public_genre_id=genre,
            public_genre_name=genre_labels[genre][0],
            musicbrainz_genre_name=genre_labels[genre][1],
            model_score=None,
            musicbrainz_tag_weight=reference.weight,
        )
        for (artist, genre), reference in reference_subset.items()
        if reference.weight >= threshold and (artist, genre) not in predicted
    ]
    errors = tuple(
        sorted(
            fp,
            key=lambda item: (
                -float(item.model_score or 0.0),
                item.artist_id,
                item.public_genre_id,
            ),
        )[:_MAX_ERROR_SAMPLES]
        + sorted(
            fn,
            key=lambda item: (
                -float(item.musicbrainz_tag_weight),
                item.artist_id,
                item.public_genre_id,
            ),
        )[:_MAX_ERROR_SAMPLES]
    )
    return ProfileThresholdEvaluation(
        profile_kind=profile_kind,
        coverage=coverage,
        micro=micro,
        macro_precision=sum(item.metrics.precision for item in support) / len(support)
        if support
        else 0.0,
        macro_recall=sum(item.metrics.recall for item in support) / len(support)
        if support
        else 0.0,
        macro_f1=sum(item.metrics.f1 for item in support) / len(support) if support else 0.0,
        per_genre_support=support,
        calibration=_calibration(predicted, reference_subset, threshold),
        error_samples=errors,
    )


def _evaluate_once(  # noqa: C901, PLR0915
    public_database: Path, research_database: Path, thresholds: tuple[float, ...]
) -> PublicMembershipExternalEvaluationReport:
    input_identity, prohibited_checks = _ensure_post_seal_inputs(public_database, research_database)
    with _readonly_connection(public_database) as connection:
        predictions = _public_predictions(connection, input_identity.public_model_run_id)
    with _readonly_connection(research_database) as connection:
        references = _research_references(connection)
    artist_names: dict[str, str] = {}
    reference_by_artist_genre_name: dict[tuple[str, str], _Reference] = {}
    for reference in references:
        artist_names.setdefault(reference.artist_mbid, reference.artist_name)
        reference_by_artist_genre_name[
            (reference.artist_mbid, _normalized_name(reference.genre_name))
        ] = reference
    public_name_map = _unique_name_map(
        [(prediction.genre_ref, prediction.genre_name) for prediction in predictions]
    )
    research_name_map = _unique_name_map(
        [
            ("research:" + _normalized_name(reference.genre_name), reference.genre_name)
            for reference in references
        ]
    )
    resolved_by_profile: dict[ProfileKind, list[_ResolvedPrediction]] = {
        "direct": [],
        "one_hop": [],
    }
    coverage_counts: dict[ProfileKind, dict[str, int]] = {
        "direct": defaultdict(int),
        "one_hop": defaultdict(int),
    }
    for prediction in predictions:
        counts = coverage_counts[prediction.profile_kind]
        counts["public"] += 1
        if prediction.artist_mbid not in artist_names:
            counts["unmatched_artist"] += 1
            continue
        counts["artist_matched"] += 1
        name_key = _normalized_name(prediction.genre_name)
        public_target = public_name_map.get(name_key)
        research_target = research_name_map.get(name_key)
        if public_target is None:
            counts["ambiguous_genre"] += 1
            continue
        if research_target is None:
            counts["unmatched_genre"] += 1
            continue
        counts["genre_matched"] += 1
        reference = reference_by_artist_genre_name.get((prediction.artist_mbid, name_key))
        musicbrainz_name = reference.genre_name if reference is not None else prediction.genre_name
        resolved_by_profile[prediction.profile_kind].append(
            _ResolvedPrediction(
                prediction.profile_kind,
                prediction.artist_mbid,
                artist_names[prediction.artist_mbid],
                prediction.genre_ref,
                prediction.genre_name,
                musicbrainz_name,
                prediction.score,
            )
        )
        counts["evaluated"] += 1
    all_references: dict[tuple[str, str], _Reference] = {}
    for profile in ("direct", "one_hop"):
        for prediction in resolved_by_profile[profile]:
            candidate = reference_by_artist_genre_name.get(
                (prediction.artist_mbid, _normalized_name(prediction.musicbrainz_genre_name))
            )
            if candidate is not None:
                all_references[(prediction.artist_mbid, prediction.genre_ref)] = candidate
    for reference in references:
        public_target = public_name_map.get(_normalized_name(reference.genre_name))
        if public_target is not None:
            all_references[(reference.artist_mbid, public_target)] = reference
    coverage: dict[ProfileKind, MatchingCoverage] = {}
    for profile in ("direct", "one_hop"):
        resolved = tuple(resolved_by_profile[profile])
        artists = {item.artist_mbid for item in resolved}
        genres = {item.genre_ref for item in resolved}
        subset = {
            key: item
            for key, item in all_references.items()
            if key[0] in artists and key[1] in genres
        }
        reference_positive = sum(item.weight >= min(thresholds) for item in subset.values())
        predicted_keys = {(item.artist_mbid, item.genre_ref) for item in resolved}
        reference_only = sum(
            item.weight >= min(thresholds) and key not in predicted_keys
            for key, item in subset.items()
        )
        counts = coverage_counts[profile]
        coverage[profile] = MatchingCoverage(
            profile_kind=profile,
            public_prediction_count=counts["public"],
            artist_id_matched_prediction_count=counts["artist_matched"],
            genre_name_matched_prediction_count=counts["genre_matched"],
            evaluated_prediction_count=counts["evaluated"],
            unmatched_artist_prediction_count=counts["unmatched_artist"],
            unmatched_genre_prediction_count=counts["unmatched_genre"],
            ambiguous_genre_prediction_count=counts["ambiguous_genre"],
            reference_positive_pair_count=reference_positive,
            reference_only_positive_pair_count=reference_only,
            reference_only_abstention_rate=reference_only / reference_positive
            if reference_positive
            else 0.0,
        )
    sensitivity = tuple(
        ThresholdSensitivity(
            musicbrainz_tag_weight_threshold=threshold,
            direct=_profile_threshold_evaluation(
                "direct",
                tuple(resolved_by_profile["direct"]),
                all_references,
                threshold,
                coverage["direct"],
            ),
            one_hop=_profile_threshold_evaluation(
                "one_hop",
                tuple(resolved_by_profile["one_hop"]),
                all_references,
                threshold,
                coverage["one_hop"],
            ),
        )
        for threshold in thresholds
    )
    caveats = (
        "MusicBrainz artist tags are community-supplied and incomplete; missing tags are not reliable negatives.",  # noqa: E501
        "The public model and MusicBrainz both use MusicBrainz identifiers, so identifier overlap is source-dependent rather than independent sampling.",  # noqa: E501
        "Genre comparison is limited to unique exact normalized labels; aliases, hierarchy, semantic similarity, and fuzzy matching are intentionally excluded.",  # noqa: E501
        "One-hop memberships are graph propagation outputs, while the reference contains direct artist tags; lower agreement is not a direct error estimate.",  # noqa: E501
        "Public membership scores are ranking scores, not calibrated probabilities; calibration cells are descriptive only.",  # noqa: E501
        "The evaluated universe is the union of observed public predictions and observed MusicBrainz tags, so it has no meaningful true-negative or specificity denominator.",  # noqa: E501
    )
    payload = {
        "revision": _REVISION,
        "input": input_identity.model_dump(mode="json"),
        "prohibited_input_checks": prohibited_checks.model_dump(mode="json"),
        "sensitivity": [item.model_dump(mode="json") for item in sensitivity],
    }
    evaluation_sha = _sha256(payload)
    return PublicMembershipExternalEvaluationReport(
        input=input_identity,
        prohibited_input_checks=prohibited_checks,
        source_dependence_caveats=caveats,
        sensitivity=sensitivity,
        evaluation_sha256=evaluation_sha,
        stability=ReplayStability(
            exact_replay=True,
            initial_evaluation_sha256=evaluation_sha,
            replay_evaluation_sha256=evaluation_sha,
        ),
    )


def evaluate_public_memberships_externally(
    public_database: Path,
    musicbrainz_research_database: Path,
    *,
    thresholds: tuple[float, ...] = _THRESHOLDS,
) -> PublicMembershipExternalEvaluationReport:
    """Compare the sealed public model twice and fail if deterministic replay changes it."""
    if (
        not thresholds
        or any(value <= 0.0 for value in thresholds)
        or tuple(sorted(set(thresholds))) != thresholds
    ):
        raise ValueError("MusicBrainz thresholds must be distinct, positive, and ascending")
    initial = _evaluate_once(public_database, musicbrainz_research_database, thresholds)
    replay = _evaluate_once(public_database, musicbrainz_research_database, thresholds)
    if initial.evaluation_sha256 != replay.evaluation_sha256:
        raise ValueError("external evaluation replay changed; database state was not stable")
    return initial.model_copy(
        update={
            "stability": ReplayStability(
                exact_replay=True,
                initial_evaluation_sha256=initial.evaluation_sha256,
                replay_evaluation_sha256=replay.evaluation_sha256,
            )
        }
    )


__all__ = ["PublicMembershipExternalEvaluationReport", "evaluate_public_memberships_externally"]
