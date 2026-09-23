"""Fixture coverage for the local Album example query."""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import override
from unittest.mock import patch

from opennoise.ingest.musicbrainz.release_group_album_examples import (
    AlbumCreditArtist,
    AlbumExample,
    ReleaseGroupAlbumExamplesReport,
    SeedAlbumExamples,
    report_sha256,
)
from opennoise.serving.local.musicbrainz_album_discovery import (
    AlbumDiscoveryError,
    query_album_examples,
    response_json,
)
from opennoise.serving.local.musicbrainz_artist_metadata import (
    ArtistMetadataArtifact,
    ArtistMetadataCounters,
    ArtistMetadataSettings,
    CertifiedLocalArtistMetadataSources,
    LocalArtistMetadataSources,
    artist_metadata_artifact_sha256,
)


class MusicBrainzAlbumDiscoveryTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        artist_one = "00000000-0000-4000-8000-000000000001"
        artist_two = "00000000-0000-4000-8000-000000000002"
        self.artist_one = artist_one
        examples = (
            AlbumExample(
                release_group_mbid="00000000-0000-4000-8000-000000000010",
                title="First Album",
                first_release_date="2001-02-03",
                secondary_types=("Compilation",),
                credited_artist_mbids=(
                    AlbumCreditArtist(artist_mbid=artist_one),
                    AlbumCreditArtist(artist_mbid=artist_two),
                ),
                record_content_sha256="a" * 64,
                genre_mbid="00000000-0000-4000-8000-000000000020",
                genre_name="Rock",
                genre_vote_count=8,
            ),
            AlbumExample(
                release_group_mbid="00000000-0000-4000-8000-000000000011",
                title="Second Album",
                first_release_date=None,
                secondary_types=(),
                credited_artist_mbids=(AlbumCreditArtist(artist_mbid=artist_two),),
                record_content_sha256="b" * 64,
                genre_mbid="00000000-0000-4000-8000-000000000021",
                genre_name="rock",
                genre_vote_count=3,
            ),
        )
        preliminary = ReleaseGroupAlbumExamplesReport(
            source_archive_sha256="c" * 64,
            source_archive_bytes=1,
            source_cache_receipt_sha256="d" * 64,
            seed_reconciliation_sha256="e" * 64,
            seed_count=1,
            examples_per_seed_limit=5,
            raw_records_seen=2,
            records_over_limit=0,
            malformed_records=0,
            parsed_release_group_count=2,
            album_release_group_count=2,
            positive_native_proper_genre_observation_count=2,
            exact_seed_positive_observation_count=2,
            seed_rows=(
                SeedAlbumExamples(
                    seed_source_item_id="seed-rock",
                    normalized_seed_name="rock",
                    examples=examples,
                ),
            ),
            output_sha256="0" * 64,
        )
        self.report = preliminary.model_copy(update={"output_sha256": report_sha256(preliminary)})

    def test_exact_genre_name_preserves_votes_and_roles(self) -> None:
        response = query_album_examples(self.report, genre_name="Rock")
        self.assertEqual(response.result_count, 1)
        result = response.results[0]
        self.assertEqual(result.album_title, "First Album")
        self.assertEqual(result.genre_vote_count, 8)
        self.assertEqual(result.first_release_date, "2001-02-03")
        self.assertEqual(result.source_type, "musicbrainz_release_group_native_proper_genre")
        self.assertEqual(result.record_content_sha256, "a" * 64)
        self.assertEqual(result.genre_role, "native_proper_genre_observation")
        self.assertEqual(result.album_role, "ranked_source_context_example")
        self.assertFalse(result.defines_genre)
        self.assertFalse(result.asserts_artist_membership)
        self.assertEqual(result.credited_artists[0].canonical_name, None)
        self.assertEqual(result.credited_artists[0].artist_mbid, self.artist_one)
        self.assertEqual(len(result.credited_artists), 2)
        self.assertEqual(result.credited_artists[1].canonical_name, None)

    def test_exact_credited_artist_query_and_json_are_deterministic(self) -> None:
        first = query_album_examples(self.report, artist_mbid=self.artist_one)
        second = query_album_examples(self.report, artist_mbid=self.artist_one)
        self.assertEqual(first.results[0].album_title, "First Album")
        self.assertEqual(response_json(first), response_json(second))
        self.assertEqual(response_json(first), response_json(first.model_copy()))

    def test_verified_name_lookup_is_batched_and_keeps_missing_names_null(self) -> None:
        preliminary = ArtistMetadataArtifact(
            source_archive_sha256="a" * 64,
            source_archive_bytes=1,
            source_snapshot="fixture",
            evidence_output_sha256="b" * 64,
            evidence_database_sha256="c" * 64,
            evidence_database_bytes=1,
            metadata_database_sha256="d" * 64,
            metadata_database_bytes=1,
            target_artist_count=2,
            observed_artist_count=1,
            conflicting_artist_count=0,
            counters=ArtistMetadataCounters(
                records_seen=1,
                records_parsed=1,
                rejected_records=0,
                target_credit_observations=1,
            ),
            settings=ArtistMetadataSettings(),
            output_sha256="0" * 64,
        )
        artifact = preliminary.model_copy(
            update={"output_sha256": artist_metadata_artifact_sha256(preliminary)}
        )
        certified = CertifiedLocalArtistMetadataSources(
            LocalArtistMetadataSources(Path("fixture.sqlite"), artifact), object()
        )
        with (
            patch.object(CertifiedLocalArtistMetadataSources, "is_valid", return_value=True),
            patch(
                "opennoise.serving.local.musicbrainz_album_discovery.exact_certified_canonical_names",
                return_value={self.artist_one: "Artist One"},
            ) as lookup,
        ):
            response = query_album_examples(
                self.report, artist_mbid=self.artist_one, artist_metadata=certified
            )

        lookup.assert_called_once_with(
            certified, (self.artist_one, "00000000-0000-4000-8000-000000000002")
        )
        artist_entries = response.results[0].credited_artists
        self.assertEqual(
            tuple(item.canonical_name for item in artist_entries), ("Artist One", None)
        )

    def test_requires_exactly_one_query(self) -> None:
        with self.assertRaisesRegex(AlbumDiscoveryError, "exactly one"):
            query_album_examples(self.report)
        with self.assertRaisesRegex(AlbumDiscoveryError, "exactly one"):
            query_album_examples(self.report, genre_name="Rock", artist_mbid=self.artist_one)
