"""Versioned, held-out evaluation for public artist-membership predictions.

This is intentionally a *calibration* harness.  It accepts only a bounded,
hash-addressed judgment document and does not treat its user-authored fixture
labels as independent evidence of real-world quality.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterable  # noqa: TC003
from dataclasses import dataclass
from pathlib import Path  # noqa: TC003
from typing import Literal

from pydantic import Field, FiniteFloat, model_validator

from musix.models import FrozenModel
from musix.models.modeling import PublicModelArtifact  # noqa: TC001
from musix.storage import ObjectKey, ObjectStore, ObjectWrite
from musix.types import Sha256  # noqa: TC001

type EvaluationProfileKind = Literal["direct", "one_hop"]
type JudgmentSourceKind = Literal["user_authored_fixture", "openly_publishable_public_record"]

_REVISION: Literal["artist-membership-evaluation-v1"] = "artist-membership-evaluation-v1"
_MAX_JUDGMENTS = 10_000
_SPLIT_BUCKET_COUNT = 10
_ALLOWED_SOURCE_FACETS: dict[EvaluationProfileKind, dict[str, frozenset[str]]] = {
    "direct": {
        "musicbrainz": frozenset({"musicbrainz_tag"}),
        "wikidata": frozenset({"wikidata_p136"}),
    },
    "one_hop": {"listenbrainz": frozenset({"listenbrainz_one_hop"})},
}


def _canonical_json(value: object) -> str:
    """Encode one normalized value so hashes do not depend on JSON formatting."""
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    )


def _sha256(value: object) -> Sha256:
    """Hash one canonical JSON value."""
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> Sha256:
    """Hash one immutable input file without parsing it a second time."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _split_bucket(judgment_id: str) -> int:
    """Assign a stable held-out bucket without random state."""
    return int(hashlib.sha256(judgment_id.encode("utf-8")).hexdigest(), 16) % _SPLIT_BUCKET_COUNT


class JudgmentSource(FrozenModel):
    """Declare the publishable origin and canonical record hash of a judgment set."""

    kind: JudgmentSourceKind
    source_ref: str = Field(min_length=1, max_length=500)
    description: str = Field(min_length=1, max_length=2_000)
    records_sha256: Sha256
    excludes_musicbrainz_supplementary_genres: Literal[True] = True
    excludes_historical_every_noise_assignments: Literal[True] = True


class JudgmentStratum(FrozenModel):
    """Declare one required source/facet stratum in the held-out fixture."""

    profile_kind: EvaluationProfileKind
    source_key: str = Field(min_length=1, max_length=100)
    facet: str = Field(min_length=1, max_length=100)
    expected_count: int = Field(ge=2, le=_MAX_JUDGMENTS)

    @model_validator(mode="after")
    def require_known_source_facet(self) -> JudgmentStratum:
        """Keep the evaluation surface limited to public-model facets."""
        allowed = _ALLOWED_SOURCE_FACETS[self.profile_kind].get(self.source_key, frozenset())
        if self.facet not in allowed:
            raise ValueError("judgment stratum has an unsupported source/facet")
        return self


