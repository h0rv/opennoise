import tempfile
import unittest
from pathlib import Path

from musix.app import create_app
from musix.models import Settings
from musix.open_construction_graph_v2 import (
    OpenConstructionGraphV2Config,
    build_open_construction_graph_v2,
    write_open_construction_graph_v2,
)
from tests._test_client import create_test_client
from tests.test_open_construction_graph_v2 import build_expansion


class OpenConstructionV2ApiTests(unittest.TestCase):
    def test_unconfigured_v2_path_is_unavailable_and_never_falls_back_to_v1(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = create_app(
                Path(temporary) / "catalog.sqlite", open_construction_graph_v2_path=None
            )
            with create_test_client(app) as client:
                response = client.get("/api/open-construction-map/v2")

        self.assertEqual(response.status_code, 503)
        self.assertIn("v2 graph is disabled", response.text)

    def test_invalid_configured_v2_artifact_fails_startup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            invalid = root / "invalid-v2.json"
            invalid.write_text("{}", encoding="utf-8")
            app = create_app(root / "app.sqlite", open_construction_graph_v2_path=invalid)
            with self.assertRaises(ExceptionGroup), create_test_client(app):
                pass

    def test_configured_v2_routes_are_bounded_and_preserve_edge_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = build_open_construction_graph_v2(
                build_expansion(root),
                config=OpenConstructionGraphV2Config(expected_legacy_seed_count=5),
            )
            graph_path = root / "open-v2.json"
            write_open_construction_graph_v2(graph, graph_path)
            app = create_app(
                root / "app.sqlite",
                open_construction_graph_v2_path=graph_path,
            )
            with create_test_client(app) as client:
                overview = client.get("/api/open-construction-map/v2", params={"level": 0})
                invalid_level = client.get("/api/open-construction-map/v2", params={"level": 4})
                partial_viewport = client.get("/api/open-construction-map/v2", params={"min_x": 0})
                search = client.get("/api/open-construction-map/v2/search", params={"q": "rock"})
                search_fragment = client.get(
                    "/fragments/open-construction-map/v2/search", params={"q": "rock"}
                )
                page = client.get("/", params={"view": "open", "q": "rock"})
                node_id = overview.json()["nodes"][0]["node_id"]
                drill = client.get(f"/api/open-construction-map/v2/neighbors/{node_id}")

        self.assertEqual(overview.status_code, 200)
        payload = overview.json()
        self.assertEqual(payload["source"], "open-construction-v2-artifact")
        self.assertEqual(payload["revision"], "open-construction-graph-v2")
        self.assertEqual(payload["legacy_seed_node_count"], 5)
        self.assertEqual(payload["total_node_count"], 7)
        self.assertLessEqual(len(payload["nodes"]), payload["node_budget"])
        self.assertLessEqual(len(payload["edges"]), 512)
        self.assertEqual(invalid_level.status_code, 400)
        self.assertEqual(partial_viewport.status_code, 400)
        self.assertEqual(search.status_code, 200)
        self.assertIn("Rock Music", [hit["name"] for hit in search.json()["hits"]])
        self.assertEqual(search_fragment.status_code, 200)
        self.assertIn('data-open-node-id="legacy:1"', search_fragment.text)
        self.assertIn('data-map-mode="open"', page.text)
        self.assertIn('data-open-graph-version="v2"', page.text)
        self.assertIn('data-graph-url="/api/open-construction-map/v2?level=0"', page.text)
        self.assertIn('data-neighbor-url="/api/open-construction-map/v2/neighbors/"', page.text)
        self.assertIn('hx-get="/fragments/open-construction-map/v2/search"', page.text)
        self.assertIn('data-open-node-id="legacy:1"', page.text)
        self.assertEqual(drill.status_code, 200)
        self.assertLessEqual(len(drill.json()["nodes"]), 25)
        self.assertLessEqual(len(drill.json()["edges"]), 24)
        self.assertTrue(
            all(
                not edge["factual_relationship"]
                for edge in drill.json()["edges"]
                if edge["review_candidate"]
            )
        )

    def test_v2_configuration_is_explicitly_disabled_by_default(self) -> None:
        self.assertIsNone(
            Settings(open_construction_graph_v2_path=None).open_construction_graph_v2_path
        )


if __name__ == "__main__":
    unittest.main()
