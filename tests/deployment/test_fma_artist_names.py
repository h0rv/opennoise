"""Track-supplied display names never repair or merge source artist identities."""

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from opennoise.deployment.fma_artist_names import TRACK_NAME_SOURCE, track_artist_names
from opennoise.deployment.fma_static import build_fma_static
from tests.deployment.test_fma_static import tables


def row(artist: int | None, name: str | None) -> dict[str, Any]:
    """Create only the two allowed fields used by the fallback."""
    return {"artist_id": artist, "artist_name": name}


class FMAArtistNameTests(unittest.TestCase):
    def test_unanimous_exact_ids_not_name_merges(self) -> None:
        tracks = [row(1, "Native"), row(2, "Same name"), row(2, "Same name"), row(3, "Same name")]
        self.assertEqual(track_artist_names(tracks, {1}), {2: "Same name", 3: "Same name"})
        self.assertEqual(
            track_artist_names(list(reversed(tracks)), {1}), {2: "Same name", 3: "Same name"}
        )

    def test_missing_conflicting_null_and_whitespace_abstain(self) -> None:
        tracks = [
            row(1, "A"),
            row(1, "a"),
            row(2, "B"),
            row(2, None),
            row(3, ""),
            row(4, " "),
            row(None, "Null alias"),
            row(0, "Zero"),
            row(5, "Name"),
            row(5, "Name "),
            {"artist_id": 6},
        ]
        self.assertEqual(track_artist_names(tracks, set()), {})

    def test_export_preserves_status_counts_source_and_privacy_allowlist(self) -> None:
        data = tables()
        data["tracks"][1].update(
            {
                "artist_name": "Same name",
                "artist_contact": "PRIVATE",
                "artist_bio": "PRIVATE",
                "artist_url": "PRIVATE",
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            projected = root / "projected"
            projected.mkdir()
            corpus = {"metadata_license": "CC-BY-4.0", "source_receipt_sha256": "a" * 64}
            (projected / "corpus-receipt.json").write_text(json.dumps(corpus))
            with patch(
                "opennoise.deployment.fma_static.verified_tables", return_value=(corpus, data)
            ):
                build_fma_static(source=root / "source", projected=projected, output=root / "out")
            output = root / "out"
            index = json.loads((output / "artist-index.json").read_bytes())["artists"]
            self.assertEqual(
                index,
                [
                    [1, "Same name", 1, "source_artist_record"],
                    [999, "Same name", 1, "missing_source_artist_record", TRACK_NAME_SOURCE],
                ],
            )
            profile = json.loads((output / "artists/103.json").read_bytes())["artists"]["999"]
            self.assertEqual(profile["name"], "Same name")
            self.assertEqual(profile["name_source"], TRACK_NAME_SOURCE)
            self.assertEqual(profile["status"], "missing_source_artist_record")
            self.assertEqual(profile["track_ids"], [3])
            catalog = json.loads((output / "catalog.json").read_bytes())
            self.assertEqual(catalog["counts"]["missing_artist_records"], 1)
            self.assertEqual(catalog["counts"]["tracks_with_missing_artist_records"], 1)
            self.assertEqual(catalog["counts"]["source_artists"], 1)
            for path in output.rglob("*.json"):
                self.assertNotIn("PRIVATE", path.read_text())
