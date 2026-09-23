"""Offline and replay tests for the ListenBrainz popularity boundary."""

from __future__ import annotations

import hashlib
import json
import unittest
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import httpx
from pydantic import HttpUrl

from opennoise.evidence.musicbrainz_album_review import (
    AlbumReviewCandidate,
    AlbumSeedReview,
    MusicBrainzAlbumReviewPacket,
    review_source_sha256,
)
from opennoise.ingest.listenbrainz.popularity import (
    ArtistPopularity,
    ListenBrainzPopularityError,
    PopularityFetchSettings,
    PopularityProbeBundle,
    PopularityProbeReport,
    PopularityReceipt,
    RecordingRanking,
    ReleaseGroupRanking,
    compare_album_candidate_packet,
    fetch_popularity_probe,
    measure_exact_catalog_coverage,
    parse_ranking,
    verify_popularity_probe_bundle,
)

ARTIST = UUID("b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d")
MAX_RESULTS = 10
RECORDING_A = UUID("00000000-0000-4000-8000-000000000011")
RECORDING_B = UUID("00000000-0000-4000-8000-000000000012")
GROUP_A = UUID("00000000-0000-4000-8000-000000000021")
GROUP_B = UUID("00000000-0000-4000-8000-000000000022")


def _receipt(payload: bytes, kind: Literal["recording", "release_group"]) -> PopularityReceipt:
    route = "recordings" if kind == "recording" else "release-groups"
    return PopularityReceipt(
        source_url=HttpUrl(
            f"https://api.listenbrainz.org/1/popularity/top-{route}-for-artist/{ARTIST}"
        ),
        fetched_at=datetime(2026, 9, 23, tzinfo=UTC),
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        payload_bytes=len(payload),
        ranking_kind=kind,
        artist_mbid=ARTIST,
    )


def _row(key: str, identifier: UUID, count: int) -> dict[str, object]:
    return {
        key: str(identifier),
        "total_listen_count": count,
        "total_user_count": count // 2,
        "recording_name": "title is discarded",
        "tag": {"genre": 100},
    }


