"""Exercise exact credits, safe links and deterministic diversity."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from opennoise.serving.metadata.artist_works import (
    CreditedMusicCandidate,
    rank_artist_works,
    verify_projected_artist_work_examples,
)

ARTIST = "f22942a1-6f70-4f48-866e-238cb2308fbd"


def candidate(number: int, group: str, *, artist: str = ARTIST) -> CreditedMusicCandidate:
    """Create a small independently credited recording fixture."""
    return CreditedMusicCandidate(
        entity_kind="recording",
        entity_id=f"musicbrainz:recording:00000000-0000-0000-0000-{number:012d}",
        title=f"Track {number}",
        credited_artist_mbids=(artist,),
        evidence_refs=("capture:fixture",),
        release_group_ids=(group,),
        original_album=True,
    )


class ArtistWorkExamplesTests(unittest.TestCase):
    def test_exact_credit_and_release_diversity(self) -> None:
        rows = (
            candidate(1, "a"),
            candidate(2, "a"),
            candidate(3, "b"),
            candidate(4, "c", artist="other"),
        )
        selected = rank_artist_works(ARTIST, rows, limit=3)
        self.assertEqual(
            [row.candidate.title for row in selected], ["Track 1", "Track 3", "Track 2"]
        )
        self.assertEqual(selected, rank_artist_works(ARTIST, tuple(reversed(rows)), limit=3))
        self.assertEqual(selected[2].score_components["unseen_release_context"], 0)
        self.assertTrue(
            all(row.url.startswith("https://musicbrainz.org/recording/") for row in selected)
        )

    def test_arbitrary_media_url_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CreditedMusicCandidate(
                entity_kind="recording",
                entity_id="https://example.org/audio.mp3",
                title="x",
                credited_artist_mbids=(ARTIST,),
                evidence_refs=("fixture",),
            )

    def test_invalid_limit(self) -> None:
        with self.assertRaises(ValueError):
            rank_artist_works(ARTIST, (), limit=101)


class ArtistWorkReplayTests(unittest.TestCase):
    def test_duplicates_merge_independent_of_input_order(self) -> None:
        first = candidate(1, "a")
        second = first.model_copy(
            update={"release_group_ids": ("b",), "evidence_refs": ("second",)}
        )
        selected = rank_artist_works(ARTIST, (first, second))
        self.assertEqual(selected, rank_artist_works(ARTIST, (second, first)))
        self.assertEqual(selected[0].candidate.release_group_ids, ("a", "b"))
        with self.assertRaises(ValueError):
            rank_artist_works(ARTIST, (first, first.model_copy(update={"title": "conflict"})))

    def test_replay_rejects_wrong_url_even_with_matching_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            projection, receipt = (
                Path(directory) / "projection.json",
                Path(directory) / "receipt.json",
            )
            row = candidate(1, "a").model_dump(mode="json")
            row["url"] = "https://example.org/audio.mp3"
            projection.write_text(
                json.dumps(
                    {
                        "revision": "credited-music-examples-v1",
                        "artists": [
                            {"artist_mbid": ARTIST, "recordings": [row], "release_groups": []}
                        ],
                    }
                )
            )
            receipt.write_text(
                json.dumps(
                    {
                        "license": "MusicBrainz core metadata CC0 1.0",
                        "license_url": "https://musicbrainz.org/doc/About/Data_License",
                        "projection_sha256": hashlib.sha256(projection.read_bytes()).hexdigest(),
                    }
                )
            )
            with self.assertRaises(ValueError):
                verify_projected_artist_work_examples(projection, receipt)
            projection.write_text("tampered")
            with self.assertRaises(ValueError):
                verify_projected_artist_work_examples(projection, receipt)
