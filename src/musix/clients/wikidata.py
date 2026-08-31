"""Async acquisition of bounded Wikidata SPARQL snapshots."""

import asyncio
import hashlib
import os
from pathlib import Path

import httpx
from pydantic import Field, HttpUrl

from musix.models import FrozenModel
from musix.types import Sha256

TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class WikidataClientError(RuntimeError):
    """Report an unsafe or invalid Wikidata response."""


class WikidataQueryRequest(FrozenModel):
    """Define one reproducible bounded query acquisition."""

    endpoint: HttpUrl = HttpUrl("https://query.wikidata.org/sparql")
    query_path: Path
    destination: Path
    user_agent: str = Field(min_length=8)
    max_response_bytes: int = Field(default=64 * 1024 * 1024, gt=0)
    timeout_seconds: float = Field(default=180.0, gt=0)
    retries: int = Field(default=3, ge=0, le=8)


class WikidataQueryResult(FrozenModel):
    """Describe an immutable query response and its exact query identity."""

    path: Path
    sha256: Sha256
    query_sha256: Sha256
    byte_size: int = Field(gt=0)
    status_code: int


def _sha256(value: bytes) -> Sha256:
    return hashlib.sha256(value).hexdigest()


async def _fetch_once(
    client: httpx.AsyncClient,
    request: WikidataQueryRequest,
    query: str,
) -> tuple[int, Sha256]:
    temporary = request.destination.with_name(f".{request.destination.name}.{os.getpid()}.tmp")
    byte_size = 0
    digest = hashlib.sha256()
    temporary.unlink(missing_ok=True)
    try:
        async with client.stream(
            "POST",
            str(request.endpoint),
            data={"query": query},
            headers={
                "Accept": "application/sparql-results+json",
                "User-Agent": request.user_agent,
            },
        ) as response:
            if response.status_code in TRANSIENT_STATUS_CODES:
                raise httpx.HTTPStatusError(
                    "transient Wikidata response",
                    request=response.request,
                    response=response,
                )
            response.raise_for_status()
            if "json" not in response.headers.get("content-type", "").casefold():
                raise WikidataClientError("Wikidata response is not JSON")
            with temporary.open("xb") as stream:
                async for chunk in response.aiter_bytes():
                    byte_size += len(chunk)
                    if byte_size > request.max_response_bytes:
                        raise WikidataClientError("Wikidata response exceeds configured bound")
                    digest.update(chunk)
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
        if byte_size == 0:
            raise WikidataClientError("Wikidata returned an empty response")
        temporary.replace(request.destination)
        return byte_size, digest.hexdigest()
    finally:
        temporary.unlink(missing_ok=True)


async def fetch_wikidata_query(
    request: WikidataQueryRequest,
    *,
    client: httpx.AsyncClient | None = None,
) -> WikidataQueryResult:
    """Fetch a bounded query with transient-only retry and atomic publication."""
    query_bytes = request.query_path.read_bytes()
    query = query_bytes.decode("utf-8")
    if not query.strip():
        raise WikidataClientError("Wikidata query is empty")
    request.destination.parent.mkdir(parents=True, exist_ok=True)
    owns_client = client is None
    http_client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(request.timeout_seconds),
        follow_redirects=True,
    )
    try:
        for attempt in range(request.retries + 1):
            try:
                byte_size, digest = await _fetch_once(http_client, request, query)
            except httpx.HTTPStatusError as error:
                if (
                    error.response.status_code not in TRANSIENT_STATUS_CODES
                    or attempt == request.retries
                ):
                    raise
                await asyncio.sleep(2**attempt)
            else:
                return WikidataQueryResult(
                    path=request.destination,
                    sha256=digest,
                    query_sha256=_sha256(query_bytes),
                    byte_size=byte_size,
                    status_code=200,
                )
    finally:
        if owns_client:
            await http_client.aclose()
    raise WikidataClientError("Wikidata retry loop exited without a result")
