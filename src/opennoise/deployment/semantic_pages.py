"""Export the verified semantic atlas as a backend-free Pages directory."""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Final

from opennoise.common import canonical_json, sha256_file, sha256_hex, write_atomic_bytes
from opennoise.ml.semantic_layout.contracts import (
    SemanticLayoutArtifact,
    verify_semantic_map_layout,
)

_REVISION: Final = "opennoise-semantic-pages-v1"
_PACKAGE_ROOT: Final = Path(__file__).resolve().parents[1]
_STATIC_ROOT: Final = _PACKAGE_ROOT / "static"


class SemanticPagesExportError(ValueError):
    """The canonical semantic atlas cannot be published safely."""


@dataclass(frozen=True, slots=True)
class SemanticPagesExportInputs:
    """One sealed atlas and a new, empty static deployment directory."""

    semantic_layout_path: Path
    output_directory: Path


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
    atlas_payload = _renderer_payload(artifact)
    atlas_payload["edges"] = [
        {
            "source": f"legacy:{edge.left_seed_id}",
            "target": f"legacy:{edge.right_seed_id}",
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


def _write_fingerprinted_asset(assets: Path, stem: str, suffix: str, data: bytes) -> Path:
    """Persist an asset under a URL derived from its exact published bytes."""
    path = assets / f"{stem}.{sha256(data).hexdigest()}{suffix}"
    write_atomic_bytes(path, data)
    return path


def _renderer_payload(artifact: SemanticLayoutArtifact) -> dict[str, object]:
    """Project a verified atlas into the sole static browser payload."""
    nodes = [
        {
            "id": f"legacy:{coordinate.seed_id}",
            "name": coordinate.name,
            "x": coordinate.x,
            "y": coordinate.y,
            "lod": coordinate.lod,
            "importance": coordinate.importance,
            "community_id": coordinate.community_id,
            "display_parent_id": (
                f"legacy:{coordinate.display_parent_id}"
                if coordinate.display_parent_id is not None
                else None
            ),
            "hierarchy_root_id": (
                f"legacy:{coordinate.hierarchy_root_id}"
                if coordinate.hierarchy_root_id is not None
                else None
            ),
            "hierarchy_depth": coordinate.hierarchy_depth,
        }
        for coordinate in sorted(artifact.coordinates, key=lambda value: value.seed_id)
    ]
    anchors = {
        f"legacy:{community.anchor_seed_id}"
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
            f"legacy:{coordinate.seed_id}"
            for coordinate in ranked_coordinates
            if coordinate.lod <= level and f"legacy:{coordinate.seed_id}" not in prior
        ]
        prior.extend(candidates[: max(0, budget - len(prior))])
        labels.append({"level": level, "ids": list(prior)})
    aliases = {
        (coordinate.name.casefold(), f"legacy:{coordinate.seed_id}")
        for coordinate in artifact.coordinates
    }
    aliases.update(
        {
            ("idm", "legacy:item887"),
            ("intelligent dance", "legacy:item887"),
            ("pop music", "legacy:item1"),
            ("popular music", "legacy:item1"),
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
        "labels": labels,
        "aliases": [{"term": term, "target": target} for term, target in sorted(aliases)],
    }


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
