"""FMA catalog namespace, source annotation, sharding, and preservation contracts."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import zstandard

from opennoise.deployment.fma_static import (
    MAX_SHARD_BYTES,
    _genre_connections,
    _playback_binding,
    build_fma_static,
    refresh_fma_static_display,
    validated_metadata_url,
)


def tables() -> dict[str, list[dict[str, object]]]:
    """Small native rows with unknown artist IDs and deliberately absent track labels."""
    return {
        "artists": [{"artist_id": 1, "name": "Same name", "missing_fields": {}}],
        "genres": [
            {
                "genre_id": 21,
                "title": "Hip-Hop",
                "parent_id": None,
                "missing_fields": {"parent_id": "source_empty"},
            },
            {
                "genre_id": 38,
                "title": "Unannotated parent",
                "parent_id": None,
                "missing_fields": {},
            },
        ],
        "tracks": [
            {
                "track_id": 2,
                "title": "Track",
                "artist_id": 1,
                "genre_ids": [21],
                "audio_license_title": "CC BY-NC-SA",
                "audio_license_url": "https://creativecommons.org/licenses/by-nc-sa/3.0/",
                "source_metadata_url": "https://freemusicarchive.org/music/a/track",
                "album_id": 77,
                "missing_fields": {},
            },
            {
                "track_id": 3,
                "title": "No annotation",
                "artist_id": 999,
                "genre_ids": None,
                "audio_license_title": None,
                "audio_license_url": None,
                "source_metadata_url": "javascript:alert(1)",
                "album_id": None,
                "missing_fields": {"genre_ids": "source_empty"},
            },
        ],
    }


class FMAStaticTests(unittest.TestCase):
    """The optional FMA pack stays separate from CC0 artist catalogs and inference."""

    def test_playable_index_uses_only_attached_native_track_annotations(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            audio = root / "audio"
            audio.mkdir()
            (audio / "manifest.json").write_text("{}")
            attached = {
                "tracks": {"3": {"track_id": 3, "artist_id": 999}},
                "audio_bytes": 10,
            }
            with patch(
                "opennoise.deployment.fma_static.validate_playback_export", return_value=attached
            ):
                binding = _playback_binding(audio, root / "explorer", tables()["tracks"])
                self.assertEqual(
                    binding["tracks"], [{"track_id": 3, "artist_id": 999, "genre_ids": []}]
                )
                attached["tracks"]["3"]["artist_id"] = 1
                with self.assertRaisesRegex(ValueError, "identity differs"):
                    _playback_binding(audio, root / "explorer", tables()["tracks"])

    def test_connections_use_shared_track_labels_not_parent_or_artist_inference(self) -> None:
        tracks = [
            {"genre_ids": [1, 2, 2]},
            {"genre_ids": [1, 3]},
            {"genre_ids": [1]},
            {"genre_ids": None},
        ]
        connections = _genre_connections(tracks, {1: [10, 11, 12], 2: [10], 3: [11]})
        self.assertEqual([row["genre_id"] for row in connections[1]], [2, 3])
        self.assertEqual(connections[1][0]["shared_tracks"], 1)
        self.assertEqual(connections[1][0]["overlap"], 1 / 3)
        self.assertEqual(connections[2][0]["genre_id"], 1)
        self.assertNotIn(38, connections)
        self.assertEqual(
            _genre_connections([{"genre_ids": [1]}, {"genre_ids": None}], {1: [10]}), {}
        )

    def test_only_source_declared_native_metadata_urls_survive(self) -> None:
        """External or malformed destinations cannot masquerade as playback links."""
        native = "https://freemusicarchive.org/music/a/track"
        self.assertEqual(validated_metadata_url(native), native)
        for value in [
            "javascript:alert(1)",
            "https://freemusicarchive.org.evil.example/a",
            "https://person:password@freemusicarchive.org/a",
            "https://freemusicarchive.org:81/a",
            "https://example.com/a",
            None,
        ]:
            with self.subTest(value=value):
                self.assertIsNone(validated_metadata_url(value))

    def test_catalog_preserves_exact_track_labels_missingness_and_prior_snapshot(self) -> None:
        """Parents inherit no labels, unknown artists stay accessible, refresh is atomic."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            projected = root / "projected"
            projected.mkdir()
            corpus = {"metadata_license": "CC-BY-4.0", "source_receipt_sha256": "a" * 64}
            (projected / "corpus-receipt.json").write_text(json.dumps(corpus))
            with patch(
                "opennoise.deployment.fma_static.verified_tables", return_value=(corpus, tables())
            ):
                output = root / "static"
                receipt = build_fma_static(
                    source=root / "source", projected=projected, output=output
                )
                with self.assertRaises(FileExistsError):
                    build_fma_static(source=root / "source", projected=projected, output=output)
            catalog = json.loads((output / "catalog.json").read_bytes())
            self.assertEqual(catalog["counts"]["raw_tracks"], 2)
            self.assertEqual(catalog["counts"]["missing_artist_records"], 1)
            self.assertEqual(catalog["genres"][1]["track_count"], 0)
            artist = json.loads((output / "artists/1.json").read_bytes())["artists"]["1"]
            self.assertEqual(artist["track_ids"], [2])
            self.assertEqual(artist["track_genre_counts"], [{"genre_id": 21, "track_count": 1}])
            self.assertEqual(catalog["genres"][1]["connections"], [])
            self.assertNotIn("genre_ids", artist)
            self.assertNotIn("musicbrainz_id", artist)
            self.assertEqual(
                json.loads((output / "cohorts/unannotated/0.json").read_bytes())["track_ids"], [3]
            )
            tracks = json.loads((output / "tracks/0.json").read_bytes())["tracks"]
            self.assertIsNone(tracks[1][5])
            self.assertEqual(catalog["unvalidated_source_urls"], 1)
            before = (output / "fma-catalog.js").read_bytes()
            refreshed = root / "refreshed"
            result = refresh_fma_static_display(source=output, output=refreshed)
            self.assertEqual((output / "fma-catalog.js").read_bytes(), before)
            self.assertEqual(
                (output / "tracks/0.json").stat().st_ino,
                (refreshed / "tracks/0.json").stat().st_ino,
            )
            self.assertNotEqual(
                (output / "fma-catalog.js").stat().st_ino,
                (refreshed / "fma-catalog.js").stat().st_ino,
            )
            self.assertEqual(result["counts"], receipt["counts"])
            manifest = json.loads(
                zstandard.ZstdDecompressor().decompress(
                    (output / "files-manifest.json.zst").read_bytes()
                )
            )
            self.assertTrue(
                all(
                    binding["bytes"] <= MAX_SHARD_BYTES
                    for name, binding in manifest.items()
                    if name != "artist-index.json"
                )
            )
