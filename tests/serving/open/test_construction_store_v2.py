import tempfile
import unittest
from pathlib import Path

from musix.serving.open.construction_graph_v2 import (
    OpenConstructionGraphV2Config,
    build_open_construction_graph_v2,
    write_open_construction_graph_v2,
)
from musix.serving.open.construction_store_v2 import (
    OpenConstructionV2MapStore,
    OpenConstructionV2MapStoreError,
)
from tests.serving.open.test_construction_graph_v2 import build_expansion

ROOT = Path(__file__).resolve().parents[3]


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
            factual_parent = next(
                edge for edge in graph.edges if edge.kind == "public_catalog_taxonomy_parent"
            )
            factual_neighbors = store.neighbors(factual_parent.source_node_id)
            self.assertTrue(
                any(
                    edge.kind == "public_catalog_taxonomy_parent" and edge.factual_relationship
                    for edge in factual_neighbors.edges
                )
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

    def test_idm_alias_keeps_its_source_identity_and_excludes_music_review_anchor(self) -> None:
        store = OpenConstructionV2MapStore(ROOT / "data/model/open-construction-graph-v2.json")

        acronym = store.search("idm").hits
        full_name = store.search("intelligent dance music").hits
        neighbors = store.neighbors("legacy:item887")
        related_name = store.search("acid idm").hits

        self.assertEqual([item.node_id for item in acronym[:1]], ["legacy:item887"])
        self.assertEqual([item.node_id for item in full_name[:1]], ["legacy:item887"])
        self.assertEqual(acronym[0].name, "Intelligent dance music (IDM)")
        self.assertEqual(acronym[0].source_name, "intelligent dance music")
        self.assertEqual(neighbors.node_id, "legacy:item887")
        self.assertEqual(neighbors.edges, ())
        self.assertEqual([item.node_id for item in related_name[:1]], ["legacy:item5061"])

    def test_unresolved_imports_do_not_navigate_to_the_generic_music_review_root(self) -> None:
        store = OpenConstructionV2MapStore(ROOT / "data/model/open-construction-graph-v2.json")

        neighbors = store.neighbors("legacy:item4656")

        self.assertEqual(neighbors.node_id, "legacy:item4656")
        self.assertEqual(neighbors.edges, ())

    def test_projects_factual_taxonomy_roles_without_turning_them_into_peers(self) -> None:
        store = OpenConstructionV2MapStore(ROOT / "data/model/open-construction-graph-v2.json")

        hip_hop = store.neighbors("catalog:wikidata:genre:Q11401")
        pop_music = store.neighbors("catalog:wikidata:genre:Q37073")
        popular_music = store.neighbors("catalog:wikidata:genre:Q373342")
        review_only = store.neighbors("legacy:item887")

        self.assertEqual(
            [item.node_id for item in hip_hop.hierarchy.broader],
            ["catalog:wikidata:genre:Q373342"],
        )
        self.assertIn(
            "catalog:wikidata:genre:Q438503",
            {item.node_id for item in hip_hop.hierarchy.narrower},
        )
        self.assertEqual(hip_hop.hierarchy.narrower_total, 39)
        self.assertEqual(len(hip_hop.hierarchy.narrower), 12)
        self.assertEqual(hip_hop.hierarchy.narrower_remaining, 27)
        self.assertEqual(
            [item.node_id for item in pop_music.hierarchy.broader],
            ["catalog:wikidata:genre:Q373342"],
        )
        self.assertEqual(pop_music.hierarchy.siblings_total, 28)
        self.assertEqual(len(pop_music.hierarchy.siblings), 12)
        self.assertEqual(pop_music.hierarchy.siblings_remaining, 16)
        self.assertIn(
            "catalog:wikidata:genre:Q37073",
            {item.node_id for item in popular_music.hierarchy.narrower},
        )
        self.assertEqual(
            next(
                item for item in pop_music.nodes if item.node_id == pop_music.node_id
            ).taxonomy_presentation,
            "ordinary",
        )
        self.assertEqual(
            next(
                item for item in popular_music.nodes if item.node_id == popular_music.node_id
            ).taxonomy_presentation,
            "structural_umbrella",
        )
        self.assertNotIn(
            "catalog:wikidata:genre:Q373342",
            {item.node_id for item in store.response(level=0).nodes},
        )
        popular_hits = store.search("popular music").hits
        self.assertEqual(
            [item.node_id for item in popular_hits[:2]],
            [
                "catalog:wikidata:genre:Q37073",
                "catalog:wikidata:genre:Q373342",
            ],
        )
        self.assertEqual(popular_hits[0].taxonomy_presentation, "ordinary")
        self.assertEqual(popular_hits[1].taxonomy_presentation, "structural_umbrella")
        self.assertEqual(review_only.hierarchy.broader, ())
        self.assertEqual(review_only.hierarchy.narrower, ())
        self.assertEqual(review_only.hierarchy.siblings, ())
        self.assertEqual(review_only.hierarchy.broader_total, 0)
        self.assertEqual(review_only.hierarchy.narrower_total, 0)
        self.assertEqual(review_only.hierarchy.siblings_total, 0)


if __name__ == "__main__":
    unittest.main()
