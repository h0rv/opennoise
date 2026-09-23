"""Tests for the source-pinned exact playlist recording-to-artist bridge."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

import httpx
from pydantic import HttpUrl

from opennoise.analysis.listenbrainz_playlist_artist_bridge import (
    ListenBrainzPlaylistArtistBridgeError,
    make_playlist_selection_receipt,
    measure_playlist_artist_bridge,
    replay_playlist_artist_bridge,
)
from opennoise.ingest.listenbrainz.playlists import (
    PlaylistSourceReceipt,
    PublicPlaylistFetchSettings,
    PublicPlaylistSnapshot,
    PublicPlaylistSnapshotBundle,
    parse_public_playlist_snapshot,
)
from tests._test_client import PollingIsolatedAsyncioTestCase

PLAYLIST_A = UUID("00000000-0000-4000-8000-000000000001")
PLAYLIST_B = UUID("00000000-0000-4000-8000-000000000002")
ARTIST_A = "10000000-0000-4000-8000-000000000001"
ARTIST_B = "10000000-0000-4000-8000-000000000002"


def _payload(playlist_id: UUID, recording_ids: tuple[UUID, ...]) -> bytes:
    return json.dumps(
        {
            "playlist": {
                "identifier": f"https://listenbrainz.org/playlist/{playlist_id}",
                "track": [
                    {"identifier": f"https://musicbrainz.org/recording/{recording_id}"}
                    for recording_id in recording_ids
                ],
            }
        },
        separators=(",", ":"),
    ).encode()


def _snapshot(
    playlist_id: UUID, recording_ids: tuple[UUID, ...]
) -> tuple[PublicPlaylistSnapshot, bytes]:
    payload = _payload(playlist_id, recording_ids)
    receipt = PlaylistSourceReceipt(
        source_url=HttpUrl(f"https://api.listenbrainz.org/1/playlist/{playlist_id}"),
        fetched_at=datetime(2026, 9, 23, tzinfo=UTC),
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        payload_bytes=len(payload),
        selection_method="direct_playlist_id",
    )
    return parse_public_playlist_snapshot(payload, receipt), payload


def _write_source_bundle(directory: Path) -> tuple[Path, tuple[UUID, ...]]:
    recording_ids = tuple(UUID(f"00000000-0000-4000-8000-{index:012d}") for index in range(11, 35))
    first, first_payload = _snapshot(PLAYLIST_A, recording_ids[:12])
    second, second_payload = _snapshot(PLAYLIST_B, recording_ids[12:])
    raw_directory = directory / "raw" / "sha256"
    raw_directory.mkdir(parents=True)
    for payload in (first_payload, second_payload):
        (raw_directory / hashlib.sha256(payload).hexdigest()).write_bytes(payload)
    bundle = PublicPlaylistSnapshotBundle(
        fetch_settings=PublicPlaylistFetchSettings(), snapshots=(first, second)
    )
    bundle_path = directory / "snapshots.json"
    bundle_path.write_text(bundle.model_dump_json(indent=2), encoding="utf-8")
    return bundle_path, recording_ids


def _write_overlapping_source_bundle(directory: Path) -> tuple[Path, UUID, UUID, UUID]:
    shared = UUID("00000000-0000-4000-8000-000000000100")
    first_unique = tuple(UUID(f"00000000-0000-4000-8000-{index:012d}") for index in range(101, 114))
    second_unique = tuple(
        UUID(f"00000000-0000-4000-8000-{index:012d}") for index in range(201, 214)
    )
    first, first_payload = _snapshot(PLAYLIST_A, (shared, *first_unique))
    second, second_payload = _snapshot(PLAYLIST_B, (shared, *second_unique))
    raw_directory = directory / "raw" / "sha256"
    raw_directory.mkdir(parents=True)
    for payload in (first_payload, second_payload):
        (raw_directory / hashlib.sha256(payload).hexdigest()).write_bytes(payload)
    bundle_path = directory / "snapshots.json"
    bundle_path.write_text(
        PublicPlaylistSnapshotBundle(
            fetch_settings=PublicPlaylistFetchSettings(), snapshots=(first, second)
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )
    return bundle_path, shared, first_unique[0], second_unique[0]


class ListenBrainzPlaylistArtistBridgeTests(PollingIsolatedAsyncioTestCase):
    async def test_receipts_source_order_and_replays_exact_artist_credits(self) -> None:
        async def no_sleep(_: float) -> None:
            return None

        async def handler(request: httpx.Request) -> httpx.Response:
            recording_id = request.url.path.rsplit("/", 1)[-1]
            artists = [ARTIST_A, ARTIST_B] if recording_id.endswith("000011") else [ARTIST_A]
            return httpx.Response(
                200,
                json={
                    "id": recording_id,
                    "title": "must not be retained",
                    "artist-credit": [
                        {"name": "must not be retained", "artist": {"id": artist}}
                        for artist in artists
                    ],
                },
            )

        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            bundle_path, expected_ids = _write_source_bundle(directory)
            selection = make_playlist_selection_receipt(
                bundle_path, raw_object_directory=directory / "raw" / "sha256"
            )
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                artifact = await measure_playlist_artist_bridge(
                    selection,
                    client,
                    user_agent="opennoise/0.1 (maintainer@example.org)",
                    response_cache_directory=directory / "musicbrainz",
                    clock=lambda: 1.0,
                    sleep=no_sleep,
                )
            replay = replay_playlist_artist_bridge(artifact, directory / "musicbrainz")

        self.assertEqual(
            selection.selected_recording_ids,
            tuple(
                item
                for pair in zip(expected_ids[:12], expected_ids[12:], strict=True)
                for item in pair
            ),
        )
        self.assertEqual(
            tuple(source.playlist_mbid for source in selection.ordered_playlist_sources),
            (PLAYLIST_A, PLAYLIST_B),
        )
        self.assertEqual(
            tuple(source.curator_kind for source in selection.ordered_playlist_sources),
            ("unknown", "unknown"),
        )
        self.assertEqual(artifact.coverage.successful_exact_lookup_count, 24)
        self.assertEqual(artifact.coverage.unique_artist_id_count, 2)
        self.assertEqual(artifact.coverage.cross_recording_artist_pair_observation_count, 11)
        self.assertEqual(artifact.coverage.unique_cross_recording_artist_pair_potential_count, 1)
        self.assertNotIn("must not be retained", artifact.model_dump_json())
        self.assertEqual(replay, artifact)

    def test_rejects_a_tampered_source_raw_object(self) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            bundle_path, _ = _write_source_bundle(directory)
            raw_path = next((directory / "raw" / "sha256").iterdir())
            raw_path.write_bytes(b"tampered")
            with self.assertRaises(ListenBrainzPlaylistArtistBridgeError):
                make_playlist_selection_receipt(
                    bundle_path, raw_object_directory=directory / "raw" / "sha256"
                )

    async def test_projects_a_selected_overlap_in_each_source_playlist(self) -> None:
        async def no_sleep(_: float) -> None:
            return None

        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            bundle_path, shared, first_artist_b, second_artist_b = _write_overlapping_source_bundle(
                directory
            )
            selection = make_playlist_selection_receipt(
                bundle_path, raw_object_directory=directory / "raw" / "sha256"
            )

            async def handler(request: httpx.Request) -> httpx.Response:
                recording_id = UUID(request.url.path.rsplit("/", 1)[-1])
                artist_id = (
                    ARTIST_B if recording_id in {first_artist_b, second_artist_b} else ARTIST_A
                )
                return httpx.Response(
                    200,
                    json={
                        "id": str(recording_id),
                        "artist-credit": [{"artist": {"id": artist_id}}],
                    },
                )

            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                artifact = await measure_playlist_artist_bridge(
                    selection,
                    client,
                    user_agent="opennoise/0.1 (maintainer@example.org)",
                    response_cache_directory=directory / "musicbrainz",
                    clock=lambda: 1.0,
                    sleep=no_sleep,
                )

        self.assertEqual(selection.selected_recording_ids[0], shared)
        self.assertEqual(
            tuple(
                len(item.selected_recording_ids)
                for item in selection.selected_recording_order_by_playlist
            ),
            (12, 13),
        )
        self.assertEqual(
            tuple(
                shared in item.selected_recording_ids
                for item in selection.selected_recording_order_by_playlist
            ),
            (True, True),
        )
        self.assertEqual(artifact.coverage.cross_recording_artist_pair_observation_count, 23)
        self.assertEqual(artifact.coverage.unique_cross_recording_artist_pair_potential_count, 1)
