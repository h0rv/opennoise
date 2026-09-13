from __future__ import annotations

# ruff: noqa: SLF001
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from opennoise.serving.local.research_map_store import (
    LocalResearchMapError,
    LocalResearchMapStore,
)
from opennoise.serving.routes import SearchController
from opennoise.taxonomy.seeds.reconciliation import load_seed_reconciliation
from tests._test_client import PollingIsolatedAsyncioTestCase

ROOT = Path(__file__).parents[3]
LAYOUT = ROOT / ".cache/musicbrainz-full-seed-targets/pipeline/peer-community-layout-v1.json"
INDEX = ROOT / ".cache/musicbrainz-full-seed-targets/pipeline/peer-similarity-local-research.sqlite"
RECONCILIATION = ROOT / ".cache/musicbrainz-full-seed-targets/pipeline/seed-reconciliation.json"


class LocalResearchMapStoreTests(PollingIsolatedAsyncioTestCase):
    def test_overview_drill_genre_and_unplaced_search_are_explicit(self) -> None:
        store = _store()
        overview = store.response(level=0)
        self.assertEqual(len(overview.nodes), 136)
        self.assertTrue(all(node.node_kind == "peer_community" for node in overview.nodes))
        community = store.neighbors(overview.nodes[0].node_id)
        self.assertLessEqual(len(community.nodes), 240)
        genre = store.neighbors(community.nodes[0].node_id)
        self.assertEqual(genre.nodes[0].node_kind, "legacy_name_seed")
        self.assertTrue(all(not edge.factual_relationship for edge in genre.edges))
        assert store._nodes is not None
        placed = {node.source_item_id for node in store._nodes.values()}
        unplaced = next(
            row for row in store.reconciliation.dispositions if row.source_item_id not in placed
        )
        hit = next(
            row
            for row in store.search(unplaced.seed_name)
            if row.node_id.endswith(unplaced.source_item_id)
        )
        self.assertFalse(hit.placed)
        self.assertEqual(hit.unplaced_reason, "no_peer_similarity_evidence")

    def test_community_pagination_keeps_all_members_accessible(self) -> None:
        store = _store()
        assert store._communities is not None
        communities = store._communities
        community_id = max(communities, key=lambda key: len(communities[key]))
        first = store.neighbors(f"community:{community_id}")
        second = store.neighbors(f"community:{community_id}", offset=240)
        self.assertTrue(first.truncated)
        self.assertTrue(second.nodes)
        self.assertFalse(
            {node.node_id for node in first.nodes} & {node.node_id for node in second.nodes}
        )
        pages = []
        offset = 0
        while True:
            page = store.neighbors(f"community:{community_id}", offset=offset)
            pages.extend(node.node_id for node in page.nodes)
            if not page.truncated:
                break
            offset += 240
        self.assertEqual(len(pages), len(set(pages)))
        self.assertEqual(len(pages), len(communities[community_id]))

    def test_tampered_layout_hash_fails_binding(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "layout.json"
            payload = json.loads(LAYOUT.read_text())
            payload["output_sha256"] = "0" * 64
            path.write_text(json.dumps(payload))
            store = LocalResearchMapStore(path, INDEX, load_seed_reconciliation(RECONCILIATION))
            with self.assertRaisesRegex(LocalResearchMapError, "logical hash"):
                store.start()

    async def test_local_search_fragment_keeps_layout_scope_for_unplaced_names(self) -> None:
        store = _store()
        assert store._nodes is not None
        placed = next(iter(store._nodes.values()))
        unplaced = next(
            row
            for row in store.reconciliation.dispositions
            if f"legacy:{row.source_item_id}" not in store._nodes
        )
        placed_response = await SearchController.local_research_map_search_fragment.fn(
            None, store, placed.name
        )
        unplaced_response = await SearchController.local_research_map_search_fragment.fn(
            None, store, unplaced.seed_name
        )
        self.assertEqual(placed_response.template_name, "local_research_map_search_results.html")
        placed_hits = placed_response.context["hits"]
        unplaced_hits = unplaced_response.context["hits"]
        assert isinstance(placed_hits, tuple)
        assert isinstance(unplaced_hits, tuple)
        self.assertTrue(any(hit.placed for hit in placed_hits))
        self.assertTrue(
            any(
                not hit.placed and hit.unplaced_reason == "no_peer_similarity_evidence"
                for hit in unplaced_hits
            )
        )


def _store() -> LocalResearchMapStore:
    store = LocalResearchMapStore(LAYOUT, INDEX, load_seed_reconciliation(RECONCILIATION))
    store.start()
    return store
