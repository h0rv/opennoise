"""Tests for the strictly route-only ListenBrainz user-playlist cohort."""

from __future__ import annotations

import hashlib
import json
import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from pydantic import HttpUrl

from opennoise.analysis.listenbrainz_playlist_artist_bridge import (
    ListenBrainzPlaylistArtistBridgeArtifact,
    PlaylistArtistBridgeCoverage,
    PlaylistRecordingSelectionReceipt,
    PlaylistSelectedRecordingOrder,
    PlaylistSourcePin,
)
from opennoise.analysis.listenbrainz_playlist_user_created_cohort import (
    ListenBrainzUserCreatedCohortError,
    build_user_created_playlist_cohort,
)
from opennoise.ingest.listenbrainz.playlist_source_roles import (
    make_playlist_discovery_route_receipt,
)
from opennoise.ingest.listenbrainz.playlists import (
    PlaylistSourceReceipt,
    PublicPlaylistFetchSettings,
    PublicPlaylistSnapshotBundle,
    parse_public_playlist_snapshot,
)

PLAYLIST_A = UUID("00000000-0000-4000-8000-000000000001")
PLAYLIST_B = UUID("00000000-0000-4000-8000-000000000002")


def _playlist_payload(playlist_id: UUID, recording_start: int) -> bytes:
    return json.dumps(
        {
            "playlist": {
                "identifier": f"https://listenbrainz.org/playlist/{playlist_id}",
                "track": [
                    {
                        "identifier": (
                            "https://musicbrainz.org/recording/"
                            f"00000000-0000-4000-8000-{recording_start + index:012d}"
                        )
                    }
                    for index in range(12)
                ],
            }
        },
        separators=(",", ":"),
    ).encode()


def _listing_payload(*playlist_ids: UUID) -> bytes:
    return json.dumps(
        {
            "playlists": [
                {"playlist": {"identifier": f"https://listenbrainz.org/playlist/{playlist_id}"}}
                for playlist_id in playlist_ids
            ]
        },
        separators=(",", ":"),
    ).encode()


def _bundle(directory: Path) -> tuple[bytes, Path]:
    raw_directory = directory / "raw" / "sha256"
    raw_directory.mkdir(parents=True)
    snapshots = []
    for playlist_id, recording_start in ((PLAYLIST_A, 10), (PLAYLIST_B, 30)):
        payload = _playlist_payload(playlist_id, recording_start)
        receipt = PlaylistSourceReceipt(
            source_url=HttpUrl(f"https://api.listenbrainz.org/1/playlist/{playlist_id}"),
            fetched_at=datetime(2026, 9, 22, tzinfo=UTC),
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            payload_bytes=len(payload),
            selection_method="direct_playlist_id",
        )
        snapshots.append(parse_public_playlist_snapshot(payload, receipt))
        (raw_directory / receipt.payload_sha256).write_bytes(payload)
    bundle = PublicPlaylistSnapshotBundle(
        fetch_settings=PublicPlaylistFetchSettings(), snapshots=tuple(snapshots)
    )
    return bundle.model_dump_json().encode(), raw_directory


def _bridge(bundle_bytes: bytes) -> ListenBrainzPlaylistArtistBridgeArtifact:
    selected_ids = tuple(
        UUID(f"00000000-0000-4000-8000-{recording_id:012d}")
        for recording_id in (*range(10, 22), *range(30, 42))
    )
    selection = PlaylistRecordingSelectionReceipt(
        source_playlist_bundle_file_sha256=hashlib.sha256(bundle_bytes).hexdigest(),
        source_raw_object_layout="raw/sha256/<payload_sha256>",
        ordered_playlist_sources=(
            PlaylistSourcePin(
                playlist_mbid=PLAYLIST_A, curator_kind="unknown", payload_sha256="a" * 64
            ),
            PlaylistSourcePin(
                playlist_mbid=PLAYLIST_B, curator_kind="unknown", payload_sha256="b" * 64
            ),
        ),
        selected_recording_ids=selected_ids,
        selected_recording_order_by_playlist=(
            PlaylistSelectedRecordingOrder(
                playlist_mbid=PLAYLIST_A, selected_recording_ids=selected_ids[:12]
            ),
            PlaylistSelectedRecordingOrder(
                playlist_mbid=PLAYLIST_B, selected_recording_ids=selected_ids[12:]
            ),
        ),
    )
    return ListenBrainzPlaylistArtistBridgeArtifact.model_construct(
        selection_receipt=selection,
        coverage=PlaylistArtistBridgeCoverage(
            requested_recording_count=24,
            successful_exact_lookup_count=23,
            artist_credit_present_count=22,
            multiple_artist_credit_count=0,
            unique_artist_id_count=22,
            cross_recording_artist_pair_observation_count=30,
            unique_cross_recording_artist_pair_potential_count=27,
        ),
        lookups=(),
    )


