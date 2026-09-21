import hashlib
import sqlite3
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import override
from unittest.mock import AsyncMock, patch

import httpx
from pydantic import HttpUrl, ValidationError

from opennoise.catalog.co_listens import ArtistCoListenProjector, ArtistCoListenRunProjector
from opennoise.catalog.registry import ProjectorRegistry
from opennoise.models.catalog import ArtistCoListenProjection, ArtistCoListenRunProjection
from opennoise.models.pipeline import ParsedSourceRecord, SourceLimits, SourceRecord
from opennoise.models.sources import DownloadResult, DownloadSource
from opennoise.pipeline.multi_source import (
    MultiArtifactOptions,
    run_multi_artifact_pipeline,
    run_multi_artifact_pipeline_from_verified_downloads,
)
from tests._test_client import PollingIsolatedAsyncioTestCase


class _Adapter:
    key = "joint-fixture"
    version = "1"

    def supports(self, source: DownloadSource) -> bool:
        return source.adapter == self.key

    def iter_records(
        self, path: Path, limits: SourceLimits, *, start_after: int
    ) -> Iterator[SourceRecord]:
        raise AssertionError((path, limits, start_after))


def _source(index: int, payload: bytes) -> DownloadSource:
    digest = hashlib.sha256(payload).hexdigest()
    return DownloadSource(
        id=f"listenbrainz_fixture_{index}",
        adapter="joint-fixture",
        snapshot=f"fixture-{index}",
        url=HttpUrl(f"https://example.test/{index}.json"),
        discovery_url=HttpUrl("https://example.test/"),
        expected_content_type="application/json",
        compression="none",
        expected_bytes=len(payload),
        checksum_algorithm="sha256",
        checksum=digest,
        data_license="CC0-1.0",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        rights_classification="public_domain",
        local_only=False,
        normalize=True,
        local_search=False,
        display=False,
        embed=True,
        train=True,
        export_metadata=True,
    )


def _record(
    projection: ArtistCoListenProjection | ArtistCoListenRunProjection, ordinal: int
) -> ParsedSourceRecord:
    payload = projection.model_dump_json().encode()
    return ParsedSourceRecord(
        ordinal=ordinal,
        exact_sha256=hashlib.sha256(payload).hexdigest(),
        byte_length=len(payload),
        projection=projection,
    )


