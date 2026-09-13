"""Receipt-bound, renderer-neutral structural map layout."""

from .atlas import AtlasPoint, AtlasRegion, AtlasResult, AtlasSettings, build_rectangular_atlas
from .builder import build_semantic_map_layout, write_semantic_map_layout
from .contracts import (
    SemanticLayoutArtifact,
    SemanticLayoutInputs,
    SemanticLayoutSettings,
    verify_semantic_map_layout,
)

__all__ = [
    "AtlasPoint",
    "AtlasRegion",
    "AtlasResult",
    "AtlasSettings",
    "SemanticLayoutArtifact",
    "SemanticLayoutInputs",
    "SemanticLayoutSettings",
    "build_rectangular_atlas",
    "build_semantic_map_layout",
    "verify_semantic_map_layout",
    "write_semantic_map_layout",
]
