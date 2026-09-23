"""Tests for the bounded local ListenBrainz public-playlist probe."""

from __future__ import annotations

import hashlib
import json
import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID

import httpx
from pydantic import HttpUrl

from opennoise.ingest.listenbrainz.playlists import (
    ListenBrainzPlaylistProbeError,
    PlaylistProbeSettings,
    PlaylistRecording,
    PlaylistSelectionMethod,
    PlaylistSourceReceipt,
    PublicPlaylistFetchSettings,
    PublicPlaylistSnapshot,
    PublicPlaylistSnapshotBundle,
    assess_exact_catalog_join,
    evaluate_public_playlist_probe,
    fetch_public_playlist_snapshot,
    fetch_public_playlist_snapshots,
    normalized_recording_pairs,
    parse_public_playlist_snapshot,
    write_public_playlist_snapshot_bundle,
)

PLAYLIST = "00000000-0000-4000-8000-000000000001"
RECORDING_A = "00000000-0000-4000-8000-000000000011"
RECORDING_B = "00000000-0000-4000-8000-000000000012"
RECORDING_C = "00000000-0000-4000-8000-000000000013"


def _payload(
    *recordings: str,
    playlist: str = PLAYLIST,
    extra_identifier: str | None = None,
) -> bytes:
    tracks = [
        {"identifier": f"https://musicbrainz.org/recording/{recording}"} for recording in recordings
    ]
    if extra_identifier is not None:
        tracks.append({"identifier": extra_identifier})
    return json.dumps(
        {
            "playlist": {
                "identifier": f"https://listenbrainz.org/playlist/{playlist}",
                "title": "electronic examples",
                "creator": "not used to infer curation",
                "track": tracks,
            }
        },
        separators=(",", ":"),
    ).encode()


def _array_identifier_payload(*recordings: str) -> bytes:
    return json.dumps(
        {
            "playlist": {
                "identifier": f"https://listenbrainz.org/playlist/{PLAYLIST}",
                "track": [
                    {
                        "identifier": [
                            f"https://musicbrainz.org/recording/{recording}",
                            "https://example.test/not-used",
                        ]
                    }
                    for recording in recordings
                ],
            }
        },
        separators=(",", ":"),
    ).encode()


def _receipt(
    payload: bytes,
    *,
    playlist: str = PLAYLIST,
    selection_method: PlaylistSelectionMethod = "direct_playlist_id",
) -> PlaylistSourceReceipt:
    return PlaylistSourceReceipt(
        source_url=HttpUrl(f"https://api.listenbrainz.org/1/playlist/{playlist}"),
        fetched_at=datetime(2026, 9, 22, tzinfo=UTC),
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        payload_bytes=len(payload),
        selection_method=selection_method,
    )


def _bundle(*snapshots: PublicPlaylistSnapshot) -> PublicPlaylistSnapshotBundle:
    return PublicPlaylistSnapshotBundle(
        fetch_settings=PublicPlaylistFetchSettings(),
        snapshots=snapshots,
    )


