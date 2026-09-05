"""Tests for the name-only Every Noise to catalog bridge."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from musix.genre_seed_universe import build_genre_seed_universe, load_seed_input


class GenreSeedUniverseTests(unittest.TestCase):
    def _database(self, directory: Path) -> Path:
        path = directory / "catalog.sqlite"
        with sqlite3.connect(path) as connection:
            connection.executescript(
                """
                CREATE TABLE genres (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
                CREATE TABLE entity_names (
                    entity_id INTEGER NOT NULL, name_kind TEXT NOT NULL, name TEXT NOT NULL
                );
                CREATE TABLE artists (id INTEGER PRIMARY KEY);
                CREATE TABLE data_sources (source_key TEXT PRIMARY KEY);
                CREATE TABLE artist_genre_evidence (
                    id INTEGER PRIMARY KEY, genre_id INTEGER NOT NULL, artist_id INTEGER NOT NULL,
                    evidence_kind TEXT NOT NULL, evidence_value REAL NOT NULL,
                    source_key TEXT NOT NULL, source_record_id TEXT NOT NULL
                );
                INSERT INTO genres VALUES (1, 'techno'), (2, 'jazz'), (3, 'jazz');
                INSERT INTO entity_names VALUES (1, 'alias', 'techno music');
                INSERT INTO entity_names VALUES (2, 'alias', 'blue jazz');
                INSERT INTO artists VALUES (11), (12);
                INSERT INTO data_sources VALUES ('fixture-public');
                INSERT INTO artist_genre_evidence VALUES
                    (101, 1, 11, 'direct_source_claim', 1.0, 'fixture-public', 'g1'),
                    (102, 1, 12, 'release_group_propagation', 1.0, 'fixture-public', 'g2'),
                    (103, 2, 11, 'direct_source_claim', 0.5, 'fixture-public', 'g3');
                """
            )
        return path

    def _seed(self, path: Path, *, noisy: bool = False) -> None:
        genres = [
            {
                "external_id": "enao-legacy:item1",
                "source_item_id": "item1",
                "source_order": 1,
                "name": "TECHNÓ",
                "coordinate": {"x_px": 10, "y_px": 20, "color_hex": "#ffffff"},
                "representative": {"artist_name": "invented", "track_title": "ignored"},
            },
            {
                "external_id": "enao-legacy:item2",
                "source_item_id": "item2",
                "source_order": 2,
                "name": "Techno Music",
                "coordinate": {"x_px": 30, "y_px": 40, "color_hex": "#000000"},
            },
            {
                "external_id": "enao-legacy:item3",
                "source_item_id": "item3",
                "source_order": 3,
                "name": "Swedish techno",
                "h3_memberships": [{"artist": "must not be read"}],
                "historical_neighbors": ["jazz"],
            },
            {
                "external_id": "enao-legacy:item4",
                "source_item_id": "item4",
                "source_order": 4,
                "name": "Blue jazz",
            },
            {
                "external_id": "enao-legacy:item5",
                "source_item_id": "item5",
                "source_order": 5,
                "name": "No Such Thing",
            },
            {
                "external_id": "enao-legacy:item6",
                "source_item_id": "item6",
                "source_order": 6,
                "name": "jazz",
            },
        ]
        if noisy:
            genres[0]["coordinate"] = {"x_px": 999999, "y_px": -1, "color_hex": "#123456"}
            genres[2]["sample"] = {"audio": "should not affect result"}
        payload = {
            "artifact": {
                "source_id": "enao_quint_legacy_map_2025",
                "content_sha256": "a" * 64,
                "byte_size": 123,
            },
            "genres": genres,
            "h3": {"memberships": ["ignored"]},
        }
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_non_name_historical_fields_do_not_affect_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            seed = root / "seed.json"
            noisy = root / "noisy.json"
            self._seed(seed)
            self._seed(noisy, noisy=True)
            database = self._database(root)
            first = build_genre_seed_universe(seed, [database])
            second = build_genre_seed_universe(noisy, [database])
            self.assertEqual(first.model_dump(), second.model_dump())

    def test_classification_and_no_invented_artist_edges(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            seed = root / "seed.json"
            self._seed(seed)
            artifact = build_genre_seed_universe(seed, [self._database(root)])
            classes = {item.seed_name: item.classification for item in artifact.resolutions}
            self.assertEqual(classes["TECHNÓ"], "direct_exact")
            self.assertEqual(classes["Techno Music"], "alias_exact")
            self.assertEqual(classes["Swedish techno"], "compositional_candidate")
            self.assertEqual(classes["Blue jazz"], "alias_exact")
            self.assertEqual(classes["No Such Thing"], "unresolved")
            self.assertEqual(classes["jazz"], "ambiguous")
            techno = next(item for item in artifact.resolutions if item.seed_name == "TECHNÓ")
            self.assertEqual(techno.direct_evidence_count, 1)
            self.assertEqual(techno.distinct_artist_count, 1)
            candidate = next(
                item for item in artifact.resolutions if item.seed_name == "Swedish techno"
            )
            self.assertEqual(candidate.evidence_refs, ())

    def test_normalization_is_conservative_and_build_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            seed = root / "seed.json"
            self._seed(seed)
            database = self._database(root)
            first = build_genre_seed_universe(seed, [database])
            second = build_genre_seed_universe(seed, [database])
            self.assertEqual(first.model_dump(), second.model_dump())
            self.assertEqual(load_seed_input(seed).names[0].name, "TECHNÓ")
            self.assertEqual(first.output_sha256, second.output_sha256)


if __name__ == "__main__":
    unittest.main()
