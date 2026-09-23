"""Behavioral checks for the local JSPF and Last.fm matched holdout."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from opennoise.analysis.listenbrainz_playlist_embedded_artist_ids import (
    EmbeddedArtistIdentifierCoverage,
    ListenBrainzPlaylistEmbeddedArtistIdsArtifact,
    PlaylistArtistIdentifierOccurrence,
)
from opennoise.analysis.listenbrainz_playlist_lastfm_holdout import (
    PairOverlap,
    PlaylistLastFmHoldoutError,
    PlaylistLastFmHoldoutSettings,
    PlaylistLastFmMatchedHoldout,
    _load_pinned_playlist_receipt,
    _overlap,
    _positive_cohort,
    _PositiveCohort,
    _rank_candidates,
    _ranking_metrics,
    _report_hash,
    _sha256_bytes,
)
from scripts.evaluate_listenbrainz_playlist_lastfm_holdout import _local_cache_output_path

_PLAYLIST_ONE = UUID("00000000-0000-4000-8000-000000000001")
_PLAYLIST_TWO = UUID("00000000-0000-4000-8000-000000000002")
_RECORDING_ONE = UUID("00000000-0000-4000-8000-000000000011")
_RECORDING_TWO = UUID("00000000-0000-4000-8000-000000000012")
_ARTIST_A = UUID("00000000-0000-4000-8000-000000000101")
_ARTIST_B = UUID("00000000-0000-4000-8000-000000000102")
_ARTIST_C = UUID("00000000-0000-4000-8000-000000000103")


def _receipt() -> ListenBrainzPlaylistEmbeddedArtistIdsArtifact:
    """Build a source receipt where only one pair repeats across playlists."""
    occurrences = (
        PlaylistArtistIdentifierOccurrence(
            playlist_mbid=_PLAYLIST_ONE,
            recording_mbid=_RECORDING_ONE,
            ordinal=0,
            source_claimed_artist_mbids=(_ARTIST_A,),
        ),
        PlaylistArtistIdentifierOccurrence(
            playlist_mbid=_PLAYLIST_ONE,
            recording_mbid=_RECORDING_TWO,
            ordinal=1,
            source_claimed_artist_mbids=(_ARTIST_B,),
        ),
        PlaylistArtistIdentifierOccurrence(
            playlist_mbid=_PLAYLIST_TWO,
            recording_mbid=_RECORDING_ONE,
            ordinal=0,
            source_claimed_artist_mbids=(_ARTIST_A,),
        ),
        PlaylistArtistIdentifierOccurrence(
            playlist_mbid=_PLAYLIST_TWO,
            recording_mbid=_RECORDING_TWO,
            ordinal=1,
            source_claimed_artist_mbids=(_ARTIST_B,),
        ),
        PlaylistArtistIdentifierOccurrence(
            playlist_mbid=_PLAYLIST_TWO,
            recording_mbid=_RECORDING_TWO,
            ordinal=2,
            source_claimed_artist_mbids=(_ARTIST_C,),
        ),
    )
    return ListenBrainzPlaylistEmbeddedArtistIdsArtifact(
        source_playlist_bundle_file_sha256="0" * 64,
        source_raw_object_layout="raw/sha256/<payload_sha256>",
        source_payload_sha256s=("1" * 64,),
        claims_by_occurrence=occurrences,
        coverage=EmbeddedArtistIdentifierCoverage(
            raw_track_occurrence_count=5,
            exact_recording_occurrence_count=5,
            distinct_recording_count=2,
            occurrences_with_nonempty_source_claim_count=5,
            syntactically_valid_source_artist_uri_count=5,
            invalid_source_artist_uri_count=0,
            distinct_source_claimed_artist_id_count=3,
            multi_artist_source_claim_occurrence_count=0,
            playlist_extension_creator_present_count=0,
            source_track_added_by_present_count=0,
            source_track_added_at_present_count=0,
            source_track_added_by_equal_playlist_extension_creator_count=0,
            cross_recording_artist_pair_observation_count=0,
            distinct_cross_recording_artist_pair_count=0,
            repeat_within_one_account_cohort_pair_count_at_least_two_playlists=0,
        ),
    )


class PlaylistLastFmHoldoutTests(unittest.TestCase):
    """Keep positives source-derived and ranking candidate order deterministic."""

    def test_positive_rule_requires_distinct_playlists_and_distinct_recordings(self) -> None:
        cohort = _positive_cohort(_receipt(), PlaylistLastFmHoldoutSettings())

        self.assertEqual(cohort.artists, tuple(sorted(map(str, (_ARTIST_A, _ARTIST_B, _ARTIST_C)))))
        self.assertEqual(len(cohort.pair_potentials), 2)
        self.assertEqual(cohort.positives, {(str(_ARTIST_A), str(_ARTIST_B))})
        self.assertNotIn((str(_ARTIST_B), str(_ARTIST_C)), cohort.pair_potentials)
        self.assertEqual(
            cohort.positive_targets,
            {
                str(_ARTIST_A): frozenset({str(_ARTIST_B)}),
                str(_ARTIST_B): frozenset({str(_ARTIST_A)}),
            },
        )

    def test_lastfm_support_precedes_zeroes_and_hash_baseline_is_repeatable(self) -> None:
        cohort = _PositiveCohort(
            artists=tuple(sorted(map(str, (_ARTIST_A, _ARTIST_B, _ARTIST_C)))),
            pair_potentials=frozenset({(str(_ARTIST_A), str(_ARTIST_B))}),
            positives=frozenset({(str(_ARTIST_A), str(_ARTIST_B))}),
            positive_targets={
                str(_ARTIST_A): frozenset({str(_ARTIST_B)}),
                str(_ARTIST_B): frozenset({str(_ARTIST_A)}),
            },
        )
        supports = {(str(_ARTIST_A), str(_ARTIST_B)): 5}

        signal = _ranking_metrics(cohort, supports, use_lastfm_score=True)
        baseline_first = _rank_candidates(
            str(_ARTIST_A), cohort.artists, supports, use_lastfm_score=False
        )
        baseline_second = _rank_candidates(
            str(_ARTIST_A), cohort.artists, supports, use_lastfm_score=False
        )

        self.assertEqual(signal.recalled_at_1, 2)
        self.assertEqual(signal.recall_at_1, 1.0)
        self.assertEqual(baseline_first, baseline_second)

    def test_zero_support_uses_the_baseline_hash_tie_order(self) -> None:
        cohort = _PositiveCohort(
            artists=tuple(sorted(map(str, (_ARTIST_A, _ARTIST_B, _ARTIST_C)))),
            pair_potentials=frozenset({(str(_ARTIST_A), str(_ARTIST_B))}),
            positives=frozenset({(str(_ARTIST_A), str(_ARTIST_B))}),
            positive_targets={
                str(_ARTIST_A): frozenset({str(_ARTIST_B)}),
                str(_ARTIST_B): frozenset({str(_ARTIST_A)}),
            },
        )

        self.assertEqual(
            _rank_candidates(str(_ARTIST_A), cohort.artists, {}, use_lastfm_score=True),
            _rank_candidates(str(_ARTIST_A), cohort.artists, {}, use_lastfm_score=False),
        )

    def test_missing_lastfm_pair_is_reported_as_unsupported(self) -> None:
        cohort = _PositiveCohort(
            artists=tuple(sorted(map(str, (_ARTIST_A, _ARTIST_B)))),
            pair_potentials=frozenset({(str(_ARTIST_A), str(_ARTIST_B))}),
            positives=frozenset({(str(_ARTIST_A), str(_ARTIST_B))}),
            positive_targets={
                str(_ARTIST_A): frozenset({str(_ARTIST_B)}),
                str(_ARTIST_B): frozenset({str(_ARTIST_A)}),
            },
        )

        overlap = _overlap(cohort, {})

        self.assertEqual(overlap.lastfm_recovered_positive_pair_count, 0)
        self.assertEqual(overlap.lastfm_unsupported_positive_pair_count, 1)
        self.assertEqual(overlap.lastfm_recovered_positive_pair_rate, 0.0)

    def test_report_hash_must_match_the_parsed_receipt(self) -> None:
        cohort = _PositiveCohort(
            artists=tuple(sorted(map(str, (_ARTIST_A, _ARTIST_B)))),
            pair_potentials=frozenset({(str(_ARTIST_A), str(_ARTIST_B))}),
            positives=frozenset({(str(_ARTIST_A), str(_ARTIST_B))}),
            positive_targets={
                str(_ARTIST_A): frozenset({str(_ARTIST_B)}),
                str(_ARTIST_B): frozenset({str(_ARTIST_A)}),
            },
        )
        metrics = _ranking_metrics(
            cohort, {(str(_ARTIST_A), str(_ARTIST_B)): 5}, use_lastfm_score=True
        )
        report = PlaylistLastFmMatchedHoldout.model_construct(
            playlist_coappearance_scope="within_one_account_playlist_cohort_only",
            expected_playlist_receipt_sha256="0" * 64,
            playlist_receipt_sha256="0" * 64,
            playlist_bundle_sha256="1" * 64,
            lastfm_artifact_sha256="2" * 64,
            lastfm_companion_receipt_sha256="3" * 64,
            lastfm_database_sha256="4" * 64,
            lastfm_pair_floor=5,
            settings=PlaylistLastFmHoldoutSettings(),
            overlap=PairOverlap(
                jspf_artist_count=2,
                pair_endpoint_artist_count=2,
                jspf_pair_potential_count=1,
                repeat_positive_pair_count=1,
                lastfm_supported_jspf_pair_count=1,
                lastfm_supported_jspf_pair_rate=1.0,
                lastfm_recovered_positive_pair_count=1,
                lastfm_unsupported_positive_pair_count=0,
                lastfm_recovered_positive_pair_rate=1.0,
            ),
            lastfm_ranking=metrics,
            deterministic_baseline=metrics,
            output_sha256="0" * 64,
        )
        payload = report.model_dump(mode="json")
        payload["output_sha256"] = _report_hash(report)

        parsed = PlaylistLastFmMatchedHoldout.model_validate_json(json.dumps(payload))
        payload["output_sha256"] = "f" * 64

        self.assertEqual(parsed.output_sha256, _report_hash(parsed))
        with self.assertRaisesRegex(ValueError, "output hash"):
            PlaylistLastFmMatchedHoldout.model_validate_json(json.dumps(payload))

    def test_valid_shaped_changed_playlist_receipt_is_rejected_before_parsing(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "playlist-receipt.json"
            original = _receipt()
            path.write_text(original.model_dump_json(), encoding="utf-8")
            expected_hash = _sha256_bytes(path.read_bytes())

            _load_pinned_playlist_receipt(path, expected_sha256=expected_hash)
            changed = original.model_copy(update={"source_playlist_bundle_file_sha256": "f" * 64})
            path.write_text(changed.model_dump_json(), encoding="utf-8")

            with self.assertRaisesRegex(PlaylistLastFmHoldoutError, "required hash"):
                _load_pinned_playlist_receipt(path, expected_sha256=expected_hash)

    def test_output_must_resolve_under_cache_not_dist_or_a_symlink_to_dist(self) -> None:
        with self.assertRaisesRegex(PlaylistLastFmHoldoutError, "resolve under .cache"):
            _local_cache_output_path(Path("dist") / "holdout-report.json")
        with TemporaryDirectory(dir=".cache") as directory:
            redirect = Path(directory) / "redirect"
            redirect.symlink_to(Path("dist").resolve(), target_is_directory=True)

            with self.assertRaisesRegex(PlaylistLastFmHoldoutError, "resolve under .cache"):
                _local_cache_output_path(redirect / "holdout-report.json")
