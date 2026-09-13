import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from opennoise.serving.public.taxonomy_expansion import (
    PublicTaxonomyExpansionConfig,
    _read_catalog,
    build_public_taxonomy_expansion,
    publish_public_taxonomy_expansion,
    verify_public_taxonomy_expansion,
)
from opennoise.storage import LocalObjectStore
from opennoise.taxonomy.seeds.taxonomy import (
    PublicTaxonomyConfig,
    build_genre_seed_public_taxonomy,
    write_genre_seed_public_taxonomy,
)


class PublicTaxonomyExpansionTests(unittest.TestCase):
    def _seed(self, path: Path) -> None:
        path.write_text(
            json.dumps(
                {
                    "artifact": {"source_id": "legacy", "content_sha256": "a" * 64},
                    "genres": [
                        {
                            "source_item_id": "1",
                            "external_id": "legacy:1",
                            "name": "Rock Music",
                        },
                        {
                            "source_item_id": "2",
                            "external_id": "legacy:2",
                            "name": "New Rock Music",
                        },
                        {
                            "source_item_id": "3",
                            "external_id": "legacy:3",
                            "name": "Jazz",
                        },
                        {
                            "source_item_id": "4",
                            "external_id": "legacy:4",
                            "name": "Blue Jazz",
                        },
                        {
                            "source_item_id": "5",
                            "external_id": "legacy:5",
                            "name": "No Match",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

    def _catalog(
        self,
        path: Path,
        *,
        local_only_hierarchy: bool = False,
        unrelated_non_cc0_source: bool = False,
    ) -> None:
        with sqlite3.connect(path) as db:
            db.executescript(
                """
                CREATE TABLE data_sources (
                    id INTEGER PRIMARY KEY, license_name TEXT NOT NULL
                );
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
                INSERT INTO rights_policies VALUES (2, 'local-only', 1);
                INSERT INTO rights_policy_permissions VALUES (2, 'export', 'allow');
                INSERT INTO provenance_records VALUES (2, 1, 2);
                INSERT INTO entity_provenance VALUES (1, 1), (2, 1);
                """
            )
            db.execute(
                "INSERT INTO genre_hierarchy VALUES (279, 1, 2, ?)",
                (2 if local_only_hierarchy else 1,),
            )
            if unrelated_non_cc0_source:
                db.execute("INSERT INTO data_sources VALUES (2, 'proprietary')")

    def _build(self, root: Path):  # noqa: ANN202
        root.mkdir(parents=True, exist_ok=True)
        seed = root / "seed.json"
        catalog = root / "catalog.sqlite"
        taxonomy_path = root / "taxonomy.json"
        self._seed(seed)
        self._catalog(catalog)
        taxonomy = build_genre_seed_public_taxonomy(
            seed,
            catalog,
            config=PublicTaxonomyConfig(expected_seed_count=5),
        )
        write_genre_seed_public_taxonomy(taxonomy, taxonomy_path)
        return build_public_taxonomy_expansion(
            taxonomy_path,
            catalog,
            config=PublicTaxonomyExpansionConfig(expected_legacy_seed_count=5),
        )

    def test_keeps_factual_and_review_connectivity_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact = self._build(Path(temporary))
            self.assertEqual(artifact.coverage.legacy_seed_node_count, 5)
            self.assertEqual(artifact.coverage.catalog_node_count, 2)
            self.assertEqual(artifact.coverage.canonical_identity_edge_count, 2)
            self.assertEqual(artifact.coverage.catalog_taxonomy_edge_count, 1)
            self.assertEqual(artifact.coverage.compositional_review_edge_count, 2)
            self.assertGreater(
                artifact.coverage.review_enabled.connected_legacy_seed_count,
                artifact.coverage.factual_only.connected_legacy_seed_count,
            )
            factual = [edge for edge in artifact.edges if edge.factual_relationship]
            review = [edge for edge in artifact.edges if edge.review_candidate]
            self.assertTrue(all(edge.kind != "compositional_review_anchor" for edge in factual))
            self.assertTrue(all(not edge.factual_relationship for edge in review))
            self.assertEqual(artifact.coverage.inferred_artist_membership_count, 0)
            self.assertEqual(artifact.coverage.review_links_promoted_to_artist_memberships, 0)

    def test_replays_and_publishes_immutable_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = self._build(root)
            second = self._build(root / "repeat")
            self.assertEqual(first.output_sha256, second.output_sha256)
            gate = verify_public_taxonomy_expansion(first)
            receipt, write = publish_public_taxonomy_expansion(
                first,
                output_path=root / "expansion.json",
                store=LocalObjectStore(root / "objects"),
            )
            self.assertEqual(receipt.artifact_sha256, write.sha256)
            self.assertEqual(receipt.gate, gate)
            self.assertTrue((root / "objects" / receipt.object_key).is_file())

    def test_excludes_a_hierarchy_row_without_row_level_export_permission(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            seed = root / "seed.json"
            catalog = root / "catalog.sqlite"
            taxonomy_path = root / "taxonomy.json"
            self._seed(seed)
            self._catalog(catalog, local_only_hierarchy=True)
            taxonomy = build_genre_seed_public_taxonomy(
                seed,
                catalog,
                config=PublicTaxonomyConfig(expected_seed_count=5),
            )
            write_genre_seed_public_taxonomy(taxonomy, taxonomy_path)
            artifact = build_public_taxonomy_expansion(
                taxonomy_path,
                catalog,
                config=PublicTaxonomyExpansionConfig(expected_legacy_seed_count=5),
            )
            self.assertEqual(artifact.coverage.catalog_taxonomy_edge_count, 0)

    def test_ignores_unrelated_non_cc0_catalog_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog = root / "catalog.sqlite"
            self._catalog(catalog, unrelated_non_cc0_source=True)
            public_nodes, public_relations = _read_catalog(catalog)
            self.assertEqual(len(public_nodes), 2)
            self.assertEqual(len(public_relations), 1)

    def test_deduplicates_relation_rows_from_multiple_qualifying_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog = root / "catalog.sqlite"
            self._catalog(catalog)
            with sqlite3.connect(catalog) as db:
                db.execute("INSERT INTO rights_policy_permissions VALUES (1, 'export', 'allow')")
            _public_nodes, public_relations = _read_catalog(catalog)
            self.assertEqual(len(public_relations), 1)


if __name__ == "__main__":
    unittest.main()
