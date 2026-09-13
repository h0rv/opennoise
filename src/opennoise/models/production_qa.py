"""Strict, renderer-neutral acceptance records for the production genre map."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Literal

from pydantic import Field, FiniteFloat, model_validator

from opennoise.models.web import FrozenModel

_RANDOM_NULL_TOLERANCE = 1e-12
_MIN_DESKTOP_OVERVIEW_LABELS = 18
_MIN_MOBILE_OVERVIEW_LABELS = 6


class ProductionMapCoordinate(FrozenModel):
    """One normalized production-map position."""

    entity_id: str = Field(min_length=1, max_length=200)
    x: FiniteFloat = Field(ge=0.0, le=1.0)
    y: FiniteFloat = Field(ge=0.0, le=1.0)


class ProductionMapLabelBox(FrozenModel):
    """One rendered label's screen bounds in a named viewport."""

    entity_id: str = Field(min_length=1, max_length=200)
    min_x: FiniteFloat = Field(ge=0.0)
    min_y: FiniteFloat = Field(ge=0.0)
    max_x: FiniteFloat = Field(gt=0.0)
    max_y: FiniteFloat = Field(gt=0.0)
    font_size_px: FiniteFloat = Field(gt=0.0, le=128.0)

    @model_validator(mode="after")
    def require_nonempty_bounds(self) -> ProductionMapLabelBox:
        """Reject labels which cannot occupy visible screen space."""
        if self.min_x >= self.max_x or self.min_y >= self.max_y:
            raise ValueError("label bounds must have positive area")
        return self


class ProductionMapLod(FrozenModel):
    """Visible nodes and label decisions for one persistent semantic zoom level."""

    level: int = Field(ge=0, le=10)
    visible_entity_ids: tuple[str, ...] = Field(default=(), max_length=20_000)
    visible_overview_community_ids: tuple[str, ...] = Field(default=(), max_length=24)
    desktop_labels: tuple[ProductionMapLabelBox, ...] = Field(max_length=4_000)
    mobile_labels: tuple[ProductionMapLabelBox, ...] = Field(max_length=4_000)

    @model_validator(mode="after")
    def require_unique_visible_entities_and_labels(self) -> ProductionMapLod:
        """Keep the LOD record deterministic and self-contained."""
        visible = set(self.visible_entity_ids)
        if len(visible) != len(self.visible_entity_ids):
            raise ValueError("visible entities must be unique")
        visible_labels = set(self.visible_entity_ids) | set(self.visible_overview_community_ids)
        if not visible_labels:
            raise ValueError("a semantic-zoom level must expose a map item")
        if len(self.visible_overview_community_ids) != len(
            set(self.visible_overview_community_ids)
        ):
            raise ValueError("visible overview communities must be unique")
        for name, labels in (("desktop", self.desktop_labels), ("mobile", self.mobile_labels)):
            ids = [label.entity_id for label in labels]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{name} labels must be unique")
            if not set(ids).issubset(visible_labels):
                raise ValueError(f"{name} labels must belong to visible map items")
        return self


class ProductionMapRegion(FrozenModel):
    """One visible hierarchy subtree region emitted by the model, never inferred by UI."""

    region_id: str = Field(min_length=1, max_length=200)
    owner_entity_id: str = Field(min_length=1, max_length=200)
    entity_ids: tuple[str, ...] = Field(min_length=1, max_length=20_000)
    min_x: FiniteFloat = Field(ge=0.0, le=1.0)
    min_y: FiniteFloat = Field(ge=0.0, le=1.0)
    max_x: FiniteFloat = Field(ge=0.0, le=1.0)
    max_y: FiniteFloat = Field(ge=0.0, le=1.0)
    is_root: bool = False
    allow_overlap: bool = False

    @model_validator(mode="after")
    def require_nonempty_region_and_unique_entities(self) -> ProductionMapRegion:
        """Reject empty and ambiguous region declarations."""
        if self.min_x >= self.max_x or self.min_y >= self.max_y:
            raise ValueError("region bounds must have positive area")
        if len(self.entity_ids) != len(set(self.entity_ids)):
            raise ValueError("region entities must be unique")
        return self


