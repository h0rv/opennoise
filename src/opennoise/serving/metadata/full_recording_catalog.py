"""Frozen, count-checked native pagination; catalog membership is not musical relevance."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from opennoise.serving.metadata.recording_facts import project_recording_fact
from opennoise.serving.metadata.selected_recording_catalog import canonical_json

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

REVISION = "selected-150-native-core-browse-catalog-v2"
HTTP_OK = 200
PAGE_SIZE = 100
MIN_SPACING = 1.1
LIMITS: dict[str, Any] = {
    "requests": 2000,
    "decoded_bytes": 120_000_000,
    "logical_pack_bytes": 40_000_000,
    "metadata_reserve_bytes": 5_000_000,
    "response_bytes": 600_000,
    "max_process_rss_bytes": 40_000_000,
    "spacing_seconds": 1.1,
    "page_size": 100,
    "header_value_bytes": 1024,
    "header_metadata_bytes": 8192,
}


def source_url(identity: str, offset: int) -> str:
    """Only exact native identity and core artist credits are requested."""
    if str(UUID(identity)) != identity or type(offset) is not int or offset < 0:
        raise ValueError("noncanonical native request")
    return (
        f"https://musicbrainz.org/ws/2/recording?artist={identity}"
        f"&limit=100&offset={offset}&inc=artist-credits&fmt=json"
    )


def request_plan(selection: dict[str, Any], candidates: dict[str, Any]) -> dict[str, Any]:
    """Freeze continuation counts from the independently replayed v1 before new HTTP."""
    identities = [r["artist_mbid"] for r in selection["artists"]]
    if [r["artist_mbid"] for r in candidates["artists"]] != identities:
        raise ValueError("baseline native count roster differs")
    requests = []
    for row in candidates["artists"]:
        count = row.get("advertised_recording_count")
        if type(count) is not int or count < 0:
            raise ValueError("new pagination requires an observed baseline count for every artist")
        offsets = range(0, max(count, 1), 100)
        for offset in offsets:
            requests.append(  # noqa: PERF401 - preserve explicit request order.
                {
                    "artist_mbid": row["artist_mbid"],
                    "baseline_count": count,
                    "stage": "initial" if offset == 0 else "continuation",
                    "offset": offset,
                    "url": source_url(row["artist_mbid"], offset),
                }
            )
        requests.append(
            {
                "artist_mbid": row["artist_mbid"],
                "baseline_count": count,
                "stage": "closing",
                "offset": 0,
                "url": source_url(row["artist_mbid"], 0),
            }
        )
    if len(requests) > LIMITS["requests"]:
        raise ValueError("frozen plan exceeds request budget")
    return {
        "revision": REVISION,
        "limits": dict(LIMITS),
        "roster_sha256": selection["roster_sha256"],
        "baseline_candidates_sha256": hashlib.sha256(canonical_json(candidates)).hexdigest(),
        "requests": requests,
        "scope": "Native observation window; no representative recording or musical-fit claim.",
    }


def project_page(body: bytes, request: dict[str, Any]) -> dict[str, Any]:
    """Validate the whole envelope and individually account for every native row."""
    payload = json.loads(body)
    if not isinstance(payload, dict) or set(payload) != {
        "recording-count",
        "recording-offset",
        "recordings",
    }:
        raise ValueError("mixed or unknown browse envelope; custody only")
    count, offset, rows = (
        payload["recording-count"],
        payload["recording-offset"],
        payload["recordings"],
    )
    if (
        type(count) is not int
        or count < 0
        or type(offset) is not int
        or offset != request["offset"]
    ):
        raise ValueError("native count or pagination offset is invalid")
    if not isinstance(rows, list) or len(rows) > PAGE_SIZE or len(rows) > max(count - offset, 0):
        raise ValueError("native page cardinality is invalid")
    accepted, rejected, ids = [], [], []
    for index, row in enumerate(rows):
        identity = row.get("id") if isinstance(row, dict) else None
        try:
            if not isinstance(identity, str):
                raise TypeError("native UUID missing")  # noqa: TRY301
            fact = project_recording_fact(canonical_json(row), identity, request["artist_mbid"])
        except (ValueError, TypeError, KeyError):
            rejected.append({"row_index": index, "reason": "not_strict_core_exact_credit"})
        else:
            ids.append(identity)
            accepted.append(fact)
    # No response with mixed unapproved rows is called a CC0 projected page.
    return {
        "advertised_count": count,
        "offset": offset,
        "returned_count": len(rows),
        "recording_mbids": ids,
        "rejected_rows": rejected,
        "facts": accepted if not rejected else [],
        "field_scope": "core_only_CC0" if not rejected else "raw_custody_only",
        "semantic_page_sha256": hashlib.sha256(canonical_json(payload)).hexdigest(),
    }


def page_binding(page: dict[str, Any] | None) -> dict[str, Any] | None:
    """Bind reproducible facts without duplicating native recording rows in the ledger."""
    if page is None:
        return None
    return {
        "projection_sha256": hashlib.sha256(canonical_json(page)).hexdigest(),
        "advertised_count": page["advertised_count"],
        "returned_count": page["returned_count"],
        "field_scope": page["field_scope"],
        "unapproved_row_count": len(page["rejected_rows"]),
    }


def read_ledger(  # noqa: C901, PLR0912 - strict durable event replay.
    directory: Path, plan: dict[str, Any], *, allow_partial: bool = False
) -> list[dict[str, Any]]:
    """Replay durable event order; interrupted starts remain a disclosed unfinished prefix."""
    captures = []
    started = response = None
    with (directory / "request-ledger.jsonl").open("rb") as stream:
        for raw in stream:
            if not raw.endswith(b"\n"):
                if allow_partial:
                    break
                raise ValueError("durable ledger ends in an interrupted event write")
            event = json.loads(raw)
            sequence = len(captures)
            if event.get("sequence") != sequence or sequence >= len(plan["requests"]):
                raise ValueError("durable ledger sequence differs from frozen requests")
            if event.get("event") == "started":
                if started is not None or set(event) != {
                    "event",
                    "sequence",
                    "request",
                    "fetched_at",
                    "started_monotonic_seconds",
                }:
                    raise ValueError("duplicate or unknown request-start fields")
                if event["request"] != plan["requests"][sequence]:
                    raise ValueError("durable started request differs")
                started = event
            elif event.get("event") == "response":
                if (
                    started is None
                    or response is not None
                    or set(event) != {"event", "sequence", "status_code", "headers", "header_scope"}
                ):
                    raise ValueError("response has no unique preceding request")
                response = event
            elif event.get("event") == "outcome":
                if set(event) != {"event", "sequence", "capture"}:
                    raise ValueError("unknown outcome event fields")
                capture = event["capture"]
                if capture["actual_request"] != (started is not None):
                    raise ValueError("outcome invents or loses an actual request")
                if started is not None and any(
                    capture[key] != started[key]
                    for key in ["request", "fetched_at", "started_monotonic_seconds"]
                ):
                    raise ValueError("outcome differs from durable request start")
                if response is not None and any(
                    capture[key] != response[key]
                    for key in ["status_code", "headers", "header_scope"]
                ):
                    raise ValueError("outcome differs from durable native response")
                if response is None and capture["status_code"] is not None:
                    raise ValueError("outcome invents a response status")
                captures.append(capture)
                started = response = None
            else:
                raise ValueError("unknown durable ledger stage")
    if not allow_partial and (started is not None or len(captures) != len(plan["requests"])):
        raise ValueError("durable ledger is an unfinished acquisition prefix")
    return captures


def verify_source_state(capture: dict[str, Any]) -> None:  # noqa: C901, PLR0912
    """Prevent transport failures from being promoted into source projections."""
    if not capture["actual_request"]:
        if capture["outcome"] not in {
            "process_rss_limit",
            "encoded_or_physical_pack_limit",
            "cgroup_memory_pressure",
            "cgroup_capacity_unknown",
            "decoded_pack_limit",
            "native_body_or_budget_limit",
            "metadata_reservation_limit",
        }:
            raise ValueError("unknown resource-stop source outcome")
        return
    headers, scope = capture["headers"], capture["header_scope"]
    if (
        not isinstance(headers, dict)
        or set(headers)
        - {
            "content-type",
            "content-length",
            "content-encoding",
            "date",
            "etag",
            "last-modified",
        }
        or any(
            not isinstance(value, str) or len(value.encode("utf-8")) > LIMITS["header_value_bytes"]
            for value in headers.values()
        )
    ):
        raise ValueError("native selected headers exceed frozen field or byte scope")
    if scope is not None:
        if set(scope) != {
            "approved",
            "omitted_count",
            "omitted_names",
            "omitted_names_truncated",
            "oversized_or_duplicate_names",
        }:
            raise ValueError("native header omission accounting schema differs")
        if type(scope["approved"]) is not bool or scope["approved"] != (
            not scope["oversized_or_duplicate_names"]
        ):
            raise ValueError("native header scope approval contradicts omission evidence")
        if len(canonical_json([headers, scope])) > LIMITS["header_metadata_bytes"]:
            raise ValueError("native header metadata exceeds frozen byte cap")
    outcome, status, custody, projection = (
        capture["outcome"],
        capture["status_code"],
        capture["custody"],
        capture["projection"],
    )
    if outcome not in {
        "native_core_page",
        "mixed_rows_custody_only",
        "invalid_envelope_custody_only",
        "unsupported_transport_encoding",
        "http_status",
        "transport_error",
        "header_scope_custody_only",
        "process_rss_custody_only",
        "decoded_limit",
        "length_mismatch",
        "stream_error",
        "encoded_budget_refused",
    }:
        raise ValueError("unknown native source outcome")
    if projection is not None:
        if scope is None or not scope["approved"]:
            raise ValueError("projection uses unapproved native header metadata")
        if (
            status != HTTP_OK
            or not custody["complete_body"]
            or capture["headers"].get("content-encoding", "identity") != "identity"
        ):
            raise ValueError("projection lacks complete supported native response")
        expected = (
            "native_core_page"
            if projection["field_scope"] == "core_only_CC0"
            else "mixed_rows_custody_only"
        )
        if outcome != expected:
            raise ValueError("projection source outcome differs from its approved field scope")
    elif outcome in {"native_core_page", "mixed_rows_custody_only"}:
        raise ValueError("approved-page outcome has no source binding")
    if outcome == "invalid_envelope_custody_only" and (
        status != HTTP_OK
        or not custody["complete_body"]
        or capture["headers"].get("content-encoding", "identity") != "identity"
    ):
        raise ValueError("invalid-envelope outcome lacks complete supported source bytes")
    if outcome == "http_status" and (status in {None, HTTP_OK} or not custody["complete_body"]):
        raise ValueError("HTTP failure outcome contradicts source status or completeness")
    if (
        outcome == "unsupported_transport_encoding"
        and capture["headers"].get("content-encoding", "identity") == "identity"
    ):
        raise ValueError("unsupported encoding outcome contradicts native headers")
    if (
        outcome in {"decoded_limit", "length_mismatch", "stream_error", "encoded_budget_refused"}
        and custody["complete_body"]
    ):
        raise ValueError("partial source outcome claims complete native body")
    length = capture["headers"].get("content-length")
    if (
        custody["complete_body"]
        and length is not None
        and (not length.isdecimal() or int(length) != custody["decoded_bytes"])
    ):
        raise ValueError("complete source length contradicts native Content-Length")


def verify_ledger_order(plan: dict[str, Any], captures: list[dict[str, Any]]) -> None:  # noqa: C901, PLR0912 - independent closed-ledger checks.
    """Reject extra stages, omitted outcomes, changed requests and unbudgeted retries."""
    if plan.get("revision") != REVISION or plan.get("limits") != LIMITS:
        raise ValueError("frozen policy changed")
    if len(captures) != len(plan["requests"]) or len(captures) > LIMITS["requests"]:
        raise ValueError("ledger does not close the entire frozen request plan")
    actual, decoded = 0, 0
    last_started = None
    stopped = False
    for request, capture in zip(plan["requests"], captures, strict=True):
        allowed = {
            "request",
            "actual_request",
            "status_code",
            "custody",
            "projection",
            "started_monotonic_seconds",
            "fetched_at",
            "headers",
            "header_scope",
            "outcome",
            "error_type",
        }
        required = allowed - {"error_type"}
        if set(capture) - allowed or required - set(capture):
            raise ValueError("unknown capture source fields")
        if capture.get("request") != request or request["stage"] not in {
            "initial",
            "continuation",
            "closing",
        }:
            raise ValueError("ledger request stage, offset or global order differs")
        if set(request) != {"artist_mbid", "baseline_count", "stage", "offset", "url"}:
            raise ValueError("unknown frozen request fields")
        if request["url"] != source_url(request["artist_mbid"], request["offset"]):
            raise ValueError("native URL differs from exact source contract")
        if type(capture.get("actual_request")) is not bool:
            raise ValueError("request status is not explicit")
        custody = capture.get("custody")
        verify_source_state(capture)
        if capture["actual_request"]:
            if stopped or not isinstance(custody, dict):
                raise ValueError("request after stop or missing native custody")
            started = capture.get("started_monotonic_seconds")
            if (
                not isinstance(started, (int, float))
                or isinstance(started, bool)
                or not math.isfinite(started)
                or (last_started is not None and started - last_started < MIN_SPACING)
            ):
                raise ValueError("request timing violates frozen spacing")
            last_started = started
            timestamp = datetime.fromisoformat(capture["fetched_at"])
            offset = timestamp.utcoffset()
            if offset is None or offset.total_seconds() != 0:
                raise ValueError("actual native acquisition timestamp must be UTC")
            if type(custody.get("complete_body")) is not bool:
                raise ValueError("source transport completeness is not explicit")
            actual += 1
            length = custody.get("decoded_bytes")
            if type(length) is not int or not 0 <= length <= LIMITS["response_bytes"]:
                raise ValueError("response exceeds native body budget")
            decoded += length
        else:
            stopped = True
            if (
                custody is not None
                or capture.get("status_code") is not None
                or capture.get("projection") is not None
                or capture.get("fetched_at") is not None
                or capture.get("started_monotonic_seconds") is not None
            ):
                raise ValueError("unattempted request has invented native evidence")
    if actual > LIMITS["requests"] or decoded > LIMITS["decoded_bytes"]:
        raise ValueError("native request or decoded byte cap exceeded")


def artist_summary(
    identity: str, requests: list[dict[str, Any]], pages: Sequence[dict[str, Any] | None]
) -> dict[str, Any]:
    """Declare complete only with all pages, unique identities and stable closing probe."""
    if (
        len(requests) != len(pages)
        or not requests
        or requests[0]["stage"] != "initial"
        or requests[-1]["stage"] != "closing"
    ):
        raise ValueError("artist observation stages do not close")
    baseline = requests[0]["baseline_count"]
    seen: set[str] = set()
    duplicates = rejected = returned = 0
    inconsistent = False
    for request, page in zip(requests, pages, strict=True):
        if request["artist_mbid"] != identity or request["baseline_count"] != baseline:
            raise ValueError("artist summary mixes source identities or counts")
        if page is None:
            continue
        inconsistent |= page["advertised_count"] != baseline
        if request["stage"] != "closing":
            expected = min(100, max(baseline - request["offset"], 0))
            inconsistent |= page["returned_count"] != expected
            returned += page["returned_count"]
            rejected += len(page["rejected_rows"])
            for recording in page["recording_mbids"]:
                duplicates += recording in seen
                seen.add(recording)
    if pages[0] is not None and pages[-1] is not None:
        inconsistent |= pages[0]["semantic_page_sha256"] != pages[-1]["semantic_page_sha256"]
    all_pages = all(page is not None for page in pages)
    complete = (
        all_pages and not inconsistent and not rejected and not duplicates and len(seen) == baseline
    )
    return {
        "artist_mbid": identity,
        "baseline_advertised_count": baseline,
        "observed_initial_count": pages[0]["advertised_count"] if pages[0] else None,
        "observed_closing_count": pages[-1]["advertised_count"] if pages[-1] else None,
        "returned_nonprobe_rows": returned,
        "unique_exact_credited_recordings": len(seen),
        "duplicate_recording_rows": duplicates,
        "unapproved_rows": rejected,
        "missing_pages": sum(page is None for page in pages),
        "unfetched_baseline_count": max(baseline - len(seen), 0),
        "status": "observed_window_complete"
        if complete
        else "inconsistent"
        if inconsistent
        else "partial"
        if any(pages)
        else "unknown",
        "atomic_snapshot": False,
        "musical_relevance": "not_assessed",
    }
