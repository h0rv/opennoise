"""Reverse direct track annotations, preserving native identities and missingness."""

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from typing import Any
from unittest.mock import patch

from opennoise.deployment.fma_genre_artists import export_genre_artists
from opennoise.deployment.fma_static import _write, build_fma_static
from tests.deployment.test_fma_static import tables


class FMAGenreArtistTests(unittest.TestCase):
    def test_complete_count_order_null_identity_and_empty_genres(self) -> None:
        counts = {
            7: Counter({1: 2}),
            3: Counter({1: 2}),
            None: Counter({1: 2}),
            9: Counter({1: 1, 2: 1}),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = export_genre_artists(root, counts, {1, 2, 3}, {}, _write)
            self.assertEqual(manifest["pair_count"], 5)
            self.assertEqual(manifest["genres"], [[1, 4, 7], [2, 1, 1], [3, 0, 0]])
            page = json.loads((root / "genre-artists/1/0.json").read_bytes())
            self.assertEqual(
                page,
                {
                    "genre_id": 1,
                    "page": 0,
                    "total": 4,
                    "artists": [[None, 2], [3, 2], [7, 2], [9, 1]],
                },
            )
            self.assertEqual(
                json.loads((root / "genre-artists/3/0.json").read_bytes())["artists"], []
            )
            self.assertFalse((root / "cohorts").exists())

    def test_pages_cover_every_native_id_once(self) -> None:
        counts: dict[int | None, Counter[int]] = {
            index: Counter({1: 1}) for index in range(201, 0, -1)
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files: dict[str, Any] = {}
            export_genre_artists(root, counts, {1}, files, _write)
            self.assertEqual(len(files), 3)
            members = [
                row
                for page in range(3)
                for row in json.loads((root / f"genre-artists/1/{page}.json").read_bytes())[
                    "artists"
                ]
            ]
            self.assertEqual(members, [[index, 1] for index in range(1, 202)])

    def test_builder_deduplicates_tags_and_preserves_missing_artist_status(self) -> None:
        data = tables()
        data["tracks"][0]["genre_ids"] = [21, 21]
        data["tracks"][1].update({"genre_ids": [21], "artist_name": "Same name"})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            projected = root / "projected"
            projected.mkdir()
            corpus = {"metadata_license": "CC-BY-4.0", "source_receipt_sha256": "a" * 64}
            (projected / "corpus-receipt.json").write_text(json.dumps(corpus))
            with patch(
                "opennoise.deployment.fma_static.verified_tables", return_value=(corpus, data)
            ):
                build_fma_static(source=root / "source", projected=projected, output=root / "out")
            page = json.loads((root / "out/genre-artists/21/0.json").read_bytes())
            self.assertEqual(page["artists"], [[1, 1], [999, 1]])
            index = json.loads((root / "out/artist-index.json").read_bytes())["artists"]
            self.assertEqual(index[1][3], "missing_source_artist_record")
            self.assertEqual(index[1][4], "unanimous_track_artist_name")

    def test_invalid_counts_or_ids_reject(self) -> None:
        invalid: list[dict[int | None, Counter[int]]] = [
            {1: Counter({1: 0})},
            {1: Counter({2: 1})},
            {-1: Counter({1: 1})},
        ]
        for counts in invalid:
            with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
                export_genre_artists(Path(directory), counts, {1}, {}, _write)
