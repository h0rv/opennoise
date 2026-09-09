import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from musix.ingest.listenbrainz_offline_experiment import evaluate_listenbrainz_offline_experiment

_NOVEL_REFERENCE_COUNT = 2
_A = "00000000-0000-4000-8000-000000000001"
_B = "00000000-0000-4000-8000-000000000002"
_C = "00000000-0000-4000-8000-000000000003"
_D = "00000000-0000-4000-8000-000000000004"


class ListenBrainzOfflineExperimentTests(unittest.TestCase):
    def test_excludes_recurrent_pairs_and_uses_only_novel_future_references(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "qualified.sqlite"
            public = root / "public.sqlite"
            _source_fixture(source)
            _public_fixture(public)

            artifact = evaluate_listenbrainz_offline_experiment(
                listenbrainz_path=source,
                public_database_path=public,
                listenbrainz_database_sha256="a" * 64,
                public_database_sha256="b" * 64,
            )

        self.assertEqual(artifact.public_artist_crosswalk_count, 4)
        self.assertEqual(artifact.source_window_count, 5)
        self.assertEqual(artifact.train_pair_count, 4)
        self.assertEqual(artifact.heldout_pair_count, 2)
        # a-b is repeated in the held-out day and therefore cannot become a
        # false future positive.  Only the new b-c pair is evaluated.
        self.assertEqual(artifact.novel_heldout_pair_count, 1)
        self.assertEqual(artifact.novel_heldout_query_count, _NOVEL_REFERENCE_COUNT)
        self.assertEqual(artifact.train_candidate_cohort_count, 4)
        self.assertEqual(artifact.common_scored_query_count, _NOVEL_REFERENCE_COUNT)
        self.assertEqual(artifact.common_scored_reference_pair_count, _NOVEL_REFERENCE_COUNT)
        self.assertTrue(
            all(
                metric.reference_pair_count == _NOVEL_REFERENCE_COUNT for metric in artifact.metrics
            )
        )
        self.assertTrue(
            all(
                metric.query_count == _NOVEL_REFERENCE_COUNT
                and metric.reference_pair_count == _NOVEL_REFERENCE_COUNT
                for metric in artifact.common_scored_metrics
            )
        )
        common_neighbor = next(
            metric for metric in artifact.metrics if metric.method == "train_common_neighbor_cosine"
        )
        self.assertEqual(common_neighbor.hit_query_count_at_10, 2)
        self.assertEqual(common_neighbor.recall_at_10, 1.0)

    def test_rejects_reverse_or_self_pair_source_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "qualified.sqlite"
            public = root / "public.sqlite"
            _source_fixture(source, reverse_pair=True)
            _public_fixture(public)

            with self.assertRaisesRegex(ValueError, "ascending distinct"):
                evaluate_listenbrainz_offline_experiment(
                    listenbrainz_path=source,
                    public_database_path=public,
                    listenbrainz_database_sha256="a" * 64,
                    public_database_sha256="b" * 64,
                )


def _source_fixture(path: Path, *, reverse_pair: bool = False) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            """CREATE TABLE artist_co_listen_evidence (
                   window_start INTEGER NOT NULL,
                   left_artist_source_id TEXT NOT NULL,
                   right_artist_source_id TEXT NOT NULL
               )"""
        )
        rows = [
            (1, f"musicbrainz:artist:{_A}", f"musicbrainz:artist:{_B}"),
            (1, f"musicbrainz:artist:{_A}", f"musicbrainz:artist:{_C}"),
            (1, f"musicbrainz:artist:{_A}", f"musicbrainz:artist:{_C}"),
            (2, f"musicbrainz:artist:{_B}", f"musicbrainz:artist:{_D}"),
            (2, f"musicbrainz:artist:{_C}", f"musicbrainz:artist:{_D}"),
            (3, f"musicbrainz:artist:{_A}", f"musicbrainz:artist:{_B}"),
            (4, f"musicbrainz:artist:{_A}", f"musicbrainz:artist:{_B}"),
            (5, f"musicbrainz:artist:{_A}", f"musicbrainz:artist:{_B}"),
            (5, f"musicbrainz:artist:{_B}", f"musicbrainz:artist:{_C}"),
        ]
        if reverse_pair:
            rows[0] = (1, f"musicbrainz:artist:{_B}", f"musicbrainz:artist:{_A}")
        connection.executemany("INSERT INTO artist_co_listen_evidence VALUES (?, ?, ?)", rows)


def _public_fixture(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(
            """CREATE TABLE artists (id INTEGER PRIMARY KEY);
               CREATE TABLE entity_identifiers (
                   entity_id INTEGER NOT NULL,
                   identifier_type_id INTEGER NOT NULL,
                   value TEXT NOT NULL
               );
               CREATE TABLE identifier_types (id INTEGER PRIMARY KEY, type_key TEXT NOT NULL);
               CREATE TABLE displayable_artist_genre_evidence (
                   artist_id INTEGER NOT NULL,
                   genre_id INTEGER NOT NULL,
                   evidence_kind TEXT NOT NULL
               );"""
        )
        connection.execute("INSERT INTO identifier_types VALUES (1, 'musicbrainz_artist_id')")
        connection.executemany("INSERT INTO artists VALUES (?)", [(1,), (2,), (3,), (4,)])
        connection.executemany(
            "INSERT INTO entity_identifiers VALUES (?, 1, ?)",
            [(1, _A), (2, _B), (3, _C), (4, _D)],
        )
        connection.executemany(
            "INSERT INTO displayable_artist_genre_evidence VALUES (?, ?, 'direct_source_claim')",
            [(1, 1), (2, 1), (3, 1), (4, 2)],
        )


if __name__ == "__main__":
    unittest.main()
