"""Expand exact-credit low-level CC0 metadata to ten recordings per pilot artist."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from http import HTTPStatus
from pathlib import Path
from uuid import UUID

import httpx
from pydantic import TypeAdapter

from opennoise.catalog.musicbrainz_candidate import require_local_candidate_destination
from opennoise.common import sha256_file, sha256_hex
from opennoise.ingest.acousticbrainz.capture import feature_url, verify_benchmarks
from opennoise.ingest.acousticbrainz.models import USER_AGENT, SourceCapture
from opennoise.ingest.acousticbrainz.projection import (
    json_document,
    project_low_level,
    verify_embedded_recording,
)

MAX_BYTES = 10_000_000
RESPONSE_CAP = 300_000


async def capture(source: Path, output: Path) -> dict[str, object]:  # noqa: C901, PLR0912, PLR0915 - bounded capture keeps gates together.
    """Retain streamed bytes under explicit total and per-response caps, without retries."""
    require_local_candidate_destination(output)
    verify_benchmarks(directory=source)
    captures = TypeAdapter(tuple[SourceCapture, ...]).validate_json(
        (source / "source-captures.json").read_bytes()
    )
    selected: list[tuple[str, str]] = []
    for row in captures:
        if row.kind != "search" or row.artist_mbid is None or row.payload_path is None:
            continue
        document = json_document((source / row.payload_path).read_bytes())
        recordings = document.get("recordings")
        if not isinstance(recordings, list):
            raise TypeError("search recordings missing")
        eligible = set()
        for recording in recordings:
            if not isinstance(recording, dict):
                continue
            artist_credits = recording.get("artist-credit", [])
            if not isinstance(artist_credits, list):
                continue
            for credit in artist_credits:
                if not isinstance(credit, dict) or not isinstance(credit.get("artist"), dict):
                    continue
                artist = credit["artist"]
                if artist.get("id") == str(row.artist_mbid):
                    eligible.add(str(UUID(str(recording["id"]))))
        selected.extend((str(row.artist_mbid), recording) for recording in sorted(eligible)[:10])
    cached = {
        (str(row.artist_mbid), str(row.recording_mbid)): row
        for row in captures
        if row.kind == "low-level"
    }
    output.mkdir(parents=True, exist_ok=False)  # noqa: ASYNC240 - serial local capture.
    (output / "raw").mkdir()
    script_bytes = Path(__file__).read_bytes()  # noqa: ASYNC240 - small script snapshot.
    (output / "executed-script.py").write_bytes(script_bytes)
    declaration = {
        "scope": "authorized_local_research",
        "implementation_sha256": sha256_hex(script_bytes),
        "source_receipt_sha256": sha256_file(source / "receipt.json")[0],
        "recordings": selected,
        "max_new_response_bytes": MAX_BYTES,
        "response_cap": RESPONSE_CAP,
        "audio_requested": False,
        "level": "low-level",
        "retries": 0,
        "rate_interval_seconds": 1.1,
        "raw_tags_consumed": False,
    }
    (output / "declaration.json").write_text(json.dumps(declaration, indent=2) + "\n")
    outcomes: list[dict[str, object]] = []
    total = 0
    requests = 0
    async with httpx.AsyncClient(
        timeout=20, follow_redirects=False, headers={"User-Agent": USER_AGENT}
    ) as client:
        for artist_id, recording_id in selected:
            old = cached.get((artist_id, recording_id))
            status = None
            payload = b""
            reused = old is not None
            state = "request_failed"
            if old is not None and old.payload_path is not None:
                payload = (source / old.payload_path).read_bytes()
                status = old.status_code
            elif total >= MAX_BYTES:
                state = "not_requested_byte_budget"
            else:
                await asyncio.sleep(1.1)
                requests += 1
                try:
                    async with client.stream(
                        "GET", feature_url(UUID(recording_id), "low-level")
                    ) as response:
                        status = response.status_code
                        chunks = []
                        remaining = min(RESPONSE_CAP, MAX_BYTES - total)
                        async for chunk in response.aiter_bytes():
                            retained = chunk[:remaining]
                            chunks.append(retained)
                            total += len(retained)
                            remaining -= len(retained)
                            if len(chunk) > len(retained) or remaining == 0:
                                state = "truncated_byte_budget"
                                break
                        payload = b"".join(chunks)
                except httpx.HTTPError:
                    state = "request_failed"
            raw_path = f"raw/{len(outcomes):03}.bin"
            (output / raw_path).write_bytes(payload)
            descriptors = []
            identity = "not_checked"
            if state != "truncated_byte_budget" and status == HTTPStatus.OK:
                try:
                    document = json_document(payload)
                    identity = verify_embedded_recording(document, UUID(recording_id))
                    descriptors = [
                        row.model_dump(mode="json") for row in project_low_level(document)
                    ]
                    state = "available" if identity == "matched" else "identity_absent"
                except ValueError:
                    state = "invalid_projection"
            elif status == HTTPStatus.NOT_FOUND:
                state = "missing_http_404"
            elif status is not None and state != "truncated_byte_budget":
                state = "http_error"
            outcomes.append(
                {
                    "artist_id": artist_id,
                    "recording_id": recording_id,
                    "state": state,
                    "status_code": status,
                    "identity": identity,
                    "reused": reused,
                    "payload_path": raw_path,
                    "payload_sha256": sha256_hex(payload),
                    "payload_bytes": len(payload),
                    "descriptors": descriptors,
                }
            )
    result: dict[str, object] = {
        "scope": declaration,
        "outcomes": outcomes,
        "new_requests": requests,
        "new_response_bytes": total,
        "state_counts": dict(Counter(str(row["state"]) for row in outcomes)),
        "source_license": "CC0-1.0",
        "source_attribution": "AcousticBrainz / MusicBrainz contributors",
        "product_promotion_allowed": False,
        "representative_sample": False,
    }
    (output / "projection.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    inventory = {
        str(path.relative_to(output)): sha256_file(path)[0]
        for path in sorted(output.rglob("*"))  # noqa: ASYNC240 - serial local inventory.
        if path.is_file()
    }
    (output / "receipt.json").write_text(json.dumps({"files": inventory}, indent=2) + "\n")
    return {key: result[key] for key in ("new_requests", "new_response_bytes", "state_counts")}


def main() -> int:
    """Require explicit source and fresh destination."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.stdout.write(json.dumps(asyncio.run(capture(args.source, args.output))) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
