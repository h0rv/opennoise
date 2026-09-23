from __future__ import annotations

import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import HttpUrl, ValidationError

from opennoise.ingest.musicbrainz.release_group_native_artist_support import (
    ReleaseGroupNativeArtistSupportReport,
    build_release_group_native_artist_support,
    verify_release_group_native_artist_support,
)
from opennoise.ingest.musicbrainz.release_group_native_observation import (
    ReleaseGroupNativeObservationSettings,
    build_release_group_native_observation,
)
from opennoise.ingest.musicbrainz.release_group_native_observation import (
    report_sha256 as native_report_sha256,
)
from opennoise.models.sources import DownloadSource
from opennoise.pipeline.source_cache import SourceCacheEntry, SourceCacheReceipt
from opennoise.storage import ObjectKey

if TYPE_CHECKING:
    from collections.abc import Mapping

_MANIFEST_SHA = "a" * 64


def _archive(path: Path, groups: tuple[Mapping[str, object], ...]) -> None:
    payload = b"".join(
        json.dumps(group, separators=(",", ":")).encode() + b"\n" for group in groups
    )
    with tarfile.open(path, "w:xz") as archive:
        schema = b"1\n"
        schema_member = tarfile.TarInfo("JSON_DUMPS_SCHEMA_NUMBER")
        schema_member.size = len(schema)
        archive.addfile(schema_member, io.BytesIO(schema))
        member = tarfile.TarInfo("mbdump/release-group")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))


def _source(path: Path) -> DownloadSource:
    payload = path.read_bytes()
    return DownloadSource(
        id="fixture_release_group",
        adapter="musicbrainz_release_group_json_dump_v1",
        snapshot="fixture",
        url=HttpUrl("https://example.test/release-group.tar.xz"),
        discovery_url=HttpUrl("https://musicbrainz.org/"),
        expected_content_type="application/octet-stream",
        compression="tar.xz",
        expected_bytes=len(payload),
        checksum_algorithm="sha256",
        checksum=hashlib.sha256(payload).hexdigest(),
        data_license="fixture",
        license_url="https://musicbrainz.org/",
        rights_classification="restricted_research",
        local_only=True,
        normalize=True,
        local_search=True,
        display=True,
        embed=True,
        train=True,
        export_metadata=False,
    )


def _receipt(source: DownloadSource) -> SourceCacheReceipt:
    return SourceCacheReceipt(
        declared_manifest_sha256=_MANIFEST_SHA,
        entries=(
            SourceCacheEntry(
                source_id=source.id,
                adapter=source.adapter,
                snapshot=source.snapshot,
                original_url=str(source.url),
                discovery_url=str(source.discovery_url),
                expected_content_type=source.expected_content_type,
                expected_bytes=source.expected_bytes,
                sha256=source.verified_sha256(),
                data_license=source.data_license,
                license_url=source.license_url,
                rights_classification=source.rights_classification,
                local_only=True,
                portable_object_store_eligible=False,
                object_key=ObjectKey(value=f"source-artifacts/sha256/{source.verified_sha256()}"),
            ),
        ),
    )


