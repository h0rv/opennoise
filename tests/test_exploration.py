import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from musix.db import Database
from musix.exploration import CatalogLens, MapQuery, Viewport, optional_viewport

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "migrations" / "smoke" / "fixture.sql"


class ExplorationTests(unittest.TestCase):
    def test_viewport_requires_complete_ordered_bounds(self) -> None:
        self.assertIsNone(optional_viewport(None, None, None, None))
        with self.assertRaises(ValueError):
            optional_viewport(0.0, None, 1.0, 1.0)
        with self.assertRaises(ValueError):
            Viewport(minimum_x=1.0, minimum_y=0.0, maximum_x=1.0, maximum_y=2.0)

    def test_queries_map_by_viewport_source_time_and_lens(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "catalog.sqlite")
            database.initialize()
            with database.connect() as connection:
                connection.executescript(FIXTURE.read_text(encoding="utf-8"))

            included = database.query_map(
                MapQuery(
                    layout_key="genres",
                    lens=CatalogLens.GENRES,
                    source_key="fixture",
                    observed_at_or_before=datetime(2026, 1, 2, tzinfo=UTC),
                    viewport=Viewport(
                        minimum_x=0.0,
                        minimum_y=-1.0,
                        maximum_x=1.0,
                        maximum_y=0.0,
                    ),
                )
            )
            wrong_source = database.query_map(
                MapQuery(layout_key="genres", source_key="another-source")
            )
            too_early = database.query_map(
                MapQuery(
                    layout_key="genres",
                    observed_at_or_before=datetime(2025, 1, 1, tzinfo=UTC),
                )
            )

            self.assertEqual([point.name for point in included.points], ["IDM"])
            self.assertFalse(included.truncated)
            self.assertEqual(wrong_source.points, ())
            self.assertEqual(too_early.points, ())

    def test_reads_layout_metadata_and_genre_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "catalog.sqlite")
            database.initialize()
            with database.connect() as connection:
                connection.executescript(FIXTURE.read_text(encoding="utf-8"))
                connection.executescript(
                    """
                    INSERT INTO layout_runs (
                        id, layout_key, revision, algorithm_key, algorithm_revision,
                        input_fingerprint, status, policy_id, completed_at
                    ) VALUES (
                        2, 'classic', 1, 'source_coordinates', '1',
                        '3434343434343434343434343434343434343434343434343434343434343434',
                        'complete', 1, '2026-01-01T00:00:00Z'
                    );
                    INSERT INTO layout_points (
                        layout_run_id, entity_id, x, y, display_weight, color_hex
                    ) SELECT 2, entity_id, x, y, display_weight, color_hex
                      FROM layout_points WHERE layout_run_id = 1;
                    INSERT INTO current_layouts (layout_key, layout_run_id)
                    VALUES ('classic', 2);
                    """
                )

            metadata = database.layout_metadata("genres")
            layouts = database.published_layouts()
            detail = database.genre_detail(1)

            self.assertIsNotNone(metadata)
            if metadata is not None:
                self.assertEqual(metadata.strategy.key, "fixture")
                self.assertEqual(metadata.point_count, 1)
                self.assertEqual(metadata.coordinate_space.coordinate_kind, "derived")
            self.assertEqual(tuple(layout.layout_key for layout in layouts), ("classic", "genres"))
            self.assertEqual(layouts[0].coordinate_space.coordinate_kind, "historic_source")
            self.assertEqual(layouts[1].coordinate_space.coordinate_kind, "derived")
            self.assertIsNotNone(detail)
            if detail is not None:
                self.assertEqual(detail.name, "IDM")
                self.assertEqual(detail.evidence[0].source_key, "fixture")

    def test_genre_detail_and_provenance_honor_display_suppression(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "catalog.sqlite")
            database.initialize()
            with database.connect() as connection, connection:
                connection.executescript(FIXTURE.read_text(encoding="utf-8"))
                connection.execute(
                    """
                    INSERT INTO suppression_events (
                        target_kind, target_ref, use_kind, event_action, reason,
                        effective_at, event_fingerprint
                    ) VALUES ('entity', '1', 'display', 'suppress', 'Test', ?, ?)
                    """,
                    (
                        "2026-08-30T00:00:00Z",
                        "efefefefefefefefefefefefefefefefefefefefefefefefefefefefefefefef",
                    ),
                )

            self.assertIsNone(database.genre_detail(1))
            self.assertEqual(database.entity_provenance(1), ())


if __name__ == "__main__":
    unittest.main()
