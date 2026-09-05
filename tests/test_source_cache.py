import hashlib
import tempfile
from pathlib import Path

import httpx
from pydantic import HttpUrl

from musix.models.sources import DownloadSource
from musix.pipeline.manifest import source_acquisition_status
from musix.pipeline.source_cache import (
    SourceCacheAcquisition,
    SourceCacheEntry,
    SourceCacheError,
    SourceCacheLimits,
    SourceCacheReceipt,
    acquire_source_cache,
    load_source_cache_receipt,
    publish_source_cache_receipt,
    receipt_sha256,
    restore_source_cache,
    verify_source_cache_receipt,
)
from musix.storage import LocalObjectStore, ObjectKey
from tests._test_client import PollingIsolatedAsyncioTestCase

ROOT = Path(__file__).resolve().parents[1]


def _source(identifier: str, payload: bytes, *, portable: bool = True) -> DownloadSource:
    return DownloadSource(
        id=identifier,
        adapter="fixture_v1",
        snapshot="fixture-1",
        url=HttpUrl(f"https://example.test/{identifier}.json"),
        discovery_url=HttpUrl("https://example.test/"),
        expected_content_type="application/json; charset=utf-8",
        compression="none",
        expected_bytes=len(payload),
        checksum_algorithm="sha256",
        checksum=hashlib.sha256(payload).hexdigest(),
        data_license="CC0-1.0",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        rights_classification="public_domain",
        local_only=False,
        normalize=True,
        local_search=True,
        display=True,
        embed=True,
        train=True,
        export_metadata=True,
        export_raw=portable,
        redistribute=portable,
    )


