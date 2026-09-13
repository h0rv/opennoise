import hashlib
import io
import json
import sqlite3
import tarfile
import tempfile
import unittest
from pathlib import Path

from pydantic import HttpUrl

from opennoise.catalog.musicbrainz import RecordingProjector, ReleaseGroupProjector
from opennoise.catalog.registry import ProjectorRegistry
from opennoise.models.pipeline import SourceLimits
from opennoise.models.sources import DownloadSource
from opennoise.pipeline.manifest import load_download_source
from opennoise.pipeline.runner import DeterministicPartition, PipelineOptions, run_source_pipeline
from opennoise.sources.musicbrainz import (
    MusicBrainzRecordingDumpAdapter,
    MusicBrainzReleaseGroupDumpAdapter,
)
from opennoise.sources.registry import AdapterRegistry
from tests._test_client import PollingIsolatedAsyncioTestCase

ARTIST_ID = "30238ead-59fa-41e2-a7ab-b7f6e6363c4b"
GENRE_ID = "2f8f4ab6-5f11-4c1c-b3a9-17f0ef4d9cb9"


def _archive(path: Path, member: str, record: dict[str, object]) -> None:
    payload = json.dumps(record, separators=(",", ":")).encode() + b"\n"
    with tarfile.open(path, "w:xz") as archive:
        item = tarfile.TarInfo(f"mbdump/{member}")
        item.size = len(payload)
        archive.addfile(item, io.BytesIO(payload))
        schema = b"1\n"
        schema_item = tarfile.TarInfo("JSON_DUMPS_SCHEMA_NUMBER")
        schema_item.size = len(schema)
        archive.addfile(schema_item, io.BytesIO(schema))


def _source(path: Path, *, source_id: str, adapter: str) -> DownloadSource:
    payload = path.read_bytes()
    return DownloadSource(
        id=source_id,
        adapter=adapter,
        snapshot="fixture",
        url=HttpUrl(f"https://example.test/{source_id}.tar.xz"),
        discovery_url=HttpUrl("https://musicbrainz.org/"),
        expected_content_type="application/octet-stream",
        compression="tar.xz",
        expected_bytes=len(payload),
        checksum_algorithm="sha256",
        checksum=hashlib.sha256(payload).hexdigest(),
        data_license="mixed fixture",
        license_url="https://musicbrainz.org/doc/About/Data_License",
        rights_classification="restricted_research",
        local_only=True,
        normalize=True,
        local_search=True,
        display=True,
        embed=True,
        train=True,
        export_metadata=False,
    )


def _options(root: Path, source: DownloadSource) -> PipelineOptions:
    object_path = root / "vault" / "raw" / "sha256" / source.checksum
    object_path.parent.mkdir(parents=True, exist_ok=True)
    return PipelineOptions(
        manifest_path=root / "manifest.toml",
        source_id=source.id,
        database_path=root / "catalog.sqlite",
        vault_path=root / "vault",
        partition=DeterministicPartition(sha256_prefix=""),
        limits=SourceLimits(max_archive_bytes=10_000_000, max_record_bytes=100_000),
        checkpoint_every=1,
    )


