import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

import httpx
from pydantic import HttpUrl

from musix.catalog.artists import ArtistProjector
from musix.catalog.registry import ProjectorRegistry
from musix.clients.downloads import download_verified
from musix.models.sources import DownloadSource
from musix.pipeline.runner import (
    DeterministicPartition,
    PipelineOptions,
    run_source_pipeline,
)
from musix.sources.musicbrainz import MusicBrainzArtistDumpAdapter
from musix.sources.registry import AdapterRegistry


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
            "isnis": ["0000000121032683"],
            "ipis": ["00123456789"],
        },
        separators=(",", ":"),
    ).encode()


def _archive(path: Path, *, malformed: bool = False, schema: str = "1") -> None:
    records = _artist_line() + b"\n"
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


class DownloadTests(unittest.IsolatedAsyncioTestCase):
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


class SourcePipelineTests(unittest.IsolatedAsyncioTestCase):
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
                source_objects = connection.execute(
                    "SELECT count(*) FROM source_objects"
                ).fetchone()

            self.assertEqual(artist, ("Person", "fixture artist", 1981))
            self.assertEqual(len(names), 3)
            self.assertEqual(source_objects, (1,))


if __name__ == "__main__":
    unittest.main()
