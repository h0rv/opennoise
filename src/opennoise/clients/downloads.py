"""Resumable verified HTTP artifact downloads."""

import asyncio
import hashlib
import os
from pathlib import Path

import httpx

from opennoise.models.sources import DownloadResult, DownloadSource
from opennoise.policy import (
    require_metadata_file,
    require_metadata_media_type,
    require_metadata_prefix,
)

DOWNLOAD_CHUNK_BYTES = 1024 * 1024


class SourceManifestError(ValueError):
    """Report an invalid source manifest or upstream download response."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(DOWNLOAD_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


async def _stream_to_partial(
    http_client: httpx.AsyncClient,
    source: DownloadSource,
    partial: Path,
    resumed_from: int,
) -> int:
    headers = {"Range": f"bytes={resumed_from}-"} if resumed_from else {}
    async with http_client.stream("GET", str(source.url), headers=headers) as response:
        if resumed_from and response.status_code == httpx.codes.OK:
            resumed_from = 0
            await asyncio.to_thread(partial.unlink, missing_ok=True)
        elif resumed_from and response.status_code != httpx.codes.PARTIAL_CONTENT:
            raise SourceManifestError("upstream did not honor the requested byte range")
        response.raise_for_status()
        media_type = response.headers.get("content-type", "").partition(";")[0].strip()
        require_metadata_media_type(media_type)
        if media_type.casefold() != source.expected_media_type():
            expected = source.expected_content_type
            raise SourceManifestError(
                f"upstream content type is {media_type!r}; expected {expected!r}"
            )
        if resumed_from:
            content_range = response.headers.get("content-range", "")
            if not content_range.startswith(f"bytes {resumed_from}-"):
                raise SourceManifestError("upstream returned an invalid Content-Range")
        # A failed stream can leave its app-owned partial at zero bytes. A retry
        # must restart that object instead of treating the placeholder as new.
        mode = "ab" if resumed_from else "wb"
        with partial.open(mode) as stream:
            async for chunk in response.aiter_bytes(DOWNLOAD_CHUNK_BYTES):
                if stream.tell() == 0:
                    require_metadata_prefix(chunk[:16])
                stream.write(chunk)
                if stream.tell() > source.expected_bytes:
                    raise SourceManifestError("download exceeds declared expected_bytes")
            stream.flush()
            os.fsync(stream.fileno())
    return resumed_from


async def download_verified(
    source: DownloadSource,
    vault_root: Path,
    *,
    timeout_seconds: float = 120.0,
    client: httpx.AsyncClient | None = None,
) -> DownloadResult:
    """Resume one bounded download and publish it only after SHA256 verification."""
    expected_sha256 = source.verified_sha256()
    object_directory = vault_root / "raw" / "sha256"
    partial_directory = vault_root / "downloads"
    object_directory.mkdir(parents=True, exist_ok=True)
    partial_directory.mkdir(parents=True, exist_ok=True)
    destination = object_directory / expected_sha256
    partial = partial_directory / f"{source.id}.{expected_sha256}.part"

    if destination.exists():
        require_metadata_file(destination)
        size = destination.stat().st_size
        digest = _sha256_file(destination)
        if size != source.expected_bytes or digest != expected_sha256:
            raise SourceManifestError("existing vault object does not match its manifest")
        return DownloadResult(
            path=destination,
            sha256=digest,
            byte_size=size,
            resumed_from=size,
            reused=True,
        )

    resumed_from = partial.stat().st_size if partial.exists() else 0
    if resumed_from:
        require_metadata_file(partial)
    if resumed_from > source.expected_bytes:
        raise SourceManifestError("partial artifact is larger than the declared source")
    owns_client = client is None
    http_client = client or httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(timeout_seconds),
        headers={"User-Agent": "opennoise/0.1 (local metadata research)"},
    )
    try:
        resumed_from = await _stream_to_partial(http_client, source, partial, resumed_from)
    finally:
        if owns_client:
            await http_client.aclose()

    byte_size = partial.stat().st_size
    if byte_size != source.expected_bytes:
        raise SourceManifestError(f"downloaded {byte_size} bytes; expected {source.expected_bytes}")
    digest = _sha256_file(partial)
    if digest != expected_sha256:
        raise SourceManifestError(f"download SHA256 is {digest}; expected {expected_sha256}")
    partial.replace(destination)
    return DownloadResult(
        path=destination,
        sha256=digest,
        byte_size=byte_size,
        resumed_from=resumed_from,
        reused=False,
    )
