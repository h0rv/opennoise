"""Export the verified semantic atlas as a backend-free Pages directory."""

from __future__ import annotations

import gzip
import json
import math
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

from opennoise.common import canonical_json, sha256_file, sha256_hex, write_atomic_bytes
from opennoise.ml.semantic_layout.contracts import (
    SemanticCoordinate,
    SemanticLayoutArtifact,
    verify_semantic_map_layout,
)

_REVISION: Final = "opennoise-semantic-pages-v1"
_PACKAGE_ROOT: Final = Path(__file__).resolve().parents[1]
_STATIC_ROOT: Final = _PACKAGE_ROOT / "static"
_HIERARCHY_REGION_MAX_DISTANCE: Final = 0.08
_HIERARCHY_REGION_MIN_MEMBERS: Final = 4
_LABEL_FONT_PX: Final = 14.0
# Canvas records a 14px baseline plus the 4px stroke halo.  Reserve the full
# 22px observed box so export certification and actual browser collision tests
# use the same geometry.
_LABEL_HEIGHT_PX: Final = 22.0
_LABEL_PADDING_PX: Final = 3.0
_LABEL_ANCHOR_GAP_PX: Final = 12.0
_REFERENCE_FIT_SCALE: Final = 900.0
_LABEL_FLOAT_EPSILON: Final = 1e-15
_WIDE_GLYPH_BOUNDARY: Final = 0x2FF
_LABEL_REVEAL_BY_LOD: Final = (
    0.0,
    _REFERENCE_FIT_SCALE * 2**0.2,
    _REFERENCE_FIT_SCALE * 2**1.2,
    _REFERENCE_FIT_SCALE * 2**2.2,
)
_LABEL_ADMISSION_FACTOR: Final = 1.25
_LABEL_ADMISSION_GROWTH: Final = 0.5
_FIRST_LABEL_ADMISSION_SCALE: Final = _LABEL_REVEAL_BY_LOD[1]


class SemanticPagesExportError(ValueError):
    """The canonical semantic atlas cannot be published safely."""


