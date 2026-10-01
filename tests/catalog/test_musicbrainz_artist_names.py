"""Official name projection replay, exact-ID abstentions and immutable sources."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import override

import httpx

from opennoise.catalog.musicbrainz_artist_names import (
    acquire_artist_name_enrichment,
    verify_artist_name_enrichment,
)
from opennoise.catalog.musicbrainz_candidate import (
    CandidateCatalogError,
    build_local_musicbrainz_candidate_catalog,
)
from opennoise.common import canonical_json, sha256_file, sha256_json
from tests.catalog.test_musicbrainz_candidate import _fixture, _uuid

_ROOT = Path(__file__).resolve().parents[2]
_USER_AGENT = "OpenNoise/0.1 (test; https://github.com/h0rv/opennoise)"


class ArtistNameEnrichmentTests(unittest.IsolatedAsyncioTestCase):
    @override
    def setUp(self) -> None:
        cache = _ROOT / ".cache" / "test-tmp"
        cache.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=cache)
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.catalog = self.directory / "catalog"
        build_local_musicbrainz_candidate_catalog(
            **_fixture(self.directory), output_directory=self.catalog
        )
        self.output = self.directory / "names"

    async def _acquire(self, page: dict[str, object]) -> dict[str, object]:
        def respond(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/ws/2/artist")
            self.assertEqual(request.url.params["query"], f"arid:({_uuid(3)})")
            self.assertEqual(request.url.params["limit"], "100")
            return httpx.Response(200, json=page)

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await acquire_artist_name_enrichment(
                catalog_directory=self.catalog,
                directory=self.output,
                client=client,
                user_agent=_USER_AGENT,
            )

    async def test_exact_name_join_preserves_catalog_and_replays_without_http(self) -> None:
        before = sha256_file(self.catalog / "catalog.sqlite")
        result = await self._acquire(
            {
                "count": 1,
                "offset": 0,
                "artists": [
                    {
                        "id": _uuid(3),
                        "name": " Cafe\u0301 Band\u202e ",
                        "tags": [{"name": "invented genre", "count": 999}],
                        "aliases": [{"name": "wrong identity"}],
                        "score": 98,
                    }
                ],
            }
        )
        self.assertEqual(result["resolved_artist_count"], 1)
        self.assertEqual(result["combined_named_artist_count"], 3)
        self.assertEqual(result["newly_named_direct_pair_count"], 1)
        self.assertEqual(result["remaining_unresolved_artist_count"], 0)
        self.assertEqual(result["membership_claims_added"], 0)
        self.assertNotIn("invented genre", json.dumps(result["rows"]))
        rows = result["rows"]
        assert isinstance(rows, list)
        self.assertEqual(rows[0]["display_name"], "Café Band")
        self.assertEqual(rows[0]["canonical_name"], " Cafe\u0301 Band\u202e ")
        self.assertEqual(before, sha256_file(self.catalog / "catalog.sqlite"))
        self.assertEqual(
            result,
            verify_artist_name_enrichment(catalog_directory=self.catalog, directory=self.output),
        )
        requests: list[object] = []

        def unexpected(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(500)

        async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as client:
            repeated = await acquire_artist_name_enrichment(
                catalog_directory=self.catalog,
                directory=self.output,
                client=client,
                user_agent=_USER_AGENT,
            )
        self.assertEqual(repeated, result)
        self.assertEqual(requests, [])

    async def test_incomplete_acquisition_resumes_from_verified_pages_without_http(self) -> None:
        result = await self._acquire(
            {"count": 1, "offset": 0, "artists": [{"id": _uuid(3), "name": "Actual"}]}
        )
        (self.output / "name-enrichment.json").unlink()
        requests: list[object] = []

        def unexpected(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(500)

        async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as client:
            resumed = await acquire_artist_name_enrichment(
                catalog_directory=self.catalog,
                directory=self.output,
                client=client,
                user_agent=_USER_AGENT,
            )
        self.assertEqual(result, resumed)
        self.assertEqual(requests, [])

    async def test_unusable_native_label_does_not_acquire_a_fabricated_display_name(self) -> None:
        result = await self._acquire(
            {
                "count": 1,
                "offset": 0,
                "artists": [{"id": _uuid(3), "name": "\u202e\x00 \n"}],
            }
        )
        self.assertEqual(result["resolved_artist_count"], 1)
        self.assertEqual(result["unusable_display_count"], 1)
        rows = result["rows"]
        assert isinstance(rows, list)
        self.assertIsNone(rows[0]["display_name"])
        self.assertEqual(rows[0]["status"], "unusable_display")

    async def test_absent_official_identity_remains_unresolved(self) -> None:
        result = await self._acquire({"count": 0, "offset": 0, "artists": []})
        self.assertEqual(result["resolved_artist_count"], 0)
        self.assertEqual(result["remaining_unresolved_artist_count"], 1)
        self.assertEqual(result["missing_official_identity_count"], 1)

    async def test_search_must_not_substitute_another_identity(self) -> None:
        with self.assertRaisesRegex(CandidateCatalogError, "outside the exact-ID query"):
            await self._acquire(
                {"count": 1, "offset": 0, "artists": [{"id": _uuid(1), "name": "Existing Artist"}]}
            )
        self.assertFalse((self.output / "name-enrichment.json").exists())

    async def test_duplicate_and_incomplete_search_results_fail(self) -> None:
        with self.assertRaisesRegex(CandidateCatalogError, "duplicate or incomplete"):
            await self._acquire(
                {
                    "count": 2,
                    "offset": 0,
                    "artists": [{"id": _uuid(3), "name": "A"}, {"id": _uuid(3), "name": "A"}],
                }
            )

    async def test_rehashing_fabricated_projection_or_policy_cannot_pass_replay(self) -> None:
        await self._acquire(
            {"count": 1, "offset": 0, "artists": [{"id": _uuid(3), "name": "Actual"}]}
        )
        path = self.output / "name-enrichment.json"
        original = json.loads(path.read_bytes())
        for key, value in (
            ("combined_named_artist_count", 999),
            ("public_export_authorized", True),
            ("membership_claims_added", 1),
        ):
            changed = {**original, key: value}
            changed["output_sha256"] = sha256_json(
                {k: v for k, v in changed.items() if k != "output_sha256"}
            )
            path.write_bytes(canonical_json(changed) + b"\n")
            with self.assertRaisesRegex(CandidateCatalogError, "source declarations"):
                verify_artist_name_enrichment(catalog_directory=self.catalog, directory=self.output)

    async def test_source_bytes_and_exact_url_are_verified(self) -> None:
        await self._acquire(
            {"count": 1, "offset": 0, "artists": [{"id": _uuid(3), "name": "Actual"}]}
        )
        page = self.output / "batch-0000.json"
        original = page.read_bytes()
        page.write_bytes(original + b" ")
        with self.assertRaisesRegex(CandidateCatalogError, "do not replay"):
            verify_artist_name_enrichment(catalog_directory=self.catalog, directory=self.output)
        page.write_bytes(original)
        binding_path = self.output / "batch-0000-receipt.json"
        binding = json.loads(binding_path.read_bytes())
        binding["request_url"] = "https://other.example/ws/2/artist"
        binding_path.write_bytes(canonical_json(binding))
        with self.assertRaisesRegex(CandidateCatalogError, "do not replay"):
            verify_artist_name_enrichment(catalog_directory=self.catalog, directory=self.output)

    async def test_public_destination_and_unbounded_selection_are_rejected(self) -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(500))
        ) as client:
            for limit in (0, 40_001):
                with self.assertRaisesRegex(CandidateCatalogError, "40,000"):
                    await acquire_artist_name_enrichment(
                        catalog_directory=self.catalog,
                        directory=self.output,
                        client=client,
                        user_agent=_USER_AGENT,
                        limit=limit,
                    )
            with self.assertRaisesRegex(CandidateCatalogError, "inside project .cache"):
                await acquire_artist_name_enrichment(
                    catalog_directory=self.catalog,
                    directory=_ROOT / "dist" / "names",
                    client=client,
                    user_agent=_USER_AGENT,
                )