class ProductionMapUmbrellaCentroid(FrozenModel):
    """One explicit overview anchor derived from a display-tree root's descendants."""

    root_entity_id: str = Field(min_length=1, max_length=200)
    descendant_entity_ids: tuple[str, ...] = Field(min_length=1, max_length=20_000)
    x: FiniteFloat = Field(ge=0.0, le=1.0)
    y: FiniteFloat = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def require_unique_descendants(self) -> ProductionMapUmbrellaCentroid:
        """Reject an ambiguous umbrella population."""
        if len(self.descendant_entity_ids) != len(set(self.descendant_entity_ids)):
            raise ValueError("umbrella centroid descendants must be unique")
        if self.root_entity_id not in self.descendant_entity_ids:
            raise ValueError("umbrella centroid must include its root entity")
        return self


class ProductionMapOverviewNaming(FrozenModel):
    """Explain the public umbrella name assigned to one overview community."""

    method: Literal[
        "canonical_taxonomy_ancestor_weighted_coverage_v1",
        "community_centrality_fallback_v1",
    ]
    anchor_entity_id: str = Field(min_length=1, max_length=200)
    weighted_coverage: FiniteFloat = Field(ge=0.0, le=1.0)
    provenance_refs: tuple[str, ...] = Field(min_length=1, max_length=32)


class ProductionMapOverviewCommunity(FrozenModel):
    """One model-emitted overview community with an exact coordinate provenance."""

    community_id: str = Field(min_length=1, max_length=200)
    member_entity_ids: tuple[str, ...] = Field(min_length=1, max_length=20_000)
    name: str = Field(min_length=1, max_length=500)
    naming: ProductionMapOverviewNaming
    x: FiniteFloat = Field(ge=0.0, le=1.0)
    y: FiniteFloat = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def require_unique_members(self) -> ProductionMapOverviewCommunity:
        """Keep the community population auditable and deterministic."""
        if len(self.member_entity_ids) != len(set(self.member_entity_ids)):
            raise ValueError("overview community members must be unique")
        return self


class ProductionMapPresentationParent(FrozenModel):
    """The explicit, explainable one-parent rendering choice for a DAG node."""

    child_id: str = Field(min_length=1, max_length=200)
    parent_id: str | None = Field(default=None, min_length=1, max_length=200)
    relation: Literal["taxonomy", "generated_community", "none"]
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def require_consistent_parent_choice(self) -> ProductionMapPresentationParent:
        """Make synthetic and absent parents explicit rather than implicit UI behavior."""
        if self.relation == "none" and self.parent_id is not None:
            raise ValueError("an absent presentation parent cannot have a parent ID")
        if self.relation != "none" and self.parent_id is None:
            raise ValueError("a presentation parent relation needs a parent ID")
        if self.parent_id == self.child_id:
            raise ValueError("a presentation parent cannot point at itself")
        return self


class ProductionMapEligibleSet(FrozenModel):
    """One query's exact eligible pool for deterministic neighborhood QA."""

    query_entity_id: str = Field(min_length=1, max_length=200)
    eligible_candidate_count: int = Field(ge=1, le=19_999)
    reference_neighbor_count: int = Field(ge=0, le=10)
    eligible_candidate_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def require_reference_neighbors_within_eligible_pool(self) -> ProductionMapEligibleSet:
        """Reject source-neighbor claims outside the layout's eligible pool."""
        if self.reference_neighbor_count > self.eligible_candidate_count:
            raise ValueError("reference neighbor count exceeds the eligible candidate pool")
        return self


