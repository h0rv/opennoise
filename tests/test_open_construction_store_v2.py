import tempfile
import unittest
from pathlib import Path

from musix.open_construction_graph_v2 import (
    OpenConstructionGraphV2Config,
    build_open_construction_graph_v2,
    write_open_construction_graph_v2,
)
from musix.open_construction_store_v2 import (
    OpenConstructionV2MapStore,
    OpenConstructionV2MapStoreError,
)
from tests.test_open_construction_graph_v2 import build_expansion


class OpenConstructionV2MapStoreTests(unittest.TestCase):
    def test_bounded_responses_keep_fact_and_review_counts_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = build_open_construction_graph_v2(
                build_expansion(root),
                config=OpenConstructionGraphV2Config(expected_legacy_seed_count=5),
            )
            artifact_path = root / "open-v2.json"
            write_open_construction_graph_v2(graph, artifact_path)
            store = OpenConstructionV2MapStore(artifact_path)

            response = store.response(level=0)
            self.assertEqual(response.source, "open-construction-v2-artifact")
            self.assertEqual(response.revision, "open-construction-graph-v2")
            self.assertEqual(response.legacy_seed_node_count, 5)
            self.assertEqual(response.total_node_count, 7)
            self.assertEqual(
                response.factual_taxonomy_edge_count,
                graph.coverage.catalog_taxonomy_edge_count,
            )
            self.assertEqual(
                response.review_navigation_edge_count,
                graph.coverage.compositional_review_edge_count
                + graph.coverage.ambiguous_identity_review_edge_count,
            )
            self.assertLessEqual(len(response.nodes), response.node_budget)
            self.assertLessEqual(len(response.edges), 512)
            drill = store.neighbors(response.nodes[0].node_id)
            self.assertLessEqual(len(drill.nodes), 25)
            self.assertLessEqual(len(drill.edges), 24)
            self.assertTrue(
                all(not edge.factual_relationship for edge in drill.edges if edge.review_candidate)
            )

    def test_rejects_missing_path_partial_viewports_and_invalid_artifacts(self) -> None:
        with self.assertRaisesRegex(OpenConstructionV2MapStoreError, "disabled"):
            OpenConstructionV2MapStore(None).response(level=0)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invalid.json"
            path.write_text("{}", encoding="utf-8")
            store = OpenConstructionV2MapStore(path)
            with self.assertRaisesRegex(OpenConstructionV2MapStoreError, "unavailable"):
                store.response(level=0)


if __name__ == "__main__":
    unittest.main()
