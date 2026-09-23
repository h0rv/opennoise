"""Tests for the disjoint 50-recording playlist artist-credit audit."""

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
    ListenBrainzPlaylistArtistBridgeArtifact,
    PlaylistArtistBridgeCoverage,
    PlaylistRecordingSelectionReceipt,
    PlaylistSelectedRecordingOrder,
    PlaylistSourcePin,
)
from opennoise.analysis.listenbrainz_playlist_artist_followup import (
    ListenBrainzPlaylistArtistFollowupError,
    make_followup_selection,
    measure_followup_artist_credits,
    replay_followup_artist_credits,
)
from opennoise.analysis.musicbrainz_recording_coverage import (
    LocalResponseObject,
    RecordingLookupReceipt,
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


def _recording_id(value: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{value:012d}")


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
        fetched_at=datetime(2026, 9, 22, tzinfo=UTC),
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        payload_bytes=len(payload),
        selection_method="direct_playlist_id",
    )
    return parse_public_playlist_snapshot(payload, receipt), payload


def _write_sources(directory: Path) -> tuple[Path, Path, Path, tuple[UUID, ...]]:
    first_ids = tuple(_recording_id(value) for value in range(1, 41))
    second_ids = tuple(_recording_id(value) for value in range(41, 81))
    first, first_payload = _snapshot(PLAYLIST_A, first_ids)
    second, second_payload = _snapshot(PLAYLIST_B, second_ids)
    raw_directory = directory / "raw" / "sha256"
    raw_directory.mkdir(parents=True)
    for payload in (first_payload, second_payload):
        (raw_directory / hashlib.sha256(payload).hexdigest()).write_bytes(payload)
    bundle = PublicPlaylistSnapshotBundle(
        fetch_settings=PublicPlaylistFetchSettings(), snapshots=(first, second)
    )
    bundle_path = directory / "snapshots.json"
    bundle_bytes = bundle.model_dump_json(indent=2).encode()
    bundle_path.write_bytes(bundle_bytes)
    prior_ids = tuple(
        item for pair in zip(first_ids[:12], second_ids[:12], strict=True) for item in pair
    )
    source_pins = tuple(
        PlaylistSourcePin(
            playlist_mbid=snapshot.playlist_mbid,
            curator_kind=snapshot.curator_kind,
            payload_sha256=snapshot.receipt.payload_sha256,
        )
        for snapshot in (first, second)
    )
    prior_selection = PlaylistRecordingSelectionReceipt(
        source_playlist_bundle_file_sha256=hashlib.sha256(bundle_bytes).hexdigest(),
        source_raw_object_layout=bundle.raw_object_layout,
        ordered_playlist_sources=source_pins,
        selected_recording_ids=prior_ids,
        selected_recording_order_by_playlist=(
            PlaylistSelectedRecordingOrder(
                playlist_mbid=PLAYLIST_A, selected_recording_ids=first_ids[:12]
            ),
            PlaylistSelectedRecordingOrder(
                playlist_mbid=PLAYLIST_B, selected_recording_ids=second_ids[:12]
            ),
        ),
    )
    lookups = tuple(
        RecordingLookupReceipt(
            requested_recording_id=recording_id,
            outcome="http_not_found",
            http_status_code=404,
            response_object=LocalResponseObject(sha256="a" * 64, byte_size=0),
            fetched_at_utc=datetime(2026, 9, 22, tzinfo=UTC),
        )
        for recording_id in prior_ids
    )
    bridge = ListenBrainzPlaylistArtistBridgeArtifact(
        selection_receipt=prior_selection,
        lookups=lookups,
        coverage=PlaylistArtistBridgeCoverage(
            requested_recording_count=24,
            successful_exact_lookup_count=0,
            artist_credit_present_count=0,
            multiple_artist_credit_count=0,
            unique_artist_id_count=0,
            cross_recording_artist_pair_observation_count=0,
            unique_cross_recording_artist_pair_potential_count=0,
        ),
    )
    bridge_path = directory / "prior-bridge.json"
    bridge_path.write_text(bridge.model_dump_json(indent=2), encoding="utf-8")
    return bundle_path, raw_directory, bridge_path, prior_ids


class ListenBrainzPlaylistArtistFollowupTests(PollingIsolatedAsyncioTestCase):
    async def test_selects_50_new_source_order_ids_and_replays_exact_lookups(self) -> None:
        async def no_sleep(_: float) -> None:
            return None

        requested: list[UUID] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            recording_id = UUID(request.url.path.rsplit("/", 1)[-1])
            requested.append(recording_id)
            artist_id = ARTIST_B if recording_id.int % 2 else ARTIST_A
            return httpx.Response(
                200,
                json={
                    "id": str(recording_id),
                    "title": "must not be retained",
                    "artist-credit": [
                        {"name": "must not be retained", "artist": {"id": artist_id}}
                    ],
                },
            )

        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            bundle_path, raw_directory, bridge_path, prior_ids = _write_sources(directory)
            selection = make_followup_selection(
                bundle_path,
                raw_object_directory=raw_directory,
                prior_bridge_file=bridge_path,
                expected_prior_bridge_file_sha256=hashlib.sha256(
                    bridge_path.read_bytes()
                ).hexdigest(),
            )
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                artifact = await measure_followup_artist_credits(
                    selection,
                    client,
                    user_agent="opennoise/0.1 (maintainer@example.org)",
                    response_cache_directory=directory / "musicbrainz",
                    clock=lambda: 1.0,
                    sleep=no_sleep,
                )
            replay = replay_followup_artist_credits(artifact, directory / "musicbrainz")

        expected = tuple(
            item
            for pair in zip(
                tuple(_recording_id(value) for value in range(13, 38)),
                tuple(_recording_id(value) for value in range(53, 78)),
                strict=True,
            )
            for item in pair
        )
        self.assertEqual(selection.selected_recording_ids, expected)
        self.assertFalse(set(selection.selected_recording_ids) & set(prior_ids))
        self.assertEqual(
            tuple(
                len(item.selected_recording_ids)
                for item in selection.selected_recording_order_by_playlist
            ),
            (25, 25),
        )
        self.assertEqual(requested, list(expected))
        self.assertEqual(artifact.coverage.requested_recording_count, 50)
        self.assertEqual(artifact.coverage.successful_exact_lookup_count, 50)
        self.assertEqual(artifact.coverage.unique_artist_id_count, 2)
        self.assertNotIn("must not be retained", artifact.model_dump_json())
        self.assertEqual(replay, artifact)

    def test_rejects_a_prior_bridge_for_a_different_playlist_bundle(self) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            bundle_path, raw_directory, bridge_path, _ = _write_sources(directory)
            bridge = ListenBrainzPlaylistArtistBridgeArtifact.model_validate_json(
                bridge_path.read_bytes()
            )
            mismatched = bridge.model_copy(
                update={
                    "selection_receipt": bridge.selection_receipt.model_copy(
                        update={"source_playlist_bundle_file_sha256": "b" * 64}
                    )
                }
            )
            bridge_path.write_text(mismatched.model_dump_json(indent=2), encoding="utf-8")
            with self.assertRaises(ListenBrainzPlaylistArtistFollowupError):
                make_followup_selection(
                    bundle_path,
                    raw_object_directory=raw_directory,
                    prior_bridge_file=bridge_path,
                    expected_prior_bridge_file_sha256=hashlib.sha256(
                        bridge_path.read_bytes()
                    ).hexdigest(),
                )

    def test_rejects_prior_bridge_source_pins_that_do_not_match_the_same_bundle(self) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            bundle_path, raw_directory, bridge_path, _ = _write_sources(directory)
            bridge = ListenBrainzPlaylistArtistBridgeArtifact.model_validate_json(
                bridge_path.read_bytes()
            )
            altered_first_source = bridge.selection_receipt.ordered_playlist_sources[0].model_copy(
                update={"payload_sha256": "b" * 64}
            )
            altered_selection = bridge.selection_receipt.model_copy(
                update={
                    "ordered_playlist_sources": (
                        altered_first_source,
                        *bridge.selection_receipt.ordered_playlist_sources[1:],
                    )
                }
            )
            mismatched = bridge.model_copy(update={"selection_receipt": altered_selection})
            bridge_path.write_text(mismatched.model_dump_json(indent=2), encoding="utf-8")
            with self.assertRaisesRegex(
                ListenBrainzPlaylistArtistFollowupError, "source pins do not match"
            ):
                make_followup_selection(
                    bundle_path,
                    raw_object_directory=raw_directory,
                    prior_bridge_file=bridge_path,
                    expected_prior_bridge_file_sha256=hashlib.sha256(
                        bridge_path.read_bytes()
                    ).hexdigest(),
                )

    def test_rejects_a_bridge_that_is_not_the_retained_receipt(self) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            bundle_path, raw_directory, bridge_path, _ = _write_sources(directory)
            with self.assertRaisesRegex(
                ListenBrainzPlaylistArtistFollowupError, "SHA-256 does not match"
            ):
                make_followup_selection(
                    bundle_path, raw_object_directory=raw_directory, prior_bridge_file=bridge_path
                )

    async def test_recasts_an_oversized_musicbrainz_response_as_followup_error(self) -> None:
        async def no_sleep(_: float) -> None:
            return None

        async def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"x" * (512 * 1024 + 1))

        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            bundle_path, raw_directory, bridge_path, _ = _write_sources(directory)
            selection = make_followup_selection(
                bundle_path,
                raw_object_directory=raw_directory,
                prior_bridge_file=bridge_path,
                expected_prior_bridge_file_sha256=hashlib.sha256(
                    bridge_path.read_bytes()
                ).hexdigest(),
            )
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                with self.assertRaisesRegex(
                    ListenBrainzPlaylistArtistFollowupError, "response exceeds custody limit"
                ):
                    await measure_followup_artist_credits(
                        selection,
                        client,
                        user_agent="opennoise/0.1 (maintainer@example.org)",
                        response_cache_directory=directory / "musicbrainz",
                        clock=lambda: 1.0,
                        sleep=no_sleep,
                    )

    async def test_recasts_an_oversized_response_custody_object_on_replay(self) -> None:
        async def no_sleep(_: float) -> None:
            return None

        async def handler(request: httpx.Request) -> httpx.Response:
            recording_id = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(
                200,
                json={"id": recording_id, "artist-credit": [{"artist": {"id": ARTIST_A}}]},
            )

        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            bundle_path, raw_directory, bridge_path, _ = _write_sources(directory)
            selection = make_followup_selection(
                bundle_path,
                raw_object_directory=raw_directory,
                prior_bridge_file=bridge_path,
                expected_prior_bridge_file_sha256=hashlib.sha256(
                    bridge_path.read_bytes()
                ).hexdigest(),
            )
            cache_directory = directory / "musicbrainz"
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                artifact = await measure_followup_artist_credits(
                    selection,
                    client,
                    user_agent="opennoise/0.1 (maintainer@example.org)",
                    response_cache_directory=cache_directory,
                    clock=lambda: 1.0,
                    sleep=no_sleep,
                )
            first_receipt = artifact.lookups[0]
            (
                cache_directory / "sha256" / f"{first_receipt.response_object.sha256}.json"
            ).write_bytes(b"x" * (512 * 1024 + 1))
            with self.assertRaisesRegex(
                ListenBrainzPlaylistArtistFollowupError,
                "response custody replay failed: response custody object exceeds boundary",
            ):
                replay_followup_artist_credits(artifact, cache_directory)
