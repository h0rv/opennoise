import unittest
from pathlib import Path

from musix.open_construction_store import OpenConstructionMapStore, OpenConstructionMapStoreError

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "data" / "model" / "open-construction-graph-v1.json"


class OpenConstructionMapStoreTests(unittest.TestCase):
    def test_levels_and_viewports_never_serialize_the_global_node_set(self) -> None:
        store = OpenConstructionMapStore(ARTIFACT)
        expected_budgets = (240, 480, 720, 720)
        for level, budget in enumerate(expected_budgets):
            with self.subTest(level=level):
                response = store.response(level=level)
                self.assertEqual(response.node_budget, budget)
                self.assertEqual(response.total_node_count, 6291)
                self.assertLessEqual(len(response.nodes), budget)
                self.assertLess(len(response.nodes), response.total_node_count)
                self.assertLessEqual(len(response.edges), 512)
        viewport = store.response(level=3, min_x=-10.0, min_y=-10.0, max_x=10.0, max_y=10.0)
        self.assertLessEqual(len(viewport.nodes), 720)

    def test_rejects_partial_viewports_and_bounds_one_hop_drills(self) -> None:
        store = OpenConstructionMapStore(ARTIFACT)
        with self.assertRaisesRegex(OpenConstructionMapStoreError, "viewport"):
            store.response(level=2, min_x=0.0)
        overview = store.response(level=0)
        drill = store.neighbors(overview.nodes[0].genre_id)
        self.assertLessEqual(len(drill.nodes), 25)
        self.assertLessEqual(len(drill.edges), 24)


if __name__ == "__main__":
    unittest.main()
