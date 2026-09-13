"""Typed, replayable contracts for the source-neutral hierarchy fusion checkpoint."""

from __future__ import annotations

from typing import Final, Literal

from pydantic import Field, model_validator

from opennoise.common import canonical_json, sha256_hex
from opennoise.models import FrozenModel

_REVISION: Final = "hierarchy-fusion-v1"
_SEED_COUNT: Final = 6_291
_SHA_PATTERN: Final = r"^[0-9a-f]{64}$"
_INPUT_ROLES: Final = frozenset(
    {
        "seed_reconciliation",
        "evidence_graph_database",
        "evidence_graph_receipt",
        "wikidata_p279",
        "public_candidate_corpus",
        "public_candidate_receipt",
        "full_graph_containment",
        "full_graph_containment_receipt",
    }
)

type EdgeDisposition = Literal["factual", "review", "abstained", "self_rejected", "cycle_rejected"]
type SeedState = Literal["observed", "review", "abstained", "isolated"]


class HierarchyFusionError(ValueError):
    """The inputs cannot make a bounded, replayable hierarchy checkpoint."""


class HierarchyFusionSettings(FrozenModel):
    """A small, explicit policy for source-neutral multi-parent hierarchy review."""

    revision: Literal["hierarchy-fusion-settings-v1"] = "hierarchy-fusion-settings-v1"
    expected_seed_count: Literal[6291] = _SEED_COUNT
    factual_split_seed: int = Field(default=20260913, ge=0)
    factual_calibration_fraction: float = Field(default=0.2, gt=0.0, lt=0.5)
    factual_holdout_fraction: float = Field(default=0.2, gt=0.0, lt=0.5)
    review_score_thresholds: tuple[float, ...] = (0.25, 0.4, 0.55, 0.7, 0.85)
    lexical_signal_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    minimum_shared_artist_count: int = Field(default=5, ge=1, le=10_000)
    minimum_child_artist_count: int = Field(default=5, ge=1, le=10_000)
    calibration_recovery_tolerance: float = Field(default=0.02, ge=0.0, le=1.0)
    maximum_public_candidate_rows: int = Field(default=100_000, ge=1, le=500_000)

    @model_validator(mode="after")
    def require_distinct_sorted_thresholds(self) -> HierarchyFusionSettings:
        """Reject an ambiguous calibration policy at the model boundary."""
        if not self.review_score_thresholds:
            raise ValueError("review score thresholds cannot be empty")
        if any(not 0.0 <= value <= 1.0 for value in self.review_score_thresholds):
            raise ValueError("review score thresholds must be within [0, 1]")
        if tuple(self.review_score_thresholds) != tuple(sorted(self.review_score_thresholds)):
            raise ValueError("review score thresholds must be distinct and sorted")
        if self.factual_calibration_fraction + self.factual_holdout_fraction >= 1.0:
            raise ValueError("factual calibration and holdout fractions must leave training facts")
        return self


class SourceBinding(FrozenModel):
    """A byte-bound input used by the construction-only checkpoint."""

    role: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA_PATTERN)
    byte_count: int = Field(gt=0)
    logical_sha256: str | None = Field(default=None, pattern=_SHA_PATTERN)


class EdgeProvenance(FrozenModel):
    """One source-local explanation; references point back to immutable inputs."""

    source_role: Literal["wikidata_p279", "public_candidate_corpus", "full_graph_containment"]
    source_ref: str = Field(min_length=1, max_length=300)
    score: float = Field(ge=0.0, le=1.0)
    lexical_score: float = Field(ge=0.0, le=1.0)
    artist_containment_score: float = Field(ge=0.0, le=1.0)
    shared_artist_count: int = Field(ge=0)
    child_artist_count: int = Field(ge=0)
    parent_artist_count: int = Field(ge=0)


class FusedHierarchyEdge(FrozenModel):
    """A directed child-to-parent relation, never conflating review with fact."""

    child_seed_id: str = Field(min_length=1, max_length=200)
    parent_seed_id: str = Field(min_length=1, max_length=200)
    disposition: EdgeDisposition
    review_score: float = Field(ge=0.0, le=1.0)
    factual_source: bool
    included_in_dag: bool
    provenance: tuple[EdgeProvenance, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def require_explicit_edge_semantics(self) -> FusedHierarchyEdge:
        """Keep facts, review proposals, and DAG projection decisions distinguishable."""
        if self.disposition == "factual" and not self.factual_source:
            raise ValueError("factual dispositions require a factual source")
        if self.disposition == "factual" and not self.included_in_dag:
            raise ValueError("factual dispositions must be included in the DAG")
        if self.disposition == "review" and (self.factual_source or not self.included_in_dag):
            raise ValueError("review dispositions are non-factual included DAG edges")
        if (
            self.disposition in {"abstained", "self_rejected", "cycle_rejected"}
            and self.included_in_dag
        ):
            raise ValueError("rejected edge dispositions cannot enter the DAG")
        if self.disposition == "self_rejected" and self.child_seed_id != self.parent_seed_id:
            raise ValueError("self rejection must preserve the original self edge")
        if self.disposition != "self_rejected" and self.child_seed_id == self.parent_seed_id:
            raise ValueError("self edges must be explicitly rejected")
        return self


class SeedHierarchyState(FrozenModel):
    """One exhaustive state for one immutable stable seed."""

    seed_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=500)
    state: SeedState
    factual_incident_edge_count: int = Field(ge=0)
    accepted_review_incident_edge_count: int = Field(ge=0)
    rejected_candidate_incident_edge_count: int = Field(ge=0)
    explicit_unknown_reasons: tuple[str, ...] = Field(max_length=64)

    @model_validator(mode="after")
    def require_state_partition(self) -> SeedHierarchyState:
        """Require one state with evidence counts that make that state meaningful."""
        if self.state == "observed" and self.factual_incident_edge_count == 0:
            raise ValueError("observed state requires a factual incident edge")
        if self.state == "review" and (
            self.factual_incident_edge_count or self.accepted_review_incident_edge_count == 0
        ):
            raise ValueError("review state requires no facts and an accepted review edge")
        if self.state == "abstained" and (
            self.factual_incident_edge_count
            or self.accepted_review_incident_edge_count
            or self.rejected_candidate_incident_edge_count == 0
        ):
            raise ValueError("abstained state requires rejected evidence only")
        if self.state == "isolated" and (
            self.factual_incident_edge_count
            or self.accepted_review_incident_edge_count
            or self.rejected_candidate_incident_edge_count
        ):
            raise ValueError("isolated state cannot have incident edges")
        return self


