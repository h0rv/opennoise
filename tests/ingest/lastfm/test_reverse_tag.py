from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from musix.ingest.lastfm.reverse_tag import (
    LastFmHttpClient,
    LastFmResponseCache,
    LastFmReverseTagAdapter,
    LastFmReverseTagArtifact,
    LastFmReverseTagError,
    LastFmReverseTagSettings,
    ReverseTagAdapterRegistry,
    _tag_query,
    publish_lastfm_reverse_tag_evidence,
    verify_lastfm_reverse_tag_artifact,
    write_lastfm_query_manifest,
)
from musix.storage import LocalObjectStore
from musix.taxonomy.seeds.reconciliation import (
    SeedReconciliationArtifact,
    SeedReconciliationCoverage,
    SeedReconciliationDisposition,
)
from scripts.build_lastfm_reverse_tag_evidence import _run
from tests._test_client import PollingIsolatedAsyncioTestCase


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _reconciliation() -> SeedReconciliationArtifact:
    rows = (
        SeedReconciliationDisposition(
            source_item_id="ambient",
            source_external_id="eno:ambient",
            seed_name="Ambient",
            normalized_name="ambient",
            disposition="unresolved",
            reason="fixture unresolved",
        ),
        SeedReconciliationDisposition(
            source_item_id="proto-rock",
            source_external_id="eno:proto-rock",
            seed_name="Proto Rock",
            normalized_name="proto rock",
            disposition="review_only",
            review_identity_names=("proto rock candidate",),
            reason="fixture review",
        ),
    )
    identity = _sha(
        [
            {
                "source_item_id": row.source_item_id,
                "source_external_id": row.source_external_id,
                "name": row.seed_name,
            }
            for row in rows
        ]
    )
    preliminary = SeedReconciliationArtifact(
        seed_input_sha256="a" * 64,
        seed_source_id="fixture",
        seed_source_content_sha256="b" * 64,
        seed_identity_sha256=identity,
        taxonomy_artifact_sha256="c" * 64,
        input_sha256="d" * 64,
        seed_count=len(rows),
        dispositions=rows,
        coverage=SeedReconciliationCoverage(
            seed_count=len(rows),
            reconciled_count=0,
            public_only_count=0,
            musicbrainz_only_count=0,
            review_only_count=1,
            ambiguous_count=0,
            unresolved_count=1,
            public_identity_count=0,
            musicbrainz_identity_count=0,
            musicbrainz_genre_identity_count=0,
            musicbrainz_tag_identity_count=0,
            collision_seed_count=0,
        ),
        output_sha256="0" * 64,
    )
    output_sha256 = _sha(preliminary.model_dump(mode="json", exclude={"output_sha256"}))
    return preliminary.model_copy(update={"output_sha256": output_sha256})


