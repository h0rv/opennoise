import inspect
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.prepare_phase3_genre_enrichment import GenreTarget, render_genre_query
from scripts.prepare_phase3_media_details import (
    MediaIdentity,
    load_discovery,
    render_detail_query,
)
from scripts.prepare_phase3_wikidata import (
    prepare,
    render_artist_query,
    render_media_discovery_query,
    select_artists,
)


class Phase3WikidataTests(unittest.TestCase):
    def test_selection_and_shards_are_exact_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "catalog.sqlite"
            with sqlite3.connect(database) as connection:
                connection.executescript(
                    """CREATE TABLE derived_outputs (
                         output_kind TEXT, output_ref TEXT, content_sha256 TEXT
                       );
                       CREATE TABLE data_sources (id INTEGER, source_key TEXT);
                       CREATE TABLE source_snapshots (id INTEGER, source_id INTEGER);
                       CREATE TABLE source_artifacts (id INTEGER, snapshot_id INTEGER, sha256 TEXT);
                       CREATE TABLE artist_co_listen_runs (
                         run_ref TEXT, ingest_attempt_id INTEGER, artifact_id INTEGER
                       );
                       CREATE TABLE artist_co_listen_evidence (
                         ingest_attempt_id INTEGER, left_artist_source_id TEXT,
                         right_artist_source_id TEXT, window_start INTEGER,
                         distinct_user_count INTEGER
                       );
                       INSERT INTO data_sources VALUES
                         (1, 'listenbrainz_joint_20260824_20260830');
                       INSERT INTO source_snapshots VALUES (1, 1);
                       INSERT INTO artist_co_listen_runs VALUES ('fixture-run', 1, 1);
                    """
                )
                connection.execute(
                    "INSERT INTO source_artifacts VALUES (1, 1, ?)",
                    ("a" * 64,),
                )
                connection.execute(
                    """INSERT INTO derived_outputs VALUES
                       ('multi_source_aggregate',
                        'listenbrainz_joint_20260824_20260830', ?)""",
                    ("a" * 64,),
                )
                connection.executemany(
                    """INSERT INTO artist_co_listen_evidence
                       VALUES (1, ?, ?, ?, ?)""",
                    (
                        (
                            "musicbrainz:artist:11111111-1111-4111-8111-111111111111",
                            "musicbrainz:artist:22222222-2222-4222-8222-222222222222",
                            1,
                            5,
                        ),
                        (
                            "musicbrainz:artist:11111111-1111-4111-8111-111111111111",
                            "musicbrainz:artist:33333333-3333-4333-8333-333333333333",
                            2,
                            7,
                        ),
                    ),
                )

            selection = select_artists(database, 2)
            self.assertEqual(selection.aggregate_sha256, "a" * 64)
            self.assertEqual(selection.run_ref, "fixture-run")
            self.assertEqual(selection.artists[0].weighted_degree, 12)
            first = prepare(database, root / "first", 2, 1, 1)
            second = prepare(database, root / "second", 2, 1, 1)
            self.assertEqual(first, second)
            self.assertEqual(first["artist_shards"], 2)
            self.assertEqual(first["media_shards"], 2)
            self.assertEqual(first["query_files"], 6)

    def test_query_contains_only_exact_identifier_join_and_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "missing.sqlite"
            with self.assertRaises(sqlite3.OperationalError):
                select_artists(database, 1)

        query = render_artist_query(())
        self.assertIn("wdt:P434 ?musicbrainzId", query)
        self.assertIn("FILTER(?otherEntity != ?entity)", query)
        self.assertIn("FILTER(?otherMusicbrainzId != ?musicbrainzId)", query)
        self.assertIn("LIMIT 20000", query)
        self.assertIn("wikibase:DeprecatedRank", query)
        self.assertIn("STRSTARTS(STR(?genre), STR(wd:Q))", query)
        self.assertNotIn("CONTAINS", query)
        self.assertNotIn("LCASE", query)

        media = render_media_discovery_query((), "release_group")
        self.assertIn("wdt:P436 ?musicbrainzId", media)
        self.assertIn("LIMIT 100", media)
        self.assertIn("REGEX(STR(?musicbrainzId)", media)
        self.assertIn("wikibase:DeprecatedRank", media)
        self.assertIn("STRSTARTS(STR(?genre), STR(wd:Q))", media)
        self.assertNotIn("CONTAINS", media)

        details = render_detail_query(
            (
                MediaIdentity(
                    entity_kind="recording",
                    qid="Q100",
                    musicbrainz_id="11111111-1111-4111-8111-111111111111",
                ),
            ),
            "recording",
        )
        self.assertIn("VALUES ?entity { wd:Q100 }", details)
        self.assertIn("wdt:P4404 ?musicbrainzId", details)
        self.assertIn("wikibase:DeprecatedRank", details)
        self.assertIn("STRSTARTS(STR(?genre), STR(wd:Q))", details)
        self.assertIn("LIMIT 20000", details)
        self.assertNotIn("CONTAINS", details)

    def test_discovery_identity_query_deduplicates_provenance_rows(self) -> None:
        source = inspect.getsource(load_discovery)

        self.assertIn("SELECT DISTINCT entity.entity_kind", source)

    def test_genre_query_uses_exact_qids_and_direct_ranked_p279(self) -> None:
        query = render_genre_query((GenreTarget(qid="Q100"),))

        self.assertIn("VALUES ?entity { wd:Q100 }", query)
        self.assertIn("ps:P279 ?parent", query)
        self.assertIn("wikibase:DeprecatedRank", query)
        self.assertIn("STRSTARTS(STR(?parent), STR(wd:Q))", query)
        self.assertNotIn("CONTAINS", query)
