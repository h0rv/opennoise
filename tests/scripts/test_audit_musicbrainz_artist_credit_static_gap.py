from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from scripts.audit_musicbrainz_artist_credit_static_gap import (
    StaticGapAuditError,
    _bridgeable_genre_ids,
    _load_static,
    _musicbrainz_artist_id,
    _placed_name_counts,
)

_DATABASE_SHA256 = "a" * 64
_MBID = "11111111-1111-1111-1111-111111111111"
_ATLAS_HASH = "469f207021157031e88853be1b9f2d1eb63af8f0fcfc9c504e19e7584fd0cc38"


class MusicBrainzArtistCreditStaticGapTests(unittest.TestCase):
    def test_rejects_wrong_static_database_hash(self) -> None:
        payload = _static_payload()
        payload["source"] = _static_source(database_sha256="b" * 64)

        self._assert_static_rejected(payload, "bound")

    def test_rejects_wrong_static_revision(self) -> None:
        payload = _static_payload()
        payload["revision"] = "other"

        self._assert_static_rejected(payload, "typed contract")

    def test_rejects_unavailable_static_payload(self) -> None:
        payload = _static_payload()
        payload["availability"] = "unavailable"

        self._assert_static_rejected(payload, "not ready")

    def test_rejects_non_direct_static_observation_kind(self) -> None:
        payload = _static_payload()
        payload["source"] = _static_source(observation_kind="derived")

        self._assert_static_rejected(payload, "typed contract")

    def test_rejects_malformed_static_artist_mbid(self) -> None:
        with self.assertRaisesRegex(StaticGapAuditError, "canonical MBID"):
            _musicbrainz_artist_id("https://musicbrainz.org/artist/not-an-mbid")

    def test_rejects_atlas_with_wrong_revision(self) -> None:
        atlas = _atlas_payload()
        atlas["revision"] = "other"

        self._assert_atlas_rejected(atlas, "renderer revision")

    def test_duplicate_catalog_genres_do_not_form_a_bridge(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        with connection:
            connection.executescript(
                """CREATE TABLE genres (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
                   INSERT INTO genres VALUES (1, 'Jazz'), (2, 'jazz'), (3, 'Pop');"""
            )
        self.assertEqual(_bridgeable_genre_ids(connection, Counter({"jazz": 1, "pop": 1})), {3})

    def _assert_static_rejected(self, payload: dict[str, object], message: str) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "static-discovery.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(StaticGapAuditError, message):
                _load_static(path, _DATABASE_SHA256)

    def _assert_atlas_rejected(self, payload: dict[str, object], message: str) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "semantic-atlas.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(StaticGapAuditError, message):
                _placed_name_counts(path)


def _static_payload() -> dict[str, object]:
    return {
        "revision": "static-direct-discovery-v1",
        "availability": "ready",
        "source": _static_source(),
        "artists": [
            {
                "artist_id": "artist:1",
                "name": "Artist",
                "musicbrainz_url": f"https://musicbrainz.org/artist/{_MBID}",
                "memberships": [],
                "shared_genre_artists": [],
            }
        ],
        "genres": [],
    }


def _static_source(
    *, database_sha256: str = _DATABASE_SHA256, observation_kind: str = "direct_source_claim"
) -> dict[str, object]:
    return {
        "database_sha256": database_sha256,
        "database_byte_count": 1,
        "observation_kind": observation_kind,
        "sources": [],
    }


def _atlas_payload() -> dict[str, object]:
    return {
        "revision": "semantic-scatter-map-v2",
        "source": "semantic-map-layout-v2",
        "logical_output_sha256": _ATLAS_HASH,
        "placed_node_count": 1,
        "nodes": [{"id": "item1", "name": "pop"}],
    }