class MusicBrainzCatalogPipelineTests(PollingIsolatedAsyncioTestCase):
    def test_real_manifests_pin_metadata_only_research_archives(self) -> None:
        manifest = Path(__file__).resolve().parents[1] / "config" / "data_sources.toml"
        release_groups = load_download_source(
            manifest, "musicbrainz_json_release_group_research_20260829"
        )
        recordings = load_download_source(manifest, "musicbrainz_json_recording_research_20260829")
        self.assertEqual(release_groups.expected_bytes, 1_187_679_180)
        self.assertEqual(recordings.expected_bytes, 33_572_648)
        for source in (release_groups, recordings):
            self.assertEqual(source.content_kind, "metadata")
            self.assertTrue(source.local_only)
            self.assertTrue(source.embed)
            self.assertFalse(source.export_metadata)

    def test_current_release_group_manifest_pin_is_official_and_metadata_only(self) -> None:
        manifest = Path(__file__).resolve().parents[1] / "config" / "data_sources.toml"
        source = load_download_source(manifest, "musicbrainz_json_release_group_research_20260905")
        self.assertEqual(source.snapshot, "20260905-001001")
        self.assertEqual(source.expected_bytes, 1_159_485_640)
        self.assertEqual(
            source.checksum,
            "6f153846228dc6034b2f8f43b472b088792cc2e242b09783a8968fa8d4bd7a43",
        )
        self.assertTrue(source.local_only)
        self.assertFalse(source.export_raw)

    async def test_ingests_release_group_and_recording_without_media_fields(self) -> None:
        credit = [
            {
                "artist": {"id": ARTIST_ID, "name": "Blue Guy"},
                "name": "Blue Guy feat.",
                "joinphrase": " & ",
            }
        ]
        genres = [{"id": GENRE_ID, "name": "Electric blues", "count": 4}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            group_archive = root / "release-group.tar.xz"
            _archive(
                group_archive,
                "release-group",
                {
                    "id": "6b2a8b9e-6a3d-4de3-bf6d-282f349cd51a",
                    "title": "Synthetic Album",
                    "primary-type": "Album",
                    "secondary-types": ["Compilation"],
                    "first-release-date": "2025-04-03",
                    "artist-credit": credit,
                    "genres": genres,
                    "cover-art-archive": {"artwork": True},
                },
            )
            recording_archive = root / "recording.tar.xz"
            _archive(
                recording_archive,
                "recording",
                {
                    "id": "5f68e6b3-f4df-45a3-a128-1e5bc2d2727e",
                    "title": "Synthetic Track",
                    "disambiguation": "studio version",
                    "first-release-date": "2025",
                    "artist-credit": credit,
                    "isrcs": ["USABC2500001"],
                    "genres": genres,
                    "length": 123456,
                    "video": False,
                },
            )
            group_source = _source(
                group_archive,
                source_id="musicbrainz_group_fixture",
                adapter="musicbrainz_release_group_json_dump_v1",
            )
            recording_source = _source(
                recording_archive,
                source_id="musicbrainz_recording_fixture",
                adapter="musicbrainz_recording_json_dump_v1",
            )
            group_object = root / "vault" / "raw" / "sha256" / group_source.checksum
            group_object.parent.mkdir(parents=True, exist_ok=True)
            group_object.write_bytes(group_archive.read_bytes())
            recording_object = root / "vault" / "raw" / "sha256" / recording_source.checksum
            recording_object.write_bytes(recording_archive.read_bytes())
            projectors = ProjectorRegistry((ReleaseGroupProjector(), RecordingProjector()))
            group_summary = await run_source_pipeline(
                group_source,
                AdapterRegistry((MusicBrainzReleaseGroupDumpAdapter(),)),
                projectors,
                _options(root, group_source),
            )
            recording_summary = await run_source_pipeline(
                recording_source,
                AdapterRegistry((MusicBrainzRecordingDumpAdapter(),)),
                projectors,
                _options(root, recording_source),
            )
            replay_group = await run_source_pipeline(
                group_source,
                AdapterRegistry((MusicBrainzReleaseGroupDumpAdapter(),)),
                projectors,
                _options(root, group_source),
            )
            replay_recording = await run_source_pipeline(
                recording_source,
                AdapterRegistry((MusicBrainzRecordingDumpAdapter(),)),
                projectors,
                _options(root, recording_source),
            )

            with sqlite3.connect(root / "catalog.sqlite") as connection:
                counts = connection.execute(
                    """SELECT
                         (SELECT count(*) FROM release_groups),
                         (SELECT count(*) FROM recordings),
                         (SELECT count(*) FROM artists),
                         (SELECT count(*) FROM artist_credit_members),
                         (SELECT count(*) FROM album_genre_membership_observations),
                         (SELECT count(*) FROM recording_genre_membership_observations)"""
                ).fetchone()
                identifiers = connection.execute(
                    """SELECT type.type_key, identifier.normalized_value
                       FROM entity_identifiers AS identifier
                       JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
                       ORDER BY type.type_key"""
                ).fetchall()
                staged = " ".join(
                    str(row[0])
                    for row in connection.execute("SELECT parsed_json FROM staged_records")
                )
            self.assertEqual(group_summary.accepted, 1)
            self.assertEqual(recording_summary.accepted, 1)
            self.assertTrue(replay_group.reused_attempt)
            self.assertTrue(replay_recording.reused_attempt)
            self.assertEqual(counts, (1, 1, 1, 1, 1, 1))
            self.assertIn(("isrc", "USABC2500001"), identifiers)
            self.assertIn(("musicbrainz_artist_id", ARTIST_ID), identifiers)
            self.assertNotIn("length", staged)
            self.assertNotIn("video", staged)
            self.assertNotIn("cover-art", staged)
            self.assertNotIn("preview", staged)


if __name__ == "__main__":
    unittest.main()