class HeldOutSplit(FrozenModel):
    """Make the deterministic, stratified hold-out policy inspectable."""

    revision: Literal["sha256-judgment-id-modulo-10-v1"] = "sha256-judgment-id-modulo-10-v1"
    held_out_buckets: tuple[int, ...] = Field(min_length=1, max_length=_SPLIT_BUCKET_COUNT)
    strata: tuple[JudgmentStratum, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def require_unique_holdout_and_strata(self) -> HeldOutSplit:
        """Reject accidental duplicate denominator definitions."""
        if any(bucket < 0 or bucket >= _SPLIT_BUCKET_COUNT for bucket in self.held_out_buckets):
            raise ValueError("held-out buckets must be in the configured split range")
        if len(self.held_out_buckets) != len(set(self.held_out_buckets)):
            raise ValueError("held-out buckets must be unique")
        keys = tuple((item.profile_kind, item.source_key, item.facet) for item in self.strata)
        if len(keys) != len(set(keys)):
            raise ValueError("judgment strata must be unique")
        return self


class ArtistMembershipJudgment(FrozenModel):
    """One binary held-out membership decision with a declared source facet."""

    judgment_id: str = Field(min_length=1, max_length=200)
    artist_id: str = Field(min_length=1, max_length=300)
    genre_id: str = Field(min_length=1, max_length=300)
    profile_kind: EvaluationProfileKind
    expected_member: bool
    source_key: str = Field(min_length=1, max_length=100)
    facet: str = Field(min_length=1, max_length=100)
    split_bucket: int = Field(ge=0, lt=_SPLIT_BUCKET_COUNT)

    @model_validator(mode="after")
    def require_stable_bucket_and_known_facet(self) -> ArtistMembershipJudgment:
        """Bind an individual judgment to its deterministic source/facet split."""
        if self.split_bucket != _split_bucket(self.judgment_id):
            raise ValueError("judgment split bucket does not match its stable identifier hash")
        allowed = _ALLOWED_SOURCE_FACETS[self.profile_kind].get(self.source_key, frozenset())
        if self.facet not in allowed:
            raise ValueError("judgment has an unsupported source/facet")
        return self


class ArtistMembershipJudgmentSet(FrozenModel):
    """Parse the complete bounded evaluation input at one strict boundary."""

    revision: Literal["artist-membership-judgments-v1"] = "artist-membership-judgments-v1"
    purpose: Literal["user_authored_fixture_calibration_not_independent_public_gold"] = (
        "user_authored_fixture_calibration_not_independent_public_gold"
    )
    independent_public_gold_labels: Literal[False] = False
    source: JudgmentSource
    split: HeldOutSplit
    judgments: tuple[ArtistMembershipJudgment, ...] = Field(min_length=1, max_length=_MAX_JUDGMENTS)

    @model_validator(mode="after")
    def require_bounded_complete_held_out_strata(self) -> ArtistMembershipJudgmentSet:
        """Verify hashes, balance, and all declared held-out denominator cells."""
        ids = tuple(item.judgment_id for item in self.judgments)
        if len(ids) != len(set(ids)):
            raise ValueError("judgment identifiers must be unique")
        if self.source.records_sha256 != _sha256(
            [item.model_dump(mode="json") for item in self.judgments]
        ):
            raise ValueError("judgment record hash does not match the normalized judgments")
        held_out = set(self.split.held_out_buckets)
        if any(item.split_bucket not in held_out for item in self.judgments):
            raise ValueError("judgments must all belong to declared held-out buckets")
        actual: dict[tuple[EvaluationProfileKind, str, str], list[ArtistMembershipJudgment]] = (
            defaultdict(list)
        )
        for item in self.judgments:
            actual[(item.profile_kind, item.source_key, item.facet)].append(item)
        expected = {
            (item.profile_kind, item.source_key, item.facet): item.expected_count
            for item in self.split.strata
        }
        if set(actual) != set(expected):
            raise ValueError("judgment strata do not exactly match declared held-out strata")
        for key, items in actual.items():
            if len(items) != expected[key]:
                raise ValueError("judgment stratum count differs from declared denominator")
            if not any(item.expected_member for item in items) or not any(
                not item.expected_member for item in items
            ):
                raise ValueError("each judgment stratum requires both positive and negative labels")
        return self


class BinaryMetrics(FrozenModel):
    """One explicit binary metric cell with no hidden zero-denominator policy."""

    judgment_count: int = Field(ge=0)
    true_positive: int = Field(ge=0)
    false_positive: int = Field(ge=0)
    false_negative: int = Field(ge=0)
    true_negative: int = Field(ge=0)
    abstention_count: int = Field(ge=0)
    precision: FiniteFloat = Field(ge=0.0, le=1.0)
    recall: FiniteFloat = Field(ge=0.0, le=1.0)
    f1: FiniteFloat = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def require_complete_confusion_matrix(self) -> BinaryMetrics:
        """Make counts and deterministic zero-denominator behavior auditable."""
        if self.judgment_count != (
            self.true_positive + self.false_positive + self.false_negative + self.true_negative
        ):
            raise ValueError("metric counts do not sum to the judgment denominator")
        if self.abstention_count > self.judgment_count:
            raise ValueError("abstentions cannot exceed judged predictions")
        return self


class FacetBreakdown(FrozenModel):
    """Report one source/facet stratum separately from its profile aggregate."""

    profile_kind: EvaluationProfileKind
    source_key: str
    facet: str
    metrics: BinaryMetrics


class ProfileEvaluation(FrozenModel):
    """Keep direct and one-hop macro metrics separate."""

    profile_kind: EvaluationProfileKind
    judgment_count: int = Field(ge=0)
    prediction_count: int = Field(ge=0)
    abstention_rate: FiniteFloat = Field(ge=0.0, le=1.0)
    macro_precision: FiniteFloat = Field(ge=0.0, le=1.0)
    macro_recall: FiniteFloat = Field(ge=0.0, le=1.0)
    macro_f1: FiniteFloat = Field(ge=0.0, le=1.0)
    facet_breakdown: tuple[FacetBreakdown, ...] = Field(min_length=1, max_length=32)


class ReplayStability(FrozenModel):
    """Record exactly what was compared during deterministic replay."""

    exact_replay: bool
    initial_evaluation_sha256: Sha256
    replay_evaluation_sha256: Sha256
    prediction_sha256: Sha256


class ArtistMembershipEvaluationReport(FrozenModel):
    """A release-bindable calibration report, not a real-world quality claim."""

    revision: Literal["artist-membership-evaluation-v1"] = _REVISION
    quality_claim: Literal["fixture_calibration_only_not_independent_public_quality"] = (
        "fixture_calibration_only_not_independent_public_quality"
    )
    release_quality_eligible: Literal[False] = False
    passed: bool
    failures: tuple[str, ...]
    judgment_revision: Literal["artist-membership-judgments-v1"]
    judgment_file_sha256: Sha256
    judgment_records_sha256: Sha256
    model_file_sha256: Sha256 | None = None
    model_output_sha256: Sha256
    prediction_sha256: Sha256
    evaluation_sha256: Sha256
    direct: ProfileEvaluation
    one_hop: ProfileEvaluation
    stability: ReplayStability


class EvaluationPublicationReceipt(FrozenModel):
    """Name immutable ObjectStore bindings for one report and its judgment source."""

    judgment: ObjectWrite
    report: ObjectWrite


@dataclass(frozen=True, slots=True)
class _Prediction:
    present: bool
    facets: frozenset[str]


def _prediction_index(artifact: PublicModelArtifact) -> dict[tuple[str, str, str], _Prediction]:
    indexed: dict[tuple[str, str, str], _Prediction] = {}
    for profile in artifact.profiles:
        for membership in profile.memberships:
            key = (profile.profile_kind, membership.artist_id, membership.genre_id)
            facets = frozenset(component.component_kind for component in membership.components)
            existing = indexed.get(key)
            if existing is None:
                indexed[key] = _Prediction(present=True, facets=facets)
            else:
                indexed[key] = _Prediction(present=True, facets=existing.facets | facets)
    return indexed


def _binary_metrics(rows: Iterable[tuple[ArtistMembershipJudgment, _Prediction]]) -> BinaryMetrics:
    """Score positive membership predictions; absent pairs are abstentions."""
    true_positive = false_positive = false_negative = true_negative = abstentions = 0
    count = 0
    for judgment, prediction in rows:
        count += 1
        if not prediction.present:
            abstentions += 1
        if prediction.present and judgment.expected_member:
            true_positive += 1
        elif prediction.present:
            false_positive += 1
        elif judgment.expected_member:
            false_negative += 1
        else:
            true_negative += 1
    positive_predictions = true_positive + false_positive
    positive_judgments = true_positive + false_negative
    precision = true_positive / positive_predictions if positive_predictions else 0.0
    recall = true_positive / positive_judgments if positive_judgments else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return BinaryMetrics(
        judgment_count=count,
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
        true_negative=true_negative,
        abstention_count=abstentions,
        precision=precision,
        recall=recall,
        f1=f1,
    )


def _profile_evaluation(
    profile_kind: EvaluationProfileKind,
    judgments: tuple[ArtistMembershipJudgment, ...],
    predictions: dict[tuple[str, str, str], _Prediction],
) -> ProfileEvaluation:
    rows = tuple(
        (
            item,
            predictions.get(
                (item.profile_kind, item.artist_id, item.genre_id),
                _Prediction(present=False, facets=frozenset()),
            ),
        )
        for item in judgments
        if item.profile_kind == profile_kind
    )
    grouped: dict[tuple[str, str], list[tuple[ArtistMembershipJudgment, _Prediction]]] = (
        defaultdict(list)
    )
    for item, prediction in rows:
        grouped[(item.source_key, item.facet)].append((item, prediction))
    breakdown = tuple(
        FacetBreakdown(
            profile_kind=profile_kind,
            source_key=source_key,
            facet=facet,
            metrics=_binary_metrics(group_rows),
        )
        for (source_key, facet), group_rows in sorted(grouped.items())
    )
    all_metrics = _binary_metrics(rows)
    return ProfileEvaluation(
        profile_kind=profile_kind,
        judgment_count=len(rows),
        prediction_count=sum(prediction.present for _, prediction in rows),
        abstention_rate=all_metrics.abstention_count / len(rows) if rows else 0.0,
        macro_precision=sum(item.metrics.precision for item in breakdown) / len(breakdown),
        macro_recall=sum(item.metrics.recall for item in breakdown) / len(breakdown),
        macro_f1=sum(item.metrics.f1 for item in breakdown) / len(breakdown),
        facet_breakdown=breakdown,
    )


def _prediction_payload(
    judgments: tuple[ArtistMembershipJudgment, ...],
    predictions: dict[tuple[str, str, str], _Prediction],
) -> list[dict[str, object]]:
    """Hash only queried pairs so unrelated model growth cannot change the result."""
    return [
        {
            "judgment_id": item.judgment_id,
            "present": prediction.present,
            "facets": sorted(prediction.facets),
        }
        for item in sorted(judgments, key=lambda item: item.judgment_id)
        for prediction in (
            predictions.get(
                (item.profile_kind, item.artist_id, item.genre_id),
                _Prediction(present=False, facets=frozenset()),
            ),
        )
    ]


@dataclass(frozen=True, slots=True)
class _EvaluationContext:
    judgment_file_sha256: Sha256
    judgment_set: ArtistMembershipJudgmentSet
    model_file_sha256: Sha256 | None
    artifact: PublicModelArtifact
    prediction_sha256: Sha256
    direct: ProfileEvaluation
    one_hop: ProfileEvaluation


def _evaluation_payload(context: _EvaluationContext) -> dict[str, object]:
    return {
        "revision": _REVISION,
        "judgment_file_sha256": context.judgment_file_sha256,
        "judgment_records_sha256": context.judgment_set.source.records_sha256,
        "model_file_sha256": context.model_file_sha256,
        "model_output_sha256": context.artifact.output_sha256,
        "prediction_sha256": context.prediction_sha256,
        "direct": context.direct.model_dump(mode="json"),
        "one_hop": context.one_hop.model_dump(mode="json"),
    }


def evaluate_artist_memberships(
    artifact: PublicModelArtifact,
    judgment_set: ArtistMembershipJudgmentSet,
    *,
    judgment_file_sha256: Sha256,
    model_file_sha256: Sha256 | None = None,
) -> ArtistMembershipEvaluationReport:
    """Run one deterministic held-out calibration and an exact in-process replay."""
    predictions = _prediction_index(artifact)
    prediction_sha256 = _sha256(_prediction_payload(judgment_set.judgments, predictions))
    direct = _profile_evaluation("direct", judgment_set.judgments, predictions)
    one_hop = _profile_evaluation("one_hop", judgment_set.judgments, predictions)
    evaluation_sha256 = _sha256(
        _evaluation_payload(
            _EvaluationContext(
                judgment_file_sha256,
                judgment_set,
                model_file_sha256,
                artifact,
                prediction_sha256,
                direct,
                one_hop,
            )
        )
    )
    replay_predictions = _prediction_index(artifact)
    replay_prediction_sha256 = _sha256(
        _prediction_payload(judgment_set.judgments, replay_predictions)
    )
    replay_direct = _profile_evaluation("direct", judgment_set.judgments, replay_predictions)
    replay_one_hop = _profile_evaluation("one_hop", judgment_set.judgments, replay_predictions)
    replay_sha256 = _sha256(
        _evaluation_payload(
            _EvaluationContext(
                judgment_file_sha256,
                judgment_set,
                model_file_sha256,
                artifact,
                replay_prediction_sha256,
                replay_direct,
                replay_one_hop,
            )
        )
    )
    failures: list[str] = []
    if evaluation_sha256 != replay_sha256:
        failures.append("deterministic replay changed the evaluation payload")
    return ArtistMembershipEvaluationReport(
        passed=not failures,
        failures=tuple(failures),
        judgment_revision=judgment_set.revision,
        judgment_file_sha256=judgment_file_sha256,
        judgment_records_sha256=judgment_set.source.records_sha256,
        model_file_sha256=model_file_sha256,
        model_output_sha256=artifact.output_sha256,
        prediction_sha256=prediction_sha256,
        evaluation_sha256=evaluation_sha256,
        direct=direct,
        one_hop=one_hop,
        stability=ReplayStability(
            exact_replay=evaluation_sha256 == replay_sha256,
            initial_evaluation_sha256=evaluation_sha256,
            replay_evaluation_sha256=replay_sha256,
            prediction_sha256=replay_prediction_sha256,
        ),
    )


def load_judgment_set(path: Path) -> tuple[ArtistMembershipJudgmentSet, Sha256]:
    """Parse one judgment document and retain its byte-level release identity."""
    document = ArtistMembershipJudgmentSet.model_validate_json(path.read_text(encoding="utf-8"))
    return document, _file_sha256(path)


class ArtistMembershipEvaluationStore:
    """Persist immutable report identities using only stdlib SQLite."""

    def __init__(self, database: Path) -> None:
        """Create the small immutable-report ledger when it does not already exist."""
        self._database = database
        with sqlite3.connect(database) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS artist_membership_evaluations (
                    evaluation_sha256 TEXT PRIMARY KEY,
                    judgment_file_sha256 TEXT NOT NULL,
                    model_output_sha256 TEXT NOT NULL,
                    report_json TEXT NOT NULL
                ) STRICT"""
            )

    def record(self, report: ArtistMembershipEvaluationReport) -> bool:
        """Store a report once, rejecting same-hash rows with changed bytes."""
        payload = report.model_dump_json()
        with sqlite3.connect(self._database) as connection:
            existing = connection.execute(
                "SELECT report_json FROM artist_membership_evaluations WHERE evaluation_sha256 = ?",
                (report.evaluation_sha256,),
            ).fetchone()
            if existing is not None:
                if existing[0] != payload:
                    raise ValueError("evaluation hash already refers to different report bytes")
                return True
            connection.execute(
                """INSERT INTO artist_membership_evaluations (
                    evaluation_sha256, judgment_file_sha256, model_output_sha256, report_json
                ) VALUES (?, ?, ?, ?)""",
                (
                    report.evaluation_sha256,
                    report.judgment_file_sha256,
                    report.model_output_sha256,
                    payload,
                ),
            )
        return False


def publish_evaluation_evidence(
    store: ObjectStore,
    judgment_path: Path,
    report_path: Path,
    report: ArtistMembershipEvaluationReport,
) -> EvaluationPublicationReceipt:
    """Content-address both inputs through the shared immutable ObjectStore contract."""
    if _file_sha256(judgment_path) != report.judgment_file_sha256:
        raise ValueError("judgment file changed after evaluation")
    report_sha256 = _file_sha256(report_path)
    judgment = store.push(
        judgment_path,
        ObjectKey(
            value=f"evaluation/artist-membership/judgments/{report.judgment_file_sha256}.json"
        ),
    )
    stored_report = store.push(
        report_path,
        ObjectKey(value=f"evaluation/artist-membership/reports/{report_sha256}.json"),
    )
    return EvaluationPublicationReceipt(judgment=judgment, report=stored_report)


__all__ = [
    "ArtistMembershipEvaluationReport",
    "ArtistMembershipEvaluationStore",
    "ArtistMembershipJudgmentSet",
    "EvaluationPublicationReceipt",
    "evaluate_artist_memberships",
    "load_judgment_set",
    "publish_evaluation_evidence",
]
