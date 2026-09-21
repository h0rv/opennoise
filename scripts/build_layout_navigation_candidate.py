"""Build an offline navigation-layout candidate from sealed open graph inputs.

The published atlas supplied with ``--baseline-atlas`` is read only after the
candidate is complete.  It is evaluation data, never a coordinate input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from scipy.spatial import KDTree

from opennoise.deployment.semantic_pages import _PublicIdMapper, _static_label_atlas
from opennoise.ml.semantic_layout import (
    SemanticLayoutInputs,
    SemanticLayoutSettings,
    build_semantic_map_layout,
    write_semantic_map_layout,
)
from opennoise.ml.semantic_layout.contracts import SemanticLayoutArtifact

if TYPE_CHECKING:
    from collections.abc import Iterable


_CANDIDATE_REVISION = "layout-navigation-candidate-v1"
_NEAR_DISTANCE = 1e-4
_EXTREME_REVEAL_SCALE = 1e6


@dataclass(frozen=True, slots=True)
class _NearGroups:
    node_count: int
    group_count: int
    largest_group_count: int

    def as_json(self) -> dict[str, int]:
        """Return the report boundary shape without exposing mutable state."""
        return {
            "node_count": self.node_count,
            "group_count": self.group_count,
            "largest_group_count": self.largest_group_count,
        }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--peer-index", required=True, type=Path)
    parser.add_argument("--peer-manifold-artifact", required=True, type=Path)
    parser.add_argument("--hierarchy-artifact", required=True, type=Path)
    parser.add_argument("--colisten-artifact", required=True, type=Path)
    parser.add_argument("--colisten-cache", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument(
        "--baseline-atlas",
        required=True,
        type=Path,
        help="Published atlas used only for post-build comparison.",
    )
    return parser.parse_args()


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _near_groups(points: Iterable[tuple[float, float]]) -> _NearGroups:
    values = tuple(points)
    if not values:
        return _NearGroups(0, 0, 0)
    parent: list[int] = list(range(len(values)))

    def root(index: int) -> int:
        current = index
        while (next_index := int(parent[current])) != current:
            current = next_index
        return current

    for left, right in KDTree(values).query_pairs(_NEAR_DISTANCE):
        left_root, right_root = root(left), root(right)
        if left_root != right_root:
            parent[right_root] = left_root
    sizes: dict[int, int] = {}
    for index in range(len(values)):
        resolved = root(index)
        sizes[resolved] = sizes.get(resolved, 0) + 1
    groups = tuple(size for size in sizes.values() if size > 1)
    return _NearGroups(sum(groups), len(groups), max(groups, default=0))


def _baseline_points(path: Path) -> tuple[tuple[float, float], ...]:
    """Parse only display positions from an already-published comparison asset."""
    raw = json.loads(path.read_bytes())
    if not isinstance(raw, dict):
        raise TypeError("baseline atlas must be a JSON object")
    rows = raw.get("coordinates", raw.get("nodes"))
    if not isinstance(rows, list):
        raise TypeError("baseline atlas has no coordinate or node rows")
    points: list[tuple[float, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("baseline coordinate row is invalid")
        x, y = row.get("x"), row.get("y")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            raise TypeError("baseline coordinate lacks finite x/y")
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("baseline coordinate lacks finite x/y")
        points.append((float(x), float(y)))
    return tuple(points)


def _baseline_graph_metrics(path: Path) -> dict[str, float | None]:
    """Read optional prior measurements only for the post-build comparison."""
    raw = json.loads(path.read_bytes())
    metrics = raw.get("metrics") if isinstance(raw, dict) else None
    if not isinstance(metrics, dict):
        return {"mean_peer_knn_preservation": None}
    value = metrics.get("mean_peer_knn_preservation")
    return {
        "mean_peer_knn_preservation": float(value)
        if isinstance(value, (int, float)) and math.isfinite(value)
        else None
    }


def _reveal_metrics(scales: Iterable[float]) -> dict[str, float | int]:
    """Summarize the static-label reveal debt using the renderer's own packer."""
    values = tuple(scales)
    return {
        "label_count": len(values),
        "labels_above_1e6": sum(value > _EXTREME_REVEAL_SCALE for value in values),
        "maximum_reveal_scale": max(values, default=0.0),
    }


