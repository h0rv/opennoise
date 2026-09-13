import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

import httpx
from pydantic import HttpUrl, ValidationError

from opennoise.catalog.artists import ArtistProjector, _genre_slug
from opennoise.catalog.registry import ProjectorRegistry
from opennoise.clients.downloads import download_verified
from opennoise.models.pipeline import SourceLimits
from opennoise.models.sources import DownloadSource
from opennoise.pipeline.manifest import load_download_source
from opennoise.pipeline.runner import (
    DeterministicPartition,
    PipelineOptions,
    run_source_pipeline,
)
from opennoise.sources.musicbrainz import MusicBrainzArtistDumpAdapter
from opennoise.sources.registry import AdapterRegistry
from tests._test_client import PollingIsolatedAsyncioTestCase

ROOT = Path(__file__).resolve().parents[1]


def _add_member(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    archive.addfile(info, io.BytesIO(payload))


def _artist_line() -> bytes:
    return json.dumps(
        {
            "id": "30238ead-59fa-41e2-a7ab-b7f6e6363c4b",
            "name": "Blue Guy",
            "sort-name": "Guy, Blue",
            "type": "Person",
            "disambiguation": "fixture artist",
            "life-span": {"begin": "1981-02-03", "end": None},
            "aliases": [{"name": "The Blue Guy", "locale": "en"}],
            "genres": [
                {
                    "id": "2f8f4ab6-5f11-4c1c-b3a9-17f0ef4d9cb9",
                    "name": "Electric blues",
                    "count": 4,
                },
                {
                    "id": "0c9d31a7-66ef-4b80-8b71-18b33dcce554",
                    "name": "Ignored negative tag",
                    "count": -1,
                },
            ],
            "tags": [
                {"name": "micro-genre", "count": 3},
                {"name": "zero tag", "count": 0},
                {"name": "negative tag", "count": -1},
            ],
            "isnis": ["0000000121032683"],
            "ipis": ["00123456789"],
        },
        separators=(",", ":"),
    ).encode()


def _archive(
    path: Path,
    *,
    malformed: bool = False,
    oversized: bool = False,
    schema: str = "1",
) -> None:
    records = _artist_line() + b"\n"
    if oversized:
        records = b'{"oversized":"' + (b"x" * 2048) + b'"}\n' + records
    if malformed:
        records += b'{"id":false}\n'
    with tarfile.open(path, "w:xz") as archive:
        _add_member(archive, "mbdump/artist", records)
        _add_member(archive, "JSON_DUMPS_SCHEMA_NUMBER", f"{schema}\n".encode())


def _source(path: Path) -> DownloadSource:
    payload = path.read_bytes()
    return DownloadSource(
        id="musicbrainz_fixture",
        adapter="musicbrainz_artist_json_dump_v1",
        snapshot="fixture-1",
        url=HttpUrl("https://example.test/artist.tar.xz"),
        discovery_url=HttpUrl("https://musicbrainz.org/"),
        expected_content_type="application/octet-stream",
        compression="tar.xz",
        expected_bytes=len(payload),
        checksum_algorithm="sha256",
        checksum=hashlib.sha256(payload).hexdigest(),
        data_license="fixture CC0",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        rights_classification="public_domain",
        local_only=False,
        normalize=True,
        local_search=True,
        display=True,
        embed=True,
        train=True,
        export_metadata=True,
    )


class DownloadTests(PollingIsolatedAsyncioTestCase):
    def test_source_id_rejects_filesystem_separators_traversal_and_controls(self) -> None:
        source = load_download_source(
            ROOT / "config" / "data_sources.toml",
            "musicbrainz_json_artist_20260829",
        )
        for invalid in (
            "../escape",
            "nested/source",
            r"nested\source",
            ".",
            "..",
            "bad\nsource",
            "bad\x00source",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                DownloadSource.model_validate({**source.model_dump(), "id": invalid})

    async def test_musicbrainz_genres_keep_the_restrictive_supplementary_policy(self) -> None:
        public_source = load_download_source(
            ROOT / "config" / "data_sources.toml",
            "musicbrainz_json_artist_20260829",
        )
        research_source = load_download_source(
            ROOT / "config" / "data_sources.toml",
            "musicbrainz_json_artist_research_20260829",
        )

        self.assertEqual(public_source.rights_classification, "restricted_research")
        self.assertIn("CC-BY-NC-SA-3.0", public_source.data_license)
        self.assertFalse(public_source.embed)
        self.assertFalse(public_source.train)
        self.assertFalse(public_source.export_metadata)
        self.assertTrue(research_source.local_only)
        self.assertTrue(research_source.embed)
        self.assertTrue(research_source.train)
        self.assertFalse(research_source.export_metadata)
        self.assertEqual(research_source.checksum, public_source.checksum)

    async def test_restarts_an_empty_partial_left_by_a_failed_stream(self) -> None:
        payload = b"verified source bytes"
        digest = hashlib.sha256(payload).hexdigest()
        source = DownloadSource(
            id="fixture",
            adapter="fixture_v1",
            snapshot="1",
            url=HttpUrl("https://example.test/source.bin"),
            discovery_url=HttpUrl("https://example.test/"),
            expected_content_type="application/octet-stream",
            compression="none",
            expected_bytes=len(payload),
            checksum_algorithm="sha256",
            checksum=digest,
            data_license="CC0",
            license_url="https://creativecommons.org/publicdomain/zero/1.0/",
            rights_classification="public_domain",
            local_only=False,
            normalize=True,
            local_search=True,
            display=True,
            embed=True,
            train=True,
            export_metadata=True,
        )

        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=payload,
                headers={"Content-Type": "application/octet-stream"},
            )

        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory)
            partial = vault / "downloads" / f"{source.id}.{digest}.part"
            partial.parent.mkdir(parents=True)
            partial.touch()
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                result = await download_verified(source, vault, client=client)

            self.assertEqual(result.path.read_bytes(), payload)
            self.assertEqual(result.resumed_from, 0)

    async def test_resumes_and_verifies_into_content_addressed_vault(self) -> None:
        payload = b"verified source bytes"
        digest = hashlib.sha256(payload).hexdigest()
        source = DownloadSource(
            id="fixture",
            adapter="fixture_v1",
            snapshot="1",
            url=HttpUrl("https://example.test/source.bin"),
            discovery_url=HttpUrl("https://example.test/"),
            expected_content_type="application/octet-stream",
            compression="none",
            expected_bytes=len(payload),
            checksum_algorithm="sha256",
            checksum=digest,
            data_license="CC0",
            license_url="https://creativecommons.org/publicdomain/zero/1.0/",
            rights_classification="public_domain",
            local_only=False,
            normalize=True,
            local_search=True,
            display=True,
            embed=True,
            train=True,
            export_metadata=True,
        )
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            offset = int(request.headers["range"].removeprefix("bytes=").removesuffix("-"))
            return httpx.Response(
                206,
                content=payload[offset:],
                headers={
                    "Content-Type": "application/octet-stream",
                    "Content-Range": f"bytes {offset}-{len(payload) - 1}/{len(payload)}",
                },
            )

        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory)
            partial = vault / "downloads" / f"{source.id}.{digest}.part"
            partial.parent.mkdir(parents=True)
            partial.write_bytes(payload[:8])
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                result = await download_verified(source, vault, client=client)

            self.assertEqual(result.path.read_bytes(), payload)
            self.assertEqual(result.resumed_from, 8)
            self.assertEqual(requests[0].headers["range"], "bytes=8-")


