"""ASGI coverage for the all-placed semantic renderer endpoint."""

from __future__ import annotations

import unittest
from os import environ
from pathlib import Path
from unittest.mock import patch

from opennoise.serving.app import create_app
from tests._test_client import create_test_client

ROOT = Path(__file__).parents[3]
PIPELINE = ROOT / ".cache/musicbrainz-full-seed-targets/pipeline"


class LocalResearchMapAppTests(unittest.TestCase):
    def test_map_only_app_serves_all_placed_points_without_catalog_startup(self) -> None:
        environment = {
            "OPENNOISE_MAP_ONLY": "true",
            "OPENNOISE_DATABASE_READ_ONLY": "false",
            "OPENNOISE_PRODUCTION_MAP_PATH": "",
            "OPENNOISE_LOCAL_RESEARCH_PEER_LAYOUT": str(PIPELINE / "peer-community-layout-v1.json"),
            "OPENNOISE_LOCAL_RESEARCH_MAP_PEER_INDEX": str(
                PIPELINE / "peer-similarity-local-research.sqlite"
            ),
            "OPENNOISE_LOCAL_RESEARCH_SEED_RECONCILIATION": str(
                PIPELINE / "seed-reconciliation.json"
            ),
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
        self.assertEqual(payload["placed_node_count"], 1580)
        self.assertEqual(payload["total_seed_count"], 6291)
        self.assertEqual(len(payload["nodes"]), 1580)
        self.assertEqual(len(payload["labels"][0]["ids"]), 36)
        self.assertIn({"term": "idm", "target": "legacy:item887"}, payload["aliases"])
