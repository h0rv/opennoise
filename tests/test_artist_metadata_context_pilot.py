"""Behavioral tests for the bounded, cache-first artist context pilot."""

from __future__ import annotations

import asyncio
import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from musix.artist_metadata_context_pilot import CachedRequest, _load_or_fetch
from musix.sources.musicbrainz import MusicBrainzArtist, MusicBrainzClient

_ARTIST = "00000000-0000-4000-8000-000000000001"
_AREA = "00000000-0000-4000-8000-000000000002"
_BEGIN_AREA = "00000000-0000-4000-8000-000000000003"


class ArtistMetadataContextPilotTests(unittest.TestCase):
    """Exercise source preservation and cache reuse without network traffic."""

    def test_preserves_optional_source_areas_and_aliases(self) -> None:
        artist = MusicBrainzArtist.model_validate_json(json.dumps(_artist_payload()))

        self.assertEqual(artist.country, "GB")
        self.assertEqual(str(artist.area.id) if artist.area else None, _AREA)
        self.assertEqual(artist.area.name if artist.area else None, "United Kingdom")
        self.assertEqual(str(artist.begin_area.id) if artist.begin_area else None, _BEGIN_AREA)
        self.assertEqual(artist.aliases[0].name, "Pilot Alias")

    def test_cached_response_is_reused_without_a_client_request(self) -> None:
        raw = json.dumps(_artist_payload(), separators=(",", ":")).encode()
        digest = hashlib.sha256(raw).hexdigest()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw_path = root / "raw" / "sha256" / digest / "artist.json"
            raw_path.parent.mkdir(parents=True)
            raw_path.write_bytes(raw)
            request_path = root / "requests" / f"{_ARTIST}.json"
            request_path.parent.mkdir()
            request_path.write_text(
                CachedRequest(
                    artist_mbid=_ARTIST,
                    request_url="https://musicbrainz.org/ws/2/artist/example",
                    received_at="2026-09-08T00:00:00+00:00",
                    outcome="success",
                    raw_sha256=digest,
                    raw_byte_size=len(raw),
                ).model_dump_json(),
                encoding="utf-8",
            )
            artist, request, cache_hit = asyncio.run(_cached_load(root))

        self.assertTrue(cache_hit)
        self.assertIsNotNone(artist)
        self.assertEqual(request.raw_sha256, digest)


def _artist_payload() -> dict[str, object]:
    return {
        "id": _ARTIST,
        "name": "Pilot Artist",
        "sort-name": "Artist, Pilot",
        "country": "GB",
        "area": {"id": _AREA, "name": "United Kingdom", "type": "Country"},
        "begin-area": {"id": _BEGIN_AREA, "name": "London", "type": "Municipality"},
        "aliases": [{"name": "Pilot Alias", "locale": "en"}],
    }


async def _cached_load(root: Path) -> tuple[MusicBrainzArtist | None, CachedRequest, bool]:
    async with httpx.AsyncClient() as http_client:
        client = MusicBrainzClient(http_client, user_agent="musix/0.1 (test@example.test)")
        return await _load_or_fetch(client, root, _ARTIST)
