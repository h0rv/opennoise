import tempfile
import unittest
from pathlib import Path

import httpx

from opennoise.clients.wikidata import (
    WikidataClientError,
    WikidataQueryRequest,
    fetch_wikidata_query,
)
from tests._test_client import PollingIsolatedAsyncioTestCase


class WikidataClientTests(PollingIsolatedAsyncioTestCase):
    async def test_fetches_a_bounded_identified_snapshot(self) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                content=b'{"results":{"bindings":[]}}',
                headers={"content-type": "application/sparql-results+json"},
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            query = root / "query.rq"
            query.write_text("SELECT * WHERE {}", encoding="utf-8")
            destination = root / "snapshot.json"
            request = WikidataQueryRequest(
                query_path=query,
                destination=destination,
                user_agent="opennoise/0.1 (maintainer@example.test)",
            )
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                result = await fetch_wikidata_query(request, client=client)

        self.assertEqual(result.byte_size, 27)
        self.assertEqual(len(result.sha256), 64)
        self.assertEqual(len(result.query_sha256), 64)
        self.assertIn(b"SELECT+%2A+WHERE", requests[0].content)

    async def test_rejects_a_response_over_its_bound_without_publishing(self) -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=b'{"results":{"bindings":[]}}',
                headers={"content-type": "application/sparql-results+json"},
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            query = root / "query.rq"
            query.write_text("SELECT * WHERE {}", encoding="utf-8")
            destination = root / "snapshot.json"
            request = WikidataQueryRequest(
                query_path=query,
                destination=destination,
                user_agent="opennoise/0.1 (maintainer@example.test)",
                max_response_bytes=1,
            )
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                with self.assertRaises(WikidataClientError):
                    await fetch_wikidata_query(request, client=client)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
