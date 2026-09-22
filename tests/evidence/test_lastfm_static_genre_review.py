from __future__ import annotations

import hashlib
import tarfile
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import patch

from opennoise.common import sha256_file
from opennoise.evidence.lastfm_static_genre_review import build_lastfm_static_genre_review

if TYPE_CHECKING:
    from collections.abc import Generator


class LastFmStaticGenreReviewTests(unittest.TestCase):
    def test_emits_deterministic_literal_candidates_as_unreviewed_abstentions(self) -> None:
        with (
            self._source(
                b"11111111-1111-4111-8111-111111111111<sep>Artist<sep>rock<sep>7\n"
                b"22222222-2222-4222-8222-222222222222<sep>Other<sep>Rock<sep>9\n"
            ) as (archive, static, archive_hash, static_hash),
            self._patched_static(archive_hash, static_hash),
        ):
            first = build_lastfm_static_genre_review(archive, static, sample_size=1)
            second = build_lastfm_static_genre_review(archive, static, sample_size=1)
        self.assertEqual(first, second)
        self.assertEqual(first.literal_candidate_pair_count, 1)
        row = first.rows[0]
        self.assertEqual(row.musicbrainz_artist_id, "11111111-1111-4111-8111-111111111111")
        self.assertEqual(row.source_tag, "rock")
        self.assertEqual(row.catalog_genre_id, 7)
        self.assertEqual(row.review_state, "unreviewed_abstain")
        self.assertIsNone(row.reviewer_artist_genre_member)
        self.assertTrue(row.question_id.startswith("lastfm2007-static-v2:"))
        self.assertEqual(row.source_row_sha256, hashlib.sha256(self._rock_row()).hexdigest())
        self.assertFalse(first.automatic_tag_to_genre_approval)
        self.assertFalse(first.negative_labels_present)
        self.assertFalse(first.predictions_read)

    def test_rejects_nonliteral_tag_without_creating_a_question(self) -> None:
        with (
            self._source(b"22222222-2222-4222-8222-222222222222<sep>Other<sep>Rock<sep>9\n") as (
                archive,
                static,
                archive_hash,
                static_hash,
            ),
            self._patched_static(archive_hash, static_hash),
            self.assertRaisesRegex(ValueError, "not enough literal"),
        ):
            build_lastfm_static_genre_review(archive, static, sample_size=1)

    def test_excludes_duplicate_artist_tag_questions(self) -> None:
        with (
            self._source(
                self._rock_row()
                + self._rock_row()
                + b"33333333-3333-4333-8333-833333333333<sep>Third<sep>jazz<sep>3\n"
            ) as (archive, static, archive_hash, static_hash),
            self._patched_static(archive_hash, static_hash),
        ):
            packet = build_lastfm_static_genre_review(archive, static, sample_size=2)
        self.assertEqual(packet.literal_candidate_pair_count, 2)
        self.assertEqual(
            len({(row.musicbrainz_artist_id, row.source_tag) for row in packet.rows}), 2
        )

    def test_rejects_unpinned_static_asset_before_reading_candidates(self) -> None:
        with (
            self._source(self._rock_row()) as (archive, static, archive_hash, _static_hash),
            patch("opennoise.evidence.lastfm_static_genre_review._ARCHIVE_SHA256", archive_hash),
            self.assertRaisesRegex(ValueError, "static discovery hash"),
        ):
            build_lastfm_static_genre_review(archive, static, sample_size=1)

    @staticmethod
    def _rock_row() -> bytes:
        return b"11111111-1111-4111-8111-111111111111<sep>Artist<sep>rock<sep>7\n"

    @staticmethod
    @contextmanager
    def _source(rows: bytes) -> Generator[tuple[Path, Path, str, str]]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "source.tar.gz"
            source = root / "ArtistTags.dat"
            static = root / "static.json"
            source.write_bytes(rows)
            static.write_bytes(b"static-v2-test")
            with tarfile.open(archive, "w:gz") as output:
                output.add(source, arcname="Lastfm-ArtistTags2007/ArtistTags.dat")
            archive_hash, _ = sha256_file(archive)
            static_hash, _ = sha256_file(static)
            yield archive, static, archive_hash, static_hash

    @staticmethod
    @contextmanager
    def _patched_static(archive_hash: str, static_hash: str) -> Generator[None]:
        genres = (
            SimpleNamespace(catalog_genre_name="rock", catalog_genre_id=7, node_id="item7"),
            SimpleNamespace(catalog_genre_name="jazz", catalog_genre_id=8, node_id="item8"),
        )
        payload = SimpleNamespace(
            revision="static-direct-discovery-v2",
            output_sha256="a" * 64,
            genres=genres,
            artists=(
                SimpleNamespace(
                    musicbrainz_url="https://musicbrainz.org/artist/11111111-1111-4111-8111-111111111111"
                ),
                SimpleNamespace(
                    musicbrainz_url="https://musicbrainz.org/artist/33333333-3333-4333-8333-833333333333"
                ),
            ),
        )
        with ExitStack() as patches:
            patches.enter_context(
                patch.multiple(
                    "opennoise.evidence.lastfm_static_genre_review",
                    _ARCHIVE_SHA256=archive_hash,
                    _STATIC_DISCOVERY_SHA256=static_hash,
                )
            )
            patches.enter_context(
                patch(
                    "opennoise.evidence.lastfm_static_genre_review.PublicStaticDiscoveryV2Payload.model_validate_json",
                    return_value=payload,
                )
            )
            patches.enter_context(
                patch(
                    "opennoise.evidence.lastfm_static_genre_review.public_static_discovery_v2_sha256",
                    return_value="a" * 64,
                )
            )
            yield