class ProductionMapSimilarityEvidence(FrozenModel):
    """Comparable source-space and layout-space neighborhood evidence."""

    source_model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_neighbor_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_coordinate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_baseline_model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_baseline_neighbor_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_baseline_coordinate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    eligibility_rule_version: str = Field(min_length=1, max_length=200)
    eligible_sets_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_baseline_eligibility_rule_version: str = Field(min_length=1, max_length=200)
    canonical_baseline_eligible_sets_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluated_entity_count: int = Field(ge=1, le=20_000)
    eligible_sets: tuple[ProductionMapEligibleSet, ...] = Field(min_length=1, max_length=20_000)
    top_10_recall: FiniteFloat = Field(ge=0.0, le=1.0)
    top_25_recall: FiniteFloat = Field(ge=0.0, le=1.0)
    canonical_baseline_top_10_recall: FiniteFloat = Field(ge=0.0, le=1.0)
    random_top_10_recall: FiniteFloat = Field(ge=0.0, le=1.0)
    metric: Literal["one_hop_weighted_jaccard"] = "one_hop_weighted_jaccard"

    @model_validator(mode="after")
    def require_meaningful_baseline(self) -> ProductionMapSimilarityEvidence:
        """Require a comparable, non-random canonical reference for map selection."""
        if self.source_model_sha256 != self.canonical_baseline_model_sha256:
            raise ValueError("candidate and canonical baseline must use the same source model hash")
        if self.source_neighbor_sha256 != self.canonical_baseline_neighbor_sha256:
            raise ValueError("candidate and canonical baseline must use the same neighbor hash")
        if self.eligibility_rule_version != self.canonical_baseline_eligibility_rule_version:
            raise ValueError("candidate and canonical baseline must use the same eligibility rule")
        if self.eligible_sets_sha256 != self.canonical_baseline_eligible_sets_sha256:
            raise ValueError("candidate and canonical baseline must use the same eligible-set hash")
        if self.evaluated_entity_count != len(self.eligible_sets):
            raise ValueError("eligible sets must match the evaluated entity count")
        query_ids = [entry.query_entity_id for entry in self.eligible_sets]
        if len(query_ids) != len(set(query_ids)):
            raise ValueError("eligible sets must have one record per query entity")
        if self.eligible_sets_sha256 != hash_eligible_sets(self.eligible_sets):
            raise ValueError("eligible-set hash must match its exact ordered query records")
        expected_random = sum(
            min(10, entry.reference_neighbor_count) / entry.eligible_candidate_count
            for entry in self.eligible_sets
        ) / len(self.eligible_sets)
        if abs(self.random_top_10_recall - expected_random) > _RANDOM_NULL_TOLERANCE:
            raise ValueError("random top-10 recall must match the exact eligible-neighbor null")
        if self.canonical_baseline_top_10_recall <= self.random_top_10_recall:
            raise ValueError("canonical neighborhood baseline must exceed its random null")
        return self


