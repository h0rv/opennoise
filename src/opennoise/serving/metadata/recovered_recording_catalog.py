"""A separately declared source-reuse recipe; original v2 limits and captures stay frozen."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import zstandard

from opennoise.serving.metadata import full_recording_catalog as original

REVISION = "selected-150-native-core-browse-catalog-v3-recovered"
LIMITS = {**original.LIMITS, "metadata_reserve_bytes": 8_000_000}
ORIGINAL_PREFIX_SHA256 = "c0ede62497d22f1c629fd778ba7cadfcfc4ab9f6527a97b717a1620de69e9b02"

artist_summary = original.artist_summary
page_binding = original.page_binding
project_page = original.project_page
read_ledger = original.read_ledger


def request_plan(selection: dict[str, Any], candidates: dict[str, Any]) -> dict[str, Any]:
    """Keep the exact baseline-derived native request denominator and every source URL."""
    count = 0
    for artist in candidates["artists"]:
        native_count = artist.get("advertised_recording_count")
        if type(native_count) is not int or native_count < 0:
            raise ValueError("baseline native source count is not known")
        count += max((native_count + 99) // 100, 1) + 1
        if count > LIMITS["requests"]:
            raise ValueError("recovery request denominator exceeds cap before allocation")
    plan = original.request_plan(selection, candidates)
    return {**plan, "revision": REVISION, "limits": LIMITS}


def verify_ledger_order(plan: dict[str, Any], captures: list[dict[str, Any]]) -> None:
    """Apply the shared request/state guards; v3 byte allocation is independently checked."""
    if plan.get("revision") != REVISION or plan.get("limits") != LIMITS:
        raise ValueError("new recovery recipe policy differs")
    # The shared checker enforces identical request/body caps, native states and
    # timestamps. Its metadata allocation is not used by that checker; the v3
    # closed-pack verifier and collector independently enforce the declared 8MB.
    original.verify_ledger_order(
        {**plan, "revision": original.REVISION, "limits": original.LIMITS}, captures
    )


def verify_source_prefix(  # noqa: C901 - authenticate closure before bounded page replay.
    proof_path: Path, *, expected_sha256: str = ORIGINAL_PREFIX_SHA256
) -> dict[str, Any]:
    """Check closed immutable original files and independently replay every completed page."""
    from opennoise.ingest.musicbrainz.compressed_catalog_custody import (  # noqa: PLC0415
        replay_and_verify,
    )
    from opennoise.serving.metadata.selected_recording_catalog import sha256_file  # noqa: PLC0415

    if hashlib.sha256(proof_path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError("original source prefix proof differs from independently trusted pin")
    proof = json.loads(proof_path.read_bytes())
    directory = Path(proof["source_directory"])
    files = {str(p.relative_to(directory)) for p in directory.rglob("*") if p.is_file()}
    if files != set(proof["files"]) or any(p.is_symlink() for p in directory.rglob("*")):
        raise ValueError("interrupted source prefix closure differs")
    for relative, pin in proof["files"].items():
        if sha256_file(directory / relative) != (pin["sha256"], pin["bytes"]):
            raise ValueError("interrupted source prefix bytes changed")
    plan = json.loads((directory / "plan.json").read_bytes())
    captures = original.read_ledger(directory, plan, allow_partial=True)
    last_event = None
    with (directory / "request-ledger.jsonl").open("rb") as stream:
        for line in stream:
            last_event = json.loads(line)
    if last_event is None or last_event.get("event") != "outcome":
        raise ValueError(
            "unfinished original request needs a separately declared unknown-request budget"
        )
    if len(captures) != proof["completed_requests"] or len(captures) >= len(plan["requests"]):
        raise ValueError("source prefix count differs or falsely declares full acquisition")
    original.verify_ledger_order({**plan, "requests": plan["requests"][: len(captures)]}, captures)
    artist_index, position, identity = -1, 0, None
    for request, capture in zip(plan["requests"][: len(captures)], captures, strict=True):
        if request["artist_mbid"] != identity:
            identity = request["artist_mbid"]
            artist_index += 1
            position = 0
        custody = capture["custody"]
        relative = f"custody/{artist_index:03d}-{position:04d}.json.zst"
        if custody["path"] != relative or relative not in proof["files"]:
            raise ValueError("original native custody path differs from frozen request position")
        path = directory / relative
        position += 1
        replay_and_verify(path, custody)
        with path.open("rb") as encoded:  # noqa: SIM117 - decoder ends before source file.
            with zstandard.ZstdDecompressor(max_window_size=1048576).stream_reader(
                encoded
            ) as reader:
                body = reader.read(600001)
        if original.page_binding(original.project_page(body, request)) != capture["projection"]:
            raise ValueError("source prefix native page facts differ")
    return {
        "source_directory": str(directory),
        "source_proof_path": str(proof_path),
        "source_proof_sha256": hashlib.sha256(proof_path.read_bytes()).hexdigest(),
        "verified_prefix_requests": len(captures),
        "original_source_times_retained": True,
        "remaining_request_sequences": list(range(len(captures), len(plan["requests"]))),
    }


def verify_inherited_sources(
    directory: Path, *, expected_sha256: str = ORIGINAL_PREFIX_SHA256
) -> None:
    """Reject consistently rewritten inherited native values or acquisition timestamps."""
    from opennoise.serving.metadata.selected_recording_catalog import sha256_file  # noqa: PLC0415

    reuse = json.loads((directory / "source-reuse.json").read_bytes())
    verified = verify_source_prefix(
        Path(reuse["source_proof_path"]), expected_sha256=expected_sha256
    )
    if reuse != verified:
        raise ValueError("source reuse declaration differs from authenticated prefix")
    source = Path(reuse["source_directory"])
    proof = json.loads(Path(reuse["source_proof_path"]).read_bytes())
    with (
        (source / "request-ledger.jsonl").open("rb") as old_events,
        (directory / "request-ledger.jsonl").open("rb") as new_events,
    ):
        for event in old_events:
            if new_events.readline() != event:
                raise ValueError("inherited source events differ from original acquisition bytes")
    for relative, pin in proof["files"].items():
        if relative.startswith("custody/") and sha256_file(directory / relative) != (
            pin["sha256"],
            pin["bytes"],
        ):
            raise ValueError("inherited source frame differs from original native custody")
