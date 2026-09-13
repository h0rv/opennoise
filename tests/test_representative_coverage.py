import sqlite3
import tempfile
import unittest
from pathlib import Path

from opennoise.ml.representative_coverage import (
    RepresentativeCoverageSettings,
    representative_coverage,
)
from tests.test_public_model_repository import _catalog


class RepresentativeCoverageTests(unittest.TestCase):
    def test_reports_candidate_and_selected_gaps_per_kind(self) -> None:
        source = _catalog()
        self.addCleanup(source.close)
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "catalog.sqlite"
            with sqlite3.connect(database) as destination:
                source.backup(destination)
                destination.executescript(
                    """
                    CREATE TABLE current_public_models (model_key TEXT, model_run_id INTEGER);
                    CREATE TABLE servable_public_model_runs (id INTEGER, output_sha256 TEXT);
                    CREATE TABLE displayable_public_genre_representatives (
                      entity_kind TEXT, genre_id INTEGER, rank INTEGER, source_entity_ref TEXT
                    );
                    INSERT INTO current_public_models VALUES ('public-graph', 7);
                    INSERT INTO servable_public_model_runs VALUES
                      (7, 'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc');
                    INSERT INTO displayable_public_genre_representatives VALUES
                      ('artist', 20, 1, 'musicbrainz:artist:11111111-1111-4111-8111-111111111111');
                    """
                )

            report = representative_coverage(database)

        self.assertEqual(report.modelable_genres, 1)
        self.assertEqual(report.selected_model_output_sha256, "c" * 64)
        self.assertEqual(
            tuple(item.entity_kind for item in report.by_kind),
            (
                "artist",
                "release_group",
                "recording",
            ),
        )
        artist, album, track = report.by_kind
        self.assertEqual(
            (artist.candidate_pairs, artist.candidate_entities, artist.candidate_genres), (1, 1, 1)
        )
        self.assertEqual((artist.published_items, artist.published_genres), (1, 1))
        self.assertEqual(
            (artist.candidate_zero_coverage_genres, artist.published_zero_coverage_genres), (0, 0)
        )
        self.assertEqual((album.candidate_pairs, album.published_items), (1, 0))
        self.assertEqual(
            (album.candidate_zero_coverage_genres, album.published_zero_coverage_genres), (0, 1)
        )
        self.assertEqual((track.candidate_pairs, track.published_items), (0, 0))
        self.assertEqual(
            (track.candidate_zero_coverage_genres, track.published_zero_coverage_genres), (1, 1)
        )

    def test_respects_candidate_bound(self) -> None:
        source = _catalog()
        self.addCleanup(source.close)
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "catalog.sqlite"
            with sqlite3.connect(database) as destination:
                source.backup(destination)
                destination.executescript(
                    """
                    CREATE TABLE current_public_models (model_key TEXT, model_run_id INTEGER);
                    CREATE TABLE servable_public_model_runs (id INTEGER, output_sha256 TEXT);
                    CREATE TABLE displayable_public_genre_representatives (
                      entity_kind TEXT, genre_id INTEGER, rank INTEGER, source_entity_ref TEXT
                    );
                    """
                )
            with self.assertRaisesRegex(RuntimeError, "combined metadata candidates"):
                representative_coverage(
                    database,
                    RepresentativeCoverageSettings(max_metadata_candidates=1),
                )


if __name__ == "__main__":
    unittest.main()
