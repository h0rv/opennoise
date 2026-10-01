"""Complete static navigation preserves source pairs across page boundaries."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from opennoise.deployment.direct_artist_shards import (
    write_direct_artist_shards,
    write_genre_detail_shards,
)


class DirectArtistShardTests(unittest.TestCase):
    def test_overview_defers_details_and_preserves_source_and_inferred_roles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            genre = {
                "id": "genre",
                "name": "Jazz",
                "x": 0.4,
                "y": 0.2,
                "observed_artist_count": 1,
                "direct_artist_page_count": 1,
                "direct_artist_page_size": 100,
                "direct_artist_ids": ["artist"],
                "peers": [{"seed_id": "neighbor", "role": "inferred_genre_overlap_neighbor"}],
                "proposals": [{"artist_mbid": "proposal", "role": "inferred_artist_candidate"}],
            }
            source_profile = {"name": "Source", "genre_ids": ["genre"]}
            proposal_profile = {"name": "Proposal", "genre_ids": ["neighbor"]}
            payload: dict[str, object] = {
                "genres": [genre],
                "artists": {"artist": source_profile, "proposal": proposal_profile},
            }
            write_genre_detail_shards(payload, directory)
            overview = json.loads(json.dumps(payload))
            self.assertEqual(overview["artists"], {})
            self.assertEqual(overview["genres"][0]["modeled_neighbor_count"], 1)
            self.assertEqual(overview["genres"][0]["peers"], [])
            detail = json.loads((directory / overview["genres"][0]["detail_path"]).read_bytes())
            self.assertEqual((detail["x"], detail["y"]), (0.4, 0.2))
            self.assertEqual(detail["direct_artist_ids"], ["artist"])
            self.assertEqual(detail["artist_profiles"]["proposal"], proposal_profile)
            self.assertEqual(detail["proposals"][0]["role"], "inferred_artist_candidate")

    def test_every_pair_and_artist_is_reachable_once_with_collision_safe_order(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary,
            closing(sqlite3.connect(":memory:")) as connection,
        ):
            connection.executescript(
                "CREATE TABLE artist(artist_mbid TEXT,display_name TEXT,name_status TEXT);"
                "CREATE TABLE seed_artist(seed_id TEXT,artist_mbid TEXT);"
            )
            artists = [(f"artist{index:03}", "Same", "exact") for index in range(205)]
            connection.executemany("INSERT INTO artist VALUES (?,?,?)", artists)
            pairs = [("genre-a", artist) for artist, _, _ in artists] + [("genre-b", "artist000")]
            connection.executemany("INSERT INTO seed_artist VALUES (?,?)", pairs)
            output = Path(temporary)
            manifest = write_direct_artist_shards(connection, output)
            self.assertEqual(manifest["artist_count"], 205)
            self.assertEqual(manifest["direct_pair_count"], 206)
            self.assertEqual(manifest["genre_page_counts"], {"genre-a": 3, "genre-b": 1})
            reconstructed = []
            for file in sorted((output / "genre-artists").rglob("*.json")):
                page = json.loads(file.read_bytes())
                self.assertLessEqual(len(page["artists"]), 100)
                self.assertEqual(page["role"], "direct_source_observation")
                reconstructed.extend((page["genre_id"], row["id"]) for row in page["artists"])
            self.assertEqual(sorted(reconstructed), sorted(pairs))
            profiles = json.loads((output / "artists/art.json").read_bytes())["artists"]
            self.assertEqual(profiles["artist000"]["genre_ids"], ["genre-a", "genre-b"])
            last_page = json.loads((output / "genre-artists/genre-a/2.json").read_bytes())
            self.assertEqual(
                [row["id"] for row in last_page["artists"]], [row[0] for row in artists[200:]]
            )
            search = json.loads((output / "artist-search.json").read_bytes())
            self.assertEqual([row[0] for row in search["artists"]], [row[0] for row in artists])

    def test_display_overlay_changes_names_and_order_only(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary,
            closing(sqlite3.connect(":memory:")) as connection,
        ):
            connection.executescript(
                "CREATE TABLE artist(artist_mbid TEXT,display_name TEXT,name_status TEXT);"
                "CREATE TABLE seed_artist(seed_id TEXT,artist_mbid TEXT);"
                "INSERT INTO artist VALUES ('first',NULL,'unresolved'),('second','B','exact');"
                "INSERT INTO seed_artist VALUES ('genre','first'),('genre','second');"
            )
            output = Path(temporary)
            write_direct_artist_shards(connection, output, display_names={"first": "Z"})
            page = json.loads((output / "genre-artists/genre/0.json").read_bytes())
            self.assertEqual([row["id"] for row in page["artists"]], ["second", "first"])
            self.assertEqual(page["artists"][1]["name_status"], "exact_official_name_overlay")
            self.assertEqual(page["artists"][1]["genre_ids"], ["genre"])
            self.assertIsNone(
                connection.execute(
                    "SELECT display_name FROM artist WHERE artist_mbid='first'"
                ).fetchone()[0]
            )

    def test_untrusted_ids_cannot_become_paths(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary,
            closing(sqlite3.connect(":memory:")) as connection,
        ):
            connection.executescript(
                "CREATE TABLE artist(artist_mbid TEXT,display_name TEXT,name_status TEXT);"
                "CREATE TABLE seed_artist(seed_id TEXT,artist_mbid TEXT);"
                "INSERT INTO artist VALUES ('../escape','Name','exact');"
            )
            with self.assertRaisesRegex(ValueError, "unsafe artist identity"):
                write_direct_artist_shards(connection, Path(temporary))


if __name__ == "__main__":
    unittest.main()
