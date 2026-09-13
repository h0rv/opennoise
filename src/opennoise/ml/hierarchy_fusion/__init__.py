"""Source-neutral fusion of factual and review-only genre hierarchy evidence."""

from .contracts import (
    HierarchyFusionArtifact,
    HierarchyFusionError,
    HierarchyFusionSettings,
    hierarchy_fusion_artifact_sha256,
)
from .inputs import HierarchyFusionInputs
from .pipeline import build_hierarchy_fusion, verify_hierarchy_fusion

__all__ = (
    "HierarchyFusionArtifact",
    "HierarchyFusionError",
    "HierarchyFusionInputs",
    "HierarchyFusionSettings",
    "build_hierarchy_fusion",
    "hierarchy_fusion_artifact_sha256",
    "verify_hierarchy_fusion",
)
