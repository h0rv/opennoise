import tempfile
import unittest
from pathlib import Path
from typing import override

from litestar.testing import TestClient

from musix.app import create_app
from musix.db import Database
from musix.models import MapPoint, map_view

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "migrations" / "smoke" / "fixture.sql"


class AppTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(Path(self.temporary.name) / "catalog.sqlite"))
        self.client.__enter__()

    @override
    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.temporary.cleanup()

    def test_home_is_a_minimal_full_viewport_shell(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn('<main id="map"', response.text)
        self.assertNotIn("<h1", response.text)
        self.assertIn("htmx-4.0.0.min.js", response.text)
        self.assertIn("/static/app.css?v=3", response.text)
        self.assertNotIn('id="count"', response.text)
        self.assertNotIn("6291", response.text)

    def test_health_queries_sqlite(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "ok")

    def test_empty_map_search_and_fragment(self) -> None:
        self.assertEqual(self.client.get("/api/map").json(), {"points": []})
        self.assertEqual(self.client.get("/api/search", params={"q": "---"}).json(), {"hits": []})
        fragment = self.client.get("/fragments/search", params={"q": "---"})
        self.assertEqual(fragment.status_code, 200)
        self.assertEqual(fragment.text.strip(), "")

    def test_exploration_contract_rejects_partial_viewport(self) -> None:
        empty = self.client.get("/api/explore/map")
        invalid = self.client.get("/api/explore/map", params={"min_x": "0"})
        missing = self.client.get("/api/genres/999")

        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.json()["points"], [])
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(missing.status_code, 404)

    def test_selection_does_not_change_source_coordinate_bounds(self) -> None:
        points = [
            MapPoint(
                entity_id=1,
                entity_kind="genre",
                name="Top",
                x=0.0,
                y=0.0,
                display_weight=None,
                color_hex=None,
            ),
            MapPoint(
                entity_id=2,
                entity_kind="genre",
                name="Bottom",
                x=100.0,
                y=1_000.0,
                display_weight=None,
                color_hex=None,
            ),
        ]

        full = map_view(points)
        selected = map_view(points, 2)

        self.assertEqual(selected.view_box, full.view_box)
        self.assertEqual(selected.view_width, full.view_width)
        self.assertEqual(selected.view_height, full.view_height)
        self.assertGreater(selected.view_height, selected.view_width)

    def test_empty_bounded_map_preserves_viewport_aspect(self) -> None:
        view = map_view([], view_box="10 20 300 700")

        self.assertEqual(view.view_box, "10 20 300 700")
        self.assertEqual(view.view_width, 300.0)
        self.assertEqual(view.view_height, 700.0)


class PopulatedAppTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary.name) / "catalog.sqlite"
        database = Database(self.database_path)
        database.initialize()
        with database.connect() as connection:
            connection.executescript(FIXTURE.read_text(encoding="utf-8"))
            connection.executescript(
                """
                INSERT INTO layout_runs (
                    id, layout_key, revision, algorithm_key, algorithm_revision,
                    input_fingerprint, status, policy_id, completed_at
                ) VALUES (
                    2, 'default', 1, 'fixture', '1',
                    '3434343434343434343434343434343434343434343434343434343434343434',
                    'complete', 1, '2026-01-01T00:00:00Z'
                );
                INSERT INTO layout_points (
                    layout_run_id, entity_id, x, y, display_weight, color_hex
                ) SELECT 2, entity_id, x, y, display_weight, color_hex
                  FROM layout_points WHERE layout_run_id = 1;
                INSERT INTO current_layouts (layout_key, layout_run_id) VALUES ('default', 2);
                INSERT INTO search_documents (
                    entity_id, field_kind, search_text, input_fingerprint,
                    provenance_id, policy_id
                ) VALUES (
                    1, 'primary_name', 'IDM',
                    '3535353535353535353535353535353535353535353535353535353535353535',
                    1, 1
                );
                """
            )
        self.client = TestClient(create_app(self.database_path))
        self.client.__enter__()

    @override
    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.temporary.cleanup()

    def test_genre_links_have_one_canonical_selection_contract(self) -> None:
        response = self.client.get("/")

        self.assertIn('href="/genres/1"', response.text)
        self.assertIn('hx-get="/fragments/workspace?focus=1"', response.text)
        self.assertIn('hx-target="#workspace"', response.text)
        self.assertIn('hx-push-url="/genres/1"', response.text)
        self.assertIn('preserveAspectRatio="xMinYMin meet"', response.text)
        self.assertNotIn('id="count"', response.text)

    def test_canonical_genre_url_is_a_complete_fallback(self) -> None:
        response = self.client.get("/genres/1")

        self.assertEqual(response.status_code, 200)
        self.assertIn('class="point genre selected"', response.text)
        self.assertIn('aria-current="true"', response.text)
        self.assertIn('id="selection-clear"', response.text)
        self.assertIn('href="/" aria-label="Clear IDM selection"', response.text)
        self.assertNotIn('id="genre-detail"', response.text)
        self.assertNotIn("Every Noise legacy genre map", response.text)
        self.assertNotIn("2026-01-01", response.text)

    def test_workspace_selection_and_deselection_are_atomic(self) -> None:
        selected = self.client.get("/fragments/workspace", params={"focus": "1"})
        reset = self.client.get("/fragments/workspace")

        self.assertEqual(selected.status_code, 200)
        self.assertEqual(selected.text.count('id="workspace"'), 1)
        self.assertEqual(selected.text.count('hx-swap-oob="innerHTML"'), 1)
        self.assertIn('class="point genre selected"', selected.text)
        self.assertIn('id="selection-clear"', selected.text)
        self.assertNotIn('id="genre-detail"', selected.text)
        self.assertNotIn("Every Noise legacy genre map", selected.text)
        self.assertIn('hx-push-url="/"', selected.text)
        self.assertNotIn("600.0 800.0", selected.text)

        self.assertEqual(reset.status_code, 200)
        self.assertNotIn(" selected", reset.text)
        self.assertNotIn('id="genre-detail"', reset.text)
        self.assertNotIn('id="selection-clear"', reset.text)
        self.assertEqual(reset.text.count('hx-swap-oob="innerHTML"'), 1)

    def test_search_results_are_navigable_and_share_selection_history(self) -> None:
        response = self.client.get("/fragments/search", params={"q": "idm"})

        self.assertEqual(response.status_code, 200)
        self.assertIn('<a class="result" href="/genres/1"', response.text)
        self.assertIn('hx-get="/fragments/workspace?focus=1"', response.text)
        self.assertIn('hx-push-url="/genres/1"', response.text)
        self.assertNotIn("<button", response.text)


if __name__ == "__main__":
    unittest.main()
