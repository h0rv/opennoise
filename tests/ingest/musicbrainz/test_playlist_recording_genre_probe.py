import hashlib
import json
import unittest
from uuid import UUID

from opennoise.ingest.musicbrainz.entity_genre_observation import (
    EntityGenreSourceReceipt,
    RetainedEntityGenreResponse,
    build_entity_genre_observation_report,
)
from opennoise.ingest.musicbrainz.playlist_recording_genre_probe import (
    exact_recording_overlap,
    summarize_recording_genres,
)

RECORDINGS = tuple(str(UUID(int=value)) for value in range(1, 5))
GENRE = str(UUID(int=101))


def _retained(
    recording_id: str, *, genres: list[dict[str, object]], tags: list[dict[str, object]]
) -> RetainedEntityGenreResponse:
    payload = json.dumps(
        {"id": recording_id, "genres": genres, "tags": tags}, separators=(",", ":")
    ).encode()
    return RetainedEntityGenreResponse(
        receipt=EntityGenreSourceReceipt(
            source_partition="fixture-playlist-recording-genre-probe",
            source_snapshot="fixture-20260923",
            entity_kind="recording",
            entity_mbid=UUID(recording_id),
            request_url=f"https://musicbrainz.org/ws/2/recording/{recording_id}?fmt=json&inc=genres%2Btags",
            response_sha256=hashlib.sha256(payload).hexdigest(),
        ),
        payload=payload,
    )


class PlaylistRecordingGenreProbeTests(unittest.TestCase):
    def test_overlap_is_exact_uuid_only_and_sorted(self) -> None:
        overlap = exact_recording_overlap(
            frozenset(UUID(value) for value in (RECORDINGS[2], RECORDINGS[0])),
            frozenset(UUID(value) for value in (RECORDINGS[0], RECORDINGS[1])),
        )
        self.assertEqual(overlap, (UUID(RECORDINGS[0]),))

    def test_positive_native_genre_coverage_is_distinct_and_tags_stay_separate(self) -> None:
        retained = (
            _retained(
                RECORDINGS[0],
                genres=[{"id": GENRE, "name": "Electronic", "count": 1}],
                tags=[{"name": "synthpop", "count": 9}],
            ),
            _retained(
                RECORDINGS[1],
                genres=[{"id": str(UUID(int=102)), "name": "Rock", "count": 0}],
                tags=[{"name": "rock", "count": 1}],
            ),
            _retained(RECORDINGS[2], genres=[], tags=[]),
        )
        summary = summarize_recording_genres(build_entity_genre_observation_report(retained))

        self.assertEqual(summary.observed_recordings, 3)
        self.assertEqual(summary.proper_genre_observations, 2)
        self.assertEqual(summary.positive_tag_observations, 2)
        self.assertEqual(summary.recordings_with_positive_proper_genre, 1)
        self.assertFalse(summary.recording_genre_coverage_threshold_exceeded)

    def test_more_than_two_positive_proper_genre_recordings_exceeds_threshold(self) -> None:
        report = build_entity_genre_observation_report(
            tuple(
                _retained(
                    recording_id,
                    genres=[
                        {"id": str(UUID(int=110 + index)), "name": f"Genre {index}", "count": 1}
                    ],
                    tags=[],
                )
                for index, recording_id in enumerate(RECORDINGS[:3])
            )
        )
        summary = summarize_recording_genres(report)

        self.assertEqual(summary.recordings_with_positive_proper_genre, 3)
        self.assertTrue(summary.recording_genre_coverage_threshold_exceeded)


if __name__ == "__main__":
    unittest.main()
