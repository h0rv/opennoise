"""Explainable construction of a factual-plus-review overlapping genre DAG."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import pairwise
from typing import TYPE_CHECKING

from .contracts import (
    EdgeProvenance,
    FactualHoldoutEvaluation,
    FusedHierarchyEdge,
    HierarchyCoverage,
    HierarchyFusionArtifact,
    HierarchyFusionError,
    HierarchyFusionSettings,
    SeedHierarchyState,
    SemanticSpotcheck,
    ThresholdMetric,
    hierarchy_fusion_artifact_sha256,
    hierarchy_fusion_settings_sha256,
)
from .inputs import HierarchyFusionInputs, load_hierarchy_fusion_inputs

if TYPE_CHECKING:
    from .inputs import LoadedHierarchyFusionInputs


@dataclass(slots=True)
class _Proposal:
    factual: list[EdgeProvenance] = field(default_factory=list)
    review: list[EdgeProvenance] = field(default_factory=list)


def _split_factual(edge: tuple[str, str], settings: HierarchyFusionSettings) -> str:
    """Deterministically reserve exact P279 pairs for calibration and blind holdout."""
    digest = hashlib.sha256(f"{settings.factual_split_seed}:{edge[0]}:{edge[1]}".encode()).digest()
    value = int.from_bytes(digest[:8]) / 2**64
    if value < settings.factual_calibration_fraction:
        return "calibration"
    if value < settings.factual_calibration_fraction + settings.factual_holdout_fraction:
        return "holdout"
    return "train"


def _review_score(
    provenance: tuple[EdgeProvenance, ...], settings: HierarchyFusionSettings
) -> float:
    """Fuse lexical evidence with reliability-gated correlated artist signals."""
    lexical = max((item.lexical_score for item in provenance), default=0.0)
    artist = max(
        (
            min(item.score, item.artist_containment_score)
            * min(1.0, item.shared_artist_count / settings.minimum_shared_artist_count)
            * min(1.0, item.child_artist_count / settings.minimum_child_artist_count)
            for item in provenance
            if item.artist_containment_score > 0.0
        ),
        default=0.0,
    )
    return round(1.0 - (1.0 - settings.lexical_signal_weight * lexical) * (1.0 - artist), 12)


def _has_path(parents: dict[str, set[str]], start: str, target: str) -> bool:
    pending = [start]
    visited: set[str] = set()
    while pending:
        node = pending.pop()
        if node == target:
            return True
        if node in visited:
            continue
        visited.add(node)
        pending.extend(sorted(parents.get(node, ()), reverse=True))
    return False


def _assert_acyclic(parents: dict[str, set[str]], seed_ids: tuple[str, ...]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(seed_id: str) -> None:
        if seed_id in visiting:
            raise HierarchyFusionError("fused hierarchy contains a cycle")
        if seed_id in visited:
            return
        visiting.add(seed_id)
        for parent in sorted(parents.get(seed_id, ())):
            visit(parent)
        visiting.remove(seed_id)
        visited.add(seed_id)

    for seed_id in seed_ids:
        visit(seed_id)


def _component_count(seed_ids: tuple[str, ...], parents: dict[str, set[str]]) -> int:
    neighbors: dict[str, set[str]] = defaultdict(set)
    for child, values in parents.items():
        for parent in values:
            neighbors[child].add(parent)
            neighbors[parent].add(child)
    seen: set[str] = set()
    count = 0
    for seed_id in seed_ids:
        if seed_id in seen:
            continue
        count += 1
        pending = [seed_id]
        while pending:
            node = pending.pop()
            if node in seen:
                continue
            seen.add(node)
            pending.extend(sorted(neighbors[node], reverse=True))
    return count


def _maximum_depth(seed_ids: tuple[str, ...], parents: dict[str, set[str]]) -> int:
    memo: dict[str, int] = {}

    def depth(seed_id: str) -> int:
        if seed_id in memo:
            return memo[seed_id]
        values = parents.get(seed_id, set())
        result = 0 if not values else 1 + max(depth(parent) for parent in values)
        memo[seed_id] = result
        return result

    return max((depth(seed_id) for seed_id in seed_ids), default=0)


def _calibrate(
    factual: dict[tuple[str, str], tuple[EdgeProvenance, ...]],
    proposals: dict[tuple[str, str], _Proposal],
    settings: HierarchyFusionSettings,
) -> FactualHoldoutEvaluation:
    calibration = {edge for edge in factual if _split_factual(edge, settings) == "calibration"}
    holdout = {edge for edge in factual if _split_factual(edge, settings) == "holdout"}
    metrics = tuple(
        ThresholdMetric(
            threshold=threshold,
            calibration_factual_edge_count=len(calibration),
            recovered_factual_edge_count=sum(
                edge in proposals
                and _review_score(tuple(proposals[edge].review), settings) >= threshold
                for edge in calibration
            ),
            recovery=(
                sum(
                    edge in proposals
                    and _review_score(tuple(proposals[edge].review), settings) >= threshold
                    for edge in calibration
                )
                / len(calibration)
                if calibration
                else None
            ),
            review_edge_count=sum(
                not proposal.factual
                and _review_score(tuple(proposal.review), settings) >= threshold
                for proposal in proposals.values()
            ),
        )
        for threshold in settings.review_score_thresholds
    )
    best_recovery = max(
        (metric.recovery for metric in metrics if metric.recovery is not None), default=0.0
    )
    # Select the sparsest graph whose calibration recovery remains within policy tolerance.
    selected = max(
        (
            metric
            for metric in metrics
            if metric.recovery is not None
            and metric.recovery >= best_recovery - settings.calibration_recovery_tolerance
        ),
        key=lambda metric: metric.threshold,
    )
    recovered_holdout = sum(
        edge in proposals
        and _review_score(tuple(proposals[edge].review), settings) >= selected.threshold
        for edge in holdout
    )
    return FactualHoldoutEvaluation(
        calibration_factual_edge_count=len(calibration),
        holdout_factual_edge_count=len(holdout),
        selected_threshold=selected.threshold,
        threshold_metrics=metrics,
        holdout_recovered_edge_count=recovered_holdout,
        holdout_recovery=recovered_holdout / len(holdout) if holdout else None,
    )


def _spotchecks(
    seed_names: dict[str, str], parents: dict[str, set[str]]
) -> tuple[SemanticSpotcheck, ...]:
    normalized: dict[str, str] = {
        " ".join(name.casefold().split()): seed_id for seed_id, name in seed_names.items()
    }
    expected = (
        ("electronic", "intelligent dance music", "braindance"),
        ("electronic", "intelligent dance music", "drill and bass"),
        ("electronic", "intelligent dance music", "ambient techno"),
        ("rock", "punk", "post-punk"),
        ("electronic", "house", "deep house"),
        ("electronic", "techno", "detroit techno"),
        ("regional", "brazilian funk", "funk mandelao"),
    )
    checks: list[SemanticSpotcheck] = []
    for path in expected:
        resolved = tuple(normalized.get(value) for value in path)
        supported = sum(
            child is not None and parent is not None and parent in parents.get(child, set())
            for parent, child in pairwise(resolved)
        )
        missing = None
        if any(value is None for value in resolved):
            missing = "one_or_more_labels_are_not_exactly_resolved_in_the_stable_seed_universe"
        elif supported != len(path) - 1:
            missing = "source_neutral_inputs_do_not_support_every_requested_adjacent_hop"
        checks.append(
            SemanticSpotcheck(
                path=path,
                resolved_seed_ids=resolved,
                supported_adjacent_hops=supported,
                missing_reason=missing,
            )
        )
    return tuple(checks)


def _merge_proposals(loaded: LoadedHierarchyFusionInputs) -> dict[tuple[str, str], _Proposal]:
    """Collect factual and review signals by directed seed pair."""
    proposals: dict[tuple[str, str], _Proposal] = {}
    for edge, rows in loaded.factual.items():
        proposals.setdefault(edge, _Proposal()).factual.extend(rows)
    for source in (loaded.public_candidate_corpus, loaded.full_graph):
        for edge, rows in source.items():
            proposals.setdefault(edge, _Proposal()).review.extend(rows)
    return proposals


def _project_edges(
    proposals: dict[tuple[str, str], _Proposal],
    settings: HierarchyFusionSettings,
    threshold: float,
) -> tuple[
    list[FusedHierarchyEdge],
    dict[str, set[str]],
    dict[str, int],
    dict[str, int],
    dict[str, int],
]:
    """Construct a factual-first DAG and retain every excluded row for audit."""
    parents: dict[str, set[str]] = defaultdict(set)
    output: list[FusedHierarchyEdge] = []
    rejected_incident: dict[str, int] = defaultdict(int)
    factual_incident: dict[str, int] = defaultdict(int)
    review_incident: dict[str, int] = defaultdict(int)
    ordered = sorted(
        proposals,
        key=lambda edge: (
            0 if proposals[edge].factual else 1,
            -_review_score(tuple(proposals[edge].review), settings),
            edge,
        ),
    )
    for child, parent in ordered:
        proposal = proposals[(child, parent)]
        provenance = tuple(
            sorted(
                (*proposal.factual, *proposal.review),
                key=lambda item: (item.source_role, item.source_ref),
            )
        )
        score = _review_score(tuple(proposal.review), settings)
        if child == parent:
            disposition = "self_rejected"
            factual_source = bool(proposal.factual)
            included_in_dag = False
            if factual_source:
                factual_incident[child] += 2
        elif proposal.factual:
            # Exact P279 is immutable fact. Its source adapter is already acyclic.
            factual_incident[child] += 1
            factual_incident[parent] += 1
            if _has_path(parents, parent, child):
                disposition = "cycle_rejected"
                factual_source = True
                included_in_dag = False
            else:
                parents[child].add(parent)
                disposition = "factual"
                factual_source = True
                included_in_dag = True
        elif score < threshold:
            disposition = "abstained"
            factual_source = False
            included_in_dag = False
        elif _has_path(parents, parent, child):
            disposition = "cycle_rejected"
            factual_source = False
            included_in_dag = False
        else:
            parents[child].add(parent)
            review_incident[child] += 1
            review_incident[parent] += 1
            disposition = "review"
            factual_source = False
            included_in_dag = True
        if disposition in {"abstained", "self_rejected", "cycle_rejected"}:
            rejected_incident[child] += 1
            rejected_incident[parent] += 1
        output.append(
            FusedHierarchyEdge(
                child_seed_id=child,
                parent_seed_id=parent,
                disposition=disposition,
                review_score=score,
                factual_source=factual_source,
                included_in_dag=included_in_dag,
                provenance=provenance,
            )
        )
    return output, parents, factual_incident, review_incident, rejected_incident


def _seed_states(
    loaded: LoadedHierarchyFusionInputs,
    factual_incident: dict[str, int],
    review_incident: dict[str, int],
    rejected_incident: dict[str, int],
) -> list[SeedHierarchyState]:
    """Make every seed's factual, review, abstained, or isolated state explicit."""
    states: list[SeedHierarchyState] = []
    for seed_id in sorted(loaded.seed_names):
        state = (
            "observed"
            if factual_incident[seed_id]
            else "review"
            if review_incident[seed_id]
            else "abstained"
            if rejected_incident[seed_id]
            else "isolated"
        )
        states.append(
            SeedHierarchyState(
                seed_id=seed_id,
                name=loaded.seed_names[seed_id],
                state=state,
                factual_incident_edge_count=factual_incident[seed_id],
                accepted_review_incident_edge_count=review_incident[seed_id],
                rejected_candidate_incident_edge_count=rejected_incident[seed_id],
                explicit_unknown_reasons=loaded.unknown_reasons.get(seed_id, ()),
            )
        )
    return states


