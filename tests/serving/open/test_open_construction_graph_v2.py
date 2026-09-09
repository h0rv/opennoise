import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from musix.serving.open.open_construction_graph_v2 import (
    OpenConstructionGraphV2Config,
    build_open_construction_graph_v2,
    publish_open_construction_graph_v2,
    verify_open_construction_graph_v2,
)
from musix.serving.public.public_taxonomy_expansion import (
    PublicTaxonomyExpansionConfig,
    build_public_taxonomy_expansion,
    write_public_taxonomy_expansion,
)
from musix.storage import LocalObjectStore
from musix.taxonomy.seeds.genre_seed_taxonomy import (
    PublicTaxonomyConfig,
    build_genre_seed_public_taxonomy,
    write_genre_seed_public_taxonomy,
)


def build_expansion(root: Path) -> Path:
    """Build a complete small public-taxonomy expansion from explicit files."""
    root.mkdir(parents=True, exist_ok=True)
    seed = root / "seed.json"
    catalog = root / "catalog.sqlite"
    taxonomy_path = root / "taxonomy.json"
    expansion_path = root / "expansion.json"
    seed.write_text(
        json.dumps(
            {
                "artifact": {"source_id": "legacy", "content_sha256": "a" * 64},
                "genres": [
                    {"source_item_id": "1", "external_id": "legacy:1", "name": "Rock Music"},
                    {"source_item_id": "2", "external_id": "legacy:2", "name": "New Rock Music"},
                    {"source_item_id": "3", "external_id": "legacy:3", "name": "Jazz"},
                    {"source_item_id": "4", "external_id": "legacy:4", "name": "Blue Jazz"},
                    {"source_item_id": "5", "external_id": "legacy:5", "name": "No Match"},
                ],
            }
        ),
        encoding="utf-8",
    )
    with sqlite3.connect(catalog) as db:
        db.executescript(
            """
            CREATE TABLE data_sources (id INTEGER PRIMARY KEY, license_name TEXT NOT NULL);
            CREATE TABLE genres (id INTEGER PRIMARY KEY, entity_kind TEXT, name TEXT);
            CREATE TABLE identifier_types (id INTEGER PRIMARY KEY, type_key TEXT NOT NULL);
            CREATE TABLE entity_identifiers (
                entity_id INTEGER NOT NULL, identifier_type_id INTEGER NOT NULL,
                normalized_value TEXT NOT NULL
            );
            CREATE TABLE entity_names (entity_id INTEGER NOT NULL, name TEXT NOT NULL);
            CREATE TABLE genre_hierarchy (
                relation_id INTEGER, child_genre_id INTEGER, parent_genre_id INTEGER,
                provenance_id INTEGER NOT NULL
            );
            CREATE TABLE rights_policies (
                id INTEGER PRIMARY KEY, policy_key TEXT, local_only INTEGER NOT NULL
            );
            CREATE TABLE rights_policy_permissions (
                policy_id INTEGER NOT NULL, use_kind TEXT NOT NULL, decision TEXT NOT NULL
            );
            CREATE TABLE provenance_records (
                id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL, policy_id INTEGER NOT NULL
            );
            CREATE TABLE entity_provenance (
                entity_id INTEGER NOT NULL, provenance_id INTEGER NOT NULL
            );
            INSERT INTO data_sources VALUES (1, 'CC0-1.0');
            INSERT INTO identifier_types VALUES (1, 'wikidata_genre_qid');
            INSERT INTO genres VALUES (1, 'genre', 'rock music'), (2, 'genre', 'jazz');
            INSERT INTO entity_identifiers VALUES (1, 1, 'Q1'), (2, 1, 'Q2');
            INSERT INTO rights_policies VALUES (1, 'test', 0);
            INSERT INTO rights_policy_permissions VALUES (1, 'export', 'allow');
            INSERT INTO provenance_records VALUES (1, 1, 1);
            INSERT INTO entity_provenance VALUES (1, 1), (2, 1);
            INSERT INTO genre_hierarchy VALUES (279, 1, 2, 1);
            """
        )
    taxonomy = build_genre_seed_public_taxonomy(
        seed,
        catalog,
        config=PublicTaxonomyConfig(expected_seed_count=5),
    )
    write_genre_seed_public_taxonomy(taxonomy, taxonomy_path)
    expansion = build_public_taxonomy_expansion(
        taxonomy_path,
        catalog,
        config=PublicTaxonomyExpansionConfig(expected_legacy_seed_count=5),
    )
    write_public_taxonomy_expansion(expansion, expansion_path)
    return expansion_path


