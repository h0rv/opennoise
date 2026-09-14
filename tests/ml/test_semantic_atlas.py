from __future__ import annotations

import math
import unittest

from opennoise.ml.semantic_layout.atlas import AtlasPoint, build_rectangular_atlas
from opennoise.ml.semantic_layout.builder import _place_branch_children

_GROUP_SPLIT_INDEX = 3
_SKEWED_CUTOFF = 80


class SemanticAtlasTests(unittest.TestCase):
    def test_global_affine_fit_preserves_neighborhood_order(self) -> None:
        points = tuple(
            AtlasPoint(
                node_id=f"node-{index}",
                x=value,
                y=value * 0.8,
                group_id="left" if index < _GROUP_SPLIT_INDEX else "right",
            )
            for index, value in enumerate((0.1, 0.2, 0.3, 0.7, 0.8, 0.9))
        )
        result = build_rectangular_atlas(points)
        left = (
            sum(result.positions[f"node-{index}"][0] for index in range(_GROUP_SPLIT_INDEX))
            / _GROUP_SPLIT_INDEX
        )
        right = (
            sum(result.positions[f"node-{index}"][0] for index in range(_GROUP_SPLIT_INDEX, 6))
            / _GROUP_SPLIT_INDEX
        )
        self.assertLess(left, right)
        self.assertGreater(result.local_neighbor_preservation or 0.0, 0.95)
        self.assertGreaterEqual(min(x for x, _y in result.positions.values()), 0.055)
        self.assertLessEqual(max(x for x, _y in result.positions.values()), 16 / 9 - 0.055)

    def test_outlier_is_clipped_without_setting_the_view(self) -> None:
        points = tuple(
            AtlasPoint(node_id=f"node-{index}", x=value, y=value / 2, group_id="all")
            for index, value in enumerate((0.1, 0.2, 0.3, 0.4, 0.5, 1000.0))
        )
        result = build_rectangular_atlas(points)
        xs = [point[0] for point in result.positions.values()]
        ys = [point[1] for point in result.positions.values()]
        self.assertGreater(max(xs) - min(xs), 1.0)
        self.assertGreater(max(ys) - min(ys), 0.5)
        self.assertTrue(all(0.0 < x < 16 / 9 for x in xs))
        self.assertTrue(all(0.0 < y < 1.0 for y in ys))

    def test_skewed_density_preserves_source_neighbors_without_rank_lattice(self) -> None:
        points = tuple(
            AtlasPoint(
                node_id=f"node-{index}",
                x=0.01 + (index / 20 if index < _SKEWED_CUTOFF else index / 100),
                y=0.01
                + (
                    ((index * 37) % 100) / 30
                    if ((index * 37) % 100) < _SKEWED_CUTOFF
                    else ((index * 37) % 100) / 120
                ),
                group_id="left" if index % 2 else "right",
            )
            for index in range(100)
        )
        result = build_rectangular_atlas(points)
        self.assertGreater(result.local_neighbor_preservation or 0.0, 0.90)
        self.assertGreater(
            max(x for x, _y in result.positions.values())
            - min(x for x, _y in result.positions.values()),
            1.0,
        )

    def test_tied_coordinate_grid_is_deterministically_de_latticed(self) -> None:
        points = tuple(
            AtlasPoint(
                node_id=f"grid-{row}-{column}",
                x=float(column),
                y=float(row),
                group_id="grid",
            )
            for row in range(12)
            for column in range(12)
        )
        first = build_rectangular_atlas(points)
        second = build_rectangular_atlas(points)
        self.assertEqual(first.positions, second.positions)
        self.assertEqual(len({round(x, 8) for x, _y in first.positions.values()}), len(points))
        self.assertEqual(len({round(y, 8) for _x, y in first.positions.values()}), len(points))
        # A Cartesian grid has tied nearest-neighbor distances, so this is a
        # conservative regression floor. The non-tied fixtures above protect
        # the substantially higher topology-preservation path.
        self.assertGreater(first.local_neighbor_preservation or 0.0, 0.80)

    def test_hierarchy_branch_is_not_a_radial_spoke_pattern(self) -> None:
        children = _place_branch_children(
            (0.8, 0.5),
            (f"child-{index}" for index in range(12)),
            bounds=(0.055, 0.055, 16 / 9 - 0.055, 0.945),
        )
        distances = [math.dist((0.8, 0.5), point) for point in children.values()]
        angles = sorted(math.atan2(y - 0.5, x - 0.8) for x, y in children.values())
        gaps = [angles[index + 1] - angles[index] for index in range(len(angles) - 1)]
        self.assertGreater(len({round(distance, 5) for distance in distances}), 3)
        self.assertGreater(max(gaps) - min(gaps), 0.02)
        self.assertLess(max(distances), 0.04)
        self.assertEqual(len({round(x, 8) for x, _y in children.values()}), len(children))
        self.assertEqual(len({round(y, 8) for _x, y in children.values()}), len(children))

    def test_edge_anchor_keeps_branch_inside_inner_world(self) -> None:
        bounds = (0.055, 0.055, 16 / 9 - 0.055, 0.945)
        children = _place_branch_children(
            (bounds[0], bounds[1]),
            (f"edge-child-{index}" for index in range(20)),
            bounds=bounds,
        )
        self.assertTrue(all(bounds[0] <= x <= bounds[2] for x, _y in children.values()))
        self.assertTrue(all(bounds[1] <= y <= bounds[3] for _x, y in children.values()))


if __name__ == "__main__":
    unittest.main()
