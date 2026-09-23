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

from opennoise.ingest.musicbrainz.entity_genre_observation import (
    EntityGenreObservationError,
    write_local_report_once,
)
from opennoise.ingest.musicbrainz.release_group_tag_census import (
    ReleaseGroupTagCensusError,
    build_release_group_tag_census,
    report_sha256,
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


class ReleaseGroupTagCensusTests(unittest.TestCase):
    def test_aggregates_signed_duplicate_exact_seed_tags_without_entity_identities(self) -> None:
        release_group_id = "00000000-0000-4000-8000-000000000100"
        artist_id = "00000000-0000-4000-8000-000000000001"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "archive.tar.xz"
            _archive(
                archive,
                (
                    {
                        "id": release_group_id,
                        "title": "private title",
                        "artist-credit": [
                            {"artist": {"id": artist_id, "name": "Artist"}, "name": "Artist"}
                        ],
                        "tags": [
                            {"name": "Rock", "count": 2},
                            {"name": "rock", "count": 0},
                            {"name": "rock", "count": -1},
                            {"name": "rock", "count": None},
                            {"name": "private nonseed tag", "count": 8},
                        ],
                    },
                ),
            )
            reconciliation = root / "reconciliation.json"
            layout = root / "layout.json"
            reconciliation.write_text(
                json.dumps(
                    {
                        "dispositions": [
                            {"source_item_id": "item1", "normalized_name": "rock"},
                            {"source_item_id": "item2", "normalized_name": "jazz"},
                        ]
                    }
                )
            )
            layout.write_text(json.dumps({"unplaced": [{"seed_id": "item1"}]}))
            source = _source(archive)
            with (
                patch("opennoise.ingest.musicbrainz.release_group_native_census._SEED_COUNT", 2),
                patch(
                    "opennoise.ingest.musicbrainz.release_group_native_census._UNPLACED_COUNT", 1
                ),
                patch(
                    "opennoise.ingest.musicbrainz.release_group_native_census._RECONCILIATION_SHA256",
                    hashlib.sha256(reconciliation.read_bytes()).hexdigest(),
                ),
                patch(
                    "opennoise.ingest.musicbrainz.release_group_native_census._LAYOUT_SHA256",
                    hashlib.sha256(layout.read_bytes()).hexdigest(),
                ),
            ):
                report = build_release_group_tag_census(
                    archive, source, _receipt(source), "a" * 64, reconciliation, layout
                )
        self.assertEqual(report.raw_records_seen, 1)
        self.assertEqual(report.parsed_release_group_count, 1)
        self.assertEqual(report.all_tag_vote_totals.observation_count, 5)
        self.assertEqual(report.exact_seed_tag_vote_totals.observation_count, 4)
        self.assertEqual(report.exact_seed_tag_vote_totals.positive_vote_count, 1)
        self.assertEqual(report.exact_seed_tag_vote_totals.zero_vote_count, 1)
        self.assertEqual(report.exact_seed_tag_vote_totals.negative_vote_count, 1)
        self.assertEqual(report.exact_seed_tag_vote_totals.missing_vote_count, 1)
        self.assertEqual(report.exact_normalized_seed_overlap_count, 1)
        self.assertEqual(report.exact_normalized_unplaced_seed_overlap_count, 1)
        self.assertEqual(
            tuple(row.matching_name_count for row in report.seed_positive_vote_support_bins),
            (1, 0, 0, 0),
        )
        self.assertEqual(report.output_sha256, report_sha256(report))
        replayed = type(report).model_validate_json(report.model_dump_json())
        self.assertEqual(replayed.output_sha256, report_sha256(replayed))
        forged = report.model_copy(update={"raw_records_seen": report.raw_records_seen + 1})
        with self.assertRaisesRegex(ValueError, "raw record counts do not reconcile"):
            type(report).model_validate_json(forged.model_dump_json())
        serialized = report.model_dump_json()
        self.assertNotIn(release_group_id, serialized)
        self.assertNotIn(artist_id, serialized)
        self.assertNotIn("private title", serialized)
        self.assertNotIn("private nonseed tag", serialized)

    def test_create_only_report_writer_refuses_a_different_existing_tag_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "musicbrainz-release-group-tag-census-v1" / "report.json"
            write_local_report_once(cache_root=root, output=output, payload=b"one\n")
            with self.assertRaises(EntityGenreObservationError):
                write_local_report_once(cache_root=root, output=output, payload=b"two\n")

    def test_rejects_seed_inputs_with_same_counts_but_wrong_pinned_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reconciliation = root / "reconciliation.json"
            layout = root / "layout.json"
            reconciliation.write_text(
                json.dumps(
                    {"dispositions": [{"source_item_id": "item1", "normalized_name": "changed"}]}
                )
            )
            layout.write_text(json.dumps({"unplaced": [{"seed_id": "item1"}]}))
            archive = root / "archive.tar.xz"
            _archive(archive, ())
            source = _source(archive)
            with (
                patch("opennoise.ingest.musicbrainz.release_group_native_census._SEED_COUNT", 1),
                patch(
                    "opennoise.ingest.musicbrainz.release_group_native_census._UNPLACED_COUNT", 1
                ),
                self.assertRaisesRegex(ReleaseGroupTagCensusError, "pinned seed scope"),
            ):
                build_release_group_tag_census(
                    archive, source, _receipt(source), "a" * 64, reconciliation, layout
                )