class ListenBrainzUserCreatedPlaylistCohortTests(unittest.TestCase):
    """Keep user-listing provenance separate from human or editorial curation."""

    def test_binds_route_listing_snapshots_and_exact_artist_coverage_without_human_claim(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            bundle_bytes, raw_directory = _bundle(Path(temporary))
            listing_payload = _listing_payload(PLAYLIST_A, PLAYLIST_B)
            receipt = make_playlist_discovery_route_receipt(
                HttpUrl("https://api.listenbrainz.org/1/user/example/playlists?count=20"),
                payload_sha256=hashlib.sha256(listing_payload).hexdigest(),
                payload_bytes=len(listing_payload),
            )
            cohort = build_user_created_playlist_cohort(
                listing_payload=listing_payload,
                listing_route_receipt=receipt,
                snapshot_bundle_bytes=bundle_bytes,
                raw_object_directory=raw_directory,
                artist_bridge=_bridge(bundle_bytes),
            )

        self.assertEqual(cohort.cohort_playlist_mbids, (PLAYLIST_A, PLAYLIST_B))
        self.assertEqual(cohort.route_establishes, "service_listed_as_created_by_account")
        self.assertFalse(cohort.human_curation_established)
        self.assertFalse(cohort.manual_or_editorial_curation_established)
        self.assertEqual(
            cohort.human_curation_claim_criterion,
            "identity_bound_curator_attestation_of_manual_selection",
        )
        self.assertEqual(cohort.artist_bridge_exact_lookup_count, 23)
        self.assertEqual(cohort.artist_bridge_distinct_artist_pair_potential_count, 27)

    def test_rejects_a_snapshot_that_is_not_in_the_source_listing(self) -> None:
        with TemporaryDirectory() as temporary:
            bundle_bytes, raw_directory = _bundle(Path(temporary))
            listing_payload = _listing_payload(PLAYLIST_A)
            receipt = make_playlist_discovery_route_receipt(
                HttpUrl("https://api.listenbrainz.org/1/user/example/playlists"),
                payload_sha256=hashlib.sha256(listing_payload).hexdigest(),
                payload_bytes=len(listing_payload),
            )
            with self.assertRaisesRegex(ListenBrainzUserCreatedCohortError, "absent"):
                build_user_created_playlist_cohort(
                    listing_payload=listing_payload,
                    listing_route_receipt=receipt,
                    snapshot_bundle_bytes=bundle_bytes,
                    raw_object_directory=raw_directory,
                    artist_bridge=_bridge(bundle_bytes),
                )

    def test_rejects_non_user_created_listing_routes(self) -> None:
        with TemporaryDirectory() as temporary:
            bundle_bytes, raw_directory = _bundle(Path(temporary))
            listing_payload = _listing_payload(PLAYLIST_A, PLAYLIST_B)
            receipt = make_playlist_discovery_route_receipt(
                HttpUrl("https://api.listenbrainz.org/1/user/example/playlists/recommendations"),
                payload_sha256=hashlib.sha256(listing_payload).hexdigest(),
                payload_bytes=len(listing_payload),
            )
            with self.assertRaisesRegex(ListenBrainzUserCreatedCohortError, "not user-created"):
                build_user_created_playlist_cohort(
                    listing_payload=listing_payload,
                    listing_route_receipt=receipt,
                    snapshot_bundle_bytes=bundle_bytes,
                    raw_object_directory=raw_directory,
                    artist_bridge=_bridge(bundle_bytes),
                )
