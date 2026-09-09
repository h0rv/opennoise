import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from musix.taxonomy.seeds.genre_seed_taxonomy import (
    PublicTaxonomyConfig,
    build_genre_seed_public_taxonomy,
    write_genre_seed_public_taxonomy,
)


class GenreSeedPublicTaxonomyTests(unittest.TestCase):
    def _seed(self, path: Path, *, noisy: bool = False) -> None:
        genres: list[dict[str, object]] = [
            {"source_item_id": "1", "external_id": "legacy:1", "name": "Rock Music"},
            {"source_item_id": "2", "external_id": "legacy:2", "name": "Rock Alias"},
            {"source_item_id": "3", "external_id": "legacy:3", "name": "Canadian Rock"},
            {"source_item_id": "4", "external_id": "legacy:4", "name": "Blue Jazz"},
            {"source_item_id": "5", "external_id": "legacy:5", "name": "Jazz"},
            {"source_item_id": "6", "external_id": "legacy:6", "name": "No Match"},
        ]
        if noisy:
            genres[2]["coordinate"] = {"x": 999, "y": -999}
            genres[2]["historical_neighbors"] = ["must not enter construction"]
            genres[2]["historical_artists"] = ["must not enter construction"]
        path.write_text(
            json.dumps(
                {
                    "artifact": {"source_id": "legacy", "content_sha256": "a" * 64},
                    "genres": genres,
                }
            ),
            encoding="utf-8",
        )

    def _catalog(self, path: Path, *, non_cc0: bool = False) -> None:
        license_name = "CC-BY-NC-SA-3.0" if non_cc0 else "CC0-1.0"
        with sqlite3.connect(path) as connection:
            connection.executescript(
                """
                CREATE TABLE data_sources (license_name TEXT NOT NULL);
                CREATE TABLE genres (
                    id INTEGER PRIMARY KEY, entity_kind TEXT NOT NULL, name TEXT NOT NULL
                );
                CREATE TABLE entity_names (entity_id INTEGER NOT NULL, name TEXT NOT NULL);
                CREATE TABLE identifier_types (
                    id INTEGER PRIMARY KEY, type_key TEXT NOT NULL
                );
                CREATE TABLE entity_identifiers (
                    entity_id INTEGER NOT NULL, identifier_type_id INTEGER NOT NULL,
                    normalized_value TEXT NOT NULL
                );
                CREATE TABLE genre_hierarchy (
                    child_genre_id INTEGER, parent_genre_id INTEGER, relation_id INTEGER
                );
                INSERT INTO identifier_types VALUES (1, 'wikidata_genre_qid');
                INSERT INTO genres VALUES
                  (1, 'genre', 'rock music'), (2, 'genre', 'jazz'), (3, 'genre', 'jazz');
                INSERT INTO entity_names VALUES (1, 'rock alias'), (1, 'rock');
                INSERT INTO entity_identifiers VALUES (1, 1, 'Q1'), (2, 1, 'Q2'), (3, 1, 'Q3');
                INSERT INTO genre_hierarchy VALUES (1, 2, 17);
                """
            )
            connection.execute("INSERT INTO data_sources VALUES (?)", (license_name,))

    def test_anchors_composition_but_never_creates_an_inferred_membership(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            seed, catalog = root / "seed.json", root / "catalog.sqlite"
            self._seed(seed)
            self._catalog(catalog)
            artifact = build_genre_seed_public_taxonomy(
                seed,
                catalog,
                config=PublicTaxonomyConfig(expected_seed_count=6, minimum_calibration_examples=1),
            )
            statuses = {item.seed_name: item for item in artifact.inferences}
            self.assertEqual(statuses["Rock Music"].status, "canonical_exact")
            self.assertEqual(statuses["Rock Alias"].status, "canonical_alias")
            anchor = statuses["Canadian Rock"]
            self.assertEqual(anchor.status, "anchored_compositional")
            self.assertEqual(anchor.lexical_modifier, "canadian")
            anchor_node = anchor.anchor
            if anchor_node is None:
                self.fail("anchored compositional seed must include a public anchor")
            self.assertEqual(anchor_node.catalog_id, "wikidata:genre:Q1")
            self.assertFalse(anchor.canonical_membership_created)
            self.assertFalse(anchor.confidence_is_membership_probability)
            self.assertEqual(statuses["Blue Jazz"].status, "abstained")
            self.assertEqual(statuses["Jazz"].status, "ambiguous_exact")
            self.assertEqual(statuses["No Match"].status, "abstained")
            self.assertEqual(artifact.coverage.canonical_membership_count, 2)
            self.assertEqual(artifact.coverage.inferred_membership_count, 0)
            self.assertEqual(artifact.coverage.covered_for_review_count, 3)

    def test_ignores_historical_fields_and_replays_identically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            seed, noisy, catalog, output = (
                root / "seed.json",
                root / "noisy.json",
                root / "catalog.sqlite",
                root / "artifact.json",
            )
            self._seed(seed)
            self._seed(noisy, noisy=True)
            self._catalog(catalog)
            config = PublicTaxonomyConfig(expected_seed_count=6)
            first = build_genre_seed_public_taxonomy(seed, catalog, config=config)
            second = build_genre_seed_public_taxonomy(noisy, catalog, config=config)
            self.assertEqual(first.model_dump(), second.model_dump())
            self.assertEqual(first.output_sha256, second.output_sha256)
            self.assertEqual(
                write_genre_seed_public_taxonomy(first, output),
                write_genre_seed_public_taxonomy(first, output),
            )

    def test_rejects_non_public_domain_catalog_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            seed, catalog = root / "seed.json", root / "catalog.sqlite"
            self._seed(seed)
            self._catalog(catalog, non_cc0=True)
            with self.assertRaisesRegex(ValueError, "CC0-only"):
                build_genre_seed_public_taxonomy(
                    seed, catalog, config=PublicTaxonomyConfig(expected_seed_count=6)
                )


if __name__ == "__main__":
    unittest.main()
