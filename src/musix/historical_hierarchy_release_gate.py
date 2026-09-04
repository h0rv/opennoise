"""Independent release-gate checks for a graph-derived historical hierarchy."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from musix.models import FrozenModel
from musix.models.historical_signal import (  # noqa: TC001
    HistoricalSignalArtifact,
    HistoricalSignalHierarchyNode,
    HistoricalSignalNode,
)
from musix.types import Sha256  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Mapping

_TOP_LEVEL = 0
_SUBCOMMUNITY_LEVEL = 1
_MICROGENRE_LEVEL = 2
_TOP_LEVEL_CAP = 24
_SUBCOMMUNITY_MEMBER_CAP = 96
_MICROGENRE_MEMBER_CAP = 24
_LARGE_TOP_MEMBER_THRESHOLD = 100
_MIN_LARGE_TOP_CHILDREN = 2
_SPOT_FAMILIES = ("Electronic", "Latin", "Hip-hop", "Rock", "Metal", "Jazz", "Classical")
_FAMILY_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Electronic", ("electronic", "electro", "house", "techno", "edm", "idm", "trance")),
    ("Hip-hop", ("hip hop", "rap")),
    ("Rock", ("rock",)),
    ("Metal", ("metal",)),
    ("Jazz", ("jazz", "bebop")),
    ("Classical", ("classical", "classique")),
    ("Latin", ("latin", "salsa", "reggaeton", "bachata", "merengue", "cumbia", "samba", "bossa")),
)
_NON_WORDS = re.compile(r"[^\w]+", re.UNICODE)


class LexicalParentConflict(FrozenModel):
    """One evaluation-only family mismatch between a child and its parent."""

    hierarchy_id: str = Field(min_length=1, max_length=200)
    representative_label: str = Field(min_length=1, max_length=500)
    parent_id: str = Field(min_length=1, max_length=200)
    parent_label: str = Field(min_length=1, max_length=500)
    child_family: str = Field(min_length=1, max_length=40)
    parent_family: str = Field(min_length=1, max_length=40)
    evaluation_only: Literal[True] = True


class FamilyPathSpotCheck(FrozenModel):
    """Child-count and path-closure facts for one explicit lexical family sample."""

    family: str = Field(min_length=1, max_length=40)
    evaluation_only: Literal[True] = True
    matching_top_count: int = Field(ge=0)
    matching_top_ids: tuple[str, ...] = Field(max_length=24)
    matching_top_member_count: int = Field(ge=0)
    matching_top_child_count: int = Field(ge=0)
    matching_subcommunity_count: int = Field(ge=0)
    matching_microgenre_count: int = Field(ge=0)
    path_node_count: int = Field(ge=0)
    path_closed_node_count: int = Field(ge=0)
    path_closed: bool


class HistoricalHierarchyReleaseGateReport(FrozenModel):
    """Structural release-gate results without clustering or semantic ground-truth claims."""

    revision: Literal["historical-hierarchy-release-gate-v1"] = (
        "historical-hierarchy-release-gate-v1"
    )
    source_artifact_sha256: Sha256
    evaluation_only: Literal[True] = True
    genre_count: int = Field(ge=0)
    duplicate_genre_id_count: int = Field(ge=0)
    hierarchy_node_count: int = Field(ge=0)
    top_level_count: int = Field(ge=0)
    max_subcommunity_member_count: int = Field(ge=0)
    max_microgenre_member_count: int = Field(ge=0)
    every_genre_assigned_exactly_once: bool
    top_level_within_cap: bool
    subcommunities_within_cap: bool
    microgenres_within_cap: bool
    large_top_families_have_multiple_children: bool
    parent_lexical_conflicts_free: bool
    passed: bool
    large_top_family_violations: tuple[str, ...] = Field(max_length=24)
    lexical_parent_conflicts: tuple[LexicalParentConflict, ...] = Field(max_length=500)
    family_spot_checks: tuple[FamilyPathSpotCheck, ...] = Field(min_length=7, max_length=7)


def evaluate_historical_hierarchy_release_gate(
    artifact: HistoricalSignalArtifact,
) -> HistoricalHierarchyReleaseGateReport:
    """Evaluate structural caps, path closure, lexical conflicts, and family spot checks."""
    hierarchy = {item.hierarchy_id: item for item in artifact.hierarchy}
    nodes_by_id = {node.genre_id: node for node in artifact.nodes}
    duplicate_count = len(artifact.nodes) - len(nodes_by_id)
    path_closed = all(_node_path_is_closed(node, hierarchy) for node in artifact.nodes)
    assigned_once = duplicate_count == 0 and path_closed
    top = tuple(item for item in artifact.hierarchy if item.level == _TOP_LEVEL)
    subcommunities = tuple(item for item in artifact.hierarchy if item.level == _SUBCOMMUNITY_LEVEL)
    microgenres = tuple(item for item in artifact.hierarchy if item.level == _MICROGENRE_LEVEL)
    large_violations = tuple(
        item.hierarchy_id
        for item in top
        if (
            item.member_count >= _LARGE_TOP_MEMBER_THRESHOLD
            and len(item.children_ids) < _MIN_LARGE_TOP_CHILDREN
        )
    )
    conflicts = _lexical_parent_conflicts(artifact)
    spot_checks = tuple(_family_spot_check(artifact, family) for family in _SPOT_FAMILIES)
    top_ok = len(top) <= _TOP_LEVEL_CAP
    sub_ok = (
        max((item.member_count for item in subcommunities), default=0) <= _SUBCOMMUNITY_MEMBER_CAP
    )
    micro_ok = max((item.member_count for item in microgenres), default=0) <= _MICROGENRE_MEMBER_CAP
    large_ok = not large_violations
    conflict_free = not conflicts
    return HistoricalHierarchyReleaseGateReport(
        source_artifact_sha256=artifact.quality.artifact_sha256,
        genre_count=len(artifact.nodes),
        duplicate_genre_id_count=duplicate_count,
        hierarchy_node_count=len(artifact.hierarchy),
        top_level_count=len(top),
        max_subcommunity_member_count=max(
            (item.member_count for item in subcommunities), default=0
        ),
        max_microgenre_member_count=max((item.member_count for item in microgenres), default=0),
        every_genre_assigned_exactly_once=assigned_once,
        top_level_within_cap=top_ok,
        subcommunities_within_cap=sub_ok,
        microgenres_within_cap=micro_ok,
        large_top_families_have_multiple_children=large_ok,
        parent_lexical_conflicts_free=conflict_free,
        passed=all((assigned_once, top_ok, sub_ok, micro_ok, large_ok, conflict_free)),
        large_top_family_violations=large_violations,
        lexical_parent_conflicts=conflicts,
        family_spot_checks=spot_checks,
    )


def _node_path_is_closed(
    node: HistoricalSignalNode, hierarchy: Mapping[str, HistoricalSignalHierarchyNode]
) -> bool:
    umbrella_id = node.umbrella_id
    subcommunity_id = node.subcommunity_id
    microgenre_id = node.microgenre_id
    umbrella = hierarchy.get(umbrella_id)
    subcommunity = hierarchy.get(subcommunity_id)
    microgenre = hierarchy.get(microgenre_id)
    if umbrella is None or subcommunity is None or microgenre is None:
        return False
    return bool(
        umbrella.level == _TOP_LEVEL
        and subcommunity.level == _SUBCOMMUNITY_LEVEL
        and microgenre.level == _MICROGENRE_LEVEL
        and subcommunity.parent_id == umbrella_id
        and microgenre.parent_id == subcommunity_id
        and subcommunity_id in umbrella.children_ids
        and microgenre_id in subcommunity.children_ids
    )


def _lexical_parent_conflicts(
    artifact: HistoricalSignalArtifact,
) -> tuple[LexicalParentConflict, ...]:
    hierarchy = {item.hierarchy_id: item for item in artifact.hierarchy}
    conflicts: list[LexicalParentConflict] = []
    for item in artifact.hierarchy:
        if item.level != _SUBCOMMUNITY_LEVEL or item.parent_id is None:
            continue
        parent = hierarchy.get(item.parent_id)
        if parent is None:
            continue
        child_family = _classify_family(item.representative_label)
        parent_family = _classify_family(parent.representative_label)
        if child_family is None or parent_family is None or child_family == parent_family:
            continue
        conflicts.append(
            LexicalParentConflict(
                hierarchy_id=item.hierarchy_id,
                representative_label=item.representative_label,
                parent_id=parent.hierarchy_id,
                parent_label=parent.representative_label,
                child_family=child_family,
                parent_family=parent_family,
            )
        )
    return tuple(conflicts)


def _family_spot_check(artifact: HistoricalSignalArtifact, family: str) -> FamilyPathSpotCheck:
    hierarchy = {item.hierarchy_id: item for item in artifact.hierarchy}
    top = tuple(
        item
        for item in artifact.hierarchy
        if item.level == _TOP_LEVEL and _classify_family(item.representative_label) == family
    )
    top_ids = {item.hierarchy_id for item in top}
    sub = tuple(
        item
        for item in artifact.hierarchy
        if item.level == _SUBCOMMUNITY_LEVEL and item.parent_id in top_ids
    )
    micro = tuple(
        item
        for item in artifact.hierarchy
        if item.level == _MICROGENRE_LEVEL and item.parent_id in {item.hierarchy_id for item in sub}
    )
    path_nodes = tuple(node for node in artifact.nodes if node.umbrella_id in top_ids)
    closed_count = sum(_node_path_is_closed(node, hierarchy) for node in path_nodes)
    return FamilyPathSpotCheck(
        family=family,
        matching_top_count=len(top),
        matching_top_ids=tuple(item.hierarchy_id for item in top),
        matching_top_member_count=sum(item.member_count for item in top),
        matching_top_child_count=sum(len(item.children_ids) for item in top),
        matching_subcommunity_count=len(sub),
        matching_microgenre_count=len(micro),
        path_node_count=len(path_nodes),
        path_closed_node_count=closed_count,
        path_closed=closed_count == len(path_nodes),
    )


def _classify_family(label: str) -> str | None:
    normalized = f" {_normalize(label)} "
    for family, terms in _FAMILY_TERMS:
        if any(f" {_normalize(term)} " in normalized for term in terms):
            return family
    return None


def _normalize(value: str) -> str:
    return " ".join(_NON_WORDS.sub(" ", unicodedata.normalize("NFKC", value).casefold()).split())


__all__ = [
    "HistoricalHierarchyReleaseGateReport",
    "evaluate_historical_hierarchy_release_gate",
]