class ListenBrainzPopularityTests(unittest.IsolatedAsyncioTestCase):
    """Exercise strict replay, exact ID joins, and request bounds without a network."""

    def test_replay_keeps_two_rankings_separate_and_measures_exact_candidate_ranks(self) -> None:
        recording_payload = json.dumps(
            [_row("recording_mbid", RECORDING_A, 30), _row("recording_mbid", RECORDING_B, 20)]
        ).encode()
        group_payload = json.dumps(
            [_row("release_group_mbid", GROUP_A, 40), _row("release_group_mbid", GROUP_B, 10)]
        ).encode()
        recording = parse_ranking(
            recording_payload,
            artist_mbid=ARTIST,
            ranking_kind="recording",
            receipt=_receipt(recording_payload, "recording"),
        )
        groups = parse_ranking(
            group_payload,
            artist_mbid=ARTIST,
            ranking_kind="release_group",
            receipt=_receipt(group_payload, "release_group"),
        )
        self.assertIsInstance(recording, RecordingRanking)
        self.assertIsInstance(groups, ReleaseGroupRanking)
        bundle = PopularityProbeBundle(
            artists=(
                ArtistPopularity(
                    artist_mbid=ARTIST,
                    recording_ranking=recording,
                    release_group_ranking=groups,
                ),
            )
        )

        coverage = measure_exact_catalog_coverage(
            bundle, recording_mbids=(RECORDING_B,), release_group_mbids=(GROUP_A,)
        )

        self.assertEqual(
            tuple(row.ranking_kind for row in coverage), ("recording", "release_group")
        )
        self.assertEqual(coverage[0].matched_candidate_ranks, (2,))
        self.assertEqual(coverage[0].unmatched_result_count, 1)
        self.assertEqual(coverage[1].matched_candidate_ranks, (1,))
        self.assertFalse(bundle.genre_evidence_eligible)
        self.assertEqual(
            recording.results[0].model_dump().keys(),
            {"recording_mbid", "total_listen_count", "total_user_count"},
        )
        replayed = RecordingRanking.model_validate_json(recording.model_dump_json(), strict=True)
        self.assertEqual(replayed.raw_payload, recording_payload)
        self.assertEqual(
            replayed.receipt.payload_sha256, hashlib.sha256(replayed.raw_payload).hexdigest()
        )
        verify_popularity_probe_bundle(
            PopularityProbeBundle.model_validate_json(bundle.model_dump_json(), strict=True)
        )

        modified_row = recording.results[0].model_copy(update={"total_listen_count": 999})
        modified_ranking = recording.model_copy(update={"results": (modified_row,)})
        modified_artist = bundle.artists[0].model_copy(
            update={"recording_ranking": modified_ranking}
        )
        modified_bundle = bundle.model_copy(update={"artists": (modified_artist,)})
        with self.assertRaisesRegex(ListenBrainzPopularityError, "projection does not replay"):
            verify_popularity_probe_bundle(modified_bundle)

        tampered_report = PopularityProbeReport(bundle=bundle).model_copy(
            update={"bundle": modified_bundle}
        )
        with self.assertRaisesRegex(ListenBrainzPopularityError, "projection does not replay"):
            verify_popularity_probe_bundle(
                PopularityProbeReport.model_validate_json(
                    tampered_report.model_dump_json(), strict=True
                ).bundle
            )

        packet = _album_packet()
        overlap = compare_album_candidate_packet(bundle, packet)
        self.assertEqual(len(overlap), 1)
        self.assertEqual(overlap[0].seed_name, "rock")
        self.assertEqual(overlap[0].matched_candidate_ranks, (1,))
        self.assertEqual(overlap[0].abstained_candidate_count, 0)
        tampered_packet = packet.model_copy(update={"output_sha256": "f" * 64})
        with self.assertRaisesRegex(ListenBrainzPopularityError, "packet output hash"):
            compare_album_candidate_packet(bundle, tampered_packet)

    def test_replay_rejects_receipt_hash_mismatch_and_invalid_counts(self) -> None:
        payload = json.dumps([_row("recording_mbid", RECORDING_A, 3)]).encode()
        wrong_receipt = _receipt(payload + b" ", "recording")
        with self.assertRaisesRegex(ListenBrainzPopularityError, "size"):
            parse_ranking(
                payload,
                artist_mbid=ARTIST,
                ranking_kind="recording",
                receipt=wrong_receipt,
            )
        invalid = json.dumps([_row("recording_mbid", RECORDING_A, -1)]).encode()
        with self.assertRaisesRegex(ListenBrainzPopularityError, "strict schema"):
            parse_ranking(
                invalid,
                artist_mbid=ARTIST,
                ranking_kind="recording",
                receipt=_receipt(invalid, "recording"),
            )
        over_limit = json.dumps(
            [_row("recording_mbid", RECORDING_A, value) for value in range(MAX_RESULTS + 1)]
        ).encode()
        limited = parse_ranking(
            over_limit,
            artist_mbid=ARTIST,
            ranking_kind="recording",
            receipt=_receipt(over_limit, "recording"),
        )
        self.assertEqual(len(limited.results), MAX_RESULTS)

    async def test_fetch_uses_only_fixed_official_top_ten_endpoints(self) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if "top-recordings" in request.url.path:
                payload = [
                    _row("recording_mbid", RECORDING_A, count)
                    for count in range(MAX_RESULTS + 1, 0, -1)
                ]
            else:
                payload = [
                    _row("release_group_mbid", GROUP_A, count)
                    for count in range(MAX_RESULTS + 1, 0, -1)
                ]
            return httpx.Response(200, json=payload, headers={"content-type": "application/json"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            bundle = await fetch_popularity_probe((ARTIST,), client=client)

        self.assertEqual(len(requests), 2)
        self.assertTrue(all(request.url.host == "api.listenbrainz.org" for request in requests))
        self.assertTrue(all(request.url.query == b"" for request in requests))
        self.assertEqual(
            PopularityFetchSettings().user_agent,
            "opennoise/0.1 (https://github.com/h0rv/opennoise)",
        )
        self.assertTrue(
            all(len(item.recording_ranking.results) <= MAX_RESULTS for item in bundle.artists)
        )
        self.assertEqual(len(bundle.artists[0].recording_ranking.results), MAX_RESULTS)
        self.assertEqual(len(bundle.artists[0].release_group_ranking.results), MAX_RESULTS)


def _album_packet() -> MusicBrainzAlbumReviewPacket:
    """Construct a tiny exact-ID packet fixture with its source digest."""
    seed = AlbumSeedReview(
        seed_source_item_id="item1",
        normalized_seed_name="rock",
        reconciliation_disposition="reconciled",
        sampling_stratum="broad",
        candidates=(
            AlbumReviewCandidate(
                release_group_mbid=str(GROUP_A),
                title="discarded descriptive context",
                first_release_date=None,
                credited_artist_mbids=(str(ARTIST),),
                source_record_content_sha256="a" * 64,
                genre_mbid="00000000-0000-4000-8000-000000000031",
                genre_name="rock",
                positive_native_vote_count=2,
            ),
        ),
    )
    draft = MusicBrainzAlbumReviewPacket.model_construct(
        source_report_sha256="b" * 64,
        source_archive_sha256="c" * 64,
        source_cache_receipt_sha256="d" * 64,
        seed_reconciliation_sha256="e" * 64,
        source_seed_count=1,
        source_seed_rows_with_examples=1,
        source_seed_example_limit=1,
        seed_reviews=(seed,),
        output_sha256="0" * 64,
    )
    return MusicBrainzAlbumReviewPacket(
        source_report_sha256="b" * 64,
        source_archive_sha256="c" * 64,
        source_cache_receipt_sha256="d" * 64,
        seed_reconciliation_sha256="e" * 64,
        source_seed_count=1,
        source_seed_rows_with_examples=1,
        source_seed_example_limit=1,
        seed_reviews=(seed,),
        output_sha256=review_source_sha256(draft),
    )


if __name__ == "__main__":
    unittest.main()
