"""Parity reports verify browser routes rather than counting available files."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from opennoise.analysis.everynoise_parity import (
    compare_genre_names,
    verify_complete_artist_navigation,
    verify_preview_files,
)
from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.deployment.direct_artist_shards import write_direct_artist_shards


def seal_fixture(directory: Path) -> None:
    """Bind all test responses after an intentional artifact mutation."""
    receipt = {
        "scope": "local_research_only",
        "public_export_authorized": False,
        "files": {
            file.relative_to(directory).as_posix(): {
                "sha256": sha256_file(file)[0],
                "bytes": file.stat().st_size,
            }
            for file in directory.rglob("*")
            if file.is_file() and file.name != "preview-receipt.json"
        },
    }
    receipt["output_sha256"] = sha256_json(receipt)
    (directory / "preview-receipt.json").write_bytes(canonical_json(receipt))


def make_fixture(directory: Path) -> None:
    """Build a complete one-artist navigation surface with real shard writer."""
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.executescript(
            "CREATE TABLE artist(artist_mbid TEXT,display_name TEXT,name_status TEXT);"
            "CREATE TABLE seed_artist(seed_id TEXT,artist_mbid TEXT);"
            "INSERT INTO artist VALUES ('abc123','Name','exact');"
            "INSERT INTO seed_artist VALUES ('genre','abc123');"
        )
        catalog = write_direct_artist_shards(connection, directory)
    payload = {
        "artist_catalog": catalog,
        "genres": [{"id": "genre", "observed_artist_count": 1, "direct_artist_page_count": 1}],
    }
    (directory / "data.json").write_bytes(canonical_json(payload))
    for name in ("index.html", "direct-custody-preview.js", "direct-custody-preview.css"):
        (directory / name).write_text("fixture")
    seal_fixture(directory)


class EveryNoiseParityTests(unittest.TestCase):
    def test_names_only_match_normalized_whole_strings(self) -> None:
        result = compare_genre_names(["Café", "post-punk"], [" CAFE\u0301 ", "post punk"])
        self.assertEqual(result["matched_reference_names"], 1)
        self.assertEqual(result["reference_name_coverage"], 0.5)
        self.assertEqual(result["missing_reference_names"], ["post-punk"])

    def test_complete_routes_search_and_profiles_are_replayed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            make_fixture(directory)
            self.assertEqual(verify_complete_artist_navigation(directory), (1, 1))

    def test_wrong_page_route_cannot_claim_reachable_membership(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            make_fixture(directory)
            (directory / "genre-artists/genre/0.json").rename(
                directory / "genre-artists/genre/99.json"
            )
            seal_fixture(directory)
            with self.assertRaises(FileNotFoundError):
                verify_complete_artist_navigation(directory)

    def test_search_and_profile_display_must_agree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            make_fixture(directory)
            (directory / "artist-search.json").write_bytes(
                canonical_json({"artists": [["abc123", "Wrong", "exact"]]})
            )
            seal_fixture(directory)
            with self.assertRaisesRegex(ValueError, "search display projection differs"):
                verify_complete_artist_navigation(directory)

    def test_missing_profile_cannot_claim_full_source_navigation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            make_fixture(directory)
            (directory / "artists/abc.json").unlink()
            seal_fixture(directory)
            with self.assertRaisesRegex(ValueError, "profile shards"):
                verify_complete_artist_navigation(directory)

    def test_missing_lazy_detail_cannot_claim_reachable_source_navigation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            make_fixture(directory)
            file = directory / "data.json"
            payload = json.loads(file.read_bytes())
            payload["genre_details_revision"] = "direct-source-genre-details-v1"
            payload["genres"][0]["detail_path"] = "genre-details/genre.json"
            file.write_bytes(canonical_json(payload))
            seal_fixture(directory)
            with self.assertRaises(FileNotFoundError):
                verify_complete_artist_navigation(directory)

    def test_omitted_entry_point_is_rejected_even_with_valid_receipt_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            make_fixture(directory)
            file = directory / "preview-receipt.json"
            receipt = json.loads(file.read_bytes())
            del receipt["files"]["data.json"]
            del receipt["output_sha256"]
            receipt["output_sha256"] = sha256_json(receipt)
            file.write_bytes(canonical_json(receipt))
            with self.assertRaisesRegex(ValueError, "mandatory entry points"):
                verify_preview_files(directory)


if __name__ == "__main__":
    unittest.main()
