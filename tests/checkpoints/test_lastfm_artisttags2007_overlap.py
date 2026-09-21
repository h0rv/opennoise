import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opennoise.checkpoints.lastfm_artisttags2007_overlap import (
    build_lastfm_artisttags2007_static_overlap,
    verify_lastfm_artisttags2007_static_overlap,
)
from opennoise.common import sha256_file
from opennoise.deployment.static_discovery import (
    StaticDiscoveryArtistPayload,
    StaticDiscoveryEvidencePayload,
    StaticDiscoveryMembershipPayload,
    StaticDiscoveryPayload,
)

_MBID = "11111111-1111-1111-1111-111111111111"


class LastFmArtistTags2007OverlapTests(unittest.TestCase):
    def test_reports_parse_rejects_and_positive_only_heldout_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "source.tar.gz"
            _write_archive(
                archive,
                "\n".join(
                    (
                        f"{_MBID}<sep>Artist<sep>rock<sep>10",
                        f"{_MBID}<sep>Artist<sep>rock<sep>9",
                        f"{_MBID}<sep>Artist<sep>jazz<sep>0",
                        "broken row",
                    )
                )
                + "\n",
            )
            static = root / "static-discovery.json"
            static.write_text(_static_payload().model_dump_json(), encoding="utf-8")
            archive_sha256, _ = sha256_file(archive)

            with patch(
                "opennoise.checkpoints.lastfm_artisttags2007_overlap._ARCHIVE_SHA256",
                archive_sha256,
            ):
                report = build_lastfm_artisttags2007_static_overlap(archive, static)
                verify_lastfm_artisttags2007_static_overlap(report)

        self.assertEqual(report.parse_coverage.total_row_count, 4)
        self.assertEqual(report.parse_coverage.accepted_positive_row_count, 1)
        self.assertEqual(report.parse_coverage.duplicate_artist_tag_row_count, 1)
        self.assertEqual(report.parse_coverage.nonpositive_count_row_count, 1)
        self.assertEqual(report.parse_coverage.malformed_row_count, 1)
        self.assertFalse(report.missing_source_tags_are_negatives)
        self.assertFalse(report.archive_used_for_training)
        self.assertFalse(report.public_output_mutated)

    def test_rejects_an_archive_with_the_wrong_pinned_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "source.tar.gz"
            _write_archive(archive, f"{_MBID}<sep>Artist<sep>rock<sep>10\n")
            static = root / "static-discovery.json"
            static.write_text(_static_payload().model_dump_json(), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "does not match the pinned source"):
                build_lastfm_artisttags2007_static_overlap(archive, static)


def _write_archive(path: Path, rows: str) -> None:
    member_path = path.parent / "ArtistTags.dat"
    member_path.write_text(rows, encoding="utf-8")
    with tarfile.open(path, "w:gz") as archive:
        archive.add(member_path, arcname="Lastfm-ArtistTags2007/ArtistTags.dat")


def _static_payload() -> StaticDiscoveryPayload:
    evidence = StaticDiscoveryEvidencePayload(
        evidence_id=1,
        source_key="fixture",
        source_record_id="fixture:1",
        method_key="fixture",
        method_version="v1",
        provenance_id=1,
    )
    membership = StaticDiscoveryMembershipPayload(
        node_id="node:rock",
        catalog_genre_id=1,
        catalog_genre_name="rock",
        binding="exact_casefolded_label",
        evidence=(evidence,),
    )
    return StaticDiscoveryPayload(
        revision="static-direct-discovery-v1",
        availability="ready",
        artists=(
            StaticDiscoveryArtistPayload(
                artist_id="artist:1",
                name="Artist",
                musicbrainz_url=f"https://musicbrainz.org/artist/{_MBID}",
                memberships=(membership,),
                shared_genre_artists=(),
            ),
        ),
    )