class SourceCacheTests(PollingIsolatedAsyncioTestCase):
    async def test_acquire_publish_and_restore_are_exact_and_offline(self) -> None:
        payloads = {"alpha": b'{"alpha":1}', "beta": b'{"beta":2}'}
        sources = tuple(_source(identifier, payload) for identifier, payload in payloads.items())
        requests: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request.url.path)
            identifier = request.url.path.removesuffix(".json").removeprefix("/")
            return httpx.Response(
                200,
                content=payloads[identifier],
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = LocalObjectStore(root / "objects")
            manifest_sha = hashlib.sha256(b"fixture manifest").hexdigest()
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                receipt = await acquire_source_cache(
                    tuple(reversed(sources)),
                    acquisition=SourceCacheAcquisition(
                        declared_manifest_sha256=manifest_sha,
                        work_directory=root / "work",
                        limits=SourceCacheLimits(max_total_bytes=1024, max_concurrency=2),
                        storage_scope="portable_object_store",
                    ),
                    store=store,
                    client=client,
                )
                replay = await acquire_source_cache(
                    sources,
                    acquisition=SourceCacheAcquisition(
                        declared_manifest_sha256=manifest_sha,
                        work_directory=root / "work",
                        limits=SourceCacheLimits(max_total_bytes=1024, max_concurrency=2),
                        storage_scope="portable_object_store",
                    ),
                    store=store,
                    client=client,
                )

            self.assertEqual(requests, ["/alpha.json", "/beta.json"])
            self.assertEqual(receipt, replay)
            self.assertEqual(tuple(entry.source_id for entry in receipt.entries), ("alpha", "beta"))
            verify_source_cache_receipt(receipt, sources, declared_manifest_sha256=manifest_sha)
            publication = publish_source_cache_receipt(
                receipt, output=root / "receipt.json", store=store
            )
            self.assertEqual(publication.receipt_sha256, receipt_sha256(receipt))
            self.assertEqual(load_source_cache_receipt(root / "receipt.json"), receipt)

            restored = await restore_source_cache(
                receipt,
                destination_root=root / "fresh-vault",
                store=store,
                max_concurrency=2,
            )
            restored_replay = await restore_source_cache(
                receipt,
                destination_root=root / "fresh-vault",
                store=store,
                max_concurrency=2,
            )
            self.assertEqual(restored, restored_replay)
            for item in restored:
                self.assertEqual(item.destination.read_bytes(), payloads[item.source_id])

    async def test_restore_rejects_tampered_object_bytes(self) -> None:
        payload = b'{"alpha":1}'
        source = _source("alpha", payload)

        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=payload, headers={"Content-Type": "application/json"}
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = LocalObjectStore(root / "objects")
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                receipt = await acquire_source_cache(
                    (source,),
                    acquisition=SourceCacheAcquisition(
                        declared_manifest_sha256="a" * 64,
                        work_directory=root / "work",
                    ),
                    store=store,
                    client=client,
                )
            object_path = root / "objects" / "source-artifacts" / "sha256" / source.checksum
            object_path.write_bytes(b'{"bad":1}')
            with self.assertRaises(ExceptionGroup) as raised:
                await restore_source_cache(receipt, destination_root=root / "fresh", store=store)
            self.assertIsInstance(raised.exception.exceptions[0], SourceCacheError)

    async def test_local_only_raw_bytes_cannot_enter_portable_receipt_publication(self) -> None:
        payload = b'{"local":1}'
        source = _source("local", payload, portable=False)

        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=payload, headers={"Content-Type": "application/json"}
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = LocalObjectStore(root / "objects")
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                with self.assertRaisesRegex(SourceCacheError, "cannot receive"):
                    await acquire_source_cache(
                        (source,),
                        acquisition=SourceCacheAcquisition(
                            declared_manifest_sha256="d" * 64,
                            work_directory=root / "portable-work",
                            storage_scope="portable_object_store",
                        ),
                        store=store,
                        client=client,
                    )
                self.assertFalse((root / "objects" / "source-artifacts").exists())
                receipt = await acquire_source_cache(
                    (source,),
                    acquisition=SourceCacheAcquisition(
                        declared_manifest_sha256="d" * 64,
                        work_directory=root / "work",
                    ),
                    store=store,
                    client=client,
                )
            self.assertFalse(receipt.entries[0].portable_object_store_eligible)
            with self.assertRaisesRegex(SourceCacheError, "cannot be published"):
                publish_source_cache_receipt(receipt, output=root / "receipt.json", store=store)
            self.assertFalse((root / "objects" / "source-cache-receipts").exists())

    def test_receipt_fails_closed_for_manifest_omission_extra_or_change(self) -> None:
        alpha = _source("alpha", b'{"alpha":1}')
        beta = _source("beta", b'{"beta":2}')
        manifest_sha = "b" * 64
        with tempfile.TemporaryDirectory() as directory:
            receipt = load_source_cache_receipt(
                self._write_receipt(Path(directory), alpha, beta, manifest_sha)
            )
        with self.assertRaisesRegex(SourceCacheError, "different manifest"):
            verify_source_cache_receipt(receipt, (alpha, beta), declared_manifest_sha256="c" * 64)
        with self.assertRaisesRegex(SourceCacheError, "exactly match"):
            verify_source_cache_receipt(receipt, (alpha,), declared_manifest_sha256=manifest_sha)
        extra = _source("extra", b'{"extra":3}')
        with self.assertRaisesRegex(SourceCacheError, "exactly match"):
            verify_source_cache_receipt(
                receipt,
                (alpha, beta, extra),
                declared_manifest_sha256=manifest_sha,
            )

    @staticmethod
    def _write_receipt(
        root: Path, alpha: DownloadSource, beta: DownloadSource, manifest_sha: str
    ) -> Path:
        def entry(source: DownloadSource) -> SourceCacheEntry:
            return SourceCacheEntry(
                source_id=source.id,
                adapter=source.adapter,
                snapshot=source.snapshot,
                original_url=str(source.url),
                discovery_url=str(source.discovery_url),
                expected_content_type=source.expected_content_type,
                expected_bytes=source.expected_bytes,
                sha256=source.checksum,
                data_license=source.data_license,
                license_url=source.license_url,
                rights_classification=source.rights_classification,
                local_only=source.local_only,
                portable_object_store_eligible=True,
                object_key=ObjectKey(value=f"source-artifacts/sha256/{source.checksum}"),
            )

        receipt = SourceCacheReceipt(
            declared_manifest_sha256=manifest_sha,
            entries=(entry(alpha), entry(beta)),
        )
        path = root / "receipt.json"
        path.write_text(receipt.model_dump_json(), encoding="utf-8")
        return path

    def test_manifest_status_separates_network_and_operator_supplied_inputs(self) -> None:
        local = source_acquisition_status(
            ROOT / "config" / "data_sources.toml", "enao_quint_legacy_map_2025"
        )
        public = source_acquisition_status(
            ROOT / "config" / "data_sources.toml", "musicbrainz_postgres_core_20260829"
        )
        unpinned = source_acquisition_status(
            ROOT / "config" / "data_sources.toml", "enao_official_public_mirror"
        )
        self.assertEqual(local.state, "network_verifiable")
        self.assertTrue(local.network_acquirable)
        self.assertFalse(local.portable_object_store_eligible)
        self.assertEqual(public.state, "network_verifiable")
        self.assertTrue(public.portable_object_store_eligible)
        self.assertEqual(unpinned.state, "operator_supplied_unpinned")
