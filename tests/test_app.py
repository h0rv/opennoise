import tempfile
import unittest
from pathlib import Path
from typing import override

from litestar.testing import TestClient

from musix.app import create_app


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


if __name__ == "__main__":
    unittest.main()
