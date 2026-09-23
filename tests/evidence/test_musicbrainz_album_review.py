"""Focused invariants for the local MusicBrainz Album review packet."""

from __future__ import annotations

import json
import unittest

from opennoise.common.hashing import sha256_json
from opennoise.evidence.musicbrainz_album_review import (
    AlbumReviewCandidate,
    AlbumSeedReview,
    MusicBrainzAlbumReviewPacket,
)


class MusicBrainzAlbumReviewTests(unittest.TestCase):
    def test_abstention_and_candidate_judgments_start_empty(self) -> None:
        abstention = AlbumSeedReview(
            seed_source_item_id="seed-pop",
            normalized_seed_name="pop",
            reconciliation_disposition="ambiguous",
            sampling_stratum="ambiguous",
            candidates=(),
        )
        candidate = AlbumReviewCandidate(
            release_group_mbid="00000000-0000-4000-8000-000000000001",
            title="Example",
            first_release_date=None,
            credited_artist_mbids=(),
            source_record_content_sha256="a" * 64,
            genre_mbid="00000000-0000-4000-8000-000000000002",
            genre_name="rock",
            positive_native_vote_count=1,
        )
        self.assertIsNone(abstention.reviewer_seed_judgment)
        self.assertIsNone(candidate.reviewer_fit_judgment)
        self.assertIsNone(candidate.reviewer_notes)

    def test_packet_hash_and_local_only_boundary_replay(self) -> None:
        candidate = AlbumReviewCandidate(
            release_group_mbid="00000000-0000-4000-8000-000000000001",
            title="Example",
            first_release_date=None,
            credited_artist_mbids=(),
            source_record_content_sha256="a" * 64,
            genre_mbid="00000000-0000-4000-8000-000000000002",
            genre_name="rock",
            positive_native_vote_count=1,
        )
        fields = {
            "revision": "musicbrainz-album-context-review-v2",
            "local_only": True,
            "export_allowed": False,
            "serving_allowed": False,
            "model_input_allowed": False,
            "artist_membership_asserted": False,
            "representative_album_claimed": False,
            "quintessential_album_claimed": False,
            "source_report_sha256": "a" * 64,
            "source_archive_sha256": "b" * 64,
            "source_cache_receipt_sha256": "c" * 64,
            "seed_reconciliation_sha256": "d" * 64,
            "source_seed_count": 6_291,
            "source_seed_rows_with_examples": 893,
            "source_seed_example_limit": 5,
            "seed_reviews": (
                AlbumSeedReview(
                    seed_source_item_id="seed-rock",
                    normalized_seed_name="rock",
                    reconciliation_disposition="reconciled",
                    sampling_stratum="broad",
                    candidates=(candidate,),
                ).model_dump(
                    exclude={
                        "reviewer_seed_judgment": True,
                        "reviewer_notes": True,
                        "candidates": {"__all__": {"reviewer_fit_judgment", "reviewer_notes"}},
                    }
                ),
            ),
        }
        packet = MusicBrainzAlbumReviewPacket.model_validate(
            {**fields, "output_sha256": sha256_json(fields)}
        )
        self.assertFalse(packet.export_allowed)
        self.assertFalse(packet.serving_allowed)
        self.assertFalse(packet.model_input_allowed)
        self.assertFalse(packet.artist_membership_asserted)
        self.assertFalse(packet.representative_album_claimed)
        self.assertFalse(packet.quintessential_album_claimed)
        reviewed = packet.model_dump(mode="json")
        reviewed["output_sha256"] = packet.output_sha256
        reviewed["seed_reviews"] = [
            {
                "seed_source_item_id": "seed-rock",
                "normalized_seed_name": "rock",
                "reconciliation_disposition": "reconciled",
                "sampling_stratum": "broad",
                "candidates": [
                    {
                        **candidate.model_dump(mode="json"),
                        "reviewer_fit_judgment": "fits",
                        "reviewer_notes": "context only",
                    }
                ],
                "reviewer_seed_judgment": "uncertain",
                "reviewer_notes": "needs more evidence",
            }
        ]
        # Reviewer notes are an overlay and do not alter the evidence digest.
        parsed = MusicBrainzAlbumReviewPacket.model_validate_json(json.dumps(reviewed))
        self.assertEqual(parsed.seed_reviews[0].reviewer_seed_judgment, "uncertain")
