import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from musix.metadata_representatives import metadata_representatives
from musix.models.modeling import MetadataCandidate


def _database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE current_public_models (model_key TEXT, model_run_id INTEGER);
            CREATE TABLE servable_public_model_runs (id INTEGER, output_sha256 TEXT);
            CREATE TABLE public_model_input_provenance (
              model_run_id INTEGER, provenance_id INTEGER
            );
            CREATE TABLE entity_identifiers (
              id INTEGER PRIMARY KEY, entity_id INTEGER, namespace TEXT, normalized_value TEXT
            );
            CREATE TABLE displayable_public_genre_representatives (
              entity_kind TEXT, genre_id INTEGER, source_entity_ref TEXT, display_name TEXT,
              rank INTEGER, direct_evidence_value REAL, source_count INTEGER,
              evidence_refs_json TEXT
            );
            INSERT INTO current_public_models VALUES ('public-graph', 7);
            INSERT INTO servable_public_model_runs VALUES
              (7, 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa');
            INSERT INTO public_model_input_provenance VALUES (7, 41), (7, 42);
            INSERT INTO entity_identifiers VALUES (1, 20, 'wikidata', 'Q100');
            INSERT INTO displayable_public_genre_representatives VALUES
              ('release_group', 20, 'musicbrainz:release-group:album-a', 'Album A', 1, 3.0, 2,
               '["catalog:metadata:1"]'),
              ('recording', 20, 'musicbrainz:recording:track-a', 'Track A', 1, 2.0, 1,
               '["catalog:metadata:2"]');
            """
        )


class MetadataRepresentativesTests(unittest.TestCase):
    def test_exports_existing_selected_examples_from_canonical_candidates(self) -> None:
        candidates = (
            MetadataCandidate(
                entity_kind="release_group",
                entity_id="musicbrainz:release-group:album-a",
                genre_id="wikidata:genre:Q100",
                name="Album A",
                direct_evidence_value=3.0,
                source_count=2,
                evidence_refs=("catalog:metadata:1",),
            ),
            MetadataCandidate(
                entity_kind="recording",
                entity_id="musicbrainz:recording:track-a",
                genre_id="wikidata:genre:Q100",
                name="Track A",
                direct_evidence_value=2.0,
                source_count=1,
                evidence_refs=("catalog:metadata:2",),
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "catalog.sqlite"
            _database(database)
            with patch(
                "musix.metadata_representatives._metadata_candidates", return_value=candidates
            ):
                artifact = metadata_representatives(database)

        self.assertEqual(artifact.run.model_run_id, 7)
        self.assertEqual(artifact.run.input_provenance_ids, (41, 42))
        self.assertEqual(
            [item.entity_kind for item in artifact.items], ["recording", "release_group"]
        )
        self.assertTrue(all(item.classification == "metadata_example" for item in artifact.items))
        self.assertIn("track-level metadata proxy", artifact.recording_semantics)

    def test_rejects_a_published_selection_missing_from_canonical_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "catalog.sqlite"
            _database(database)
            with (
                patch("musix.metadata_representatives._metadata_candidates", return_value=()),
                self.assertRaisesRegex(RuntimeError, "absent from the canonical candidate loader"),
            ):
                metadata_representatives(database)


if __name__ == "__main__":
    unittest.main()
