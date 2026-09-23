"""Tests for bounded exact-credit playlist pair support measurement."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import UUID

from opennoise.analysis.listenbrainz_playlist_artist_bridge import (
    ListenBrainzPlaylistArtistBridgeArtifact,
    PlaylistArtistBridgeCoverage,
    PlaylistRecordingSelectionReceipt,
    PlaylistSelectedRecordingOrder,
    PlaylistSourcePin,
)
from opennoise.analysis.listenbrainz_playlist_signal_quality import _coverage, _pairs_by_playlist
from opennoise.analysis.musicbrainz_recording_coverage import (
    LocalResponseObject,
    RecordingLookupReceipt,
)

_PLAYLIST_A = UUID("00000000-0000-4000-8000-000000000001")
_PLAYLIST_B = UUID("00000000-0000-4000-8000-000000000002")
_RECORDING_A = UUID("00000000-0000-4000-8000-000000000011")
_RECORDING_B = UUID("00000000-0000-4000-8000-000000000012")
_RECORDING_C = UUID("00000000-0000-4000-8000-000000000013")
_ARTIST_A = UUID("10000000-0000-4000-8000-000000000001")
_ARTIST_B = UUID("10000000-0000-4000-8000-000000000002")
_ARTIST_C = UUID("10000000-0000-4000-8000-000000000003")


def _lookup(recording_id: UUID, artists: tuple[UUID, ...]) -> RecordingLookupReceipt:
    return RecordingLookupReceipt(
        requested_recording_id=recording_id,
        outcome="exact_match",
        http_status_code=200,
        response_object=LocalResponseObject(sha256="0" * 64, byte_size=0),
        fetched_at_utc=datetime(2026, 9, 23, tzinfo=UTC),
        response_recording_id=recording_id,
        artist_credit_artist_ids=artists,
    )


def _bridge() -> ListenBrainzPlaylistArtistBridgeArtifact:
    selection = PlaylistRecordingSelectionReceipt.model_construct(
        source_playlist_bundle_file_sha256="1" * 64,
        source_raw_object_layout="raw/sha256/<payload_sha256>",
        ordered_playlist_sources=(
            PlaylistSourcePin(
                playlist_mbid=_PLAYLIST_A, curator_kind="unknown", payload_sha256="2" * 64
            ),
            PlaylistSourcePin(
                playlist_mbid=_PLAYLIST_B, curator_kind="unknown", payload_sha256="3" * 64
            ),
        ),
        selected_recording_ids=(_RECORDING_A, _RECORDING_B, _RECORDING_C),
        selected_recording_order_by_playlist=(
            PlaylistSelectedRecordingOrder(
                playlist_mbid=_PLAYLIST_A, selected_recording_ids=(_RECORDING_A, _RECORDING_B)
            ),
            PlaylistSelectedRecordingOrder(
                playlist_mbid=_PLAYLIST_B, selected_recording_ids=(_RECORDING_A, _RECORDING_C)
            ),
        ),
    )
    return ListenBrainzPlaylistArtistBridgeArtifact.model_construct(
        selection_receipt=selection,
        lookups=(
            _lookup(_RECORDING_A, (_ARTIST_A,)),
            _lookup(_RECORDING_B, (_ARTIST_B,)),
            _lookup(_RECORDING_C, (_ARTIST_C,)),
        ),
        coverage=PlaylistArtistBridgeCoverage(
            requested_recording_count=3,
            successful_exact_lookup_count=3,
            artist_credit_present_count=3,
            multiple_artist_credit_count=0,
            unique_artist_id_count=3,
            cross_recording_artist_pair_observation_count=3,
            unique_cross_recording_artist_pair_potential_count=2,
        ),
    )


class PlaylistSignalQualityTests(unittest.TestCase):
    def test_counts_distinct_playlist_support_without_exposing_pairs(self) -> None:
        bridge = _bridge()
        coverage = _coverage(bridge, _pairs_by_playlist(bridge))

        self.assertEqual(coverage.sampled_playlist_count, 2)
        self.assertEqual(coverage.exact_credit_recording_occurrence_count, 4)
        self.assertEqual(coverage.exact_credit_artist_count, 3)
        self.assertEqual(coverage.distinct_within_playlist_artist_pair_count, 2)
        self.assertEqual(coverage.pairs_supported_by_two_or_more_playlists, 0)
        self.assertEqual(coverage.maximum_distinct_playlist_support_per_pair, 1)