class ListenBrainzPublicPlaylistProbeTests(unittest.TestCase):
    """Protect playlist identity, normalization, and non-evaluation boundaries."""

    def test_parses_only_exact_recording_ids_and_defaults_curation_to_unknown(self) -> None:
        payload = _payload(
            RECORDING_A, RECORDING_B, RECORDING_A, extra_identifier="spotify:track:x"
        )

        snapshot = parse_public_playlist_snapshot(payload, _receipt(payload))

        self.assertEqual(snapshot.playlist_mbid, UUID(PLAYLIST))
        self.assertEqual(
            tuple(item.recording_mbid for item in snapshot.recordings),
            (UUID(RECORDING_A), UUID(RECORDING_B)),
        )
        self.assertEqual(snapshot.curator_kind, "unknown")
        self.assertEqual(snapshot.duplicate_recording_count, 1)
        self.assertEqual(snapshot.unsupported_track_identifier_count, 1)

    def test_parses_the_documented_array_identifier_jspf_shape(self) -> None:
        payload = _array_identifier_payload(RECORDING_A, RECORDING_B)

        snapshot = parse_public_playlist_snapshot(payload, _receipt(payload))

        self.assertEqual(
            tuple(item.recording_mbid for item in snapshot.recordings),
            (UUID(RECORDING_A), UUID(RECORDING_B)),
        )

    def test_rejects_mismatched_receipt_and_fewer_than_two_exact_ids(self) -> None:
        payload = _payload(RECORDING_A, RECORDING_B)
        mismatched = _receipt(payload)
        with self.assertRaisesRegex(ListenBrainzPlaylistProbeError, "size"):
            parse_public_playlist_snapshot(payload + b" ", mismatched)

        too_small = _payload(RECORDING_A, extra_identifier="https://example.test/nope")
        with self.assertRaisesRegex(ListenBrainzPlaylistProbeError, "fewer than two"):
            parse_public_playlist_snapshot(too_small, _receipt(too_small))

    def test_rejects_receipt_endpoint_for_another_playlist(self) -> None:
        second_playlist = "00000000-0000-4000-8000-000000000002"
        payload = _payload(RECORDING_A, RECORDING_B, playlist=second_playlist)

        with self.assertRaisesRegex(ValueError, "does not match"):
            parse_public_playlist_snapshot(payload, _receipt(payload))

    def test_normalizes_longer_playlist_to_one_total_vote_and_measures_exact_join(self) -> None:
        payload = _payload(RECORDING_A, RECORDING_B, RECORDING_C)
        snapshot = parse_public_playlist_snapshot(payload, _receipt(payload))

        pairs = normalized_recording_pairs(snapshot)
        readiness = assess_exact_catalog_join(snapshot, (UUID(RECORDING_A), UUID(RECORDING_C)))

        self.assertEqual(len(pairs), 3)
        self.assertAlmostEqual(sum(pair.weight for pair in pairs), 1.0)
        self.assertEqual(readiness.exact_catalog_recording_count, 2)
        self.assertEqual(readiness.unmatched_recording_count, 1)
        self.assertAlmostEqual(readiness.exact_catalog_join_rate, 2 / 3)

    def test_artifact_marks_title_search_as_non_independent_evidence(self) -> None:
        first_payload = _payload(RECORDING_A, RECORDING_B)
        second_playlist = "00000000-0000-4000-8000-000000000002"
        second_payload = _payload(
            RECORDING_A,
            RECORDING_B,
            RECORDING_C,
            playlist=second_playlist,
        )
        first = parse_public_playlist_snapshot(
            first_payload,
            _receipt(first_payload),
            curator_kind="reviewed_human",
        )
        second = parse_public_playlist_snapshot(
            second_payload,
            _receipt(
                second_payload,
                playlist=second_playlist,
                selection_method="title_search_candidate",
            ),
        )

        with patch(
            "opennoise.ingest.listenbrainz.playlists.normalized_recording_pairs",
            side_effect=AssertionError("aggregate must not allocate pair models"),
        ):
            artifact = evaluate_public_playlist_probe(
                _bundle(first, second),
                (UUID(RECORDING_A), UUID(RECORDING_B)),
                settings=PlaylistProbeSettings(maximum_playlists=2),
            )

        self.assertFalse(artifact.independent_genre_evaluation_eligible)
        self.assertEqual(artifact.title_search_candidate_count, 1)
        self.assertEqual(artifact.reviewed_human_playlist_count, 1)
        self.assertEqual(artifact.unknown_curator_playlist_count, 1)
        self.assertEqual(artifact.normalized_pair_count, 4)
        self.assertAlmostEqual(artifact.normalized_pair_weight_total, 2.0)
        self.assertEqual(artifact.catalog_recording_id_set_count, 2)
        self.assertEqual(len(artifact.catalog_recording_id_set_sha256), 64)
        self.assertEqual(len(artifact.source_snapshot_bundle_logical_sha256), 64)
        changed_catalog_artifact = evaluate_public_playlist_probe(
            _bundle(first, second),
            (UUID(RECORDING_A), UUID(RECORDING_C)),
            settings=PlaylistProbeSettings(maximum_playlists=2),
        )
        self.assertNotEqual(
            artifact.catalog_recording_id_set_sha256,
            changed_catalog_artifact.catalog_recording_id_set_sha256,
        )

    def test_rejects_caller_constructed_snapshot_outside_the_recording_bound(self) -> None:
        payload = _payload(RECORDING_A, RECORDING_B, RECORDING_C)
        snapshot = parse_public_playlist_snapshot(payload, _receipt(payload))
        oversized = snapshot.model_copy(
            update={
                "recordings": (
                    *snapshot.recordings,
                    PlaylistRecording(
                        recording_mbid=UUID("00000000-0000-4000-8000-000000000014"), ordinal=3
                    ),
                ),
            }
        )

        with self.assertRaisesRegex(ListenBrainzPlaylistProbeError, "exceeds"):
            evaluate_public_playlist_probe(
                _bundle(oversized),
                (),
                settings=PlaylistProbeSettings(maximum_unique_recordings_per_playlist=3),
            )