class ThresholdMetric(FrozenModel):
    """Positive-only review recovery over a deterministic factual calibration split."""

    threshold: float = Field(ge=0.0, le=1.0)
    calibration_factual_edge_count: int = Field(ge=0)
    recovered_factual_edge_count: int = Field(ge=0)
    recovery: float | None = Field(default=None, ge=0.0, le=1.0)
    review_edge_count: int = Field(ge=0)


class FactualHoldoutEvaluation(FrozenModel):
    """Strictly evaluation-only factual recovery; absence is never a negative label."""

    calibration_factual_edge_count: int = Field(ge=0)
    holdout_factual_edge_count: int = Field(ge=0)
    selected_threshold: float = Field(ge=0.0, le=1.0)
    threshold_metrics: tuple[ThresholdMetric, ...] = Field(min_length=1)
    holdout_recovered_edge_count: int = Field(ge=0)
    holdout_recovery: float | None = Field(default=None, ge=0.0, le=1.0)
    historical_inputs_used: Literal[False] = False


class HierarchyCoverage(FrozenModel):
    """Small graph-level accounting that preserves review additions separately."""

    seed_count: Literal[6291] = _SEED_COUNT
    factual_source_edge_count: int = Field(ge=0)
    factual_dag_edge_count: int = Field(ge=0)
    review_edge_count: int = Field(ge=0)
    abstained_edge_count: int = Field(ge=0)
    self_rejected_edge_count: int = Field(ge=0)
    cycle_rejected_edge_count: int = Field(ge=0)
    multi_parent_child_count: int = Field(ge=0)
    component_count: int = Field(ge=0)
    maximum_depth: int = Field(ge=0)
    observed_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    review_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    abstained_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    isolated_seed_count: int = Field(ge=0, le=_SEED_COUNT)

    @model_validator(mode="after")
    def require_seed_partition(self) -> HierarchyCoverage:
        """Ensure graph-level state accounting covers all stable seeds exactly once."""
        if self.seed_count != (
            self.observed_seed_count
            + self.review_seed_count
            + self.abstained_seed_count
            + self.isolated_seed_count
        ):
            raise ValueError("seed hierarchy states must partition the stable universe")
        return self


class SemanticSpotcheck(FrozenModel):
    """Diagnostic target, never an injected construction relation."""

    path: tuple[str, ...] = Field(min_length=2, max_length=5)
    resolved_seed_ids: tuple[str | None, ...]
    supported_adjacent_hops: int = Field(ge=0)
    missing_reason: str | None = None


class HierarchyFusionArtifact(FrozenModel):
    """A reproducible source-neutral multi-parent hierarchy checkpoint."""

    revision: Literal["hierarchy-fusion-v1"] = _REVISION
    settings: HierarchyFusionSettings
    settings_sha256: str = Field(pattern=_SHA_PATTERN)
    inputs: tuple[SourceBinding, ...] = Field(min_length=8, max_length=8)
    selected_review_threshold: float = Field(ge=0.0, le=1.0)
    factual_holdout_evaluation: FactualHoldoutEvaluation
    edges: tuple[FusedHierarchyEdge, ...]
    seed_states: tuple[SeedHierarchyState, ...] = Field(
        min_length=_SEED_COUNT, max_length=_SEED_COUNT
    )
    coverage: HierarchyCoverage
    semantic_spotchecks: tuple[SemanticSpotcheck, ...]
    historical_inputs_used_for_construction: Literal[False] = False
    output_sha256: str = Field(pattern=_SHA_PATTERN)

    @model_validator(mode="after")
    def require_complete_deduplicated_result(self) -> HierarchyFusionArtifact:
        """Verify output completeness before a logical artifact is accepted."""
        if hierarchy_fusion_settings_sha256(self.settings) != self.settings_sha256:
            raise ValueError("settings hash does not replay")
        seed_ids = tuple(row.seed_id for row in self.seed_states)
        if len(seed_ids) != len(set(seed_ids)):
            raise ValueError("seed states must be unique")
        if {item.role for item in self.inputs} != _INPUT_ROLES:
            raise ValueError("hierarchy fusion inputs must have the exact required roles")
        pairs = tuple((row.child_seed_id, row.parent_seed_id) for row in self.edges)
        if len(pairs) != len(set(pairs)):
            raise ValueError("fused edges must be unique")
        return self


def hierarchy_fusion_settings_sha256(settings: HierarchyFusionSettings) -> str:
    """Hash the complete a-priori construction policy."""
    return sha256_hex(canonical_json(settings.model_dump(mode="json")))


def hierarchy_fusion_artifact_sha256(artifact: HierarchyFusionArtifact) -> str:
    """Hash construction outputs while excluding only the self hash."""
    return sha256_hex(canonical_json(artifact.model_dump(mode="json", exclude={"output_sha256"})))
