import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from opennoise.serving.open.construction_graph import (
    OpenConstructionGraphConfig,
    assert_no_prohibited_construction_fields,
    build_open_construction_graph,
    publish_open_construction_graph,
    verify_open_construction_graph,
)
from opennoise.storage import LocalObjectStore
from opennoise.taxonomy.seeds.taxonomy import (
    PublicTaxonomyConfig,
    build_genre_seed_public_taxonomy,
    write_genre_seed_public_taxonomy,
)


class OpenConstructionGraphTests(unittest.TestCase):
    def _seed(self, path: Path, *, noisy: bool = False) -> None:
        genres: list[dict[str, object]] = [
            {"source_item_id": "1", "external_id": "legacy:1", "name": "Rock Music"},
            {"source_item_id": "2", "external_id": "legacy:2", "name": "Indie Rock"},
            {"source_item_id": "3", "external_id": "legacy:3", "name": "Jazz"},
            {"source_item_id": "4", "external_id": "legacy:4", "name": "Blue Jazz"},
            {"source_item_id": "5", "external_id": "legacy:5", "name": "Genre Rock"},
            {"source_item_id": "6", "external_id": "legacy:6", "name": "No Match"},
        ]
        if noisy:
            genres[1]["coordinate"] = {"x": 12, "y": -4}
            genres[1]["historical_neighbors"] = ["forbidden"]
            genres[1]["historical_artists"] = ["forbidden"]
        path.write_text(
            json.dumps(
                {"artifact": {"source_id": "legacy", "content_sha256": "a" * 64}, "genres": genres}
            ),
            encoding="utf-8",
        )

    def _catalog(self, path: Path) -> None:
        with sqlite3.connect(path) as connection:
            connection.executescript(
                """
                CREATE TABLE data_sources (license_name TEXT NOT NULL);
                CREATE TABLE genres (id INTEGER PRIMARY KEY, entity_kind TEXT, name TEXT);
                CREATE TABLE entity_names (entity_id INTEGER NOT NULL, name TEXT NOT NULL);
                CREATE TABLE identifier_types (id INTEGER PRIMARY KEY, type_key TEXT NOT NULL);
                CREATE TABLE entity_identifiers (
                    entity_id INTEGER NOT NULL, identifier_type_id INTEGER NOT NULL,
                    normalized_value TEXT NOT NULL
                );
                CREATE TABLE genre_hierarchy (
                    child_genre_id INTEGER, parent_genre_id INTEGER, relation_id TEXT
                );
                INSERT INTO data_sources VALUES ('CC0-1.0');
                INSERT INTO identifier_types VALUES (1, 'wikidata_genre_qid');
                INSERT INTO genres VALUES (1, 'genre', 'rock music'), (2, 'genre', 'jazz');
                INSERT INTO entity_identifiers VALUES (1, 1, 'Q1'), (2, 1, 'Q2');
                INSERT INTO genre_hierarchy VALUES (1, 2, 'P279');
                """
            )

    def _build(self, root: Path, *, noisy: bool = False):  # noqa: ANN202
        root.mkdir(parents=True, exist_ok=True)
        seed, catalog, taxonomy = (
            root / "seed.json",
            root / "catalog.sqlite",
            root / "taxonomy.json",
        )
        self._seed(seed, noisy=noisy)
        self._catalog(catalog)
        anchor = build_genre_seed_public_taxonomy(
            seed, catalog, config=PublicTaxonomyConfig(expected_seed_count=6)
        )
        write_genre_seed_public_taxonomy(anchor, taxonomy)
        return build_open_construction_graph(
            seed, taxonomy, catalog, config=OpenConstructionGraphConfig(expected_seed_count=6)
        )

    def test_builds_explainable_boundary_and_keeps_every_seed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            graph = self._build(Path(temporary))
            self.assertEqual(len(graph.nodes), 6)
            self.assertEqual(graph.coverage.inferred_membership_count, 0)
            self.assertEqual(graph.coverage.review_candidates_promoted_to_memberships, 0)
            factual = [edge for edge in graph.edges if edge.factual_relationship]
            review = [edge for edge in graph.edges if edge.review_candidate]
            self.assertEqual(len(factual), 1)
            self.assertEqual((factual[0].source_item_id, factual[0].target_item_id), ("1", "3"))
            self.assertTrue(all(not edge.factual_relationship for edge in review))
            self.assertTrue(
                all(
                    edge.kind != "lexical_review_anchor" or edge.source_item_id != "5"
                    for edge in graph.edges
                )
            )
            self.assertEqual(len(graph.layout), 6)
            self.assertTrue(verify_open_construction_graph(graph).no_prohibited_inputs)

    def test_ignores_legacy_geometry_and_replays_identically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            clean = self._build(root / "clean")
            noisy = self._build(root / "noisy", noisy=True)
            self.assertEqual(clean.model_dump(), noisy.model_dump())
            self.assertEqual(clean.output_sha256, noisy.output_sha256)

    def test_publication_receipt_is_immutable_and_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = self._build(root)
            receipt, write = publish_open_construction_graph(
                graph, output_path=root / "graph.json", store=LocalObjectStore(root / "objects")
            )
            self.assertEqual(receipt.artifact_sha256, write.sha256)
            self.assertTrue(receipt.gate.complete_seed_coverage)
            self.assertTrue((root / "objects" / receipt.object_key).is_file())

    def test_rejects_prohibited_fields_from_the_construction_projection(self) -> None:
        with self.assertRaisesRegex(ValueError, "prohibited construction field"):
            assert_no_prohibited_construction_fields({"coordinate": [0, 0]})


if __name__ == "__main__":
    unittest.main()
