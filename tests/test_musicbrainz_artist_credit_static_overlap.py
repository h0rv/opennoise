from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.audit_musicbrainz_artist_credit_static_overlap import (
    OverlapAuditError,
    _load_static,
    _musicbrainz_artist_id,
)

_DATABASE_SHA256 = "a" * 64
_MBID = "11111111-1111-1111-1111-111111111111"


class MusicBrainzArtistCreditStaticOverlapTests(unittest.TestCase):
    def test_rejects_static_payload_with_wrong_revision(self) -> None:
        payload = _static_payload()
        payload["revision"] = "other"

        self._assert_static_rejected(payload)

    def test_rejects_static_payload_that_is_not_ready(self) -> None:
        payload = _static_payload()
        payload["availability"] = "unavailable"

        self._assert_static_rejected(payload)

    def test_rejects_static_payload_with_non_direct_observation_kind(self) -> None:
        payload = _static_payload(observation_kind="derived")

        self._assert_static_rejected(payload)

    def test_rejects_noncanonical_musicbrainz_artist_id(self) -> None:
        with self.assertRaisesRegex(OverlapAuditError, "canonical MBID"):
            _musicbrainz_artist_id(
                "https://musicbrainz.org/artist/AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
            )

    def _assert_static_rejected(self, payload: dict[str, object]) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "static-discovery.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(OverlapAuditError):
                _load_static(path, _DATABASE_SHA256)


def _static_payload(*, observation_kind: str = "direct_source_claim") -> dict[str, object]:
    return {
        "revision": "static-direct-discovery-v1",
        "availability": "ready",
        "source": {
            "database_sha256": _DATABASE_SHA256,
            "database_byte_count": 1,
            "observation_kind": observation_kind,
            "sources": [],
        },
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