class ListenBrainzPublicPlaylistFetchTests(unittest.IsolatedAsyncioTestCase):
    """Exercise the client boundary with mock HTTP only."""

    async def test_fetches_only_the_exact_official_endpoint_and_parses_receipt(self) -> None:
        payload = _payload(RECORDING_A, RECORDING_B)
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                content=payload,
                headers={"content-type": "application/json"},
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            snapshot = await fetch_public_playlist_snapshot(UUID(PLAYLIST), client=client)

        self.assertEqual(
            str(requests[0].url), f"https://api.listenbrainz.org/1/playlist/{PLAYLIST}"
        )
        self.assertEqual(snapshot.receipt.source_url.host, "api.listenbrainz.org")
        self.assertEqual(snapshot.receipt.selection_method, "direct_playlist_id")

    async def test_writes_raw_object_before_a_receipt_bound_bundle(self) -> None:
        payload = _payload(RECORDING_A, RECORDING_B)

        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=payload, headers={"content-type": "application/json"}
            )

        with TemporaryDirectory() as directory:
            root = Path(directory)
            raw_object_directory = root / "raw" / "sha256"
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                snapshot = await fetch_public_playlist_snapshot(
                    UUID(PLAYLIST), client=client, raw_object_directory=raw_object_directory
                )
            destination = root / "snapshots.json"
            bundle = write_public_playlist_snapshot_bundle(
                (snapshot,), destination, raw_object_directory=raw_object_directory
            )
            self.assertEqual(bundle.snapshots, (snapshot,))
            self.assertTrue((raw_object_directory / snapshot.receipt.payload_sha256).is_file())
            with self.assertRaisesRegex(ListenBrainzPlaylistProbeError, "already exists"):
                write_public_playlist_snapshot_bundle(
                    (snapshot,), destination, raw_object_directory=raw_object_directory
                )

    async def test_rejects_non_json_and_declared_oversized_responses(self) -> None:
        payload = _payload(RECORDING_A, RECORDING_B)

        async def html_handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=payload, headers={"content-type": "text/html"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(html_handler)) as client:
            with self.assertRaisesRegex(ListenBrainzPlaylistProbeError, "application/json"):
                await fetch_public_playlist_snapshot(UUID(PLAYLIST), client=client)

        async def oversized_handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=payload,
                headers={
                    "content-type": "application/json",
                    "content-length": str(len(payload) + 1),
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(oversized_handler)) as client:
            with self.assertRaisesRegex(ListenBrainzPlaylistProbeError, "maximum_response_bytes"):
                await fetch_public_playlist_snapshot(
                    UUID(PLAYLIST),
                    settings=PublicPlaylistFetchSettings(maximum_response_bytes=len(payload)),
                    client=client,
                )

    async def test_batch_fetch_passes_its_recording_cap_to_each_snapshot(self) -> None:
        payload = _payload(RECORDING_A, RECORDING_B, RECORDING_C)

        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=payload, headers={"content-type": "application/json"}
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaisesRegex(ListenBrainzPlaylistProbeError, "maximum_unique"):
                await fetch_public_playlist_snapshots(
                    (UUID(PLAYLIST),),
                    settings=PlaylistProbeSettings(maximum_unique_recordings_per_playlist=2),
                    client=client,
                )


if __name__ == "__main__":
    unittest.main()