def _build(
    loaded: LoadedHierarchyFusionInputs, settings: HierarchyFusionSettings
) -> HierarchyFusionArtifact:
    """Build one sealed construction-only artifact from validated source inputs."""
    seed_ids = tuple(sorted(loaded.seed_names))
    proposals = _merge_proposals(loaded)
    evaluation = _calibrate(loaded.factual, proposals, settings)
    output, parents, factual_incident, review_incident, rejected_incident = _project_edges(
        proposals, settings, evaluation.selected_threshold
    )
    _assert_acyclic(parents, seed_ids)
    states = _seed_states(loaded, factual_incident, review_incident, rejected_incident)
    coverage = HierarchyCoverage(
        factual_source_edge_count=sum(edge.factual_source for edge in output),
        factual_dag_edge_count=sum(edge.disposition == "factual" for edge in output),
        review_edge_count=sum(edge.disposition == "review" for edge in output),
        abstained_edge_count=sum(edge.disposition == "abstained" for edge in output),
        self_rejected_edge_count=sum(edge.disposition == "self_rejected" for edge in output),
        cycle_rejected_edge_count=sum(edge.disposition == "cycle_rejected" for edge in output),
        multi_parent_child_count=sum(len(values) > 1 for values in parents.values()),
        component_count=_component_count(seed_ids, parents),
        maximum_depth=_maximum_depth(seed_ids, parents),
        observed_seed_count=sum(row.state == "observed" for row in states),
        review_seed_count=sum(row.state == "review" for row in states),
        abstained_seed_count=sum(row.state == "abstained" for row in states),
        isolated_seed_count=sum(row.state == "isolated" for row in states),
    )
    preliminary = HierarchyFusionArtifact(
        settings=settings,
        settings_sha256=hierarchy_fusion_settings_sha256(settings),
        inputs=loaded.bindings,
        selected_review_threshold=evaluation.selected_threshold,
        factual_holdout_evaluation=evaluation,
        edges=tuple(sorted(output, key=lambda row: (row.child_seed_id, row.parent_seed_id))),
        seed_states=tuple(states),
        coverage=coverage,
        semantic_spotchecks=_spotchecks(loaded.seed_names, parents),
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(
        update={"output_sha256": hierarchy_fusion_artifact_sha256(preliminary)}
    )


def build_hierarchy_fusion(
    inputs: HierarchyFusionInputs, settings: HierarchyFusionSettings | None = None
) -> HierarchyFusionArtifact:
    """Fuse only source-neutral artifacts into an explainable overlapping DAG."""
    resolved = settings or HierarchyFusionSettings()
    loaded = load_hierarchy_fusion_inputs(
        inputs, maximum_public_candidate_rows=resolved.maximum_public_candidate_rows
    )
    return _build(loaded, resolved)


def verify_hierarchy_fusion(artifact: HierarchyFusionArtifact) -> None:
    """Recompute the hash and validate the accepted factual-plus-review DAG."""
    if hierarchy_fusion_artifact_sha256(artifact) != artifact.output_sha256:
        raise HierarchyFusionError("hierarchy fusion artifact hash does not replay")
    parents: dict[str, set[str]] = defaultdict(set)
    for edge in artifact.edges:
        if edge.disposition in {"factual", "review"}:
            parents[edge.child_seed_id].add(edge.parent_seed_id)
    _assert_acyclic(parents, tuple(row.seed_id for row in artifact.seed_states))
