"""Import licensed native sonic bytes and acquire separately verified exact core credits."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any, Literal, cast

import httpx

from opennoise.ingest.acousticbrainz.native_sonic import (
    LICENSE_AUDIT,
    MAX_CORE_BYTES,
    MAX_CORE_REQUESTS,
    MAX_SONIC_BYTES,
    REVISION,
    NativeCreditCapture,
    NativeSonicCapture,
    NativeSonicManifest,
    SelectedRecording,
    project_native_sonic,
    sonic_source_url,
    verify_native_sonic,
)
from opennoise.ingest.acousticbrainz.projection import json_document
from opennoise.pipeline.foundation import _safe_path
from opennoise.serving.metadata.recording_facts import (
    project_recording_fact,
    recording_source_url,
    verify_recording_fact_pack,
)

RATE_INTERVAL_SECONDS = 1.1


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _digest(body: bytes | bytearray) -> str:
    return hashlib.sha256(body).hexdigest()


def _verify_source_receipt(root: Path) -> str:
    body = _safe_path(root, "receipt.json").read_bytes()
    receipt = json_document(body)
    files = receipt.get("files")
    if not isinstance(files, dict):
        raise TypeError("retained source receipt must bind files")
    for name, digest in files.items():
        if _digest(_safe_path(root, name).read_bytes()) != digest:
            raise ValueError(f"retained source receipt mismatch: {name}")
    return _digest(body)


def _import_sonic(source: Path, benchmark: Path, output: Path) -> dict[str, Any]:
    receipt_digest = _verify_source_receipt(source)
    _verify_source_receipt(benchmark)
    declaration_body = (source / "declaration.json").read_bytes()
    declaration = cast("dict[str, Any]", json_document(declaration_body))
    original = cast("dict[str, Any]", json_document((source / "projection.json").read_bytes()))
    if (
        declaration.get("scope") != "authorized_local_research"
        or original.get("product_promotion_allowed") is not False
        or declaration.get("audio_requested") is not False
        or declaration.get("raw_tags_consumed") is not False
    ):
        raise ValueError("retained research source boundary differs")
    base_captures = json.loads((benchmark / "source-captures.json").read_bytes())
    rights = next(row for row in base_captures if row["kind"] == "rights")
    rights_body = (benchmark / rights["payload_path"]).read_bytes()
    if (
        rights["requested_url"] != LICENSE_AUDIT["source"]
        or rights["status_code"] != HTTPStatus.OK
        or not rights["payload_complete"]
        or _digest(rights_body) != LICENSE_AUDIT["source_body_sha256"]
    ):
        raise ValueError("independently reviewed native source license evidence differs")
    old_by_recording = {
        row["recording_mbid"]: row for row in base_captures if row["kind"] == "low-level"
    }
    selected = [
        SelectedRecording(cohort_artist_mbid=pair[0], recording_mbid=pair[1])
        for pair in declaration["recordings"]
    ]
    if len(selected) != len(original["outcomes"]):
        raise ValueError("retained source outcome denominator differs")
    output.mkdir(parents=True, exist_ok=False)
    (output / "raw/sonic").mkdir(parents=True)
    (output / "raw/credits").mkdir()
    _write(output / "license-audit.json", LICENSE_AUDIT)
    captures = []
    total = 0
    for row, outcome in zip(selected, original["outcomes"], strict=True):
        if (row.cohort_artist_mbid, row.recording_mbid) != (
            outcome["artist_id"],
            outcome["recording_id"],
        ):
            raise ValueError("retained source rows differ from declared recording selection")
        path = _safe_path(source, outcome["payload_path"])
        body = path.read_bytes()
        if len(body) != outcome["payload_bytes"] or _digest(body) != outcome["payload_sha256"]:
            raise ValueError("retained native source row byte binding differs")
        total += len(body)
        if total > MAX_SONIC_BYTES:
            raise ValueError("native sonic source budget exceeded")
        observed_at, complete = None, None
        if outcome["reused"]:
            previous = old_by_recording[row.recording_mbid]
            if (
                previous["payload_sha256"] != _digest(body)
                or previous["status_code"] != outcome["status_code"]
            ):
                raise ValueError("reused native source capture identity differs")
            observed_at, complete = previous["fetched_at"], previous["payload_complete"]
        raw_path = f"raw/sonic/{row.recording_mbid}.json"
        (output / raw_path).write_bytes(body)
        captures.append(
            NativeSonicCapture(
                **row.model_dump(),
                url=sonic_source_url(row.recording_mbid),
                status_code=outcome["status_code"],
                source_observed_at=observed_at,
                observation_time_status="retained" if observed_at else "not_retained",
                payload_complete=complete,
                raw_path=raw_path,
                sha256=_digest(body),
                size_bytes=len(body),
            )
        )
    manifest = NativeSonicManifest(
        revision=REVISION,
        imported_at=datetime.now(UTC).isoformat(),
        selection_method=(
            "Frozen prior ten-artist benchmark; first ten exact IDs per artist from a bounded "
            "first-page recording search. Selection association is not native credit proof, "
            "discography coverage, or representative relevance. "
            "No historical genre targets are imported."
        ),
        source_receipt_sha256=receipt_digest,
        source_declaration_sha256=_digest(declaration_body),
        original_wrapper_product_promotion_allowed=False,
        original_wrapper_scope="authorized_local_research",
        selected_recordings=selected,
        sonic_captures=captures,
        credit_request_roster=[
            SelectedRecording(**row.model_dump(include={"cohort_artist_mbid", "recording_mbid"}))
            for row in captures
            if row.status_code == HTTPStatus.OK
        ],
        credit_captures=[],
    ).model_dump()
    _write(output / "manifest.json", manifest)
    return manifest


def _reuse_core(
    root: Path, output: Path, row: dict[str, Any], receipt_digest: str
) -> NativeCreditCapture:
    body = _safe_path(root, row["path"]).read_bytes()
    json_document(body)
    project_recording_fact(body, row["recording_mbid"], row["artist_mbid"])
    raw_path = f"raw/credits/{row['recording_mbid']}.json"
    (output / raw_path).write_bytes(body)
    return NativeCreditCapture(
        cohort_artist_mbid=row["artist_mbid"],
        recording_mbid=row["recording_mbid"],
        origin="reused-native",
        origin_receipt_sha256=receipt_digest,
        request_made=False,
        url=row["url"],
        source_observed_at=row["fetched_at"],
        status_code=row["status_code"],
        outcome="accepted_core",
        response_bytes=len(body),
        response_complete=True,
        raw_path=raw_path,
        sha256=_digest(body),
    )


def _fetch_core(
    output: Path, row: dict[str, Any], remaining: int, client: httpx.Client
) -> NativeCreditCapture:
    recording, artist = row["recording_mbid"], row["cohort_artist_mbid"]
    url = recording_source_url(recording)
    observed_at = datetime.now(UTC).isoformat()
    body = bytearray()
    status, outcome, complete = None, "network_error", False
    if remaining <= 0:
        return NativeCreditCapture(
            **row,
            origin="fresh-lookup",
            origin_receipt_sha256=None,
            request_made=False,
            url=url,
            source_observed_at=None,
            status_code=None,
            outcome="byte_budget",
            response_bytes=0,
            response_complete=False,
            raw_path=None,
            sha256=None,
        )
    try:
        with client.stream("GET", url, timeout=20.0) as response:
            status = response.status_code
            outcome, complete = _core_response_body(response, body, remaining)
    except httpx.HTTPError:
        outcome = "network_error"
    raw_path, digest = None, None
    if outcome == "accepted_core":
        try:
            json_document(bytes(body))
            project_recording_fact(bytes(body), recording, artist)
        except (TypeError, ValueError, KeyError):
            outcome = "unapproved_payload"
        else:
            raw_path, digest = f"raw/credits/{recording}.json", _digest(body)
            (output / raw_path).write_bytes(body)
    return NativeCreditCapture(
        **row,
        origin="fresh-lookup",
        origin_receipt_sha256=None,
        request_made=True,
        url=url,
        source_observed_at=observed_at,
        status_code=status,
        outcome=outcome,
        response_bytes=len(body),
        response_complete=complete,
        raw_path=raw_path,
        sha256=digest,
    )


def _core_response_body(
    response: httpx.Response, body: bytearray, remaining: int
) -> tuple[Literal["unapproved_payload", "byte_budget", "accepted_core", "http_status"], bool]:
    media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        return "unapproved_payload", False
    for chunk in response.iter_bytes():
        if len(body) + len(chunk) > remaining:
            body.extend(chunk[: remaining - len(body)])
            return "byte_budget", False
        body.extend(chunk)
    return "accepted_core" if response.status_code == HTTPStatus.OK else "http_status", True


def build_native_pack(
    source: Path,
    benchmark: Path,
    core: Path,
    output: Path,
    *,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Build a fresh own-role pack; leave every original source and wrapper unchanged."""
    verify_recording_fact_pack(core)
    core_receipt_body = (core / "receipt.json").read_bytes()
    core_receipt = cast("dict[str, Any]", json_document(core_receipt_body))
    reuse = {
        (row["artist_mbid"], row["recording_mbid"]): row
        for row in core_receipt["captures"]
        if row["outcome"] == "accepted_core"
    }
    manifest = _import_sonic(source, benchmark, output)
    captures, total, requests = [], 0, 0
    pending_reuse_bytes = sum(
        reuse[(row["cohort_artist_mbid"], row["recording_mbid"])]["bytes"]
        for row in manifest["credit_request_roster"]
        if (row["cohort_artist_mbid"], row["recording_mbid"]) in reuse
    )
    if pending_reuse_bytes > MAX_CORE_BYTES:
        raise ValueError("reused core source bytes exceed native pack budget")
    last_request = None
    session = client or httpx.Client(
        follow_redirects=False,
        headers={
            "User-Agent": "OpenNoise/0.1 (bounded native CC0 recording credits; https://github.com/h0rv/opennoise)"
        },
    )
    try:
        for row in manifest["credit_request_roster"]:
            key = row["cohort_artist_mbid"], row["recording_mbid"]
            if key in reuse:
                capture = _reuse_core(core, output, reuse[key], _digest(core_receipt_body))
                pending_reuse_bytes -= capture.response_bytes
            else:
                if requests >= MAX_CORE_REQUESTS:
                    raise ValueError("native core request budget exceeded")
                if last_request is not None:
                    time.sleep(max(0.0, RATE_INTERVAL_SECONDS - (time.monotonic() - last_request)))
                last_request = time.monotonic()
                capture = _fetch_core(
                    output, row, MAX_CORE_BYTES - total - pending_reuse_bytes, session
                )
                requests += int(capture.request_made)
            total += capture.response_bytes
            captures.append(capture.model_dump())
            manifest["credit_captures"] = captures
            _write(output / "manifest.json", manifest)
            sys.stderr.write(
                f"Core credits {len(captures)}/{len(manifest['credit_request_roster'])}: "
                f"{capture.origin} {capture.outcome}\n"
            )
    finally:
        if client is None:
            session.close()
    projection = project_native_sonic(output, manifest)
    _write(output / "projection.json", projection)
    names = (
        {"manifest.json", "projection.json", "license-audit.json"}
        | {row["raw_path"] for row in manifest["sonic_captures"]}
        | {row["raw_path"] for row in captures if row["raw_path"] is not None}
    )
    _write(
        output / "receipt.json",
        {
            "revision": REVISION,
            "files": {
                name: {
                    "sha256": _digest((output / name).read_bytes()),
                    "size_bytes": (output / name).stat().st_size,
                }
                for name in sorted(names)
            },
        },
    )
    return verify_native_sonic(output)


def main() -> int:
    """Capture to a fresh destination, or replay the portable pack completely offline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--benchmark-source", type=Path)
    parser.add_argument("--core-facts", type=Path, default=Path("data/examples/recording-facts"))
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    try:
        if args.verify_only:
            report = verify_native_sonic(args.output)
        else:
            if args.source is None or args.benchmark_source is None:
                parser.error("capture requires --source and --benchmark-source")
            report = build_native_pack(
                args.source, args.benchmark_source, args.core_facts, args.output
            )
    except (OSError, TypeError, ValueError, KeyError) as error:
        sys.stderr.write(f"native sonic pack error: {error}\n")
        return 2
    sys.stdout.write(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "selected_recordings",
                    "state_counts",
                    "sonic_source_bytes",
                    "exact_credit_count",
                    "missing_credit_count",
                    "fresh_core_requests",
                    "reused_core_captures",
                    "core_response_bytes",
                    "missing_source_date_count",
                    "old_research_wrappers_promoted",
                    "full_corpus_claim",
                )
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
