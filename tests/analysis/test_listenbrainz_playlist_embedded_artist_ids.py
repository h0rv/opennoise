"""Tests for bounded JSPF embedded-artist source-claim parsing."""

from __future__ import annotations

import hashlib
import json
import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from pydantic import HttpUrl

from opennoise.analysis.listenbrainz_playlist_embedded_artist_ids import (
    ListenBrainzPlaylistEmbeddedArtistIdsError,
    PlaylistArtistIdentifierOccurrence,
    _coverage,
    measure_embedded_artist_identifiers,
)
from opennoise.ingest.listenbrainz.playlists import (
    PlaylistSourceReceipt,
    PublicPlaylistFetchSettings,
    PublicPlaylistSnapshotBundle,
    parse_public_playlist_snapshot,
)

PLAYLIST_A = UUID("00000000-0000-4000-8000-000000000001")
PLAYLIST_B = UUID("00000000-0000-4000-8000-000000000002")
RECORDING_A = UUID("10000000-0000-4000-8000-000000000001")
RECORDING_B = UUID("10000000-0000-4000-8000-000000000002")
ARTIST_A = UUID("20000000-0000-4000-8000-000000000001")
ARTIST_B = UUID("20000000-0000-4000-8000-000000000002")
ARTIST_C = UUID("20000000-0000-4000-8000-000000000003")
EXPECTED_TRACK_OCCURRENCES = 4
EXPECTED_ARTIST_URI_OCCURRENCES = 6
EXPECTED_ARTIST_IDS = 3
EXPECTED_MULTI_ARTIST_OCCURRENCES = 2
EXPECTED_PAIR_OBSERVATIONS = 4
EXPECTED_DISTINCT_PAIRS = 2
OVERSIZED_PAIR_EXPANSION_OCCURRENCES = 100
OVERSIZED_PAIR_EXPANSION_ARTISTS_PER_TRACK = 16


def _payload(playlist_id: UUID) -> bytes:
    tracks = [
        (RECORDING_A, (ARTIST_A, ARTIST_B)),
        (RECORDING_B, (ARTIST_C,)),
    ]
    return json.dumps(
        {
            "playlist": {
                "identifier": f"https://listenbrainz.org/playlist/{playlist_id}",
                "track": [
                    {
                        "identifier": f"https://musicbrainz.org/recording/{recording_id}",
                        "extension": {
                            "https://musicbrainz.org/doc/jspf#track": {
                                "artist_identifiers": [
                                    f"https://musicbrainz.org/artist/{artist_id}"
                                    for artist_id in artist_ids
                                ]
                            }
                        },
                    }
                    for recording_id, artist_ids in tracks
                ],
            }
        },
        separators=(",", ":"),
    ).encode()


def _bundle(directory: Path) -> Path:
    raw_directory = directory / "raw" / "sha256"
    raw_directory.mkdir(parents=True)
    snapshots = []
    for playlist_id in (PLAYLIST_A, PLAYLIST_B):
        payload = _payload(playlist_id)
        receipt = PlaylistSourceReceipt(
            source_url=HttpUrl(f"https://api.listenbrainz.org/1/playlist/{playlist_id}"),
            fetched_at=datetime(2026, 9, 23, tzinfo=UTC),
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            payload_bytes=len(payload),
            selection_method="direct_playlist_id",
        )
        snapshots.append(parse_public_playlist_snapshot(payload, receipt))
        (raw_directory / receipt.payload_sha256).write_bytes(payload)
    path = directory / "snapshots.json"
    path.write_text(
        PublicPlaylistSnapshotBundle(
            fetch_settings=PublicPlaylistFetchSettings(), snapshots=tuple(snapshots)
        ).model_dump_json(),
        encoding="utf-8",
    )
    return path


def _check_source_claim_measurement() -> None:
    """Count only pairs crossing distinct tracks, then label repeated cohort pairs."""
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        bundle = _bundle(directory)
        artifact = measure_embedded_artist_identifiers(
            bundle, raw_object_directory=directory / "raw" / "sha256"
        )

    coverage = artifact.coverage
    assert coverage.raw_track_occurrence_count == EXPECTED_TRACK_OCCURRENCES
    assert coverage.exact_recording_occurrence_count == EXPECTED_TRACK_OCCURRENCES
    assert coverage.occurrences_with_nonempty_source_claim_count == EXPECTED_TRACK_OCCURRENCES
    assert coverage.syntactically_valid_source_artist_uri_count == EXPECTED_ARTIST_URI_OCCURRENCES
    assert coverage.distinct_source_claimed_artist_id_count == EXPECTED_ARTIST_IDS
    assert coverage.multi_artist_source_claim_occurrence_count == EXPECTED_MULTI_ARTIST_OCCURRENCES
    assert coverage.cross_recording_artist_pair_observation_count == EXPECTED_PAIR_OBSERVATIONS
    assert coverage.distinct_cross_recording_artist_pair_count == EXPECTED_DISTINCT_PAIRS
    assert (
        coverage.repeat_within_one_account_cohort_pair_count_at_least_two_playlists
        == EXPECTED_DISTINCT_PAIRS
    )
    assert artifact.coappearance_scope == "within_one_account_playlist_cohort_only"


def _check_tampered_raw_custody_object() -> None:
    """Require every raw object to remain byte- and hash-bound to its receipt."""
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        bundle = _bundle(directory)
        raw_object = next((directory / "raw" / "sha256").iterdir())
        raw_object.write_bytes(b"tampered")
        try:
            measure_embedded_artist_identifiers(
                bundle, raw_object_directory=directory / "raw" / "sha256"
            )
        except ListenBrainzPlaylistEmbeddedArtistIdsError:
            pass
        else:
            raise AssertionError("tampered custody object was accepted")


def _check_pair_expansion_boundary() -> None:
    """Reject a valid-shaped local cohort before its cross-product becomes excessive."""
    occurrences = tuple(
        PlaylistArtistIdentifierOccurrence(
            playlist_mbid=PLAYLIST_A,
            recording_mbid=UUID(int=index + 1),
            ordinal=index,
            source_claimed_artist_mbids=tuple(
                UUID(int=(index * OVERSIZED_PAIR_EXPANSION_ARTISTS_PER_TRACK) + artist + 10_000)
                for artist in range(OVERSIZED_PAIR_EXPANSION_ARTISTS_PER_TRACK)
            ),
        )
        for index in range(OVERSIZED_PAIR_EXPANSION_OCCURRENCES)
    )
    try:
        _coverage(0, 0, occurrences, 0, 0, 0, 0, 0, 0)
    except ListenBrainzPlaylistEmbeddedArtistIdsError:
        pass
    else:
        raise AssertionError("unbounded artist-pair expansion was accepted")


class ListenBrainzPlaylistEmbeddedArtistIdsTests(unittest.TestCase):
    """Exercise the raw JSPF boundary and its cohort-only pair accounting."""

    def test_measures_source_claims_and_same_cohort_repeats_without_same_track_pairs(self) -> None:
        """Count only pairs crossing distinct tracks, then label repeated cohort pairs."""
        _check_source_claim_measurement()

    def test_rejects_a_tampered_raw_custody_object(self) -> None:
        """Require every raw object to remain byte- and hash-bound to its receipt."""
        _check_tampered_raw_custody_object()

    def test_rejects_excessive_artist_pair_expansion(self) -> None:
        """Keep a valid-shaped local JSPF cohort within its declared work ceiling."""
        _check_pair_expansion_boundary()
