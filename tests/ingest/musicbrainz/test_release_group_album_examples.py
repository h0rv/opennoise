"""Fixture coverage for local-only release-group Album example candidates."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import HttpUrl

from opennoise.ingest.musicbrainz.release_group_album_examples import (
    ReleaseGroupAlbumExamplesError,
    build_release_group_album_examples,
    report_sha256,
    verify_release_group_album_examples,
)
from opennoise.models.sources import DownloadSource
from opennoise.pipeline.source_cache import SourceCacheEntry, SourceCacheReceipt
from opennoise.storage import ObjectKey


def _archive(path: Path, rows: tuple[dict[str, object], ...]) -> None:
    payload = b"".join(json.dumps(row).encode() + b"\n" for row in rows)
    with tarfile.open(path, "w:xz") as archive:
        schema = b"1\n"
        schema_member = tarfile.TarInfo("JSON_DUMPS_SCHEMA_NUMBER")
        schema_member.size = len(schema)
        archive.addfile(schema_member, io.BytesIO(schema))
        record_member = tarfile.TarInfo("mbdump/release-group")
        record_member.size = len(payload)
        archive.addfile(record_member, io.BytesIO(payload))


def _source(path: Path) -> DownloadSource:
    raw = path.read_bytes()
    return DownloadSource(
        id="fixture",
        adapter="musicbrainz_release_group_json_dump_v1",
        snapshot="fixture",
        url=HttpUrl("https://example.test/a.tar.xz"),
        discovery_url=HttpUrl("https://example.test/"),
        expected_content_type="application/octet-stream",
        compression="tar.xz",
        expected_bytes=len(raw),
        checksum_algorithm="sha256",
        checksum=hashlib.sha256(raw).hexdigest(),
        data_license="fixture",
        license_url="https://example.test/",
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
        declared_manifest_sha256="a" * 64,
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
                license_url=str(source.license_url),
                rights_classification=source.rights_classification,
                local_only=True,
                portable_object_store_eligible=False,
                object_key=ObjectKey(value=f"source-artifacts/sha256/{source.verified_sha256()}"),
            ),
        ),
    )


class ReleaseGroupAlbumExamplesTests(unittest.TestCase):
    def test_retains_exact_positive_album_contexts_in_vote_then_mbid_order(self) -> None:
        artist_one = "00000000-0000-4000-8000-000000000001"
        artist_two = "00000000-0000-4000-8000-000000000002"
        rock = "00000000-0000-4000-8000-000000000010"
        jazz = "00000000-0000-4000-8000-000000000011"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "archive.tar.xz"
            _archive(
                archive,
                (
                    {
                        "id": "00000000-0000-4000-8000-000000000103",
                        "title": "third",
                        "primary-type": "Album",
                        "secondary-types": ["Compilation"],
                        "first-release-date": "2003-01-02",
                        "artist-credit": [
                            {"artist": {"id": artist_one, "name": "One"}, "name": "One"},
                            {"artist": {"id": artist_two, "name": "Two"}, "name": "Two"},
                        ],
                        "genres": [{"id": rock, "name": "Rock", "count": 4}],
                    },
                    {
                        "id": "00000000-0000-4000-8000-000000000102",
                        "title": "second",
                        "primary-type": "Album",
                        "genres": [
                            {"id": rock, "name": "rock", "count": 4},
                            {
                                "id": "00000000-0000-4000-8000-000000000012",
                                "name": "ROCK",
                                "count": 4,
                            },
                            {"id": jazz, "name": "Jazz", "count": 2},
                        ],
                    },
                    {
                        "id": "00000000-0000-4000-8000-000000000101",
                        "title": "first",
                        "primary-type": "Album",
                        "genres": [{"id": rock, "name": "ROCK", "count": 5}],
                    },
                    {
                        "id": "00000000-0000-4000-8000-000000000104",
                        "title": "not an album",
                        "primary-type": "EP",
                        "genres": [{"id": rock, "name": "Rock", "count": 99}],
                    },
                    {
                        "id": "00000000-0000-4000-8000-000000000105",
                        "title": "signed votes ignored",
                        "primary-type": "Album",
                        "genres": [
                            {"id": rock, "name": "Rock", "count": 0},
                            {"id": rock, "name": "Rock", "count": -1},
                        ],
                    },
                    {
                        "id": "00000000-0000-4000-8000-000000000106",
                        "title": "nonexact name ignored",
                        "primary-type": "Album",
                        "genres": [{"id": rock, "name": "Rock music", "count": 50}],
                    },
                    {
                        "id": "00000000-0000-4000-8000-000000000107",
                        "title": "over the retained limit",
                        "primary-type": "Album",
                        "genres": [{"id": rock, "name": "Rock", "count": 1}],
                    },
                ),
            )
            reconciliation = root / "reconciliation.json"
            reconciliation.write_text(
                json.dumps(
                    {
                        "dispositions": [
                            {"source_item_id": "seed-rock", "normalized_name": "rock"},
                            {"source_item_id": "seed-jazz", "normalized_name": "jazz"},
                        ]
                    }
                )
            )
            source = _source(archive)
            with (
                patch("opennoise.ingest.musicbrainz.release_group_album_examples._SEED_COUNT", 2),
                patch(
                    "opennoise.ingest.musicbrainz.release_group_album_examples._RECONCILIATION_SHA256",
                    hashlib.sha256(reconciliation.read_bytes()).hexdigest(),
                ),
            ):
                report = build_release_group_album_examples(
                    archive,
                    source,
                    _receipt(source),
                    "a" * 64,
                    reconciliation,
                    examples_per_seed_limit=3,
                )
        self.assertEqual(report.parsed_release_group_count, 7)
        self.assertEqual(report.album_release_group_count, 6)
        self.assertEqual(report.positive_native_proper_genre_observation_count, 7)
        self.assertEqual(report.exact_seed_positive_observation_count, 6)
        self.assertEqual(
            tuple(row.normalized_seed_name for row in report.seed_rows), ("jazz", "rock")
        )
        rock_examples = report.seed_rows[1].examples
        self.assertEqual(
            tuple(item.release_group_mbid for item in rock_examples),
            (
                "00000000-0000-4000-8000-000000000101",
                "00000000-0000-4000-8000-000000000102",
                "00000000-0000-4000-8000-000000000103",
            ),
        )
        self.assertEqual(rock_examples[1].secondary_types, ())
        self.assertEqual(rock_examples[1].genre_mbid, rock)
        jazz_example = report.seed_rows[0].examples[0]
        self.assertEqual(jazz_example.credited_artist_mbids, ())
        compilation = rock_examples[2]
        self.assertEqual(compilation.secondary_types, ("Compilation",))
        self.assertEqual(report.output_sha256, report_sha256(report))
        verify_release_group_album_examples(report)
        forged = report.model_copy(update={"raw_records_seen": report.raw_records_seen + 1})
        with self.assertRaisesRegex(ReleaseGroupAlbumExamplesError, "schema"):
            verify_release_group_album_examples(forged)
        serialized = report.model_dump_json()
        self.assertIn('"artist_membership_asserted":false', serialized)

    def test_rejects_duplicate_normalized_seed_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "archive.tar.xz"
            _archive(archive, ())
            reconciliation = root / "reconciliation.json"
            reconciliation.write_text(
                json.dumps(
                    {
                        "dispositions": [
                            {"source_item_id": "one", "normalized_name": "rock"},
                            {"source_item_id": "two", "normalized_name": "Rock"},
                        ]
                    }
                )
            )
            source = _source(archive)
            with (
                patch("opennoise.ingest.musicbrainz.release_group_album_examples._SEED_COUNT", 2),
                patch(
                    "opennoise.ingest.musicbrainz.release_group_album_examples._RECONCILIATION_SHA256",
                    hashlib.sha256(reconciliation.read_bytes()).hexdigest(),
                ),
                self.assertRaisesRegex(ReleaseGroupAlbumExamplesError, "duplicate normalized"),
            ):
                build_release_group_album_examples(
                    archive, source, _receipt(source), "a" * 64, reconciliation
                )
