from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from opennoise.ml.semantic_layout.contracts import (
    CameraBounds,
    GeometryMetrics,
    InputBinding,
    OverviewCommunity,
    SemanticCoordinate,
    SemanticLayoutArtifact,
    SemanticLayoutSettings,
    StructuralEdge,
    UnplacedSeed,
    semantic_layout_settings_sha256,
    semantic_layout_sha256,
)
from opennoise.serving.map.semantic_store import SemanticMapStore
from tests._test_client import PollingIsolatedAsyncioTestCase

LAYOUT = Path(".cache/semantic-map-layout-v1/artifact.json")


def _fixture() -> SemanticLayoutArtifact:
    settings = SemanticLayoutSettings()
    coordinates = (
        SemanticCoordinate(
            seed_id="item1",
            name="pop",
            x=0.2,
            y=0.4,
            component_id=0,
            community_id=0,
            lod=0,
            importance=2,
            label_priority=1,
            evidence_kinds=("peer",),
            hierarchy_depth=0,
        ),
        SemanticCoordinate(
            seed_id="item887",
            name="intelligent dance music",
            x=1.2,
            y=0.6,
            component_id=0,
            community_id=0,
            lod=0,
            importance=1,
            label_priority=2,
            evidence_kinds=("peer",),
            display_parent_id="item1",
            hierarchy_root_id="item1",
            hierarchy_depth=1,
        ),
    )
    unplaced = tuple(
        UnplacedSeed(seed_id=f"unplaced{number:04d}", name=f"unplaced {number}")
        for number in range(6289)
    )
    bounds = CameraBounds(x0=0, y0=0, x1=settings.world_width, y1=1)
    base = SemanticLayoutArtifact(
        inputs=tuple(
            InputBinding(role=role, byte_sha256="a" * 64, byte_count=1)
            for role in (
                "peer_index",
                "peer_manifold_artifact",
                "hierarchy_artifact",
                "colisten_artifact",
                "colisten_cache",
            )
        ),
        settings=settings,
        settings_sha256=semantic_layout_settings_sha256(settings),
        coordinates=coordinates,
        unplaced=unplaced,
        communities=(
            OverviewCommunity(
                community_id=0,
                label="pop",
                anchor_seed_id="item1",
                member_count=2,
                component_id=0,
                x=0.2,
                y=0.4,
                overview_visible=True,
            ),
        ),
        structural_edges=(
            StructuralEdge(
                left_seed_id="item1", right_seed_id="item887", weight=1, evidence_kinds=("peer",)
            ),
        ),
        world_bounds=bounds,
        content_bounds=bounds,
        initial_camera=bounds,
        metrics=GeometryMetrics(
            placed_seed_count=2,
            unplaced_seed_count=6289,
            component_count=1,
            community_count=1,
            source_peer_edge_count=1,
            source_colisten_edge_count=0,
            source_hierarchy_edge_count=0,
            occupied_world_width_fraction=1,
            occupied_world_height_fraction=1,
            exact_coordinate_collision_count=0,
            overview_label_collision_count=0,
            largest_community_member_count=2,
            overview_visible_count=1,
            overview_root_count=1,
            overview_root_coverage_fraction=1,
            initial_camera_anchor_width_fraction=0,
            initial_camera_anchor_height_fraction=0,
        ),
        output_sha256="0" * 64,
    )
    return base.model_copy(update={"output_sha256": semantic_layout_sha256(base)})


class SemanticMapStoreFixtureTests(unittest.TestCase):
    def test_verified_fixture_exposes_lod_aliases_and_bounded_neighbors(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "semantic-map.json"
            path.write_text(_fixture().model_dump_json())
            store = SemanticMapStore(path)
            store.start()
        self.assertEqual(store.renderer().placed_node_count, 2)
        renderer = store.renderer()
        self.assertEqual(
            {(node.id, node.community_id, node.hierarchy_depth) for node in renderer.nodes},
            {("legacy:item1", 0, 0), ("legacy:item887", 0, 1)},
        )
        self.assertEqual(len(renderer.overview_regions), 1)
        self.assertEqual(renderer.overview_regions[0].label, "pop")
        self.assertEqual(renderer.overview_regions[0].heading_lod, 0)
        self.assertEqual(store.search("popular music")[0].node_id, "legacy:item1")
        self.assertEqual(len(store.neighbors("legacy:item887").edges), 1)


@unittest.skipUnless(LAYOUT.is_file(), "semantic-layout integration artifact is not provisioned")
class SemanticMapStoreTests(PollingIsolatedAsyncioTestCase):
    def test_renderer_is_complete_lod_bound_and_aliases_are_stable(self) -> None:
        store = SemanticMapStore(LAYOUT)
        store.start()
        renderer = store.renderer()

        self.assertEqual((renderer.placed_node_count, renderer.unplaced_node_count), (2945, 3346))
        overview_heading_count = sum(
            region.overview_visible for region in renderer.overview_regions
        )
        first_tier_count = next(len(record.ids) for record in renderer.labels)
        self.assertEqual(first_tier_count, overview_heading_count)
        self.assertLessEqual(first_tier_count, 45)
        self.assertTrue(
            all(node.lod == 0 for node in renderer.nodes if node.id in renderer.labels[0].ids)
        )
        self.assertLess(renderer.initial_camera.x0, renderer.initial_camera.x1)
        self.assertLess(renderer.initial_camera.y0, renderer.initial_camera.y1)
        aliases = {(alias.term, alias.target) for alias in renderer.aliases}
        self.assertTrue(
            {
                ("idm", "legacy:item887"),
                ("pop music", "legacy:item1"),
                ("popular music", "legacy:item1"),
            }
            <= aliases
        )

    def test_search_and_focused_neighbors_use_only_stable_seed_ids(self) -> None:
        store = SemanticMapStore(LAYOUT)
        store.start()
        for term, expected in (
            ("idm", "legacy:item887"),
            ("pop music", "legacy:item1"),
            ("popular music", "legacy:item1"),
        ):
            self.assertEqual(store.search(term)[0].node_id, expected)
        neighbors = store.neighbors("legacy:item887")
        self.assertLessEqual(len(neighbors.edges), 12)
        self.assertTrue(
            all("legacy:" in edge.source and "legacy:" in edge.target for edge in neighbors.edges)
        )
