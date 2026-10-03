"""Bounded, lossless custody for compressed MusicBrainz response bodies."""

from __future__ import annotations

import hashlib
from contextlib import suppress
from pathlib import Path
from typing import BinaryIO

import zstandard

DEFAULT_MAX_DECODED_BYTES = 600_000
_CHUNK_BYTES = 64 * 1024


def _encoded_bound(decoded_bytes: int) -> int:
    """Conservative bound for the stream writer's 64 KiB input chunks."""
    remaining = decoded_bytes
    bound = 128  # frame header, end marker, and fixed writer overhead
    while remaining:
        chunk = min(_CHUNK_BYTES, remaining)
        # zstd_compressBound formula, plus ample per-block framing allowance.
        bound += chunk + (chunk >> 8) + ((128 * 1024 - chunk) >> 11) + 512
        remaining -= chunk
    return bound


def compress_stream(  # noqa: C901, PLR0912, PLR0913, PLR0915
    stream: BinaryIO,
    output_path: str | Path,
    *,
    max_decoded_bytes: int = DEFAULT_MAX_DECODED_BYTES,
    remaining_total_decoded_bytes: int | None = None,
    max_encoded_bytes: int | None = None,
    remaining_total_encoded_bytes: int | None = None,
    expected_length: int | None = None,
) -> dict[str, object]:
    """Copy a bounded stream into one exclusive zstd frame and return custody metadata.

    A caller supplied stream is read only in requests no larger than the remaining
    decoded budget. At a reached cap, EOF is deliberately not probed; expected_length
    can establish completeness when it exactly matches bytes observed.
    """
    caps = [max_decoded_bytes]
    if remaining_total_decoded_bytes is not None:
        caps.append(remaining_total_decoded_bytes)
    decoded_cap = min(caps)
    encoded_caps = [v for v in (max_encoded_bytes, remaining_total_encoded_bytes) if v is not None]
    encoded_cap = min(encoded_caps) if encoded_caps else None
    if decoded_cap < 0 or (encoded_cap is not None and encoded_cap < 0):
        raise ValueError("byte limits must be non-negative")

    # Reduce the decoded allowance until its conservative zstd bound fits. If
    # even an empty frame cannot fit, refuse before creating a file or reading.
    if encoded_cap is not None:
        if encoded_cap < _encoded_bound(0):
            empty_hash = hashlib.sha256(b"").hexdigest()
            return {
                "path": None,
                "decoded_bytes": 0,
                "decoded_sha256": empty_hash,
                "encoded_bytes": 0,
                "encoded_sha256": empty_hash,
                "complete_body": False,
                "outcome": "encoded_budget_refused",
                "error": "encoded budget cannot fit a complete zstd frame",
            }
        low, high = 0, decoded_cap
        while low < high:
            midpoint = (low + high + 1) // 2
            if _encoded_bound(midpoint) <= encoded_cap:
                low = midpoint
            else:
                high = midpoint - 1
        decoded_cap = low

    decoded_hash = hashlib.sha256()
    decoded_length = 0
    complete = False
    outcome = "complete"
    error: str | None = None
    path = Path(output_path)
    # x mode is intentional: custody artifacts are immutable and never replaced.
    with path.open("xb") as raw:
        writer = zstandard.ZstdCompressor(level=1).stream_writer(raw, closefd=False)
        try:
            while decoded_length < decoded_cap:
                request_size = min(_CHUNK_BYTES, decoded_cap - decoded_length)
                chunk = stream.read(request_size)
                if not chunk:
                    complete = True
                    break
                if not isinstance(chunk, bytes):
                    raise TypeError("stream.read() must return bytes")  # noqa: TRY301
                if len(chunk) > request_size:
                    raise ValueError("stream returned more bytes than requested")  # noqa: TRY301
                decoded_hash.update(chunk)
                decoded_length += len(chunk)
                writer.write(chunk)
            if not complete:
                complete = expected_length is not None and expected_length == decoded_length
                if not complete:
                    outcome = "decoded_limit"
            writer.close()
        except Exception as exc:  # noqa: BLE001
            outcome = "stream_error"
            complete = False
            error = f"{type(exc).__name__}: {exc}"
            with suppress(Exception):
                writer.close()
        raw.flush()

    encoded_hash = hashlib.sha256()
    encoded_length = 0
    with path.open("rb") as encoded:
        while block := encoded.read(_CHUNK_BYTES):
            encoded_hash.update(block)
            encoded_length += len(block)

    if expected_length is not None and expected_length != decoded_length:
        complete = False
        if outcome == "complete":
            outcome = "length_mismatch"
    return {
        "path": str(path),
        "decoded_bytes": decoded_length,
        "decoded_sha256": decoded_hash.hexdigest(),
        "encoded_bytes": encoded_length,
        "encoded_sha256": encoded_hash.hexdigest(),
        "complete_body": complete,
        "outcome": outcome,
        "error": error,
    }


def replay_and_verify(
    path: str | Path,
    custody: dict[str, object],
    *,
    max_decoded_bytes: int = DEFAULT_MAX_DECODED_BYTES,
) -> dict[str, object]:
    """Boundedly decompress and verify a stored frame against custody metadata."""
    path = Path(path)
    encoded_hash = hashlib.sha256()
    encoded_length = 0
    with path.open("rb") as raw:
        while block := raw.read(_CHUNK_BYTES):
            encoded_hash.update(block)
            encoded_length += len(block)
    encoded_mismatch = encoded_length != custody.get(
        "encoded_bytes"
    ) or encoded_hash.hexdigest() != custody.get("encoded_sha256")
    if encoded_mismatch:
        raise ValueError("encoded artifact hash or length mismatch")

    decoded_hash = hashlib.sha256()
    decoded_length = 0
    with path.open("rb") as raw:
        # max_window_size is expressed in bytes. One MiB accommodates every
        # frame emitted here while bounding malicious replay allocations.
        reader = zstandard.ZstdDecompressor(max_window_size=1_048_576).stream_reader(raw)
        try:
            while True:
                block = reader.read(min(_CHUNK_BYTES, max_decoded_bytes - decoded_length + 1))
                if not block:
                    break
                decoded_length += len(block)
                if decoded_length > max_decoded_bytes:
                    raise ValueError("decoded artifact exceeds replay bound")
                decoded_hash.update(block)
        finally:
            reader.close()
    decoded_mismatch = decoded_length != custody.get(
        "decoded_bytes"
    ) or decoded_hash.hexdigest() != custody.get("decoded_sha256")
    if decoded_mismatch:
        raise ValueError("decoded artifact hash or length mismatch")
    # A valid replay proves stored bytes, but cannot upgrade a source marked partial.
    return {
        "decoded_bytes": decoded_length,
        "decoded_sha256": decoded_hash.hexdigest(),
        "complete_body": bool(custody.get("complete_body")),
    }