class LastFmReverseTagAdapterTests(PollingIsolatedAsyncioTestCase):
    async def test_collects_only_mbid_linked_exact_claims_and_publishes_raw_responses(self) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            method = request.url.params["method"]
            if method == "tag.getTopArtists" and request.url.params["tag"] == "Proto Rock":
                return httpx.Response(
                    200,
                    json={
                        "topartists": {
                            "artist": [
                                {
                                    "name": "MBID artist",
                                    "mbid": "11111111-1111-1111-1111-111111111111",
                                },
                                {"name": "Name only", "mbid": ""},
                            ]
                        }
                    },
                )
            if method == "tag.getTopArtists":
                return httpx.Response(
                    200,
                    json={
                        "topartists": {
                            "artist": [
                                {
                                    "name": "Other artist",
                                    "mbid": "22222222-2222-2222-2222-222222222222",
                                }
                            ]
                        }
                    },
                )
            if request.url.params["mbid"] == "11111111-1111-1111-1111-111111111111":
                return httpx.Response(
                    200,
                    json={"toptags": {"tag": [{"name": "proto rock"}, {"name": "rock"}]}},
                )
            return httpx.Response(200, json={"toptags": {"tag": [{"name": "drone"}]}})

        adapter = LastFmReverseTagAdapter()
        settings = LastFmReverseTagSettings(
            top_artists_per_tag=2,
            maximum_concurrency=2,
            requests_per_second=10.0,
            retries=0,
        )
        manifest = adapter.build_query_manifest(_reconciliation(), settings)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
                collection = await adapter.collect(
                    manifest,
                    LastFmHttpClient(
                        api_key="fixture-key",
                        cache=LastFmResponseCache(root / "cache"),
                        settings=settings,
                        client=http_client,
                    ),
                )
            manifest_path = root / "queries.json"
            write_lastfm_query_manifest(manifest, manifest_path)
            receipt = publish_lastfm_reverse_tag_evidence(
                collection,
                query_manifest_path=manifest_path,
                output_path=root / "artifact.json",
                store=LocalObjectStore(root / "objects"),
            )
            artifact = LastFmReverseTagArtifact.model_validate_json(
                (root / "artifact.json").read_bytes()
            )
            artifact_sha256 = hashlib.sha256((root / "artifact.json").read_bytes()).hexdigest()

        self.assertEqual(len(requests), 4)
        self.assertTrue(all("api_key" in request.url.params for request in requests))
        self.assertTrue(
            all(
                request.url.params["method"] != "artist.getTopTags"
                or "artist" not in request.url.params
                for request in requests
            )
        )
        self.assertEqual(collection.coverage.exact_mbid_claim_count, 1)
        self.assertEqual(collection.coverage.name_only_review_count, 1)
        self.assertEqual(collection.coverage.abstention_count, 1)
        self.assertEqual(
            collection.exact_claims[0].artist_mbid,
            "11111111-1111-1111-1111-111111111111",
        )
        self.assertEqual(collection.name_only_reviews[0].artist_name, "Name only")
        self.assertEqual(receipt.artifact.sha256, artifact_sha256)
        self.assertEqual(len(receipt.raw_responses), 4)
        self.assertTrue(verify_lastfm_reverse_tag_artifact(artifact).mbid_linked_exact_claims_only)
        self.assertEqual(artifact.observed_identities_promoted, 0)
        self.assertEqual(artifact.memberships_promoted, 0)

    async def test_retries_transient_response_and_offline_cache_miss_fails_closed(self) -> None:
        calls = 0

        async def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(429, json={"error": 29, "message": "slow down"})
            return httpx.Response(200, json={"topartists": {"artist": []}})

        settings = LastFmReverseTagSettings(retries=1, requests_per_second=10.0)
        query = _tag_query("fixture", "Fixture")
        with tempfile.TemporaryDirectory() as directory:
            cache = LastFmResponseCache(Path(directory) / "cache")
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
                with patch(
                    "musix.ingest.lastfm.reverse_tag.asyncio.sleep", new=AsyncMock()
                ) as sleep:
                    response = await LastFmHttpClient(
                        api_key="fixture-key", cache=cache, settings=settings, client=http_client
                    ).fetch(query)
            with self.assertRaises(FileNotFoundError):
                await LastFmHttpClient(
                    api_key=None,
                    cache=LastFmResponseCache(Path(directory) / "empty"),
                    settings=settings,
                    offline=True,
                ).fetch(query)

        self.assertEqual(calls, 2)
        self.assertFalse(response.cache_hit)
        sleep.assert_awaited()

    async def test_malformed_cached_raw_response_cannot_cross_into_collection(self) -> None:
        adapter = LastFmReverseTagAdapter()
        settings = LastFmReverseTagSettings(retries=0)
        manifest = adapter.build_query_manifest(_reconciliation(), settings)
        with tempfile.TemporaryDirectory() as directory:
            cache = LastFmResponseCache(Path(directory) / "cache")
            for query in manifest.queries:
                await cache.store(
                    query,
                    b'{"topartists":{"artist":[{"mbid":"not-a-name"}]}}',
                    maximum_response_bytes=settings.maximum_response_bytes,
                )
            with self.assertRaises(ValueError):
                await adapter.collect(
                    manifest,
                    LastFmHttpClient(api_key=None, cache=cache, settings=settings, offline=True),
                )

    async def test_offline_oversized_cached_raw_response_fails_before_parse(self) -> None:
        adapter = LastFmReverseTagAdapter()
        settings = LastFmReverseTagSettings(maximum_response_bytes=16, retries=0)
        manifest = adapter.build_query_manifest(_reconciliation(), settings)
        with tempfile.TemporaryDirectory() as directory:
            cache_root = Path(directory) / "cache"
            cache = LastFmResponseCache(cache_root)
            query = manifest.queries[0]
            path = cache_root / "requests" / "sha256" / f"{query.request_sha256}.json"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"{" + b"x" * 32)
            with self.assertRaisesRegex(LastFmReverseTagError, "exceeds configured bound"):
                await LastFmHttpClient(
                    api_key=None, cache=cache, settings=settings, offline=True
                ).fetch(query)

    async def test_cli_writes_plan_but_blocks_without_a_key(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict("os.environ", {"LASTFM_API_KEY": ""}, clear=False),
        ):
            root = Path(directory)
            reconciliation_path = root / "reconciliation.json"
            reconciliation_path.write_text(_reconciliation().model_dump_json(indent=2) + "\n")
            result = await _run(
                Namespace(
                    seed_reconciliation=reconciliation_path,
                    query_manifest=root / "manifest.json",
                    response_cache=root / "cache",
                    output=root / "artifact.json",
                    object_store=root / "objects",
                    receipt=root / "receipt.json",
                    offline=False,
                    maximum_seed_labels=6_291,
                    top_artists_per_tag=3,
                    maximum_tags_per_artist=100,
                    maximum_response_bytes=2 * 1024 * 1024,
                    maximum_concurrency=4,
                    requests_per_second=3.0,
                    timeout_seconds=30.0,
                    retries=3,
                )
            )
            self.assertTrue((root / "manifest.json").is_file())
            self.assertFalse((root / "artifact.json").exists())
        self.assertEqual(result, 2)

    def test_registry_rejects_duplicates_and_unknown_adapter(self) -> None:
        adapter = LastFmReverseTagAdapter()
        with self.assertRaisesRegex(ValueError, "unique"):
            ReverseTagAdapterRegistry((adapter, adapter))
        with self.assertRaises(KeyError):
            ReverseTagAdapterRegistry((adapter,)).resolve("unknown")


if __name__ == "__main__":
    unittest.main()
