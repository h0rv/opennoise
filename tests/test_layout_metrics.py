import unittest

from pydantic import ValidationError

from musix.layout_metrics import (
    CommunityEdge,
    CommunityMembership,
    DensityGrid,
    LabelBox,
    LayoutMetricPoint,
    LayoutMetricRequest,
    MetricViewport,
    ReferenceNeighborList,
    RenderBudgetInput,
    VersionedPointLayout,
    evaluate_layout,
)

FINGERPRINT = "a" * 64


def layout(*points: tuple[int, float, float], revision: int = 1) -> VersionedPointLayout:
    """Build one small immutable fixture layout."""
    return VersionedPointLayout(
        layout_key="fixture",
        revision=revision,
        input_fingerprint=FINGERPRINT,
        points=tuple(
            LayoutMetricPoint(entity_id=entity_id, x=x, y=y) for entity_id, x, y in points
        ),
    )


class LayoutMetricTests(unittest.TestCase):
    def test_evaluates_exact_neighbors_density_hash_and_render_budget(self) -> None:
        current = layout((1, 0.0, 0.0), (2, 1.0, 0.0), (3, 2.0, 0.0), (4, 3.0, 0.0))
        result = evaluate_layout(
            LayoutMetricRequest(
                layout=current,
                neighbor_count=1,
                reference_neighbors=(
                    ReferenceNeighborList(entity_id=1, neighbor_ids=(2, 3, 4)),
                    ReferenceNeighborList(entity_id=2, neighbor_ids=(1, 3, 4)),
                    ReferenceNeighborList(entity_id=3, neighbor_ids=(2, 4, 1)),
                    ReferenceNeighborList(entity_id=4, neighbor_ids=(3, 2, 1)),
                ),
                density_grid=DensityGrid(columns=2, rows=1),
                render_budget=RenderBudgetInput(
                    label_count=2, label_character_count=10, edge_count=3
                ),
            )
        )

        assert result.neighbor_preservation is not None
        self.assertEqual(result.point_count, 4)
        self.assertEqual(result.neighbor_preservation.reference_neighbor_recall, 1.0)
        self.assertEqual(result.neighbor_preservation.trustworthiness, 1.0)
        self.assertTrue(result.neighbor_preservation.trustworthiness_is_exact)
        self.assertEqual(result.viewport_density.occupied_cell_count, 2)
        self.assertEqual(result.viewport_density.max_cell_point_count, 2)
        self.assertEqual(result.render_budget.estimated_svg_element_count, 13)
        self.assertEqual(result.render_budget.estimated_svg_keyboard_stop_count, 4)
        self.assertEqual(len(result.determinism.coordinate_sha256), 64)

    def test_reports_bounded_label_overlap_community_fragmentation_and_movement(self) -> None:
        current = layout((1, 0.0, 0.0), (2, 1.0, 0.0), (3, 2.0, 0.0), (4, 3.0, 0.0))
        previous = layout((1, 0.0, 0.0), (2, 0.0, 0.0), (3, 2.0, 0.0), (5, 5.0, 5.0), revision=2)
        result = evaluate_layout(
            LayoutMetricRequest(
                layout=current,
                label_boxes=(
                    LabelBox(entity_id=1, min_x=0.0, min_y=0.0, max_x=2.0, max_y=2.0),
                    LabelBox(entity_id=2, min_x=1.0, min_y=1.0, max_x=3.0, max_y=3.0),
                    LabelBox(entity_id=3, min_x=1.5, min_y=0.5, max_x=4.0, max_y=1.5),
                ),
                community_memberships=(
                    CommunityMembership(entity_id=1, community_id="a"),
                    CommunityMembership(entity_id=2, community_id="a"),
                    CommunityMembership(entity_id=3, community_id="a"),
                    CommunityMembership(entity_id=4, community_id="b"),
                ),
                community_edges=(CommunityEdge(source_entity_id=1, target_entity_id=2),),
                previous_layout=previous,
                repeat_layout=current,
                density_grid=DensityGrid(
                    columns=2,
                    rows=2,
                    viewport=MetricViewport(min_x=0.0, min_y=0.0, max_x=2.0, max_y=2.0),
                ),
            )
        )

        assert result.label_overlap is not None
        assert result.community_fragmentation is not None
        assert result.temporal_displacement is not None
        self.assertEqual(result.label_overlap.overlapping_pair_count_lower_bound, 3)
        self.assertTrue(result.label_overlap.comparison_complete)
        self.assertEqual(result.community_fragmentation.fragmented_community_count, 1)
        self.assertEqual(result.community_fragmentation.component_count, 3)
        self.assertEqual(result.temporal_displacement.common_entity_count, 3)
        self.assertEqual(result.temporal_displacement.added_entity_count, 1)
        self.assertEqual(result.temporal_displacement.removed_entity_count, 1)
        self.assertEqual(result.temporal_displacement.percentile_95_displacement, 1.0)
        self.assertTrue(result.determinism.exact_repeat_match)
        self.assertEqual(result.viewport_density.outside_viewport_point_count, 1)

    def test_rejects_invalid_layout_references_and_reports_incomplete_overlap(self) -> None:
        current = layout((1, 0.0, 0.0), (2, 1.0, 0.0), (3, 2.0, 0.0))
        with self.assertRaises(ValidationError):
            LayoutMetricRequest(
                layout=current,
                reference_neighbors=(ReferenceNeighborList(entity_id=1, neighbor_ids=(99,)),),
            )

        result = evaluate_layout(
            LayoutMetricRequest(
                layout=current,
                label_comparison_limit=1,
                label_boxes=(
                    LabelBox(entity_id=1, min_x=0.0, min_y=0.0, max_x=4.0, max_y=4.0),
                    LabelBox(entity_id=2, min_x=1.0, min_y=0.0, max_x=5.0, max_y=4.0),
                    LabelBox(entity_id=3, min_x=2.0, min_y=0.0, max_x=6.0, max_y=4.0),
                ),
                render_budget=RenderBudgetInput(interactive_point_count=0),
            )
        )
        assert result.label_overlap is not None
        self.assertFalse(result.label_overlap.comparison_complete)
        self.assertEqual(result.label_overlap.compared_pair_count, 1)
        self.assertGreaterEqual(result.label_overlap.overlapping_pair_count_lower_bound, 1)
        self.assertEqual(result.render_budget.estimated_svg_keyboard_stop_count, 0)


if __name__ == "__main__":
    unittest.main()
