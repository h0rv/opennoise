import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opennoise.common import sha256_file
from opennoise.evidence.lastfm_artist_genre_review import (
    LastFmReviewPacket,
    build_lastfm_artist_genre_review,
)
from scripts.build_lastfm_artist_genre_review import _publish_no_replace

_SHA256_LENGTH = 64


class LastFmArtistGenreReviewTests(unittest.TestCase):
    def test_builds_balanced_unlabeled_packet_with_row_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "source.tar.gz"
            rows = (
                b"11111111-1111-4111-8111-111111111111<sep>Artist<sep>rock<sep>1\n"
                b"22222222-2222-4222-8222-222222222222<sep>Other<sep>jazz<sep>2\n"
                b"33333333-3333-4333-8333-333333333333<sep>Third<sep>pop<sep>1\n"
                b"44444444-4444-4444-8444-444444444444<sep>Fourth<sep>metal<sep>9\n"
            )
            source_file = root / "ArtistTags.dat"
            source_file.write_bytes(rows)
            with tarfile.open(archive, "w:gz") as output:
                output.add(source_file, arcname="Lastfm-ArtistTags2007/ArtistTags.dat")
            archive_hash, _ = sha256_file(archive)
            with patch(
                "opennoise.evidence.lastfm_artist_genre_review._ARCHIVE_SHA256", archive_hash
            ):
                packet = build_lastfm_artist_genre_review(archive, sample_size=4)
        self.assertEqual(packet.sample_size, 4)
        self.assertEqual(packet.stratum_counts, {"count_1": 2, "count_gt_1": 2})
        self.assertTrue(all(row.review_status == "unlabeled" for row in packet.rows))
        self.assertTrue(all(row.reviewer_artist_genre_member is None for row in packet.rows))
        self.assertTrue(all(len(row.source_row_sha256) == _SHA256_LENGTH for row in packet.rows))
        self.assertTrue(packet.source_observations_are_positive_tags)
        self.assertTrue(packet.missing_tags_are_not_negative)
        self.assertTrue(packet.reviewer_must_judge_membership)

    def test_rejects_non_even_sample_size(self) -> None:
        with self.assertRaisesRegex(ValueError, "even"):
            build_lastfm_artist_genre_review(Path("missing.tar.gz"), sample_size=3)

    def test_publish_does_not_replace_or_leave_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "packet.json"
            target.write_bytes(b"original")
            with self.assertRaises(FileExistsError):
                _publish_no_replace(target, b"replacement")
            self.assertEqual(target.read_bytes(), b"original")
            self.assertEqual(list(target.parent.glob(".packet.json.*.tmp")), [])

    def test_rejects_malformed_utf8_without_emitting_a_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "source.tar.gz"
            source_file = root / "ArtistTags.dat"
            source_file.write_bytes(
                b"\xff\n"
                b"11111111-1111-4111-8111-111111111111<sep>Artist<sep>rock<sep>1\n"
                b"22222222-2222-4222-8222-222222222222<sep>Other<sep>jazz<sep>2\n"
            )
            with tarfile.open(archive, "w:gz") as output:
                output.add(source_file, arcname="Lastfm-ArtistTags2007/ArtistTags.dat")
            archive_hash, _ = sha256_file(archive)
            with patch(
                "opennoise.evidence.lastfm_artist_genre_review._ARCHIVE_SHA256", archive_hash
            ):
                packet = build_lastfm_artist_genre_review(archive, sample_size=2)
        self.assertEqual(packet.source_row_count, 3)
        self.assertEqual(packet.accepted_positive_row_count, 2)

    def test_deduplicates_cross_stratum_artist_tag_questions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "source.tar.gz"
            source_file = root / "ArtistTags.dat"
            source_file.write_bytes(
                b"11111111-1111-4111-8111-111111111111<sep>Artist<sep>rock<sep>1\n"
                b"11111111-1111-4111-8111-111111111111<sep>Artist<sep>rock<sep>2\n"
                b"22222222-2222-4222-8222-222222222222<sep>Other<sep>jazz<sep>1\n"
                b"33333333-3333-4333-8333-333333333333<sep>Third<sep>pop<sep>2\n"
                b"44444444-4444-4444-8444-444444444444<sep>Fourth<sep>metal<sep>1\n"
                b"55555555-5555-4555-8555-555555555555<sep>Fifth<sep>folk<sep>2\n"
            )
            with tarfile.open(archive, "w:gz") as output:
                output.add(source_file, arcname="Lastfm-ArtistTags2007/ArtistTags.dat")
            archive_hash, _ = sha256_file(archive)
            with patch(
                "opennoise.evidence.lastfm_artist_genre_review._ARCHIVE_SHA256", archive_hash
            ):
                packet = build_lastfm_artist_genre_review(archive, sample_size=4)
        keys = {(row.musicbrainz_artist_id, row.source_tag) for row in packet.rows}
        self.assertEqual(len(keys), 4)

    def test_rejects_tampered_packet_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "source.tar.gz"
            source_file = root / "ArtistTags.dat"
            source_file.write_bytes(
                b"11111111-1111-4111-8111-111111111111<sep>Artist<sep>rock<sep>1\n"
                b"22222222-2222-4222-8222-222222222222<sep>Other<sep>jazz<sep>2\n"
            )
            with tarfile.open(archive, "w:gz") as output:
                output.add(source_file, arcname="Lastfm-ArtistTags2007/ArtistTags.dat")
            archive_hash, _ = sha256_file(archive)
            with patch(
                "opennoise.evidence.lastfm_artist_genre_review._ARCHIVE_SHA256", archive_hash
            ):
                packet = build_lastfm_artist_genre_review(archive, sample_size=2)
        tampered = packet.model_dump()
        tampered["output_sha256"] = "0" * _SHA256_LENGTH
        with (
            patch("opennoise.evidence.lastfm_artist_genre_review._ARCHIVE_SHA256", archive_hash),
            self.assertRaisesRegex(ValueError, "output hash"),
        ):
            LastFmReviewPacket.model_validate(tampered)
