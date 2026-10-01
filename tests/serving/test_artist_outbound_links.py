"""Test source-bound external destinations and offline metadata replay."""

import unittest
from pathlib import Path

from opennoise.serving.metadata.artist_links import (
    outbound_provider,
    project_artist_links,
    verify_artist_link_projection,
)

ARTIST = "f22942a1-6f70-4f48-866e-238cb2308fbd"


class ArtistOutboundLinksTests(unittest.TestCase):
    def test_allowlisted_hosts_are_exact(self) -> None:
        self.assertEqual(
            outbound_provider("https://aphextwin.bandcamp.com/", "bandcamp"), "Bandcamp"
        )
        for url in (
            "https://spotify.com.attacker.org/a",
            "https://user@spotify.com/a",
            "http://open.spotify.com/a",
            "https://localhost/a",
            "https://127.0.0.1/a",
        ):
            self.assertIsNone(outbound_provider(url, "streaming"))
        self.assertIsNone(outbound_provider("https://127.0.0.1/a", "official homepage"))

    def test_no_name_guessing_and_exact_response_identity(self) -> None:
        payload = {"id": ARTIST, "name": "Aphex Twin", "relations": []}
        self.assertEqual(project_artist_links(payload, ARTIST, "a" * 64)["links"], [])
        with self.assertRaises(ValueError):
            project_artist_links(payload, "another", "a" * 64)

    def test_real_cc0_capture_replays_source_destinations(self) -> None:
        directory = Path(__file__).resolve().parents[2] / "data/examples/artist-links"
        artifact = verify_artist_link_projection(
            directory / "artist-links.json", directory / "receipt.json"
        )
        aphex = next(row for row in artifact["artists"] if row["artist_mbid"] == ARTIST)
        self.assertTrue(
            any(link["url"] == "https://aphextwin.bandcamp.com/" for link in aphex["links"])
        )
        self.assertEqual(len(artifact["artists"]), 10)