class ReleaseGroupNativeArtistSupportTests(unittest.TestCase):
    def test_retains_album_facts_and_emits_only_credited_artist_support(self) -> None:
        artist_one = "00000000-0000-4000-8000-000000000001"
        artist_two = "00000000-0000-4000-8000-000000000002"
        genre = "00000000-0000-4000-8000-000000000010"
        groups = (
            {
                "id": "00000000-0000-4000-8000-000000000100",
                "title": "Credited album",
                "primary-type": "Album",
                "first-release-date": "2001-02-03",
                "artist-credit": [
                    {
                        "artist": {"id": artist_one, "name": "One"},
                        "name": "One",
                        "joinphrase": " & ",
                    },
                    {"artist": {"id": artist_two, "name": "Two"}, "name": "Two"},
                ],
                "genres": [
                    {"id": genre, "name": "Rejected Rock", "count": -7},
                    {
                        "id": "00000000-0000-4000-8000-000000000011",
                        "name": "Rock",
                        "count": 7,
                    },
                ],
            },
            {
                "id": "00000000-0000-4000-8000-000000000101",
                "title": "Uncredited album",
                "genres": [{"id": genre, "name": "Rock", "count": 3}],
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "release-group.tar.xz"
            _archive(archive, groups)
            source = _source(archive)
            receipt = _receipt(source)
            native = build_release_group_native_observation(
                archive,
                source,
                receipt,
                _MANIFEST_SHA,
                ReleaseGroupNativeObservationSettings(sample_size=2),
            )
            report = build_release_group_native_artist_support(
                archive, source, receipt, _MANIFEST_SHA, native
            )
        first = report.release_group_facts[0]
        self.assertEqual(first.title, "Credited album")
        self.assertEqual(first.primary_type, "Album")
        self.assertEqual(first.first_release_date, "2001-02-03")
        self.assertEqual(first.proper_genres[0].genre_mbid, genre)
        self.assertEqual(first.proper_genres[0].vote_count, -7)
        self.assertEqual(
            [item.artist_mbid for item in first.artist_credit], [artist_one, artist_two]
        )
        self.assertEqual(
            [(item.artist_mbid, item.credit_position) for item in report.support],
            [(artist_one, 0), (artist_two, 1)],
        )
        self.assertEqual(
            {item.genre_mbid for item in report.support}, {"00000000-0000-4000-8000-000000000011"}
        )
        self.assertFalse(report.artist_membership_propagation_allowed)
        self.assertEqual(report.coverage.groups_without_exact_artist_credit_abstained, 1)
        self.assertEqual(report.coverage.credited_artist_genre_support_count, 2)
        verify_release_group_native_artist_support(report)

    def test_rejects_support_that_is_not_the_exact_album_credit_cross_product(self) -> None:
        payload = {
            "native_observation_report_sha256": "a" * 64,
            "source_archive_sha256": "b" * 64,
            "source_archive_bytes": 1,
            "source_cache_receipt_sha256": "c" * 64,
            "release_group_facts": (),
            "support": (
                {
                    "artist_mbid": "00000000-0000-4000-8000-000000000001",
                    "credit_position": 0,
                    "release_group_mbid": "00000000-0000-4000-8000-000000000100",
                    "genre_mbid": "00000000-0000-4000-8000-000000000010",
                    "record_content_sha256": "d" * 64,
                },
            ),
            "coverage": {
                "sampled_release_group_count": 0,
                "groups_with_native_proper_genres": 0,
                "groups_with_positive_native_proper_genres": 0,
                "groups_with_exact_artist_credits": 0,
                "groups_with_positive_genres_and_credits": 0,
                "groups_without_exact_artist_credit_abstained": 0,
                "groups_without_positive_native_genre_abstained": 0,
                "multi_artist_credit_group_count": 0,
                "native_genre_observation_count": 0,
                "credited_artist_genre_support_count": 1,
            },
            "output_sha256": "e" * 64,
        }
        with self.assertRaisesRegex(ValidationError, "credited release-group genre cross product"):
            ReleaseGroupNativeArtistSupportReport.model_validate(payload)

    def test_rejects_an_inserted_valid_record_before_the_native_sample(self) -> None:
        groups = (
            {"id": "00000000-0000-4000-8000-000000000100", "title": "First"},
            {"id": "00000000-0000-4000-8000-000000000101", "title": "Expected"},
        )
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "release-group.tar.xz"
            _archive(archive, groups)
            source = _source(archive)
            receipt = _receipt(source)
            native = build_release_group_native_observation(
                archive,
                source,
                receipt,
                _MANIFEST_SHA,
                ReleaseGroupNativeObservationSettings(sample_size=2),
            )
            expected_second = native.samples[1]
            forged = native.model_copy(
                update={
                    "samples": (expected_second,),
                    "counters": native.counters.model_copy(
                        update={
                            "sampled_records": 1,
                            "sampled_release_groups_with_proper_genres": 0,
                            "proper_genre_observation_count": 0,
                            "positive_tag_observation_count": 0,
                        }
                    ),
                    "sampled_member_content_sha256": hashlib.sha256(
                        json.dumps(
                            [
                                (
                                    expected_second.record_content_sha256,
                                    expected_second.record_byte_length,
                                )
                            ],
                            separators=(",", ":"),
                        ).encode()
                    ).hexdigest(),
                    "sampled_record_receipts_sha256": hashlib.sha256(
                        json.dumps(
                            [expected_second.model_dump(mode="json")],
                            separators=(",", ":"),
                            sort_keys=True,
                        ).encode()
                    ).hexdigest(),
                    "output_sha256": "0" * 64,
                }
            )
            forged = forged.model_copy(update={"output_sha256": native_report_sha256(forged)})
            with self.assertRaisesRegex(
                ValueError, "archive valid-record order differs from native receipt"
            ):
                build_release_group_native_artist_support(
                    archive, source, receipt, _MANIFEST_SHA, forged
                )
