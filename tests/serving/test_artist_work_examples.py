"""Exercise exact credits, safe links and deterministic diversity."""

import copy
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
    def test_portable_projection_has_only_permitted_fields(self) -> None:
        root = Path(__file__).resolve().parents[2]
        projection = root / "data/examples/representative-music/credited-examples.json"
        receipt = root / "data/examples/representative-music/receipt.json"
        artifact = verify_projected_artist_work_examples(projection, receipt)
        self.assertEqual(len(artifact["artists"]), 10)

    def test_matching_hash_cannot_authorize_supplementary_or_raw_fields(self) -> None:
        root = Path(__file__).resolve().parents[2]
        original = json.loads(
            (root / "data/examples/representative-music/credited-examples.json").read_bytes()
        )
        proof = json.loads((root / "data/examples/representative-music/receipt.json").read_bytes())
        with tempfile.TemporaryDirectory() as directory:
            projection, receipt = (
                Path(directory) / "projection.json",
                Path(directory) / "receipt.json",
            )
            for scope in ("projection", "artist", "work", "ranking"):
                with self.subTest(scope=scope):
                    artifact = copy.deepcopy(original)
                    row = artifact["artists"][0]["recordings"][0]
                    match scope:
                        case "projection":
                            artifact["raw_response"] = {"tags": [{"name": "electronic"}]}
                        case "artist":
                            artifact["artists"][0]["genres"] = [{"name": "electronic"}]
                        case "work":
                            row["tags"] = [{"name": "electronic"}]
                        case "ranking":
                            row["score_components"]["supplementary_tag_score"] = 10
                    projection.write_text(json.dumps(artifact))
                    proof["projection_sha256"] = hashlib.sha256(projection.read_bytes()).hexdigest()
                    receipt.write_text(json.dumps(proof))
                    with self.assertRaisesRegex(ValueError, "unapproved .*fields"):
                        verify_projected_artist_work_examples(projection, receipt)

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