def hash_eligible_sets(entries: tuple[ProductionMapEligibleSet, ...]) -> str:
    """Hash exactly the variable eligible pools used by the random-null calculation."""
    payload = [
        {
            "eligible_candidate_count": entry.eligible_candidate_count,
            "eligible_candidate_ids_sha256": entry.eligible_candidate_ids_sha256,
            "query_entity_id": entry.query_entity_id,
            "reference_neighbor_count": entry.reference_neighbor_count,
        }
        for entry in sorted(entries, key=lambda entry: entry.query_entity_id)
    ]
    return sha256(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


class ProductionMapScreenshot(FrozenModel):
    """A reproducibly generated visual QA capture, never a hand supplied claim."""

    viewport: Literal["desktop", "mobile"]
    color_scheme: Literal["light", "dark", "system"]
    width: int = Field(gt=0, le=10_000)
    height: int = Field(gt=0, le=10_000)
    path: str = Field(min_length=1, max_length=1_000)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(gt=0, le=100_000_000)


class ProductionMapInteractionEvidence(FrozenModel):
    """Deterministic end-to-end checks captured by the UI harness."""

    drag_pan: bool
    touch_pan: bool
    wheel_zoom: bool
    pinch_zoom: bool
    click_opens_detail: bool
    search_preserves_map_state: bool
    browser_back_restores_map_state: bool
    no_javascript_svg_fallback: bool
    keyboard_focus_visible: bool
    dark_mode_toggle: bool
    overview_focus_reveals_label: bool

    @model_validator(mode="after")
    def require_every_interaction_to_pass(self) -> ProductionMapInteractionEvidence:
        """Fail closed rather than serializing a browser failure as release evidence."""
        failed = [name for name, passed in self.model_dump(mode="python").items() if not passed]
        if failed:
            raise ValueError(
                "interaction/accessibility evidence contains failed checks: " + ", ".join(failed)
            )
        return self


class StaticProductionMapInteractionEvidence(FrozenModel):
    """Browser proof for the no-runtime-layout public SVG renderer."""

    evidence_kind: Literal["static_public_map"] = "static_public_map"
    fit_route: bool
    url_lod_control: bool
    native_scroll: bool
    programmatic_scroll: bool
    ordinary_genre_link: bool
    no_runtime_graph_assets: bool
    no_browser_errors: bool

    @model_validator(mode="after")
    def require_every_static_check_to_pass(self) -> StaticProductionMapInteractionEvidence:
        """Keep static evidence as fail-closed as the legacy interaction contract."""
        failed = [
            name
            for name, passed in self.model_dump(mode="python").items()
            if isinstance(passed, bool) and not passed
        ]
        if failed:
            raise ValueError("static map evidence contains failed checks: " + ", ".join(failed))
        return self


def _validate_hierarchy_regions(
    regions: tuple[ProductionMapRegion, ...],
    coordinate_ids: set[str],
    presentation_parents: tuple[ProductionMapPresentationParent, ...],
) -> None:
    """Require one exact subtree region for every presentation-tree node."""
    children = _validate_region_owners(regions, coordinate_ids, presentation_parents)
    _validate_region_subtrees(regions, children)


def _display_subtrees(
    coordinate_ids: set[str],
    presentation_parents: tuple[ProductionMapPresentationParent, ...],
) -> tuple[set[str], dict[str, set[str]]]:
    """Return exact roots and descendant populations from explicit parent choices."""
    parent_by_child = {choice.child_id: choice.parent_id for choice in presentation_parents}
    if set(parent_by_child) != coordinate_ids:
        raise ValueError("every production coordinate needs an explicit presentation parent")
    roots = {child_id for child_id, parent_id in parent_by_child.items() if parent_id is None}
    children: dict[str, set[str]] = {}
    for child_id, parent_id in parent_by_child.items():
        if parent_id is not None and parent_id in coordinate_ids:
            children.setdefault(parent_id, set()).add(child_id)

    def descendants(owner_entity_id: str) -> set[str]:
        result: set[str] = set()
        pending = [owner_entity_id]
        while pending:
            current = pending.pop()
            if current in result:
                raise ValueError("presentation tree cannot contain a cycle")
            result.add(current)
            pending.extend(children.get(current, set()))
        return result

    return roots, {
        owner_entity_id: descendants(owner_entity_id) for owner_entity_id in coordinate_ids
    }


def _validate_similarity_first_centroids(
    value: ProductionMapAcceptanceInput,
    coordinate_ids: set[str],
) -> None:
    """Require exact, inspectable overview anchors without claiming containment geometry."""
    roots, descendant_sets = _display_subtrees(coordinate_ids, value.presentation_parents)
    if {item.root_entity_id for item in value.umbrella_centroids} != roots:
        raise ValueError("similarity-first map needs one derived umbrella centroid per root")
    coordinate_by_id = {item.entity_id: item for item in value.coordinates}
    for centroid in value.umbrella_centroids:
        descendants = descendant_sets[centroid.root_entity_id]
        if set(centroid.descendant_entity_ids) != descendants:
            raise ValueError("umbrella centroid must name its exact display subtree")
        expected_x = sum(float(coordinate_by_id[item].x) for item in descendants) / len(descendants)
        expected_y = sum(float(coordinate_by_id[item].y) for item in descendants) / len(descendants)
        if (
            abs(float(centroid.x) - expected_x) > _RANDOM_NULL_TOLERANCE
            or abs(float(centroid.y) - expected_y) > _RANDOM_NULL_TOLERANCE
        ):
            raise ValueError(
                "umbrella centroid must be derived from its declared descendant coordinates"
            )
    _validate_overview_communities(
        value.overview_communities,
        coordinate_ids,
        value.coordinates,
        value.lods,
    )


def _validate_overview_communities(
    communities: tuple[ProductionMapOverviewCommunity, ...],
    coordinate_ids: set[str],
    coordinates: tuple[ProductionMapCoordinate, ...],
    lods: tuple[ProductionMapLod, ...],
) -> None:
    """Require a bounded, exact, synthetic overview instead of every taxonomy root."""
    if not communities:
        raise ValueError("similarity-first map needs model-emitted overview communities")
    community_ids = [community.community_id for community in communities]
    if len(community_ids) != len(set(community_ids)):
        raise ValueError("overview community IDs must be unique")
    members = [member for community in communities for member in community.member_entity_ids]
    if set(members) != coordinate_ids or len(members) != len(set(members)):
        raise ValueError("overview communities must partition every mapped coordinate exactly once")
    coordinate_by_id = {item.entity_id: item for item in coordinates}
    for community in communities:
        expected_x = sum(
            float(coordinate_by_id[entity_id].x) for entity_id in community.member_entity_ids
        ) / len(community.member_entity_ids)
        expected_y = sum(
            float(coordinate_by_id[entity_id].y) for entity_id in community.member_entity_ids
        ) / len(community.member_entity_ids)
        if (
            abs(float(community.x) - expected_x) > _RANDOM_NULL_TOLERANCE
            or abs(float(community.y) - expected_y) > _RANDOM_NULL_TOLERANCE
        ):
            raise ValueError(
                "overview community centroid must match its declared member coordinates"
            )

    overview = min(lods, key=lambda item: item.level)
    if set(overview.visible_overview_community_ids) != set(community_ids):
        raise ValueError("overview LOD must expose every model-emitted overview community")
    _validate_overview_label_coverage(overview, set(community_ids))
    if any(lod.visible_overview_community_ids for lod in lods if lod.level != overview.level):
        raise ValueError("overview communities may only appear at the overview LOD")


def _validate_overview_label_coverage(overview: ProductionMapLod, community_ids: set[str]) -> None:
    """Require useful collision-free overview coverage on each target viewport."""
    for viewport, labels, minimum in (
        ("desktop", overview.desktop_labels, _MIN_DESKTOP_OVERVIEW_LABELS),
        ("mobile", overview.mobile_labels, _MIN_MOBILE_OVERVIEW_LABELS),
    ):
        label_ids = {label.entity_id for label in labels}
        if not label_ids.issubset(community_ids):
            raise ValueError(f"overview {viewport} labels must identify overview communities")
        required_count = min(minimum, len(community_ids))
        if len(label_ids) < required_count:
            raise ValueError(
                f"overview LOD must label at least {required_count} {viewport} overview communities"
            )


def _validate_layout_semantics(
    value: ProductionMapAcceptanceInput,
    coordinate_ids: set[str],
) -> None:
    """Validate the geometry claims appropriate to the declared layout semantics."""
    if value.layout_semantics == "hierarchy_containment":
        if not value.regions:
            raise ValueError("containment map needs hierarchy regions")
        if value.umbrella_centroids:
            raise ValueError("containment map cannot substitute umbrella centroids for regions")
        _validate_hierarchy_regions(value.regions, coordinate_ids, value.presentation_parents)
        return
    if value.regions:
        raise ValueError("similarity-first map cannot claim containment regions")
    _validate_similarity_first_centroids(value, coordinate_ids)


def _validate_region_owners(
    regions: tuple[ProductionMapRegion, ...],
    coordinate_ids: set[str],
    presentation_parents: tuple[ProductionMapPresentationParent, ...],
) -> dict[str, set[str]]:
    """Validate region identity, owners, roots, and direct display-tree links."""
    _validate_region_shapes(regions, coordinate_ids)
    if any(region.is_root and region.allow_overlap for region in regions):
        raise ValueError("root hierarchy regions cannot opt out of overlap validation")
    if len({region.region_id for region in regions}) != len(regions):
        raise ValueError("hierarchy region IDs must be unique")
    if len({region.owner_entity_id for region in regions}) != len(regions):
        raise ValueError("every production coordinate needs exactly one hierarchy region")
    if {region.owner_entity_id for region in regions} != coordinate_ids:
        raise ValueError("every production coordinate needs one hierarchy region")
    parent_by_child = {choice.child_id: choice.parent_id for choice in presentation_parents}
    roots = {child_id for child_id, parent_id in parent_by_child.items() if parent_id is None}
    root_region_owners = {region.owner_entity_id for region in regions if region.is_root}
    if root_region_owners != roots:
        raise ValueError("root hierarchy regions must exactly match presentation-tree roots")
    children: dict[str, set[str]] = {}
    for child_id, parent_id in parent_by_child.items():
        if parent_id is not None and parent_id in coordinate_ids:
            children.setdefault(parent_id, set()).add(child_id)
    return children


def _validate_region_shapes(
    regions: tuple[ProductionMapRegion, ...], coordinate_ids: set[str]
) -> None:
    """Require region owners and declared members to belong to the map."""
    for region in regions:
        if not set(region.entity_ids).issubset(coordinate_ids):
            raise ValueError("region contains an entity without a coordinate")
        if region.owner_entity_id not in coordinate_ids:
            raise ValueError("region owner must have a production coordinate")
        if region.owner_entity_id not in region.entity_ids:
            raise ValueError("region must contain its owner entity")


def _validate_region_subtrees(
    regions: tuple[ProductionMapRegion, ...], children: dict[str, set[str]]
) -> None:
    """Require each declared region to cover exactly its explicit display subtree."""

    def descendants(owner_entity_id: str) -> set[str]:
        result: set[str] = set()
        pending = [owner_entity_id]
        while pending:
            current = pending.pop()
            if current in result:
                raise ValueError("presentation tree cannot contain a cycle")
            result.add(current)
            pending.extend(children.get(current, set()))
        return result

    for region in regions:
        if set(region.entity_ids) != descendants(region.owner_entity_id):
            raise ValueError("hierarchy region must cover exactly its owner's display subtree")


class ProductionMapAcceptanceInput(FrozenModel):
    """All evidence needed to accept or reject one production-map artifact."""

    revision: str = Field(min_length=1, max_length=100)
    layout_semantics: Literal["hierarchy_containment", "similarity_first_non_containment"]
    coordinate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    coordinates: tuple[ProductionMapCoordinate, ...] = Field(min_length=26, max_length=20_000)
    taxonomy_edges: tuple[tuple[str, str], ...] = Field(max_length=100_000)
    presentation_parents: tuple[ProductionMapPresentationParent, ...] = Field(max_length=20_000)
    regions: tuple[ProductionMapRegion, ...] = Field(default=(), max_length=20_000)
    umbrella_centroids: tuple[ProductionMapUmbrellaCentroid, ...] = Field(
        default=(), max_length=20_000
    )
    overview_communities: tuple[ProductionMapOverviewCommunity, ...] = Field(
        default=(), max_length=24
    )
    lods: tuple[ProductionMapLod, ...] = Field(min_length=1, max_length=11)
    similarity: ProductionMapSimilarityEvidence
    screenshots: tuple[ProductionMapScreenshot, ...] = Field(default=(), max_length=12)
    interactions: (
        ProductionMapInteractionEvidence | StaticProductionMapInteractionEvidence | None
    ) = None

    @model_validator(mode="after")
    def require_consistent_production_map(self) -> ProductionMapAcceptanceInput:
        """Reject incomplete artifacts before numerical acceptance is attempted."""
        coordinate_ids = {coordinate.entity_id for coordinate in self.coordinates}
        if len(coordinate_ids) != len(self.coordinates):
            raise ValueError("coordinates must have unique entity IDs")
        if len(self.lods) != len({lod.level for lod in self.lods}):
            raise ValueError("LOD levels must be unique")
        for lod in self.lods:
            if not set(lod.visible_entity_ids).issubset(coordinate_ids):
                raise ValueError("LOD contains an entity without a coordinate")
        _validate_layout_semantics(
            self,
            coordinate_ids,
        )
        if self.similarity.candidate_coordinate_sha256 != self.coordinate_sha256:
            raise ValueError("similarity evidence must name this candidate coordinate artifact")
        similarity_query_ids = {
            eligible_set.query_entity_id for eligible_set in self.similarity.eligible_sets
        }
        if similarity_query_ids != coordinate_ids:
            raise ValueError(
                "similarity evidence must evaluate every mapped coordinate exactly once"
            )
        if any(
            eligible_set.eligible_candidate_count > len(coordinate_ids) - 1
            for eligible_set in self.similarity.eligible_sets
        ):
            raise ValueError(
                "eligible candidate pools cannot exceed the mapped coordinate population"
            )
        return self
