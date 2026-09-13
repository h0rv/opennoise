import tempfile
import unittest
from pathlib import Path

from musix.models import Settings
from musix.serving.app import create_app
from musix.serving.open.construction_graph_v2 import (
    OpenConstructionGraphV2Config,
    build_open_construction_graph_v2,
    write_open_construction_graph_v2,
)
from tests._test_client import create_test_client
from tests.serving.open.test_construction_graph_v2 import build_expansion


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

    def test_invalid_configured_v2_artifact_fails_when_its_route_is_opened(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            invalid = root / "invalid-v2.json"
            invalid.write_text("{}", encoding="utf-8")
            app = create_app(root / "app.sqlite", open_construction_graph_v2_path=invalid)
            with create_test_client(app) as client:
                response = client.get("/api/open-construction-map/v2")

        self.assertEqual(response.status_code, 503)

    def test_configured_v2_routes_are_bounded_and_preserve_edge_semantics(self) -> None:  # noqa: PLR0915
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
                default_page = client.get("/", params={"q": "rock"})
                page = client.get("/", params={"view": "open", "q": "rock"})
                node_id = overview.json()["nodes"][0]["node_id"]
                drill = client.get(f"/api/open-construction-map/v2/neighbors/{node_id}")
                focused = client.get(f"/open/{node_id}")

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
        self.assertIn('data-map-view="public"', default_page.text)
        self.assertNotIn('data-open-graph-version="v2"', default_page.text)
        self.assertNotIn('id="map-view-switch"', default_page.text)
        self.assertIn('href="/open/legacy%3A1"', search_fragment.text)
        self.assertNotIn('data-map-mode="open"', page.text)
        self.assertNotIn('data-open-graph-version="v2"', page.text)
        self.assertNotIn('data-graph-url="/api/open-construction-map/v2?level=0"', page.text)
        self.assertNotIn('data-neighbor-url="/api/open-construction-map/v2/neighbors/"', page.text)
        self.assertIn('hx-get="/fragments/open-construction-map/v2/search"', page.text)
        self.assertIn('href="/open/legacy%3A1"', page.text)
        self.assertEqual(focused.status_code, 200)
        self.assertIn('id="open-static-map"', focused.text)
        self.assertIn('href="/?view=open"', focused.text)
        self.assertEqual(drill.status_code, 200)
        self.assertLessEqual(len(drill.json()["nodes"]), 25)
        self.assertLessEqual(len(drill.json()["edges"]), 24)
        hierarchy = drill.json()["hierarchy"]
        self.assertEqual(
            set(hierarchy),
            {
                "broader",
                "broader_total",
                "broader_remaining",
                "narrower",
                "narrower_total",
                "narrower_remaining",
                "siblings",
                "siblings_total",
                "siblings_remaining",
            },
        )
        self.assertGreaterEqual(hierarchy["narrower_total"], len(hierarchy["narrower"]))
        self.assertEqual(
            hierarchy["narrower_remaining"],
            hierarchy["narrower_total"] - len(hierarchy["narrower"]),
        )
        self.assertTrue(
            all(
                not edge["factual_relationship"]
                for edge in drill.json()["edges"]
                if edge["review_candidate"]
            )
        )

    def test_v2_configuration_defaults_to_the_certified_model_artifact(self) -> None:
        settings = Settings()
        self.assertEqual(
            settings.open_construction_graph_v2_path,
            Path(__file__).resolve().parents[3] / "data/model/open-construction-graph-v2.json",
        )

    def test_certified_overview_is_broad_catalog_anchor_cohort(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = create_app(Path(temporary) / "app.sqlite")
            with create_test_client(app) as client:
                response = client.get("/api/open-construction-map/v2", params={"level": 0})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["node_budget"], 48)
        self.assertEqual(len(payload["nodes"]), 48)
        self.assertTrue(
            all(node["node_kind"] == "public_catalog_genre" for node in payload["nodes"])
        )
        names = {node["name"] for node in payload["nodes"]}
        self.assertTrue({"rock music", "jazz", "house music", "techno", "hip-hop"}.issubset(names))
        self.assertTrue({"film", "fiction", "crime film"}.isdisjoint(names))


if __name__ == "__main__":
    unittest.main()
