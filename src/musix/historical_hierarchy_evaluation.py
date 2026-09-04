"""Read-only evaluation of graph-derived historical hierarchy artifacts."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Literal

from pydantic import Field

from musix.models import FrozenModel
from musix.models.historical_signal import HistoricalSignalArtifact  # noqa: TC001
from musix.types import Sha256  # noqa: TC001

_LEVELS = (0, 1, 2)
_MICROGENRE_LEVEL = 2
_LEVEL_NAMES = ("umbrella", "subcommunity", "microgenre")
_DEFAULT_LEXICAL_COHORTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("house/deep house/techno/electronic", ("house", "deep house", "techno", "electronic")),
    ("metal/black metal/death metal", ("metal", "black metal", "death metal")),
    ("hip-hop/rap", ("hip-hop", "rap")),
    ("jazz/bebop", ("jazz", "bebop")),
    ("classical", ("classical",)),
    ("pop", ("pop",)),
)
_COHORT_SAMPLE_LIMIT = 8
_NON_WORDS = re.compile(r"[^\w]+", re.UNICODE)


class HistogramBucket(FrozenModel):
    """One deterministic member-size distribution bucket."""

    label: str = Field(min_length=1, max_length=80)
    count: int = Field(ge=0)


class HierarchyLevelCoverage(FrozenModel):
    """Coverage and closure facts for one graph-derived hierarchy level."""

    level: Literal[0, 1, 2]
    level_name: str = Field(min_length=1, max_length=30)
    hierarchy_node_count: int = Field(ge=0)
    assigned_genre_count: int = Field(ge=0)
    member_count: int = Field(ge=0)
    coverage: float = Field(ge=0.0, le=1.0)
    parent_closure: bool
    child_closure: bool
    member_count_closure: bool


class HierarchyCoverageReport(FrozenModel):
    """Report hierarchy coverage without treating labels as semantic truth."""

    artifact_node_count: int = Field(ge=0)
    hierarchy_node_count: int = Field(ge=0)
    assigned_genre_count: int = Field(ge=0)
    genre_coverage: float = Field(ge=0.0, le=1.0)
    parent_closure: bool
    child_closure: bool
    member_count_closure: bool
    node_path_closure: bool
    levels: tuple[HierarchyLevelCoverage, ...] = Field(min_length=3, max_length=3)


class SizeDistributionReport(FrozenModel):
    """Member-size facts for one hierarchy level."""

    level: Literal[0, 1, 2]
    level_name: str = Field(min_length=1, max_length=30)
    group_count: int = Field(ge=0)
    total_member_count: int = Field(ge=0)
    minimum_member_count: int = Field(ge=0)
    maximum_member_count: int = Field(ge=0)
    mean_member_count: float = Field(ge=0.0)
    buckets: tuple[HistogramBucket, ...] = Field(max_length=8)


class HierarchyEdgeRetention(FrozenModel):
    """Union and reciprocal internal-edge retention at one hierarchy level."""

    level: Literal[0, 1, 2]
    level_name: str = Field(min_length=1, max_length=30)
    internal_union_edge_count: int = Field(ge=0)
    internal_reciprocal_edge_count: int = Field(ge=0)
    total_union_edge_count: int = Field(ge=0)
    total_reciprocal_edge_count: int = Field(ge=0)
    union_retention: float = Field(ge=0.0, le=1.0)
    reciprocal_retention: float = Field(ge=0.0, le=1.0)
    modularity_weight: Literal["max_directed_weighted_jaccard"] = "max_directed_weighted_jaccard"
    weighted_modularity: float = Field(ge=-1.0, le=1.0)


class ComponentFragmentationLevel(FrozenModel):
    """Component fragmentation among groups at one hierarchy level."""

    level: Literal[0, 1, 2]
    level_name: str = Field(min_length=1, max_length=30)
    group_count: int = Field(ge=0)
    disconnected_group_count: int = Field(ge=0)
    disconnected_group_fraction: float = Field(ge=0.0, le=1.0)
    maximum_component_count: int = Field(ge=0)
    mean_component_count: float = Field(ge=0.0)


class ComponentFragmentationReport(FrozenModel):
    """Overall graph component facts and hierarchy fragmentation summaries."""

    graph_component_count: int = Field(ge=0)
    graph_isolate_count: int = Field(ge=0)
    largest_component_size: int = Field(ge=0)
    levels: tuple[ComponentFragmentationLevel, ...] = Field(min_length=3, max_length=3)


class LexicalCohortSample(FrozenModel):
    """Evaluation-only lexical matches; names are not asserted as ground truth."""

    cohort: str = Field(min_length=1, max_length=200)
    terms: tuple[str, ...] = Field(min_length=1, max_length=10)
    evaluation_only: Literal[True] = True
    names_are_ground_truth: Literal[False] = False
    matched_node_count: int = Field(ge=0)
    sample: tuple[tuple[str, str], ...] = Field(max_length=_COHORT_SAMPLE_LIMIT)


class LevelComparison(FrozenModel):
    """Current-minus-baseline deltas for one hierarchy level."""

    level: Literal[0, 1, 2]
    level_name: str = Field(min_length=1, max_length=30)
    group_count_delta: int
    maximum_member_count_delta: int
    union_retention_delta: float
    reciprocal_retention_delta: float
    weighted_modularity_delta: float


class BaselineComparison(FrozenModel):
    """Explicit current-minus-baseline comparison, when a baseline is supplied."""

    baseline_artifact_sha256: Sha256
    current_artifact_sha256: Sha256
    node_count_delta: int
    hierarchy_node_count_delta: int
    umbrella_count_delta: int
    genre_coverage_delta: float
    parent_closure_changed: bool
    edge_retention: tuple[LevelComparison, ...] = Field(min_length=3, max_length=3)
    lexical_cohort_match_count_delta: tuple[tuple[str, int], ...] = Field(max_length=10)


class HistoricalHierarchyEvaluation(FrozenModel):
    """Complete read-only evaluation report for one historical signal artifact."""

    revision: Literal["historical-hierarchy-evaluation-v1"] = "historical-hierarchy-evaluation-v1"
    source_artifact_sha256: Sha256
    coverage: HierarchyCoverageReport
    umbrella_size_distribution: SizeDistributionReport
    level_size_distributions: tuple[SizeDistributionReport, ...] = Field(min_length=3, max_length=3)
    edge_retention: tuple[HierarchyEdgeRetention, ...] = Field(min_length=3, max_length=3)
    components: ComponentFragmentationReport
    lexical_cohorts: tuple[LexicalCohortSample, ...] = Field(min_length=6, max_length=6)
    baseline_comparison: BaselineComparison | None = None


def evaluate_historical_hierarchy(
    artifact: HistoricalSignalArtifact,
    *,
    baseline: HistoricalSignalArtifact | None = None,
    lexical_cohorts: tuple[tuple[str, tuple[str, ...]], ...] = _DEFAULT_LEXICAL_COHORTS,
) -> HistoricalHierarchyEvaluation:
    """Evaluate hierarchy structure, graph retention, components, and lexical samples."""
    current = _evaluate_single(artifact, lexical_cohorts=lexical_cohorts)
    if baseline is None:
        return current
    baseline_report = _evaluate_single(baseline, lexical_cohorts=lexical_cohorts)
    return current.model_copy(update={"baseline_comparison": _compare(current, baseline_report)})


def _evaluate_single(
    artifact: HistoricalSignalArtifact,
    *,
    lexical_cohorts: tuple[tuple[str, tuple[str, ...]], ...],
) -> HistoricalHierarchyEvaluation:
    coverage = _coverage(artifact)
    sizes = tuple(_size_distribution(artifact, level) for level in _LEVELS)
    edge_retention = _edge_retention(artifact)
    components = _components(artifact)
    lexical = tuple(_lexical_sample(artifact, cohort, terms) for cohort, terms in lexical_cohorts)
    return HistoricalHierarchyEvaluation(
        source_artifact_sha256=artifact.quality.artifact_sha256,
        coverage=coverage,
        umbrella_size_distribution=sizes[0],
        level_size_distributions=sizes,
        edge_retention=edge_retention,
        components=components,
        lexical_cohorts=lexical,
    )


def _coverage(artifact: HistoricalSignalArtifact) -> HierarchyCoverageReport:
    hierarchy_by_id = {item.hierarchy_id: item for item in artifact.hierarchy}
    parent_closure = True
    child_closure = True
    member_count_closure = True
    for item in artifact.hierarchy:
        if item.level == 0:
            parent_closure &= item.parent_id is None
        else:
            parent = hierarchy_by_id.get(item.parent_id or "")
            parent_closure &= bool(
                parent is not None
                and parent.level + 1 == item.level
                and item.hierarchy_id in parent.children_ids
            )
        for child_id in item.children_ids:
            child = hierarchy_by_id.get(child_id)
            child_closure &= bool(
                child is not None
                and child.parent_id == item.hierarchy_id
                and child.level == item.level + 1
            )
        if item.children_ids:
            member_count_closure &= (
                sum(
                    hierarchy_by_id[child_id].member_count
                    for child_id in item.children_ids
                    if child_id in hierarchy_by_id
                )
                == item.member_count
            )
    node_paths = 0
    assigned_by_level: dict[int, set[str]] = {level: set() for level in _LEVELS}
    for node in artifact.nodes:
        path = (node.umbrella_id, node.subcommunity_id, node.microgenre_id)
        path_items = [hierarchy_by_id.get(identifier) for identifier in path]
        if any(item is None for item in path_items):
            valid = False
        else:
            umbrella, subcommunity, microgenre = path_items
            if umbrella is None or subcommunity is None or microgenre is None:
                valid = False
            else:
                valid = (
                    umbrella.level == 0
                    and subcommunity.level == 1
                    and microgenre.level == _MICROGENRE_LEVEL
                    and subcommunity.parent_id == umbrella.hierarchy_id
                    and microgenre.parent_id == subcommunity.hierarchy_id
                )
        if valid:
            node_paths += 1
            for level, identifier in enumerate(path):
                assigned_by_level[level].add(identifier)
    member_count_closure &= all(
        sum(node.umbrella_id == item.hierarchy_id for node in artifact.nodes) == item.member_count
        for item in artifact.hierarchy
        if item.level == 0
    )
    member_count_closure &= all(
        sum(node.subcommunity_id == item.hierarchy_id for node in artifact.nodes)
        == item.member_count
        for item in artifact.hierarchy
        if item.level == 1
    )
    member_count_closure &= all(
        sum(node.microgenre_id == item.hierarchy_id for node in artifact.nodes) == item.member_count
        for item in artifact.hierarchy
        if item.level == _MICROGENRE_LEVEL
    )
    levels = tuple(
        HierarchyLevelCoverage(
            level=level,
            level_name=_LEVEL_NAMES[level],
            hierarchy_node_count=sum(item.level == level for item in artifact.hierarchy),
            assigned_genre_count=node_paths,
            member_count=sum(
                item.member_count for item in artifact.hierarchy if item.level == level
            ),
            coverage=(node_paths / len(artifact.nodes) if artifact.nodes else 0.0),
            parent_closure=parent_closure,
            child_closure=child_closure,
            member_count_closure=member_count_closure,
        )
        for level in _LEVELS
    )
    assigned_genre_count = node_paths
    return HierarchyCoverageReport(
        artifact_node_count=len(artifact.nodes),
        hierarchy_node_count=len(artifact.hierarchy),
        assigned_genre_count=assigned_genre_count,
        genre_coverage=assigned_genre_count / len(artifact.nodes) if artifact.nodes else 0.0,
        parent_closure=parent_closure,
        child_closure=child_closure,
        member_count_closure=member_count_closure,
        node_path_closure=node_paths == len(artifact.nodes),
        levels=levels,
    )


def _size_distribution(
    artifact: HistoricalSignalArtifact, level: Literal[0, 1, 2]
) -> SizeDistributionReport:
    values = [item.member_count for item in artifact.hierarchy if item.level == level]
    return SizeDistributionReport(
        level=level,
        level_name=_LEVEL_NAMES[level],
        group_count=len(values),
        total_member_count=sum(values),
        minimum_member_count=min(values, default=0),
        maximum_member_count=max(values, default=0),
        mean_member_count=sum(values) / len(values) if values else 0.0,
        buckets=_size_buckets(values),
    )


def _size_buckets(values: list[int]) -> tuple[HistogramBucket, ...]:
    bounds = (1, 8, 25, 100, 350)
    return tuple(
        HistogramBucket(
            label=(f"{lower}-{bounds[index + 1] - 1}" if index + 1 < len(bounds) else f"{lower}+"),
            count=sum(
                value >= lower and (index + 1 == len(bounds) or value < bounds[index + 1])
                for value in values
            ),
        )
        for index, lower in enumerate(bounds)
    )


def _edge_retention(artifact: HistoricalSignalArtifact) -> tuple[HierarchyEdgeRetention, ...]:
    directed = {(edge.genre_id, edge.neighbor_genre_id) for edge in artifact.neighbors}
    union: set[tuple[str, str]] = {
        (left, right) if left < right else (right, left) for left, right in directed
    }
    reciprocal = {pair for pair in union if (pair[1], pair[0]) in directed}
    node_groups = _node_groups(artifact)
    return tuple(
        HierarchyEdgeRetention(
            level=level,
            level_name=_LEVEL_NAMES[level],
            internal_union_edge_count=sum(_same_group(pair, node_groups, level) for pair in union),
            internal_reciprocal_edge_count=sum(
                _same_group(pair, node_groups, level) for pair in reciprocal
            ),
            total_union_edge_count=len(union),
            total_reciprocal_edge_count=len(reciprocal),
            union_retention=_retention(union, node_groups, level),
            reciprocal_retention=_retention(reciprocal, node_groups, level),
            weighted_modularity=_weighted_modularity(artifact, node_groups, level),
        )
        for level in _LEVELS
    )


def _node_groups(artifact: HistoricalSignalArtifact) -> dict[int, dict[str, str]]:
    fields = ("umbrella_id", "subcommunity_id", "microgenre_id")
    return {
        level: {node.genre_id: getattr(node, fields[level]) for node in artifact.nodes}
        for level in _LEVELS
    }


def _same_group(pair: tuple[str, str], node_groups: dict[int, dict[str, str]], level: int) -> bool:
    groups = node_groups[level]
    return pair[0] in groups and pair[1] in groups and groups[pair[0]] == groups[pair[1]]


def _retention(
    pairs: set[tuple[str, str]], node_groups: dict[int, dict[str, str]], level: int
) -> float:
    return (
        sum(_same_group(pair, node_groups, level) for pair in pairs) / len(pairs) if pairs else 0.0
    )


def _weighted_modularity(
    artifact: HistoricalSignalArtifact, node_groups: dict[int, dict[str, str]], level: int
) -> float:
    """Compute weighted undirected modularity using max directed weighted-Jaccard edges."""
    directed_weights: dict[tuple[str, str], float] = {}
    for edge in artifact.neighbors:
        key = (edge.genre_id, edge.neighbor_genre_id)
        directed_weights[key] = max(directed_weights.get(key, 0.0), edge.weighted_jaccard)
    union_weights: dict[tuple[str, str], float] = {}
    for (left, right), weight in directed_weights.items():
        pair = (left, right) if left < right else (right, left)
        union_weights[pair] = max(union_weights.get(pair, 0.0), weight)
    total_weight = sum(union_weights.values())
    if total_weight <= 0.0:
        return 0.0
    degrees: dict[str, float] = {}
    internal_weights: dict[str, float] = {}
    groups = node_groups[level]
    for (left, right), weight in union_weights.items():
        degrees[left] = degrees.get(left, 0.0) + weight
        degrees[right] = degrees.get(right, 0.0) + weight
        if left in groups and right in groups and groups[left] == groups[right]:
            group = groups[left]
            internal_weights[group] = internal_weights.get(group, 0.0) + weight
    group_degree: dict[str, float] = {}
    for node_id, degree in degrees.items():
        if node_id in groups:
            group = groups[node_id]
            group_degree[group] = group_degree.get(group, 0.0) + degree
    return sum(
        internal_weights.get(group, 0.0) / total_weight
        - (group_degree[group] / (2.0 * total_weight)) ** 2
        for group in group_degree
    )


def _components(artifact: HistoricalSignalArtifact) -> ComponentFragmentationReport:
    sizes = Counter(node.component_id for node in artifact.nodes)
    levels: list[ComponentFragmentationLevel] = []
    fields = ("umbrella_id", "subcommunity_id", "microgenre_id")
    for level, field in zip(_LEVELS, fields, strict=True):
        groups: dict[str, set[int]] = {}
        for node in artifact.nodes:
            groups.setdefault(getattr(node, field), set()).add(node.component_id)
        component_counts = [len(values) for values in groups.values()]
        levels.append(
            ComponentFragmentationLevel(
                level=level,
                level_name=_LEVEL_NAMES[level],
                group_count=len(component_counts),
                disconnected_group_count=sum(value > 1 for value in component_counts),
                disconnected_group_fraction=(
                    sum(value > 1 for value in component_counts) / len(component_counts)
                    if component_counts
                    else 0.0
                ),
                maximum_component_count=max(component_counts, default=0),
                mean_component_count=(
                    sum(component_counts) / len(component_counts) if component_counts else 0.0
                ),
            )
        )
    return ComponentFragmentationReport(
        graph_component_count=len(sizes),
        graph_isolate_count=sum(value == 1 for value in sizes.values()),
        largest_component_size=max(sizes.values(), default=0),
        levels=tuple(levels),
    )


def _lexical_sample(
    artifact: HistoricalSignalArtifact, cohort: str, terms: tuple[str, ...]
) -> LexicalCohortSample:
    normalized_terms = tuple(_normalize_text(term) for term in terms)
    matches = [
        (node.genre_id, node.name)
        for node in artifact.nodes
        if any(_phrase_in_name(node.name, term) for term in normalized_terms)
    ]
    matches.sort(key=lambda item: (item[1].casefold(), item[0]))
    return LexicalCohortSample(
        cohort=cohort,
        terms=terms,
        matched_node_count=len(matches),
        sample=tuple(matches[:_COHORT_SAMPLE_LIMIT]),
    )


def _normalize_text(value: str) -> str:
    return " ".join(_NON_WORDS.sub(" ", unicodedata.normalize("NFKC", value).casefold()).split())


def _phrase_in_name(name: str, phrase: str) -> bool:
    normalized_name = f" {_normalize_text(name)} "
    return f" {_normalize_text(phrase)} " in normalized_name


def _compare(
    current: HistoricalHierarchyEvaluation, baseline: HistoricalHierarchyEvaluation
) -> BaselineComparison:
    current_levels = {item.level: item for item in current.level_size_distributions}
    baseline_levels = {item.level: item for item in baseline.level_size_distributions}
    current_edges = {item.level: item for item in current.edge_retention}
    baseline_edges = {item.level: item for item in baseline.edge_retention}
    current_cohorts = {item.cohort: item.matched_node_count for item in current.lexical_cohorts}
    baseline_cohorts = {item.cohort: item.matched_node_count for item in baseline.lexical_cohorts}
    return BaselineComparison(
        baseline_artifact_sha256=baseline.source_artifact_sha256,
        current_artifact_sha256=current.source_artifact_sha256,
        node_count_delta=(
            current.coverage.artifact_node_count - baseline.coverage.artifact_node_count
        ),
        hierarchy_node_count_delta=(
            current.coverage.hierarchy_node_count - baseline.coverage.hierarchy_node_count
        ),
        umbrella_count_delta=(
            current.umbrella_size_distribution.group_count
            - baseline.umbrella_size_distribution.group_count
        ),
        genre_coverage_delta=current.coverage.genre_coverage - baseline.coverage.genre_coverage,
        parent_closure_changed=current.coverage.parent_closure != baseline.coverage.parent_closure,
        edge_retention=tuple(
            LevelComparison(
                level=level,
                level_name=_LEVEL_NAMES[level],
                group_count_delta=(
                    current_levels[level].group_count - baseline_levels[level].group_count
                ),
                maximum_member_count_delta=(
                    current_levels[level].maximum_member_count
                    - baseline_levels[level].maximum_member_count
                ),
                union_retention_delta=(
                    current_edges[level].union_retention - baseline_edges[level].union_retention
                ),
                reciprocal_retention_delta=(
                    current_edges[level].reciprocal_retention
                    - baseline_edges[level].reciprocal_retention
                ),
                weighted_modularity_delta=(
                    current_edges[level].weighted_modularity
                    - baseline_edges[level].weighted_modularity
                ),
            )
            for level in _LEVELS
        ),
        lexical_cohort_match_count_delta=tuple(
            (cohort, current_cohorts.get(cohort, 0) - baseline_cohorts.get(cohort, 0))
            for cohort in current_cohorts
        ),
    )


__all__ = ["HistoricalHierarchyEvaluation", "evaluate_historical_hierarchy"]
