"""Serialized bounded native catalog custody, without HTTPX or schema-model imports."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, cast, override

from opennoise.ingest.musicbrainz.compressed_catalog_custody import compress_stream
from opennoise.serving.metadata.full_recording_catalog import (
    LIMITS,
    artist_summary,
    page_binding,
    project_page,
)
from opennoise.serving.metadata.selected_recording_catalog import canonical_json

MIN_MEMORY_HEADROOM = 8_000_000
HTTP_OK = 200
SELECTED_HEADERS = {
    "content-type",
    "content-length",
    "content-encoding",
    "date",
    "etag",
    "last-modified",
}
MAX_HEADER_VALUE = 1024
MAX_HEADERS_TOTAL = 8192
MAX_OMITTED_NAMES = 32
FINAL_METADATA_RESERVE = 600_000


def selected_headers(headers: Any) -> tuple[dict[str, str], dict[str, Any]]:  # noqa: ANN401
    """Retain bounded relevant fields; exclude cookie and authorization values."""
    selected = {}
    omitted, oversized = [], []
    for name, value in headers.items():
        key = name.lower()
        if key not in SELECTED_HEADERS:
            omitted.append(key[:64])
        elif key in selected or len(value.encode("utf-8")) > MAX_HEADER_VALUE:
            oversized.append(key)
        else:
            selected[key] = value
    scope = {
        "approved": not oversized,
        "omitted_count": len(omitted),
        "omitted_names": sorted(set(omitted))[:MAX_OMITTED_NAMES],
        "omitted_names_truncated": len(set(omitted)) > MAX_OMITTED_NAMES,
        "oversized_or_duplicate_names": sorted(set(oversized)),
    }
    if len(canonical_json([selected, scope])) > MAX_HEADERS_TOTAL:
        return {}, {
            "approved": False,
            "omitted_count": len(omitted),
            "omitted_names": [],
            "omitted_names_truncated": True,
            "oversized_or_duplicate_names": ["total_header_metadata_limit"],
        }
    return selected, scope


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never spend undeclared requests by following redirects."""

    @override
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        """Preserve redirect response as a failed source outcome."""


def storage(directory: Path) -> tuple[int, int]:
    """Report both logical and physically allocated source bytes."""
    logical = physical = 0
    for path in directory.rglob("*"):
        if path.is_file():
            stat = path.stat()
            logical += stat.st_size
            physical += stat.st_blocks * 512
    return logical, physical


def process_peak_bytes() -> int:
    """Read this executed process's peak, excluding inherited fork usage."""
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmHWM:"):
            return int(line.split()[1]) * 1024
    raise ValueError("process memory peak unavailable")


def append_event(directory: Path, event: dict[str, Any]) -> None:
    """Durably retain every native request start and completed outcome as an ordered prefix."""
    encoded = canonical_json(event) + b"\n"
    logical, physical = storage(directory)
    if (
        max(logical + len(encoded), physical + len(encoded) + 4096)
        > LIMITS["logical_pack_bytes"] - FINAL_METADATA_RESERVE
    ):
        raise ValueError("durable event cannot fit bounded closed-pack metadata")
    with (directory / "request-ledger.jsonl").open("ab") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


def guard(directory: Path) -> str | None:
    """Stop conservatively when available capacity or process pressure is unknown."""
    if process_peak_bytes() >= LIMITS["max_process_rss_bytes"]:
        return "process_rss_limit"
    logical, physical = storage(directory)
    ceiling = LIMITS["logical_pack_bytes"] - LIMITS["metadata_reserve_bytes"]
    if logical >= ceiling or physical + 4096 >= ceiling:
        return "encoded_or_physical_pack_limit"
    try:
        current = int(Path("/sys/fs/cgroup/memory.current").read_text())
        maximum = int(Path("/sys/fs/cgroup/memory.max").read_text())
        stats = dict(
            line.split() for line in Path("/sys/fs/cgroup/memory.stat").read_text().splitlines()
        )
        reclaimable = int(stats.get("inactive_file", "0"))
        if maximum - current + reclaimable < MIN_MEMORY_HEADROOM:
            return "cgroup_memory_pressure"
    except (OSError, ValueError, KeyError):
        return "cgroup_capacity_unknown"
    return None


