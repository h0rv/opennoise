"""ASGI coverage for the all-placed semantic renderer endpoint."""

from __future__ import annotations

import unittest
from http import HTTPStatus
from os import environ
from pathlib import Path
from unittest.mock import patch

from opennoise.serving.app import create_app
from tests._test_client import create_test_client

ROOT = Path(__file__).parents[3]
SEMANTIC_LAYOUT = ROOT / ".cache/semantic-map-layout-v1/artifact.json"


@unittest.skipUnless(
    SEMANTIC_LAYOUT.is_file(), "semantic-layout integration artifact is not provisioned"
)
class LocalResearchMapAppTests(unittest.TestCase):
    def test_map_only_app_serves_all_placed_points_without_catalog_startup(self) -> None:
        environment = {
            "OPENNOISE_MAP_ONLY": "true",
            "OPENNOISE_DATABASE_READ_ONLY": "false",
            "OPENNOISE_PRODUCTION_MAP_PATH": "",
            "OPENNOISE_SEMANTIC_MAP_LAYOUT": str(SEMANTIC_LAYOUT),
        }
        with (
            patch.dict(environ, environment, clear=False),
            create_test_client(create_app()) as client,
        ):
            page = client.get("/")
            renderer = client.get("/api/local-research-map/renderer")

        self.assertEqual(page.status_code, 200)
        self.assertIn('id="semantic-map"', page.text)
        self.assertEqual(renderer.status_code, 200)
        payload = renderer.json()
        self.assertEqual(payload["placed_node_count"], 2945)
        self.assertEqual(payload["total_seed_count"], 6291)
        self.assertEqual(len(payload["nodes"]), 2945)
        self.assertLessEqual(len(payload["labels"][0]["ids"]), 45)
        self.assertIn({"term": "idm", "target": "legacy:item887"}, payload["aliases"])
        self.assertIn({"term": "pop music", "target": "legacy:item1"}, payload["aliases"])
        self.assertIn({"term": "popular music", "target": "legacy:item1"}, payload["aliases"])

    def test_map_only_app_canonicalizes_retired_map_queries(self) -> None:
        environment = {
            "OPENNOISE_MAP_ONLY": "true",
            "OPENNOISE_DATABASE_READ_ONLY": "false",
            "OPENNOISE_PRODUCTION_MAP_PATH": "",
            "OPENNOISE_SEMANTIC_MAP_LAYOUT": str(SEMANTIC_LAYOUT),
        }
        with (
            patch.dict(environ, environment, clear=False),
            create_test_client(create_app()) as client,
        ):
            responses = tuple(
                client.get("/", params=params)
                for params in (
                    {"view": "public"},
                    {"view": "historical", "layout": "missing"},
                    {"level": "99", "zoom": "-4", "layout": "classic"},
                )
            )

        self.assertTrue(all(response.status_code == HTTPStatus.OK for response in responses))
        self.assertTrue(all('id="semantic-map"' in response.text for response in responses))
