from __future__ import annotations

import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import HttpUrl

from opennoise.ingest.musicbrainz.release_group_native_observation import (
    ReleaseGroupNativeObservationError,
    ReleaseGroupNativeObservationSettings,
    build_release_group_native_observation,
    verify_release_group_native_observation,
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
    entry = SourceCacheEntry(
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
    )
    return SourceCacheReceipt(declared_manifest_sha256=_MANIFEST_SHA, entries=(entry,))


class ReleaseGroupNativeObservationTests(unittest.TestCase):
    def test_retains_native_genre_identity_and_separate_positive_tags(self) -> None:
        group = {
            "id": "00000000-0000-4000-8000-000000000001",
            "title": "Fixture",
            "genres": [{"id": "00000000-0000-4000-8000-000000000010", "name": "Rock", "count": -2}],
            "tags": [
                {"name": "indie rock", "count": 3},
                {"name": "ignored zero", "count": 0},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "release-group.tar.xz"
            _archive(archive, (group,))
            source = _source(archive)
            report = build_release_group_native_observation(
                archive,
                source,
                _receipt(source),
                _MANIFEST_SHA,
                ReleaseGroupNativeObservationSettings(sample_size=1),
            )
        sample = report.samples[0]
        self.assertEqual(sample.release_group_mbid, group["id"])
        self.assertEqual(sample.proper_genres[0].genre_mbid, group["genres"][0]["id"])
        self.assertEqual(sample.proper_genres[0].name, "Rock")
        self.assertEqual(sample.proper_genres[0].vote_count, -2)
        self.assertEqual(
            [(tag.name, tag.vote_count) for tag in sample.positive_tags], [("indie rock", 3)]
        )
        self.assertEqual(report.counters.proper_genre_observation_count, 1)
        self.assertEqual(report.counters.positive_tag_observation_count, 1)
        self.assertEqual(report.counters.sampled_release_groups_with_proper_genres, 1)
        verify_release_group_native_observation(report)

    def test_rejects_archive_that_no_longer_matches_its_receipt(self) -> None:
        group = {"id": "00000000-0000-4000-8000-000000000001", "title": "Fixture"}
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "release-group.tar.xz"
            _archive(archive, (group,))
            source = _source(archive)
            archive.write_bytes(b"changed")
            with self.assertRaisesRegex(ReleaseGroupNativeObservationError, "archive bytes"):
                build_release_group_native_observation(
                    archive, source, _receipt(source), _MANIFEST_SHA
                )
