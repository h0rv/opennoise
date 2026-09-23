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
from opennoise.ingest.musicbrainz.release_group_native_census import (
    ReleaseGroupNativeCensusError,
    _seed_sets,
    build_release_group_native_census,
)
from opennoise.models.sources import DownloadSource
from opennoise.pipeline.source_cache import SourceCacheEntry, SourceCacheReceipt
from opennoise.storage import ObjectKey


def _archive(path: Path, rows: tuple[dict[str, object], ...]) -> None:
    payload = b"".join(json.dumps(row).encode() + b"\n" for row in rows)
    with tarfile.open(path, "w:xz") as archive:
        schema = b"1\n"
        member = tarfile.TarInfo("JSON_DUMPS_SCHEMA_NUMBER")
        member.size = len(schema)
        archive.addfile(member, io.BytesIO(schema))
        member = tarfile.TarInfo("mbdump/release-group")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))


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
                license_url=source.license_url,
                rights_classification=source.rights_classification,
                local_only=True,
                portable_object_store_eligible=False,
                object_key=ObjectKey(value=f"source-artifacts/sha256/{source.verified_sha256()}"),
            ),
        ),
    )


class ReleaseGroupNativeCensusTests(unittest.TestCase):
    def test_aggregates_signed_votes_without_retaining_raw_artist_or_release_identities(
        self,
    ) -> None:
        group_id = "00000000-0000-4000-8000-000000000100"
        artist_id = "00000000-0000-4000-8000-000000000001"
        genre_id = "00000000-0000-4000-8000-000000000010"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "archive.tar.xz"
            _archive(
                archive,
                (
                    {
                        "id": group_id,
                        "title": "private title",
                        "artist-credit": [
                            {"artist": {"id": artist_id, "name": "Artist"}, "name": "Artist"}
                        ],
                        "genres": [
                            {"id": genre_id, "name": "Rock", "count": 2},
                            {
                                "id": "00000000-0000-4000-8000-000000000011",
                                "name": "Noise",
                                "count": -1,
                            },
                        ],
                    },
                ),
            )
            reconciliation = root / "reconciliation.json"
            layout = root / "layout.json"
            reconciliation.write_text(
                json.dumps(
                    {"dispositions": [{"source_item_id": "item1", "normalized_name": "rock"}]}
                )
            )
            layout.write_text(json.dumps({"unplaced": [{"seed_id": "item1"}]}))
            source = _source(archive)
            with (
                patch("opennoise.ingest.musicbrainz.release_group_native_census._SEED_COUNT", 1),
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
                report = build_release_group_native_census(
                    archive, source, _receipt(source), "a" * 64, reconciliation, layout
                )
        self.assertEqual(report.proper_genre_observation_count, 2)
        self.assertEqual(report.exact_normalized_seed_overlap_count, 1)
        self.assertEqual(report.exact_normalized_unplaced_seed_overlap_count, 1)
        self.assertEqual(
            report.genre_rows[0].positive_vote_count + report.genre_rows[1].negative_vote_count, 2
        )
        serialized = report.model_dump_json()
        self.assertNotIn(group_id, serialized)
        self.assertNotIn(artist_id, serialized)
        self.assertNotIn("private title", serialized)

    def test_rejects_same_count_seed_input_with_wrong_pinned_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reconciliation = root / "reconciliation.json"
            layout = root / "layout.json"
            reconciliation.write_text(
                json.dumps(
                    {"dispositions": [{"source_item_id": "item1", "normalized_name": "altered"}]}
                )
            )
            layout.write_text(json.dumps({"unplaced": [{"seed_id": "item1"}]}))
            with (
                patch("opennoise.ingest.musicbrainz.release_group_native_census._SEED_COUNT", 1),
                patch(
                    "opennoise.ingest.musicbrainz.release_group_native_census._UNPLACED_COUNT", 1
                ),
                self.assertRaisesRegex(ReleaseGroupNativeCensusError, "reconciliation bytes"),
            ):
                _seed_sets(reconciliation, layout)

    def test_create_only_writer_refuses_different_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "report.json"
            write_local_report_once(cache_root=root, output=output, payload=b"one\n")
            with self.assertRaises(EntityGenreObservationError):
                write_local_report_once(cache_root=root, output=output, payload=b"two\n")