class SourcePipelineTests(PollingIsolatedAsyncioTestCase):
    def test_musicbrainz_tag_slugs_disambiguate_non_ascii_source_names(self) -> None:
        first = _genre_slug("tag:日本語", namespace="musicbrainz_tag")
        second = _genre_slug("tag:音楽", namespace="musicbrainz_tag")

        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("musicbrainz-tag-tag-"))

    async def test_oversized_record_does_not_desynchronize_following_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "artist.tar.xz"
            _archive(archive, oversized=True)
            source = _source(archive)
            vault = root / "vault"
            object_path = vault / "raw" / "sha256" / source.checksum
            object_path.parent.mkdir(parents=True)
            object_path.write_bytes(archive.read_bytes())
            options = PipelineOptions(
                manifest_path=root / "manifest.toml",
                source_id=source.id,
                database_path=root / "catalog.sqlite",
                vault_path=vault,
                partition=DeterministicPartition(sha256_prefix=""),
                limits=SourceLimits(max_record_bytes=1024),
            )

            summary = await run_source_pipeline(
                source,
                AdapterRegistry((MusicBrainzArtistDumpAdapter(),)),
                ProjectorRegistry((ArtistProjector(),)),
                options,
            )

            self.assertEqual(
                (summary.raw, summary.accepted, summary.quarantined),
                (2, 1, 1),
            )

    async def test_rolls_back_uncheckpointed_records_and_records_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "artist.tar.xz"
            _archive(archive, schema="unsupported")
            source = _source(archive)
            vault = root / "vault"
            object_path = vault / "raw" / "sha256" / source.checksum
            object_path.parent.mkdir(parents=True)
            object_path.write_bytes(archive.read_bytes())
            options = PipelineOptions(
                manifest_path=root / "manifest.toml",
                source_id=source.id,
                database_path=root / "catalog.sqlite",
                vault_path=vault,
                partition=DeterministicPartition(sha256_prefix=""),
                checkpoint_every=100,
            )

            with self.assertRaises(ValueError):
                await run_source_pipeline(
                    source,
                    AdapterRegistry((MusicBrainzArtistDumpAdapter(),)),
                    ProjectorRegistry((ArtistProjector(),)),
                    options,
                )

            with __import__("sqlite3").connect(options.database_path) as connection:
                staged = connection.execute("SELECT count(*) FROM staged_records").fetchone()
                failed = connection.execute(
                    """SELECT event_kind, error_code FROM ingest_attempt_events
                       ORDER BY id DESC LIMIT 1"""
                ).fetchone()
            self.assertEqual(staged, (0,))
            self.assertEqual(failed, ("failed", "MusicBrainzAdapterError"))

    async def test_ingests_common_artist_projection_and_reuses_complete_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "artist.tar.xz"
            _archive(archive, malformed=True)
            source = _source(archive)
            vault = root / "vault"
            object_path = vault / "raw" / "sha256" / source.checksum
            object_path.parent.mkdir(parents=True)
            object_path.write_bytes(archive.read_bytes())
            options = PipelineOptions(
                manifest_path=root / "manifest.toml",
                source_id=source.id,
                database_path=root / "catalog.sqlite",
                vault_path=vault,
                partition=DeterministicPartition(sha256_prefix=""),
                checkpoint_every=1,
            )
            registry = AdapterRegistry((MusicBrainzArtistDumpAdapter(),))

            projectors = ProjectorRegistry((ArtistProjector(),))
            summary = await run_source_pipeline(source, registry, projectors, options)
            reused = await run_source_pipeline(source, registry, projectors, options)

            self.assertEqual(
                (summary.raw, summary.selected, summary.accepted, summary.quarantined),
                (2, 1, 1, 1),
            )
            self.assertTrue(reused.reused_attempt)
            with __import__("sqlite3").connect(options.database_path) as connection:
                artist = connection.execute(
                    "SELECT artist_kind, disambiguation, begin_year FROM artists"
                ).fetchone()
                names = connection.execute(
                    "SELECT name_kind, name, language_tag FROM entity_names ORDER BY name_kind"
                ).fetchall()
                evidence = connection.execute(
                    """SELECT evidence.evidence_value, evidence.method_key,
                              evidence.parameter_manifest_json, policy.classification,
                              permission.decision
                       FROM artist_genre_evidence AS evidence
                       JOIN rights_policies AS policy ON policy.id = evidence.policy_id
                       JOIN rights_policy_permissions AS permission
                         ON permission.policy_id = evidence.policy_id
                        AND permission.use_kind = 'train'
                       ORDER BY evidence.id"""
                ).fetchall()
                source_objects = connection.execute(
                    "SELECT count(*) FROM source_objects"
                ).fetchone()

            self.assertEqual(artist, ("Person", "fixture artist", 1981))
            self.assertEqual(len(names), 5)
            self.assertEqual(len(evidence), 2)
            self.assertEqual(
                [(row[0], row[1]) for row in evidence],
                [(4.0, "musicbrainz_artist_genre"), (3.0, "musicbrainz_artist_tag")],
            )
            self.assertIn('"maximum_genres_per_artist":128', evidence[0][2])
            self.assertIn('"maximum_tags_per_artist":512', evidence[1][2])
            self.assertEqual(evidence[0][4], "allow")
            self.assertEqual(source_objects, (1,))


if __name__ == "__main__":
    unittest.main()
