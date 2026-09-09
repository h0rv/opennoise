"""Replaceable contracts for sparse semantic map presentation."""

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, FiniteFloat, model_validator

from musix.models import FrozenModel
from musix.serving.exploration import Viewport
from musix.serving.map.layouts import LayoutStrategyVersion


class LabelDecisionReason(StrEnum):
    """Why a label was shown or omitted."""

    FOCUS = "focus"
    LANDMARK = "landmark"
    PRIORITY = "priority"
    COLLISION = "collision"
    BUDGET = "budget"
    OUTSIDE_VIEWPORT = "outside_viewport"


class CollisionBox(FrozenModel):
    """A measured label rectangle in layout coordinates."""

    minimum_x: FiniteFloat
    minimum_y: FiniteFloat
    maximum_x: FiniteFloat
    maximum_y: FiniteFloat

    @model_validator(mode="after")
    def require_area(self) -> Self:
        """Reject empty or inverted collision boxes."""
        if self.minimum_x >= self.maximum_x or self.minimum_y >= self.maximum_y:
            msg = "collision box minimums must be less than maximums"
            raise ValueError(msg)
        return self


class LabelPriorityComponent(FrozenModel):
    """One named input used to order label candidates."""

    component_key: str = Field(min_length=1)
    value: FiniteFloat
    evidence_refs: tuple[str, ...]


class LandmarkEvidence(FrozenModel):
    """Evidence that a point should remain recognizable across detail levels."""

    entity_id: int
    landmark_kind: Literal["source", "derived"]
    evidence_refs: tuple[str, ...]
    method_key: str | None = None
    method_version: str | None = None

    @model_validator(mode="after")
    def require_derived_method(self) -> Self:
        """Require a versioned method for derived landmark evidence."""
        if self.landmark_kind == "derived" and (
            self.method_key is None or self.method_version is None
        ):
            msg = "derived landmark evidence requires a method key and version"
            raise ValueError(msg)
        return self


class LabelCandidate(FrozenModel):
    """A label considered by a versioned placement strategy."""

    entity_id: int
    text: str = Field(min_length=1)
    anchor_x: FiniteFloat
    anchor_y: FiniteFloat
    priority: tuple[LabelPriorityComponent, ...]
    landmark: LandmarkEvidence | None = None


class LabelPlacement(FrozenModel):
    """An auditable result from label selection and collision handling."""

    entity_id: int
    visible: bool
    reason: LabelDecisionReason
    box: CollisionBox | None
    collided_with_entity_id: int | None = None

    @model_validator(mode="after")
    def require_consistent_decision(self) -> Self:
        """Keep placement geometry and collision references consistent."""
        if self.visible and self.box is None:
            msg = "a visible label requires a collision box"
            raise ValueError(msg)
        if self.reason is LabelDecisionReason.COLLISION and self.collided_with_entity_id is None:
            msg = "a collision decision requires the blocking entity"
            raise ValueError(msg)
        return self


class DensityCell(FrozenModel):
    """An exact point count for one viewport cell."""

    bounds: Viewport
    point_count: int = Field(ge=0)
    entity_kinds: tuple[str, ...]


class EvidenceEdge(FrozenModel):
    """A display edge backed by named catalog evidence."""

    subject_entity_id: int
    object_entity_id: int
    relation_key: str = Field(min_length=1)
    evidence_kind: Literal["direct", "inferred"]
    evidence_refs: tuple[str, ...]
    method_key: str | None = None
    method_version: str | None = None

    @model_validator(mode="after")
    def require_inference_method(self) -> Self:
        """Require a versioned method for inferred edges."""
        if self.evidence_kind == "inferred" and (
            self.method_key is None or self.method_version is None
        ):
            msg = "an inferred edge requires a method key and version"
            raise ValueError(msg)
        return self


class MapPresentationArtifact(FrozenModel):
    """One removable sparse presentation output for a published layout."""

    layout_key: str = Field(min_length=1)
    layout_revision: int = Field(gt=0)
    strategy: LayoutStrategyVersion
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    viewport: Viewport
    label_budget: int = Field(ge=0)
    candidates: tuple[LabelCandidate, ...]
    labels: tuple[LabelPlacement, ...]
    density: tuple[DensityCell, ...]
    edges: tuple[EvidenceEdge, ...]
