"""Strict, renderer-neutral acceptance records for the production genre map."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Literal

from pydantic import Field, FiniteFloat, model_validator

from musix.models.web import FrozenModel

_RANDOM_NULL_TOLERANCE = 1e-12


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

    @model_validator(mode="after")
    def require_nonempty_bounds(self) -> ProductionMapLabelBox:
        """Reject labels which cannot occupy visible screen space."""
        if self.min_x >= self.max_x or self.min_y >= self.max_y:
            raise ValueError("label bounds must have positive area")
        return self


class ProductionMapLod(FrozenModel):
    """Visible nodes and label decisions for one persistent semantic zoom level."""

    level: int = Field(ge=0, le=10)
    visible_entity_ids: tuple[str, ...] = Field(min_length=1, max_length=20_000)
    desktop_labels: tuple[ProductionMapLabelBox, ...] = Field(max_length=4_000)
    mobile_labels: tuple[ProductionMapLabelBox, ...] = Field(max_length=4_000)

    @model_validator(mode="after")
    def require_unique_visible_entities_and_labels(self) -> ProductionMapLod:
        """Keep the LOD record deterministic and self-contained."""
        visible = set(self.visible_entity_ids)
        if len(visible) != len(self.visible_entity_ids):
            raise ValueError("visible entities must be unique")
        for name, labels in (("desktop", self.desktop_labels), ("mobile", self.mobile_labels)):
            ids = [label.entity_id for label in labels]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{name} labels must be unique")
            if not set(ids).issubset(visible):
                raise ValueError(f"{name} labels must belong to visible entities")
        return self


class ProductionMapRegion(FrozenModel):
    """An optional visible hierarchy region emitted by the model, not inferred by UI."""

    region_id: str = Field(min_length=1, max_length=200)
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


class ProductionMapAcceptanceInput(FrozenModel):
    """All evidence needed to accept or reject one production-map artifact."""

    revision: str = Field(min_length=1, max_length=100)
    coordinate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    coordinates: tuple[ProductionMapCoordinate, ...] = Field(min_length=26, max_length=20_000)
    taxonomy_edges: tuple[tuple[str, str], ...] = Field(max_length=100_000)
    presentation_parents: tuple[ProductionMapPresentationParent, ...] = Field(max_length=20_000)
    regions: tuple[ProductionMapRegion, ...] = Field(default=(), max_length=20_000)
    lods: tuple[ProductionMapLod, ...] = Field(min_length=1, max_length=11)
    similarity: ProductionMapSimilarityEvidence
    screenshots: tuple[ProductionMapScreenshot, ...] = Field(default=(), max_length=12)
    interactions: ProductionMapInteractionEvidence | None = None

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
        for region in self.regions:
            if not set(region.entity_ids).issubset(coordinate_ids):
                raise ValueError("region contains an entity without a coordinate")
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