class StaticLabelPayload(BaseModel):
    """One immutable, collision-certified label placement in the atlas."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: str
    side: Literal["right"]
    offset_x: float
    offset_y: float
    width_px: float
    height_px: float = _LABEL_HEIGHT_PX
    priority: int
    reveal_scale: float


@dataclass(frozen=True, slots=True)
class _PublicIdMapper:
    """Deterministically publish the terminal segment of internal IDs."""

    internal_ids: frozenset[str]

    @classmethod
    def from_artifact(cls, artifact: SemanticLayoutArtifact) -> _PublicIdMapper:
        """Seal the mapping against every seed, including unplaced evidence IDs."""
        return cls.from_ids(
            tuple(coordinate.seed_id for coordinate in artifact.coordinates)
            + tuple(seed.seed_id for seed in artifact.unplaced)
        )

    @classmethod
    def from_ids(cls, values: tuple[str, ...]) -> _PublicIdMapper:
        internal_ids = frozenset(values)
        public_ids = tuple(cls._public_id(value) for value in internal_ids)
        if len(internal_ids) != len(public_ids) or len(set(public_ids)) != len(public_ids):
            raise SemanticPagesExportError("public static ID mapping has a collision")
        return cls(internal_ids)

    @staticmethod
    def _public_id(value: str) -> str:
        return value.rsplit(":", maxsplit=1)[-1]

    def public(self, value: str) -> str:
        if value not in self.internal_ids:
            raise SemanticPagesExportError("public static ID is outside the sealed seed universe")
        public_id = self._public_id(value)
        if not public_id or ":" in public_id:
            raise SemanticPagesExportError("public static ID retains an internal namespace")
        return public_id


@dataclass(frozen=True, slots=True)
class SemanticPagesExportInputs:
    """One sealed atlas and a new, empty static deployment directory."""

    semantic_layout_path: Path
    output_directory: Path


@dataclass(frozen=True, slots=True)
class _BrowseLandmark:
    """Typed, presentation-only landmark emitted into the static payload."""

    root_id: str
    label: str
    x: float
    y: float
    member_ids: tuple[str, ...]

    def payload(self) -> dict[str, object]:
        return {
            "root_id": self.root_id,
            "label": self.label,
            "x": self.x,
            "y": self.y,
            "member_count": len(self.member_ids),
            "member_ids": list(self.member_ids),
        }


def export_semantic_pages(inputs: SemanticPagesExportInputs) -> dict[str, object]:
    """Materialize the 2,945-node atlas and its static Canvas client."""
    if inputs.output_directory.exists() and any(inputs.output_directory.iterdir()):
        raise SemanticPagesExportError("static Pages output directory must be empty")
    try:
        artifact = SemanticLayoutArtifact.model_validate_json(
            inputs.semantic_layout_path.read_bytes()
        )
        verify_semantic_map_layout(artifact)
    except (OSError, ValueError) as error:
        raise SemanticPagesExportError("invalid semantic map layout artifact") from error
    mapper = _PublicIdMapper.from_artifact(artifact)
    atlas_payload = _renderer_payload(artifact, mapper)
    atlas_payload["edges"] = [
        {
            "source": mapper.public(edge.left_seed_id),
            "target": mapper.public(edge.right_seed_id),
            "confidence": edge.weight,
        }
        for edge in artifact.structural_edges
    ]
    output = inputs.output_directory
    assets = output / "assets"
    output.mkdir(parents=True, exist_ok=True)
    assets.mkdir()
    asset_paths = _export_fingerprinted_assets(assets, atlas_payload)
    _write(output / "index.html", _html(asset_paths))
    _write(
        output / "_headers",
        "/\n"
        "  Cache-Control: no-cache\n"
        "/index.html\n"
        "  Cache-Control: no-cache\n"
        "/opennoise-static-manifest.json\n"
        "  Cache-Control: no-cache\n"
        "/assets/*\n"
        "  Cache-Control: public, max-age=31536000, immutable\n",
    )
    _write(output / "_redirects", "/ /index.html 200\n")
    file_sha256, file_byte_count = sha256_file(inputs.semantic_layout_path)
    manifest: dict[str, object] = {
        "revision": _REVISION,
        "explicit_backend_api_available": False,
        "semantic_layout": {
            "file_sha256": file_sha256,
            "file_byte_count": file_byte_count,
            "logical_output_sha256": artifact.output_sha256,
            "total_seed_count": artifact.stable_seed_count,
            "placed_node_count": len(artifact.coordinates),
            "unplaced_node_count": len(artifact.unplaced),
            "overview_region_count": sum(
                community.overview_visible for community in artifact.communities
            ),
            "structural_edge_count": len(artifact.structural_edges),
        },
        "assets": {
            role: {
                "path": str(path.relative_to(output)),
                "sha256": sha256(path.read_bytes()).hexdigest(),
            }
            for role, path in asset_paths.items()
        },
        "asset_budget": _asset_budget(output),
    }
    manifest["output_sha256"] = sha256_hex(canonical_json(manifest))
    _write_json(output / "opennoise-static-manifest.json", manifest)
    return manifest


def _export_fingerprinted_assets(assets: Path, atlas_payload: dict[str, object]) -> dict[str, Path]:
    """Write one immutable URL per content-addressed browser asset."""
    app_css = _write_fingerprinted_asset(
        assets, "app", ".css", (_STATIC_ROOT / "app.css").read_bytes()
    )
    atlas_module = _write_fingerprinted_asset(
        assets, "map-atlas", ".mjs", (_STATIC_ROOT / "map-atlas.mjs").read_bytes()
    )
    renderer_source = (_STATIC_ROOT / "map-renderer.js").read_text(encoding="utf-8")
    renderer_source = renderer_source.replace("'./map-atlas.mjs'", f"'./{atlas_module.name}'", 1)
    if "./map-atlas.mjs" in renderer_source:
        raise SemanticPagesExportError("static renderer has an unresolved atlas import")
    renderer_module = _write_fingerprinted_asset(
        assets, "map-renderer", ".js", renderer_source.encode()
    )
    semantic_atlas = _write_fingerprinted_asset(
        assets, "semantic-atlas", ".json", _json_bytes(atlas_payload)
    )
    return {
        "app_css": app_css,
        "map_atlas_module": atlas_module,
        "map_renderer_module": renderer_module,
        "semantic_atlas": semantic_atlas,
    }


def _overlap_scale_interval(
    delta: float, offset: float, lower: float, upper: float
) -> tuple[float, float] | None:
    """Return the scales where ``lower < delta*scale+offset < upper``."""
    if abs(delta) <= _LABEL_FLOAT_EPSILON:
        return (0.0, math.inf) if lower < offset < upper else None
    roots = ((lower - offset) / delta, (upper - offset) / delta)
    low, high = min(roots), max(roots)
    high = min(high, math.inf)
    if high <= 0.0 or high <= max(low, 0.0):
        return None
    return max(0.0, low), high


def _label_reveal_scale(
    candidate: StaticLabelPayload,
    candidate_x: float,
    candidate_y: float,
    prior: tuple[tuple[float, float, StaticLabelPayload], ...],
    base_scale: float,
) -> float:
    """Find the first scale at which this fixed box stays clear forever.

    Every earlier placement participates, including later semantic tiers.  A
    prior label can only collide after it is admitted, so that threshold is
    part of the interval check.  The result is immutable export metadata;
    there is no redraw-time re-ranking or placement search.
    """
    reveal = base_scale
    for x, y, label in prior:
        x_interval = _overlap_scale_interval(
            candidate_x - x,
            candidate.offset_x - label.offset_x,
            -candidate.width_px,
            label.width_px,
        )
        y_interval = _overlap_scale_interval(
            candidate_y - y,
            candidate.offset_y - label.offset_y,
            -candidate.height_px,
            label.height_px,
        )
        if x_interval is None or y_interval is None:
            continue
        low = max(x_interval[0], y_interval[0], 0.0)
        high = min(x_interval[1], y_interval[1])
        active_from = max(low, base_scale, label.reveal_scale)
        if high <= active_from:
            continue
        if math.isinf(high):
            raise SemanticPagesExportError("coincident static label placements")
        reveal = max(reveal, math.nextafter(high, math.inf))
    return reveal


def _estimated_label_width(name: str) -> float:
    """Use a conservative 14px sans-serif width estimate for certification."""
    return max(16.0, sum(9.5 if ord(char) > _WIDE_GLYPH_BOUNDARY else 8.5 for char in name) + 2.0)


def _spread_static_label_reveals(labels: list[StaticLabelPayload]) -> list[StaticLabelPayload]:
    """Delay, but never advance, admissions into stable 1.25x steps.

    Each non-overview step admits no more than half of the captions already
    visible.  Collision clearance is a lower bound, so delaying a caption
    cannot introduce an overlap.  This is one bounded pass, rather than an
    open-ended search over scale buckets.
    """
    ordered = sorted(labels, key=lambda label: (label.reveal_scale, label.priority, label.id))
    baseline = sum(label.reveal_scale <= _REFERENCE_FIT_SCALE for label in ordered)
    visible = baseline
    bucket = 0
    remaining = max(1, math.floor(max(1, visible) * _LABEL_ADMISSION_GROWTH))
    result: dict[str, StaticLabelPayload] = {}
    for label in ordered:
        if label.reveal_scale <= _REFERENCE_FIT_SCALE:
            result[label.id] = label
            continue
        raw_bucket = max(
            1,
            1
            + math.ceil(
                math.log(
                    label.reveal_scale / _FIRST_LABEL_ADMISSION_SCALE,
                    _LABEL_ADMISSION_FACTOR,
                )
            ),
        )
        if raw_bucket > bucket:
            bucket = raw_bucket
            remaining = max(1, math.floor(max(1, visible) * _LABEL_ADMISSION_GROWTH))
        elif remaining == 0:
            bucket += 1
            remaining = max(1, math.floor(max(1, visible) * _LABEL_ADMISSION_GROWTH))
        result[label.id] = label.model_copy(
            update={
                "reveal_scale": _FIRST_LABEL_ADMISSION_SCALE
                * _LABEL_ADMISSION_FACTOR ** (bucket - 1)
            }
        )
        visible += 1
        remaining -= 1
    return [result[label.id] for label in labels]


def _static_label_atlas(
    artifact: SemanticLayoutArtifact, mapper: _PublicIdMapper
) -> list[StaticLabelPayload]:
    """Build deterministic fixed-world label metadata and reveal thresholds."""
    anchors = {
        community.anchor_seed_id for community in artifact.communities if community.overview_visible
    }
    anchors.update(landmark.root_id for landmark in _browse_landmarks(artifact.coordinates))
    ranked = sorted(
        artifact.coordinates,
        key=lambda coordinate: (
            coordinate.lod,
            0 if coordinate.seed_id in anchors else 1,
            coordinate.lod,
            -coordinate.importance,
            coordinate.name.casefold(),
            coordinate.seed_id,
        ),
    )
    prior: list[tuple[float, float, StaticLabelPayload]] = []
    duplicate_positions: dict[tuple[float, float], int] = {}
    labels: list[StaticLabelPayload] = []
    for priority, coordinate in enumerate(ranked):
        position = (coordinate.x, coordinate.y)
        duplicate_index = duplicate_positions.get(position, 0)
        duplicate_positions[position] = duplicate_index + 1
        payload = StaticLabelPayload(
            id=mapper.public(coordinate.seed_id),
            side="right",
            offset_x=_LABEL_ANCHOR_GAP_PX,
            # Coordinates are unique in the certified artifact.  Keep the
            # exception explicit: only exact duplicate dots use a 28px lane,
            # which is wider than the 22px certified text box and cannot collide.
            offset_y=5.0 + duplicate_index * (_LABEL_HEIGHT_PX + _LABEL_PADDING_PX * 2),
            width_px=_estimated_label_width(coordinate.name),
            priority=priority,
            reveal_scale=_LABEL_REVEAL_BY_LOD[coordinate.lod],
        )
        reveal = _label_reveal_scale(
            payload, coordinate.x, coordinate.y, tuple(prior), payload.reveal_scale
        )
        payload = payload.model_copy(update={"reveal_scale": reveal})
        prior.append((coordinate.x, coordinate.y, payload))
        labels.append(payload)
    return _spread_static_label_reveals(labels)


def _write_fingerprinted_asset(assets: Path, stem: str, suffix: str, data: bytes) -> Path:
    """Persist an asset under a URL derived from its exact published bytes."""
    path = assets / f"{stem}.{sha256(data).hexdigest()}{suffix}"
    write_atomic_bytes(path, data)
    return path


def _renderer_payload(
    artifact: SemanticLayoutArtifact, mapper: _PublicIdMapper
) -> dict[str, object]:
    """Project a verified atlas into the sole static browser payload."""
    static_labels = _static_label_atlas(artifact, mapper)
    label_atlas = [label.model_dump(mode="json") for label in static_labels]
    nodes = [
        {
            "id": mapper.public(coordinate.seed_id),
            "name": coordinate.name,
            "x": coordinate.x,
            "y": coordinate.y,
            "lod": coordinate.lod,
            "importance": coordinate.importance,
            "community_id": coordinate.community_id,
            "display_parent_id": (
                mapper.public(coordinate.display_parent_id)
                if coordinate.display_parent_id is not None
                else None
            ),
            "hierarchy_root_id": (
                mapper.public(coordinate.hierarchy_root_id)
                if coordinate.hierarchy_root_id is not None
                else None
            ),
            "hierarchy_depth": coordinate.hierarchy_depth,
        }
        for coordinate in sorted(artifact.coordinates, key=lambda value: value.seed_id)
    ]
    anchors = {
        mapper.public(community.anchor_seed_id)
        for community in artifact.communities
        if community.overview_visible
    }
    ranked_coordinates = sorted(
        artifact.coordinates,
        key=lambda coordinate: (
            -coordinate.importance,
            coordinate.name.casefold(),
            coordinate.seed_id,
        ),
    )
    labels: list[dict[str, object]] = []
    prior = sorted(anchors)
    for level, budget in enumerate((45, 96, 210, 420)):
        candidates = [
            mapper.public(coordinate.seed_id)
            for coordinate in ranked_coordinates
            if coordinate.lod <= level and mapper.public(coordinate.seed_id) not in prior
        ]
        prior.extend(candidates[: max(0, budget - len(prior))])
        labels.append({"level": level, "ids": list(prior)})
    aliases = {
        (coordinate.name.casefold(), mapper.public(coordinate.seed_id))
        for coordinate in artifact.coordinates
    }
    aliases.update(
        {
            ("idm", mapper.public("item887")),
            ("intelligent dance", mapper.public("item887")),
            ("pop music", mapper.public("item1")),
            ("popular music", mapper.public("item1")),
        }
    )
    return {
        "revision": "semantic-scatter-map-v2",
        "source": "semantic-map-layout-v2",
        "logical_output_sha256": artifact.output_sha256,
        "total_seed_count": artifact.stable_seed_count,
        "placed_node_count": len(nodes),
        "unplaced_node_count": len(artifact.unplaced),
        "world_bounds": artifact.world_bounds.model_dump(mode="json"),
        "content_bounds": artifact.content_bounds.model_dump(mode="json"),
        "initial_camera": artifact.initial_camera.model_dump(mode="json"),
        "nodes": nodes,
        "label_atlas": label_atlas,
        # This cap is the first finite scale that admits every certified
        # caption, plus floating-point breathing room.  It is data-derived:
        # a tiny but real cluster remains inspectable, while a wheel/pinch
        # operation can never grow beyond a concrete value.
        "maximum_scale": max(
            _REFERENCE_FIT_SCALE,
            max(label.reveal_scale for label in static_labels) * 1.05,
        ),
        "overview_regions": [
            {
                "community_id": community.community_id,
                "label": community.label,
                "x": community.x,
                "y": community.y,
                "member_count": community.member_count,
                "overview_visible": community.overview_visible,
                "heading_lod": 0
                if community.overview_visible
                else min(
                    coordinate.lod
                    for coordinate in artifact.coordinates
                    if coordinate.community_id == community.community_id
                ),
            }
            for community in artifact.communities
        ],
        "browse_landmarks": [
            {
                **landmark.payload(),
                "root_id": mapper.public(landmark.root_id),
                "member_ids": [mapper.public(member_id) for member_id in landmark.member_ids],
            }
            for landmark in _browse_landmarks(artifact.coordinates)
        ],
        "labels": labels,
        "aliases": [{"term": term, "target": target} for term, target in sorted(aliases)],
    }


def _browse_landmarks(
    coordinates: tuple[SemanticCoordinate, ...],
) -> tuple[_BrowseLandmark, ...]:
    """Select presentation-only root labels from locally co-located browse groups.

    ``display_parent_id`` is presentation metadata, not a factual claim. A
    label earns a landmark only when at least three associated labels already
    occupy its local semantic neighborhood; no coordinates or edges are made.
    """
    by_id = {coordinate.seed_id: coordinate for coordinate in coordinates}
    children: dict[str, list[str]] = {}
    for coordinate in coordinates:
        parent_id = coordinate.display_parent_id
        if parent_id is not None and parent_id in by_id and parent_id != coordinate.seed_id:
            children.setdefault(parent_id, []).append(coordinate.seed_id)
    landmarks: list[_BrowseLandmark] = []
    for root_id in children:
        root = by_id[root_id]
        if root.display_parent_id is not None or root.lod != 0:
            continue
        root_members = {root_id}
        members = [
            coordinate
            for coordinate in coordinates
            if coordinate.seed_id in root_members or coordinate.hierarchy_root_id in root_members
        ]
        nearby = [
            coordinate
            for coordinate in members
            if math.hypot(coordinate.x - root.x, coordinate.y - root.y)
            <= _HIERARCHY_REGION_MAX_DISTANCE
        ]
        if len(nearby) < _HIERARCHY_REGION_MIN_MEMBERS:
            continue
        distances = sorted(
            math.hypot(coordinate.x - root.x, coordinate.y - root.y) for coordinate in nearby
        )
        radius = max(0.018, min(0.09, distances[int(len(distances) * 0.9)] + 0.008))
        owned = [
            coordinate
            for coordinate in nearby
            if math.hypot(coordinate.x - root.x, coordinate.y - root.y) <= radius
        ]
        landmarks.append(
            _BrowseLandmark(
                root_id=root_id,
                label=root.name,
                x=root.x,
                y=root.y,
                member_ids=tuple(sorted(coordinate.seed_id for coordinate in owned)),
            )
        )
    return tuple(
        sorted(
            landmarks,
            key=lambda landmark: (
                -len(landmark.member_ids),
                landmark.label.casefold(),
                landmark.root_id,
            ),
        ),
    )[:35]


def _html(asset_paths: dict[str, Path]) -> str:
    """Bind the stable document shell to its immutable content-addressed assets."""
    app_css = asset_paths["app_css"].name
    semantic_atlas = asset_paths["semantic_atlas"].name
    renderer_module = asset_paths["map_renderer_module"].name
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="description" content="An open structural atlas of music genres.">
  <title>OpenNoise</title>
  <link rel="stylesheet" href="assets/{app_css}">
</head>
<body>
  <main id="map" aria-label="Music map">
    <canvas id="semantic-map" role="img" aria-label="OpenNoise semantic music map"
            data-map-url="assets/{semantic_atlas}"></canvas>
    <nav id="map-controls" aria-label="Map controls">
      <button type="button" data-map-action="back" hidden>Back</button>
      <button type="button" data-map-action="fit">Fit</button>
      <button type="button" data-map-action="out" aria-label="Zoom out">-</button>
      <button type="button" data-map-action="in" aria-label="Zoom in">+</button>
      <button type="button" data-map-action="theme" aria-label="Toggle color theme">Theme</button>
    </nav>
    <aside id="map-detail" aria-live="polite" hidden></aside>
  </main>
  <form id="search" role="search">
    <label class="sr-only" for="query">Search map</label>
    <input id="query" type="search" placeholder="Search a genre, e.g. IDM" autocomplete="off">
  </form>
  <script type="module" src="assets/{renderer_module}"></script>
</body>
</html>
"""


def _asset_budget(directory: Path) -> list[dict[str, object]]:
    return [
        {
            "path": str(path.relative_to(directory)),
            "raw_bytes": len(data),
            "gzip_bytes": len(gzip.compress(data, mtime=0)),
            "sha256": sha256(data).hexdigest(),
        }
        for path in sorted(item for item in directory.rglob("*") if item.is_file())
        for data in (path.read_bytes(),)
    ]


def _write(path: Path, value: str) -> None:
    write_atomic_bytes(path, value.encode())


def _write_json(path: Path, value: object) -> None:
    write_atomic_bytes(path, _json_bytes(value))


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
        + b"\n"
    )
