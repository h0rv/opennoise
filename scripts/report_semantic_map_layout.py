"""Write a compact visual-geometry QA report for a sealed semantic map artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from opennoise.ml.semantic_layout.contracts import (
    SemanticLayoutArtifact,
    verify_semantic_map_layout,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    """Verify the artifact and publish only geometry/accounting diagnostics."""
    arguments = _arguments()
    artifact = SemanticLayoutArtifact.model_validate_json(arguments.artifact.read_bytes())
    verify_semantic_map_layout(artifact)
    center_x = (artifact.content_bounds.x0 + artifact.content_bounds.x1) / 2.0
    center_y = (artifact.content_bounds.y0 + artifact.content_bounds.y1) / 2.0
    quadrants = {"northwest": 0, "northeast": 0, "southwest": 0, "southeast": 0}
    for point in artifact.coordinates:
        vertical = "north" if point.y <= center_y else "south"
        horizontal = "west" if point.x <= center_x else "east"
        quadrants[f"{vertical}{horizontal}"] += 1
    normalized = {" ".join(point.name.casefold().split()): point for point in artifact.coordinates}
    paths = (
        ("electronica", "intelligent dance music"),
        ("rock", "post-punk"),
        ("hip hop",),
        ("jazz",),
        ("pop",),
    )
    path_rows = []
    for path in paths:
        resolved = [normalized.get(name) for name in path]
        path_rows.append(
            {
                "names": path,
                "resolved_seed_ids": [
                    point.seed_id if point is not None else None for point in resolved
                ],
                "display_parents": [
                    point.display_parent_id if point is not None else None for point in resolved
                ],
            }
        )
    report = {
        "artifact_output_sha256": artifact.output_sha256,
        "coordinate_count": len(artifact.coordinates),
        "unplaced_count": len(artifact.unplaced),
        "world_bounds": artifact.world_bounds.model_dump(mode="json"),
        "content_bounds": artifact.content_bounds.model_dump(mode="json"),
        "initial_camera": artifact.initial_camera.model_dump(mode="json"),
        "overview": {
            "visible_labels": [
                community.label for community in artifact.communities if community.overview_visible
            ],
            "visible_count": artifact.metrics.overview_visible_count,
            "root_count": artifact.metrics.overview_root_count,
            "root_coverage_fraction": artifact.metrics.overview_root_coverage_fraction,
            "initial_camera_anchor_width_fraction": (
                artifact.metrics.initial_camera_anchor_width_fraction
            ),
            "initial_camera_anchor_height_fraction": (
                artifact.metrics.initial_camera_anchor_height_fraction
            ),
        },
        "metrics": artifact.metrics.model_dump(mode="json"),
        "quadrants": quadrants,
        "paths": path_rows,
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