class MultiSourcePipelineTests(PollingIsolatedAsyncioTestCase):
    @override
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        payloads = (b'{"input":1}', b'{"input":2}')
        self.sources = tuple(_source(index, payload) for index, payload in enumerate(payloads))
        paths = tuple(self.root / f"input-{index}.json" for index in range(2))
        for path, payload in zip(paths, payloads, strict=True):
            path.write_bytes(payload)
        self.downloads = tuple(
            DownloadResult(
                path=path,
                sha256=source.checksum,
                byte_size=source.expected_bytes,
                resumed_from=0,
                reused=False,
            )
            for source, path in zip(self.sources, paths, strict=True)
        )
        self.options = MultiArtifactOptions(
            manifest_path=Path("fixture.toml"),
            database_path=self.root / "catalog.sqlite",
            vault_path=self.root / "vault",
            aggregate_source_id="listenbrainz_joint_fixture",
            configuration_sha256="c" * 64,
            limits=SourceLimits(max_archive_bytes=1024, max_records=100),
        )

    @override
    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _records(_downloads: tuple[DownloadResult, ...]) -> Iterator[SourceRecord]:
        yield _record(
            ArtistCoListenProjection(
                external_id="pair",
                left_artist_source_id="musicbrainz:artist:11111111-1111-4111-8111-111111111111",
                right_artist_source_id="musicbrainz:artist:22222222-2222-4222-8222-222222222222",
                window_start=1_787_443_200,
                window_end=1_787_529_600,
                distinct_user_count=5,
            ),
            0,
        )
        yield _record(
            ArtistCoListenRunProjection(
                external_id="run",
                adapter_key="joint-fixture",
                adapter_version="1",
                adapter_build_sha256="a" * 64,
                aggregation_version="joint-v1",
                configuration_sha256="c" * 64,
                window_seconds=86_400,
                minimum_distinct_users=5,
                listens_seen=10,
                listens_with_artist_mbid=10,
                distinct_artists=2,
                user_windows=5,
                candidate_pairs=1,
                emitted_pairs=1,
                quarantined_records=0,
                minimum_listened_at=1_787_443_200,
                maximum_listened_at=1_787_443_201,
                elapsed_ms=1,
                peak_rss_bytes=1,
            ),
            1,
        )

    def test_aggregate_source_id_is_a_safe_filesystem_token(self) -> None:
        payload = self.options.model_dump()
        for invalid in (
            "../escape",
            "nested/source",
            r"nested\source",
            ".",
            "..",
            "bad\tsource",
            "bad\x00source",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                MultiArtifactOptions.model_validate({**payload, "aggregate_source_id": invalid})

    async def test_atomic_lineage_and_exact_replay(self) -> None:
        projectors = ProjectorRegistry((ArtistCoListenProjector(), ArtistCoListenRunProjector()))
        downloader = AsyncMock(side_effect=(*self.downloads, *self.downloads))
        with patch("opennoise.pipeline.multi_source.download_verified", downloader):
            first = await run_multi_artifact_pipeline(
                self.sources, _Adapter(), projectors, self._records, self.options
            )
            second = await run_multi_artifact_pipeline(
                self.sources, _Adapter(), projectors, self._records, self.options
            )

        self.assertFalse(first.reused_attempt)
        self.assertTrue(second.reused_attempt)
        self.assertEqual(first.accepted, 2)
        with sqlite3.connect(self.options.database_path) as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) FROM data_sources").fetchone(), (3,)
            )
            self.assertEqual(
                connection.execute("SELECT count(*) FROM artist_co_listen_evidence").fetchone(),
                (1,),
            )
            self.assertEqual(
                connection.execute("SELECT count(*) FROM derived_outputs").fetchone(), (1,)
            )
            self.assertEqual(
                connection.execute("SELECT count(*) FROM derivation_edges").fetchone(), (2,)
            )

    async def test_failure_rolls_back_all_catalog_writes(self) -> None:
        def failed(downloads: tuple[DownloadResult, ...]) -> Iterator[SourceRecord]:
            yield from self._records(downloads)
            raise RuntimeError("fixture failure")

        downloader = AsyncMock(side_effect=self.downloads)
        with (
            patch("opennoise.pipeline.multi_source.download_verified", downloader),
            self.assertRaisesRegex(RuntimeError, "fixture failure"),
        ):
            await run_multi_artifact_pipeline(
                self.sources,
                _Adapter(),
                ProjectorRegistry((ArtistCoListenProjector(), ArtistCoListenRunProjector())),
                failed,
                self.options,
            )
        with sqlite3.connect(self.options.database_path) as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) FROM data_sources").fetchone(), (0,)
            )
            self.assertEqual(
                connection.execute("SELECT count(*) FROM artist_co_listen_evidence").fetchone(),
                (0,),
            )

    async def test_transient_server_error_retries_download(self) -> None:
        request = httpx.Request("GET", str(self.sources[0].url))
        response = httpx.Response(503, request=request)
        downloader = AsyncMock(
            side_effect=(
                httpx.HTTPStatusError("unavailable", request=request, response=response),
                self.downloads[1],
                self.downloads[0],
            )
        )
        with (
            patch("opennoise.pipeline.multi_source.download_verified", downloader),
            patch("opennoise.pipeline.multi_source.asyncio.sleep", new=AsyncMock()) as sleep,
        ):
            result = await run_multi_artifact_pipeline(
                self.sources,
                _Adapter(),
                ProjectorRegistry((ArtistCoListenProjector(), ArtistCoListenRunProjector())),
                self._records,
                self.options,
            )

        self.assertEqual(result.accepted, 2)
        self.assertEqual(downloader.await_count, 3)
        sleep.assert_awaited_once_with(1)

    async def test_verified_download_replay_rejects_same_size_tampering_before_records(
        self,
    ) -> None:
        """A caller cannot forge a verified descriptor around altered local bytes."""
        self.downloads[0].path.write_bytes(b'{"input":9}')

        def records(_: tuple[DownloadResult, ...]) -> Iterator[SourceRecord]:
            raise AssertionError("record factory must not run after hash mismatch")

        with self.assertRaisesRegex(ValueError, "bytes do not match source"):
            await run_multi_artifact_pipeline_from_verified_downloads(
                self.sources,
                self.downloads,
                _Adapter(),
                ProjectorRegistry((ArtistCoListenProjector(), ArtistCoListenRunProjector())),
                records,
                self.options,
            )
        self.assertFalse(self.options.database_path.exists())
