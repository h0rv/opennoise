import io
import json
import sqlite3
import tarfile
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from musix.ingest.spotify.musicbrainz_spotify_bridge import (
    MusicBrainzSpotifyBridgeError,
    SpotifyBridgeSettings,
    bridge_artifact_sha256,
    build_musicbrainz_spotify_bridge,
    publish_musicbrainz_spotify_bridge,
    verify_musicbrainz_spotify_bridge,
)
from musix.storage import LocalObjectStore

MBID_ONE = "00000000-0000-0000-0000-000000000001"
MBID_TWO = "00000000-0000-0000-0000-000000000002"
SPOTIFY_A = "AAAAAAAAAAAAAAAAAAAAAA"
SPOTIFY_B = "BBBBBBBBBBBBBBBBBBBBBB"
SPOTIFY_UNUSED = "CCCCCCCCCCCCCCCCCCCCCC"


def _artist(mbid: str, relations: list[object]) -> bytes:
    return (json.dumps({"id": mbid, "relations": relations}) + "\n").encode()


def _relation(resource: object) -> dict[str, object]:
    return {"target-type": "url", "url": {"resource": resource}}


def _make_fixture(root: Path) -> tuple[Path, Path]:
    database = root / "historical.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE historical_genre_artist_observations (source_artist_id TEXT)"
        )
        connection.executemany(
            "INSERT INTO historical_genre_artist_observations VALUES (?)",
            [(SPOTIFY_A,), (SPOTIFY_B,), (SPOTIFY_A,), (SPOTIFY_UNUSED,)],
        )

    archive = root / "musicbrainz.tar.xz"
    with tarfile.open(archive, mode="w:xz") as output:
        schema = b"1\n"
        schema_info = tarfile.TarInfo("JSON_DUMPS_SCHEMA_NUMBER")
        schema_info.size = len(schema)
        output.addfile(schema_info, io.BytesIO(schema))
        artists = b"".join(
            (
                _artist(
                    MBID_ONE,
                    [
                        _relation(f"https://open.spotify.com/artist/{SPOTIFY_A}?source=mb"),
                        _relation(f"https://open.spotify.com/artist/{SPOTIFY_A}/"),
                        _relation(f"https://open.spotify.com/artist/{SPOTIFY_B}/"),
                        _relation("https://example.com/artist/other"),
                        _relation("https://open.spotify.com/artist/short"),
                    ],
                ),
                _artist(MBID_TWO, [_relation(f"https://open.spotify.com/artist/{SPOTIFY_A}")]),
                _artist(MBID_TWO, [{"target-type": "url", "url": {"resource": 42}}]),
                _artist(MBID_ONE, [_relation(f"https://open.spotify.com/artist/{SPOTIFY_B}")]),
            )
        )
        artist_info = tarfile.TarInfo("mbdump/artist")
        artist_info.size = len(artists)
        output.addfile(artist_info, io.BytesIO(artists))
    return archive, database


class MusicBrainzSpotifyBridgeTests(unittest.TestCase):
    def test_nested_relations_aliases_and_reverse_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive, database = _make_fixture(Path(directory))
            artifact = build_musicbrainz_spotify_bridge(archive, database)

        self.assertEqual(artifact.counters.historical_artist_count, 3)
        self.assertEqual(artifact.counters.distinct_claim_count, 3)
        self.assertEqual(artifact.counters.duplicate_claim_count, 1)
        self.assertEqual(artifact.counters.malformed_spotify_url_count, 1)
        self.assertEqual(artifact.counters.ignored_non_spotify_relation_count, 2)
        self.assertEqual(artifact.counters.spotify_conflict_count, 1)
        self.assertEqual(artifact.counters.musicbrainz_alias_count, 1)
        self.assertEqual(artifact.counters.conflict_claim_count, 2)
        self.assertEqual(artifact.counters.accepted_bridge_count, 1)
        rows = {(row.musicbrainz_artist_id, row.spotify_artist_id): row for row in artifact.rows}
        self.assertEqual(rows[(MBID_ONE, SPOTIFY_A)].disposition, "conflict")
        self.assertEqual(rows[(MBID_TWO, SPOTIFY_A)].disposition, "conflict")
        self.assertEqual(rows[(MBID_ONE, SPOTIFY_B)].disposition, "accepted")
        self.assertEqual(
            rows[(MBID_ONE, SPOTIFY_A)].relation_url,
            f"https://open.spotify.com/artist/{SPOTIFY_A}",
        )
        self.assertEqual(
            rows[(MBID_ONE, SPOTIFY_A)].source_url,
            f"https://open.spotify.com/artist/{SPOTIFY_A}?source=mb",
        )
        verify_musicbrainz_spotify_bridge(artifact)

    def test_tamper_and_accepted_alias_of_conflicted_mbid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive, database = _make_fixture(Path(directory))
            artifact = build_musicbrainz_spotify_bridge(archive, database)

        # A conflicted MBID can still have a separate unique alias. The verifier
        # must inspect the conflicted Spotify identifier, not only the MBID.
        accepted_alias = artifact.rows[2].model_copy(
            update={"musicbrainz_artist_id": MBID_TWO, "spotify_artist_id": SPOTIFY_B}
        )
        altered = artifact.model_copy(update={"rows": (*artifact.rows[:2], accepted_alias)})
        # Recompute the sealed hash through the public model contract.
        altered = altered.model_copy(update={"output_sha256": bridge_artifact_sha256(altered)})
        verify_musicbrainz_spotify_bridge(altered)
        with self.assertRaises(ValueError):
            verify_musicbrainz_spotify_bridge(
                artifact.model_copy(update={"output_sha256": "0" * 64})
            )

    def test_bounds_and_historical_schema_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive, database = _make_fixture(Path(directory))
            with self.assertRaises(MusicBrainzSpotifyBridgeError):
                build_musicbrainz_spotify_bridge(
                    archive, database, SpotifyBridgeSettings(max_records=1)
                )
            with self.assertRaises(MusicBrainzSpotifyBridgeError):
                build_musicbrainz_spotify_bridge(
                    archive, database, SpotifyBridgeSettings(max_bridge_rows=2)
                )
            bounded = build_musicbrainz_spotify_bridge(
                archive, database, SpotifyBridgeSettings(max_record_bytes=16)
            )
            self.assertEqual(bounded.counters.record_over_limit_count, 4)
            self.assertEqual(bounded.rows, ())
            bad_database = Path(directory) / "bad.sqlite"
            sqlite3.connect(bad_database).close()
            with self.assertRaises(MusicBrainzSpotifyBridgeError):
                build_musicbrainz_spotify_bridge(archive, bad_database)

    def test_settings_reject_zero_bounds(self) -> None:
        with self.assertRaises(ValidationError):
            SpotifyBridgeSettings(max_records=0)

    def test_publication_receipt_binds_atomic_artifact_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, database = _make_fixture(root)
            artifact = build_musicbrainz_spotify_bridge(archive, database)
            receipt = publish_musicbrainz_spotify_bridge(
                artifact,
                output_path=root / "bridge.json",
                store=LocalObjectStore(root / "objects"),
            )

        self.assertEqual(receipt.logical_output_sha256, artifact.output_sha256)
        self.assertFalse(receipt.artifact.reused)


if __name__ == "__main__":
    unittest.main()
