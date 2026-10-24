"""Regression checks for source concepts being mistaken for artists or genres."""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, override

from opennoise.pipeline import wiki_artist_atlas as atlas


class WikiArtistSourceTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        """Use a small named band and genre with the actual public-source field roster."""
        self.source: dict[str, Any] = {
            "revision": "wiki-artist-atlas-v1",
            "source_version": "2022.12.01",
            "artists": [
                {
                    "uri": "http://dbpedia.org/resource/Example_band",
                    "name": "Example band",
                    "genres": ["http://dbpedia.org/resource/Dub"],
                    "features": {},
                    "source_types": ["Band", "Organisation", "Agent"],
                    "identity_evidence": ["source_type"],
                    "position": [0.5, 0.5],
                }
            ],
            "genres": [
                {
                    "uri": "http://dbpedia.org/resource/Dub",
                    "name": "Dub",
                    "music_genre_type_observed": True,
                    "source_types": ["Genre", "MusicGenre"],
                    "position": [0.5, 0.5],
                    "shared_member_neighbors": 0,
                    "genre_evidence": "dbpedia_genre_type",
                    "vocabulary_term": "dub",
                }
            ],
            "relations": [],
            "feature_labels": {},
            "source": {},
        }

    def read_source(self, data: dict[str, Any]) -> dict[str, Any]:
        """Exercise the same source reader that runs before any matrix or public output."""
        raw = json.dumps(data).encode()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / atlas.SNAPSHOT
            path.parent.mkdir(parents=True)
            path.write_bytes(gzip.compress(raw))
            vocabulary = b"dub\nclassical\n"
            path.with_name("genres.txt").write_bytes(vocabulary)
            return atlas.read_snapshot(
                root,
                {
                    "expanded_bytes": len(raw),
                    "genre_vocabulary_sha256": hashlib.sha256(vocabulary).hexdigest(),
                },
            )

    def test_band_organisation_is_a_supported_artist(self) -> None:
        """Bands remain valid even though the ontology also calls them organisations."""
        self.assertEqual(self.read_source(self.source)["artists"][0]["name"], "Example band")

    def test_relationship_role_cannot_turn_instrument_into_artist(self) -> None:
        """The Guitar/Piano contamination fails before it can affect graph context."""
        for kind in ("Instrument", "Place", "Language", "RecordLabel"):
            with self.subTest(kind=kind):
                data = copy.deepcopy(self.source)
                data["artists"][0]["source_types"] = [kind]
                data["artists"][0]["identity_evidence"] = ["source_music_relationship"]
                with self.assertRaisesRegex(ValueError, "positive artist evidence"):
                    self.read_source(data)

    def test_person_requires_positive_musical_evidence(self) -> None:
        """A human identity alone does not establish a musical artist record."""
        data = copy.deepcopy(self.source)
        data["artists"][0]["source_types"] = ["Person", "Agent"]
        data["artists"][0]["identity_evidence"] = []
        with self.assertRaisesRegex(ValueError, "positive artist evidence"):
            self.read_source(data)
        data["artists"][0]["identity_evidence"] = ["source_person_and_instrument"]
        self.assertEqual(len(self.read_source(data)["artists"]), 1)
        data["artists"][0]["identity_evidence"] = ["source_person_and_typed_music_genre"]
        with self.assertRaisesRegex(ValueError, "positive artist evidence"):
            self.read_source(data)

    def test_incompatible_genre_and_dangling_context_fail_closed(self) -> None:
        """An instrument cannot be a genre or an undeclared graph context node."""
        data = copy.deepcopy(self.source)
        data["genres"][0]["source_types"] = ["Instrument"]
        data["genres"][0]["music_genre_type_observed"] = False
        with self.assertRaisesRegex(ValueError, "Incompatible source genre"):
            self.read_source(data)
        data = copy.deepcopy(self.source)
        data["relations"] = [
            [
                data["artists"][0]["uri"],
                atlas.DBO + "bandMember",
                "http://dbpedia.org/resource/Guitar",
            ]
        ]
        with self.assertRaisesRegex(ValueError, "artist relationship"):
            self.read_source(data)

    def test_unknown_genre_type_is_not_a_negative_claim(self) -> None:
        """A named source genre statement can exist without a MusicGenre type."""
        data = copy.deepcopy(self.source)
        data["genres"][0]["source_types"] = []
        data["genres"][0]["music_genre_type_observed"] = False
        data["genres"][0]["genre_evidence"] = "musicbrainz_core_vocabulary"
        self.assertEqual(self.read_source(data)["genres"][0]["name"], "Dub")
        data["genres"][0]["name"] = "Piano"
        with self.assertRaisesRegex(ValueError, "Unvalidated source genre"):
            self.read_source(data)


if __name__ == "__main__":
    unittest.main()