def _baseline_reveal_metrics(path: Path) -> dict[str, float | int]:
    """Measure an atlas's existing label metadata without supplying coordinates to build."""
    raw = json.loads(path.read_bytes())
    if not isinstance(raw, dict):
        raise TypeError("baseline atlas must be a JSON object")
    labels = raw.get("label_atlas")
    if isinstance(labels, list):
        scales = tuple(
            float(item["reveal_scale"])
            for item in labels
            if isinstance(item, dict) and isinstance(item.get("reveal_scale"), (int, float))
        )
        return _reveal_metrics(scales)
    baseline = SemanticLayoutArtifact.model_validate_json(path.read_bytes())
    packed = _static_label_atlas(baseline, _PublicIdMapper.from_artifact(baseline))
    return _reveal_metrics(label.reveal_scale for label in packed)


def main() -> int:
    """Build, seal, then measure one non-published candidate."""
    arguments = _arguments()
    settings = SemanticLayoutSettings(
        minimum_coordinate_separation=0.0002,
        maximum_separation_iterations=96,
    )
    candidate = build_semantic_map_layout(
        SemanticLayoutInputs(
            peer_index=arguments.peer_index,
            peer_manifold_artifact=arguments.peer_manifold_artifact,
            hierarchy_artifact=arguments.hierarchy_artifact,
            colisten_artifact=arguments.colisten_artifact,
            colisten_cache=arguments.colisten_cache,
        ),
        settings=settings,
    )
    write_semantic_map_layout(arguments.output, candidate)

    # The current atlas is intentionally unavailable until construction ended.
    baseline_points = _baseline_points(arguments.baseline_atlas)
    baseline_graph_metrics = _baseline_graph_metrics(arguments.baseline_atlas)
    baseline_reveals = _baseline_reveal_metrics(arguments.baseline_atlas)
    candidate_groups = _near_groups((point.x, point.y) for point in candidate.coordinates)
    baseline_groups = _near_groups(baseline_points)
    candidate_reveals = _reveal_metrics(
        label.reveal_scale
        for label in _static_label_atlas(candidate, _PublicIdMapper.from_artifact(candidate))
    )
    baseline_peer_knn = baseline_graph_metrics["mean_peer_knn_preservation"]
    candidate_peer_knn = candidate.metrics.mean_peer_knn_preservation
    report_without_hash = {
        "revision": _CANDIDATE_REVISION,
        "construction": {
            "coordinate_source": "sealed_open_graph_inputs_only",
            "historical_coordinates_read": False,
            "published_atlas_coordinates_read": False,
            "candidate_output_sha256": candidate.output_sha256,
            "candidate_settings_sha256": candidate.settings_sha256,
            "input_bindings": [item.model_dump(mode="json") for item in candidate.inputs],
        },
        "baseline_evaluation": {
            "path": str(arguments.baseline_atlas),
            "byte_sha256": hashlib.sha256(arguments.baseline_atlas.read_bytes()).hexdigest(),
            "near_groups_at_or_below_1e-4": baseline_groups.as_json(),
            "graph_metrics": baseline_graph_metrics,
            "label_reveal": baseline_reveals,
        },
        "candidate_measurements": {
            "near_groups_at_or_below_1e-4": candidate_groups.as_json(),
            "exact_coordinate_collision_count": candidate.metrics.exact_coordinate_collision_count,
            "mean_peer_knn_preservation": candidate.metrics.mean_peer_knn_preservation,
            "mean_colisten_knn_preservation": candidate.metrics.mean_colisten_knn_preservation,
            "mean_hierarchy_endpoint_distance": candidate.metrics.mean_hierarchy_endpoint_distance,
            "overview_visible_count": candidate.metrics.overview_visible_count,
            "overview_root_coverage_fraction": candidate.metrics.overview_root_coverage_fraction,
            "label_reveal": candidate_reveals,
        },
        "gate": {
            "fewer_near_nodes_than_baseline": candidate_groups.node_count
            < baseline_groups.node_count,
            "no_exact_coordinate_collisions": candidate.metrics.exact_coordinate_collision_count
            == 0,
            "neighborhood_measure_present": candidate_peer_knn is not None,
            "peer_knn_within_0_001_of_baseline": (
                baseline_peer_knn is None
                or (
                    candidate_peer_knn is not None
                    and candidate_peer_knn >= baseline_peer_knn - 0.001
                )
            ),
            "fewer_labels_above_1e6": (
                candidate_reveals["labels_above_1e6"] < baseline_reveals["labels_above_1e6"]
            ),
            "not_published": True,
        },
    }
    report = {**report_without_hash, "report_sha256": _canonical_sha256(report_without_hash)}
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(candidate.output_sha256)  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