def capture(directory: Path) -> dict[str, Any]:  # noqa: C901, PLR0912, PLR0915
    """Execute the frozen plan; all unfetched requests retain explicit missing outcomes."""
    plan = json.loads((directory / "plan.json").read_bytes())
    (directory / "custody").mkdir(exist_ok=False)
    with (directory / "request-ledger.jsonl").open("xb"):
        pass
    opener = urllib.request.build_opener(NoRedirect())
    summaries = []
    actual_requests = 0
    requests, pages = [], []
    current = None
    stopped = None
    decoded = 0
    last_start = None
    started_at = datetime.now(UTC).isoformat()
    for index, request in enumerate(plan["requests"]):
        if current is not None and current != request["artist_mbid"]:
            summaries.append(artist_summary(current, requests, pages))
            requests, pages = [], []
        current = request["artist_mbid"]
        stopped = stopped or guard(directory)
        metadata_used = sum(
            p.stat().st_size
            for p in directory.rglob("*")
            if p.is_file() and p.parent != directory / "custody"
        )
        pending_bound = (len(plan["requests"]) - index) * 1200
        if (
            metadata_used + pending_bound + FINAL_METADATA_RESERVE + 20_000
            > LIMITS["metadata_reserve_bytes"]
        ):
            stopped = stopped or "metadata_reservation_limit"
        if decoded >= LIMITS["decoded_bytes"]:
            stopped = stopped or "decoded_pack_limit"
        row: dict[str, Any] = {
            "request": request,
            "actual_request": False,
            "status_code": None,
            "custody": None,
            "projection": None,
            "started_monotonic_seconds": None,
            "fetched_at": None,
            "headers": {},
            "header_scope": None,
            "outcome": stopped,
        }
        projected = None
        if not stopped:
            if last_start is not None:
                delay = LIMITS["spacing_seconds"] - (time.monotonic() - last_start)
                if delay > 0:
                    time.sleep(delay)
            last_start = time.monotonic()
            row.update(
                actual_request=True,
                started_monotonic_seconds=last_start,
                fetched_at=datetime.now(UTC).isoformat(),
            )
            append_event(
                directory,
                {
                    "event": "started",
                    "sequence": index,
                    "request": request,
                    "fetched_at": row["fetched_at"],
                    "started_monotonic_seconds": last_start,
                },
            )
            response = None
            try:
                try:
                    response = opener.open(
                        urllib.request.Request(  # noqa: S310 - pre-HTTP verified exact HTTPS endpoint.
                            request["url"],
                            headers={
                                "User-Agent": "OpenNoise/0.1 (open native catalog research; https://github.com/h0rv/opennoise)",
                                "Accept": "application/json",
                                "Accept-Encoding": "identity",
                            },
                        ),
                        timeout=30,
                    )
                except urllib.error.HTTPError as exc:
                    response = exc
                row["status_code"] = response.code
                row["headers"], row["header_scope"] = selected_headers(response.headers)
                append_event(
                    directory,
                    {
                        "event": "response",
                        "sequence": index,
                        "status_code": row["status_code"],
                        "headers": row["headers"],
                        "header_scope": row["header_scope"],
                    },
                )
                content_length = row["headers"].get("content-length")
                expected = (
                    int(content_length) if content_length and content_length.isdecimal() else None
                )
                if process_peak_bytes() >= LIMITS["max_process_rss_bytes"]:
                    stopped = "process_rss_limit"
                    row["outcome"] = "process_rss_custody_only"
                    raise MemoryError("native headers exceeded process memory budget")  # noqa: TRY301 - retained aborted response.
                logical, physical = storage(directory)
                path = directory / "custody" / f"{len(summaries):03d}-{len(requests):04d}.json.zst"
                custody = compress_stream(
                    cast("BinaryIO", response),
                    path,
                    remaining_total_decoded_bytes=LIMITS["decoded_bytes"] - decoded,
                    remaining_total_encoded_bytes=min(
                        LIMITS["logical_pack_bytes"] - LIMITS["metadata_reserve_bytes"] - logical,
                        LIMITS["logical_pack_bytes"]
                        - LIMITS["metadata_reserve_bytes"]
                        - physical
                        - 4096,
                    ),
                    expected_length=expected,
                )
                if custody["path"] is not None:
                    custody["path"] = str(path.relative_to(directory))
                row["custody"] = custody
                length = custody["decoded_bytes"]
                if not isinstance(length, int):
                    raise TypeError("invalid custody byte length")
                decoded += length
                row["outcome"] = custody["outcome"]
                if not row["header_scope"]["approved"]:
                    row["outcome"] = "header_scope_custody_only"
                elif row["headers"].get("content-encoding", "identity") != "identity":
                    row["outcome"] = "unsupported_transport_encoding"
                elif response.code == HTTP_OK and custody["complete_body"]:
                    import zstandard  # noqa: PLC0415 - only after bounded native custody.

                    with path.open("rb") as encoded:  # noqa: SIM117 - close decoder before source file.
                        with zstandard.ZstdDecompressor(max_window_size=1_048_576).stream_reader(
                            encoded
                        ) as reader:
                            body = reader.read(600_001)
                    try:
                        projected = project_page(body, request)
                        row["outcome"] = (
                            "native_core_page"
                            if not projected["rejected_rows"]
                            else "mixed_rows_custody_only"
                        )
                    except (ValueError, TypeError, KeyError):
                        row["outcome"] = "invalid_envelope_custody_only"
                    del body
                elif custody["complete_body"]:
                    row["outcome"] = "http_status"
                if not custody["complete_body"]:
                    stopped = "native_body_or_budget_limit"
            except (OSError, ValueError, MemoryError, urllib.error.URLError) as exc:
                if row["outcome"] != "process_rss_custody_only":
                    row["outcome"] = "transport_error"
                row["error_type"] = type(exc).__name__
                row["custody"] = row["custody"] or {
                    "path": None,
                    "decoded_bytes": 0,
                    "encoded_bytes": 0,
                    "complete_body": False,
                    "outcome": "no_response_body",
                }
            finally:
                if response is not None:
                    response.close()
            row["projection"] = page_binding(projected)
        append_event(directory, {"event": "outcome", "sequence": index, "capture": row})
        actual_requests += row["actual_request"]
        requests.append(request)
        if projected is not None:
            projected.pop("facts")
        pages.append(projected)
        if index % 25 == 0:
            print(  # noqa: T201 - timed machine-readable progress.
                json.dumps(
                    {"progress_requests": index + 1, "decoded_bytes": decoded, "stop": stopped}
                ),
                flush=True,
            )
    if current is not None:
        summaries.append(artist_summary(current, requests, pages))
    for name, value in [("artists.json", summaries)]:
        with (directory / name).open("xb") as stream:
            stream.write(canonical_json(value))
    return {
        "started_at": started_at,
        "finished_at": datetime.now(UTC).isoformat(),
        "actual_requests": actual_requests,
        "decoded_bytes": decoded,
        "stopped_reason": stopped,
        "max_rss_bytes": process_peak_bytes(),
        "logical_bytes": storage(directory)[0],
        "physical_allocated_bytes": storage(directory)[1],
    }