class OpenConstructionGraphV2Tests(unittest.TestCase):
    def test_projects_verified_expansion_with_fact_and_review_edges_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = build_open_construction_graph_v2(
                build_expansion(root),
                config=OpenConstructionGraphV2Config(expected_legacy_seed_count=5),
            )

            self.assertEqual(graph.revision, "open-construction-graph-v2")
            self.assertEqual(graph.coverage.legacy_seed_node_count, 5)
            self.assertEqual(graph.coverage.catalog_node_count, 2)
            self.assertEqual(len(graph.nodes), 7)
            self.assertEqual(len(graph.layout), 7)
            self.assertEqual(graph.coverage.canonical_identity_edge_count, 2)
            self.assertEqual(graph.coverage.catalog_taxonomy_edge_count, 1)
            self.assertEqual(graph.coverage.compositional_review_edge_count, 2)
            self.assertEqual(graph.coverage.ambiguous_identity_review_edge_count, 0)
            self.assertEqual(len(graph.edges), 5)
            self.assertEqual(graph.coverage.review_enabled_connected_legacy_seed_count, 4)
            self.assertEqual(graph.coverage.review_enabled_isolated_legacy_seed_count, 1)
            self.assertEqual(graph.coverage.inferred_artist_membership_count, 0)
            self.assertEqual(graph.coverage.review_links_promoted_to_facts, 0)
            self.assertEqual(graph.coverage.review_links_promoted_to_artist_memberships, 0)
            self.assertTrue(
                all(
                    edge.factual_relationship
                    == (
                        edge.kind
                        in {"canonical_catalog_identity", "public_catalog_taxonomy_parent"}
                    )
                    for edge in graph.edges
                )
            )
            self.assertTrue(
                all(not edge.factual_relationship for edge in graph.edges if edge.review_candidate)
            )
            self.assertTrue(verify_open_construction_graph_v2(graph).verified_taxonomy_expansion)

    def test_replays_from_explicit_artifact_and_publishes_a_gated_object(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expansion = build_expansion(root)
            settings = OpenConstructionGraphV2Config(expected_legacy_seed_count=5)
            first = build_open_construction_graph_v2(expansion, config=settings)
            second = build_open_construction_graph_v2(expansion, config=settings)
            self.assertEqual(first.output_sha256, second.output_sha256)
            receipt, write = publish_open_construction_graph_v2(
                first,
                output_path=root / "open-v2.json",
                store=LocalObjectStore(root / "objects"),
            )
            self.assertEqual(receipt.artifact_sha256, write.sha256)
            self.assertTrue(receipt.gate.complete_legacy_seed_coverage)
            self.assertTrue((root / "objects" / receipt.object_key).is_file())

    def test_fails_closed_when_the_expansion_is_absent_or_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing-expansion.json"
            with self.assertRaises(FileNotFoundError):
                build_open_construction_graph_v2(
                    missing,
                    config=OpenConstructionGraphV2Config(expected_legacy_seed_count=5),
                )
            invalid = Path(temporary) / "invalid-expansion.json"
            invalid.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                build_open_construction_graph_v2(
                    invalid,
                    config=OpenConstructionGraphV2Config(expected_legacy_seed_count=5),
                )


if __name__ == "__main__":
    unittest.main()
