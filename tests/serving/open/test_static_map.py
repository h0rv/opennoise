"""Determinism checks for the server-prepared focused SVG presentation."""

from __future__ import annotations

import hashlib
import json
import time
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

from musix.serving.open.construction_store_v2 import OpenConstructionV2MapStore

if TYPE_CHECKING:
    from musix.serving.open.static_map import StaticOpenMap

ROOT = Path(__file__).resolve().parents[3]


def _presentation_digest(value: StaticOpenMap) -> str:
    """Hash the deterministic primitive SVG presentation fields."""
    return hashlib.sha256(
        json.dumps(
            {
                "nodes": [
                    (node.node.node_id, node.x, node.y, node.label_visible)
                    for node in value.nodes
                ],
                "edges": [
                    (edge.source.node_id, edge.target.node_id, edge.factual)
                    for edge in value.edges
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


class StaticOpenMapTests(unittest.TestCase):
    def test_startup_presentations_are_cached_and_deterministic(self) -> None:
        store = OpenConstructionV2MapStore(ROOT / "data/model/open-construction-graph-v2.json")
        node_id = "catalog:wikidata:genre:Q183504"

        started = time.perf_counter()
        first = store.static_neighborhood(node_id)
        first_seconds = time.perf_counter() - started
        started = time.perf_counter()
        second = store.static_neighborhood(node_id)
        cached_seconds = time.perf_counter() - started
        self.assertIs(first, second)
        self.assertLess(first_seconds, 5.0)
        self.assertLess(cached_seconds, first_seconds)
        self.assertEqual(first.view_box, "0 0 1600 900")
        self.assertLessEqual(first.label_count, 25)
        self.assertTrue(next(node for node in first.nodes if node.focused).label_visible)

        self.assertEqual(_presentation_digest(first), _presentation_digest(second))

    def test_taxonomy_layout_is_not_used_as_the_primary_overview(self) -> None:
        store = OpenConstructionV2MapStore(ROOT / "data/model/open-construction-graph-v2.json")
        overview = store.static_overview()

        self.assertEqual(len(overview.nodes), 48)
        self.assertEqual(overview.edges, ())


if __name__ == "__main__":
    unittest.main()
