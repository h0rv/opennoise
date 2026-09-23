from __future__ import annotations

import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from opennoise.common import sha256_file
from opennoise.evidence.lastfm_artisttags2007_seed_candidates import (
    build_lastfm_artisttags2007_literal_seed_candidates,
    compare_lastfm_artisttags2007_candidates_to_public_map,
)


class LastFmArtistTags2007SeedCandidateTests(unittest.TestCase):
    def test_builds_literal_candidates_and_preserves_raw_tag_count_abstentions(self) -> None:
        with (
            self._inputs() as (archive, vocabulary, public_map, archive_sha256),
            patch(
                "opennoise.evidence.lastfm_artisttags2007_seed_candidates._ARCHIVE_SHA256",
                archive_sha256,
            ),
            patch(
                "opennoise.evidence.lastfm_artisttags2007_seed_candidates._SEED_VOCABULARY_SHA256",
                sha256_file(vocabulary)[0],
            ),
        ):
            artifact = build_lastfm_artisttags2007_literal_seed_candidates(archive, vocabulary)
            with patch(
                "opennoise.evidence.lastfm_artisttags2007_seed_candidates.PublicStaticDiscoveryV2Payload.model_validate_json",
                return_value=_public_map_payload(),
            ):
                comparison = compare_lastfm_artisttags2007_candidates_to_public_map(
                    artifact, public_map
                )
        self.assertEqual(artifact.parse_coverage.total_row_count, 5)
        self.assertEqual(artifact.parse_coverage.literal_candidate_row_count, 1)
        self.assertEqual(artifact.parse_coverage.literal_unmatched_row_count, 1)
        self.assertEqual(artifact.parse_coverage.ambiguous_seed_name_row_count, 1)
        self.assertEqual(artifact.candidates[0].source_tag, "rock")
        self.assertEqual(artifact.candidates[0].source_count, 7)
        self.assertEqual(
            {row.reason for row in artifact.abstentions},
            {"no_exact_seed_name", "ambiguous_exact_seed_name"},
        )
        self.assertEqual(comparison.candidate_pair_count, 1)
        self.assertEqual(comparison.exact_literal_pair_overlap_count, 1)
        self.assertTrue(comparison.public_map_read_after_candidate_build)

    def test_rejects_nonliteral_case_variant(self) -> None:
        with (
            self._inputs(
                rows=(b"11111111-1111-4111-8111-111111111111<sep>Artist<sep>Rock<sep>7\n",)
            ) as (archive, vocabulary, _public_map, archive_sha256),
            patch(
                "opennoise.evidence.lastfm_artisttags2007_seed_candidates._ARCHIVE_SHA256",
                archive_sha256,
            ),
            patch(
                "opennoise.evidence.lastfm_artisttags2007_seed_candidates._SEED_VOCABULARY_SHA256",
                sha256_file(vocabulary)[0],
            ),
        ):
            artifact = build_lastfm_artisttags2007_literal_seed_candidates(archive, vocabulary)
        self.assertEqual(artifact.parse_coverage.literal_candidate_row_count, 0)
        self.assertEqual(artifact.abstentions[0].source_tag, "Rock")

    def test_excludes_duplicate_artist_tag_rows_from_candidate_support(self) -> None:
        row = b"11111111-1111-4111-8111-111111111111<sep>Artist<sep>rock<sep>7\n"
        with (
            self._inputs(rows=(row, row)) as (archive, vocabulary, _public_map, archive_sha256),
            patch(
                "opennoise.evidence.lastfm_artisttags2007_seed_candidates._ARCHIVE_SHA256",
                archive_sha256,
            ),
            patch(
                "opennoise.evidence.lastfm_artisttags2007_seed_candidates._SEED_VOCABULARY_SHA256",
                sha256_file(vocabulary)[0],
            ),
        ):
            artifact = build_lastfm_artisttags2007_literal_seed_candidates(archive, vocabulary)
        self.assertEqual(artifact.parse_coverage.duplicate_artist_tag_row_count, 1)
        self.assertEqual(len(artifact.candidates), 1)
        self.assertEqual(artifact.abstentions[0].reason, "duplicate_artist_tag")

    def test_rejects_a_swapped_same_shape_seed_vocabulary(self) -> None:
        with self._inputs() as (archive, vocabulary, _public_map, archive_sha256):
            replacement = vocabulary.with_name("swapped-seed-reconciliation.json")
            replacement.write_text(
                vocabulary.read_text(encoding="utf-8").replace('"seed 4"', '"swapped seed"', 1),
                encoding="utf-8",
            )
            with (
                patch(
                    "opennoise.evidence.lastfm_artisttags2007_seed_candidates._ARCHIVE_SHA256",
                    archive_sha256,
                ),
                patch(
                    "opennoise.evidence.lastfm_artisttags2007_seed_candidates._SEED_VOCABULARY_SHA256",
                    sha256_file(vocabulary)[0],
                ),
                self.assertRaisesRegex(ValueError, "seed vocabulary hash"),
            ):
                build_lastfm_artisttags2007_literal_seed_candidates(archive, replacement)

    @staticmethod
    def _inputs(
        rows: tuple[bytes, ...] | None = None,
    ) -> _SourceInputs:
        return _SourceInputs(rows)


class _SourceInputs:
    def __init__(self, rows: tuple[bytes, ...] | None) -> None:
        self._rows = rows or (
            b"11111111-1111-4111-8111-111111111111<sep>Artist<sep>rock<sep>7\n",
            b"11111111-1111-4111-8111-111111111111<sep>Artist<sep>Rock<sep>7\n",
            b"22222222-2222-4222-8222-222222222222<sep>Other<sep>dup<sep>3\n",
            b"broken\n",
            b"33333333-3333-4333-8333-333333333333<sep>Third<sep>jazz<sep>0\n",
        )
        self._directory: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> tuple[Path, Path, Path, str]:
        self._directory = tempfile.TemporaryDirectory()
        root = Path(self._directory.name)
        source = root / "ArtistTags.dat"
        archive = root / "source.tar.gz"
        vocabulary = root / "seed-reconciliation.json"
        public_map = root / "public-map.json"
        source.write_bytes(b"".join(self._rows))
        with tarfile.open(archive, "w:gz") as output:
            output.add(source, arcname="Lastfm-ArtistTags2007/ArtistTags.dat")
        vocabulary.write_text(json.dumps(_vocabulary()), encoding="utf-8")
        public_map.write_text(json.dumps(_public_map()), encoding="utf-8")
        archive_sha256, _ = sha256_file(archive)
        return archive, vocabulary, public_map, archive_sha256

    def __exit__(self, *unused: object) -> None:
        assert self._directory is not None
        self._directory.cleanup()


def _vocabulary() -> dict[str, object]:
    dispositions = [
        {"source_item_id": "item1", "seed_name": "rock"},
        {"source_item_id": "item2", "seed_name": "dup"},
        {"source_item_id": "item3", "seed_name": "dup"},
    ]
    dispositions.extend(
        {"source_item_id": f"item{index}", "seed_name": f"seed {index}"} for index in range(4, 6292)
    )
    return {"revision": "seed-reconciliation-v3", "dispositions": dispositions}


def _public_map() -> dict[str, object]:
    return {
        "revision": "static-direct-discovery-v1",
        "availability": "ready",
        "artists": [
            {
                "artist_id": "artist:1",
                "name": "Artist",
                "musicbrainz_url": "https://musicbrainz.org/artist/11111111-1111-4111-8111-111111111111",
                "memberships": [
                    {
                        "node_id": "item1",
                        "catalog_genre_id": 1,
                        "catalog_genre_name": "rock",
                        "binding": "exact_casefolded_label",
                        "evidence": [],
                    }
                ],
                "shared_genre_artists": [],
            }
        ],
    }


def _public_map_payload() -> SimpleNamespace:
    membership = SimpleNamespace(node_id="item1")
    artist = SimpleNamespace(
        musicbrainz_url="https://musicbrainz.org/artist/11111111-1111-4111-8111-111111111111",
        memberships=(membership,),
    )
    return SimpleNamespace(artists=(artist,))
