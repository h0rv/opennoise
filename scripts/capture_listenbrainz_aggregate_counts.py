#!/usr/bin/env python3
"""Capture and replay the small, fixed ListenBrainz recording-count roster."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from opennoise.ingest.listenbrainz.aggregate_counts import (  # noqa: E402
    _native_roster,
    build_projection,
    verify_pack,
)

DEFAULT_OUTPUT = REPO / ".cache/private/listenbrainz-counts"
FACTS_PATH = REPO / "data/examples/recording-facts/recording-facts.json"
API_URL = "https://api.listenbrainz.org/1/popularity/recording"
MAX_REQUEST_BYTES = 10_000
MAX_RESPONSE_BYTES = 100_000
MAX_ITEMS_PER_REQUEST = 100
HTTP_OK = 200


def sha256(body: bytes) -> str:
    """Return a lowercase SHA-256 digest for exact source bytes."""
    return hashlib.sha256(body).hexdigest()


def write_json(path: Path, value: object) -> bytes:
    """Write deterministic JSON and return its exact UTF-8 bytes."""
    body = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    path.write_bytes(body)
    return body


def capture(output: Path) -> None:
    """Make one no-retry request and retain only a strictly valid response."""
    # The legal proof was obtained and checked before this one network request.
    legal_manifest = output / "legal-proof/manifest.json"
    if not legal_manifest.is_file():
        raise SystemExit("refusing capture until legal-proof/manifest.json exists")
    if (output / "receipt.json").exists() or (
        output / "raw/recording-counts-response.json"
    ).exists():
        raise SystemExit("refusing to overwrite an existing capture")

    roster = _native_roster(FACTS_PATH)
    ids = [row["recording_mbid"] for row in roster]
    request_body = json.dumps({"recording_mbids": ids}, separators=(",", ":")).encode("ascii")
    if len(ids) > MAX_ITEMS_PER_REQUEST or len(request_body) > MAX_REQUEST_BYTES:
        raise SystemExit("frozen request exceeds the configured safety cap")

    req = Request(
        API_URL,
        data=request_body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    requested_at = dt.datetime.now(dt.UTC).isoformat()
    try:
        # Exactly one attempt. Do not retry timeouts or unknown outcomes.
        with urlopen(req, timeout=30) as response:  # noqa: S310
            status = response.status
            if response.url != API_URL:
                raise SystemExit(f"unexpected redirect target: {response.url}")
            response_body = response.read(MAX_RESPONSE_BYTES + 1)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise SystemExit(f"single request failed; no retry was made: {exc}") from exc

    if status != HTTP_OK:
        raise SystemExit(f"expected HTTP 200, received {status}; no retry was made")
    if len(response_body) > MAX_RESPONSE_BYTES:
        raise SystemExit("response exceeds 100 KB cap; response was not retained")
    try:
        source_rows = json.loads(response_body)
        projection = build_projection(source_rows, roster)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(
            f"response failed strict validation; no files were published: {exc}"
        ) from exc

    raw_dir = output / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    request_path = raw_dir / "recording-counts-request.json"
    response_path = raw_dir / "recording-counts-response.json"
    request_path.write_bytes(request_body)
    response_path.write_bytes(response_body)
    projection_body = write_json(output / "recording-counts.json", projection)

    receipt = {
        "revision": "listenbrainz-recording-aggregate-counts-capture-v1",
        "provider": "ListenBrainz",
        "data_license": "unresolved blended ListenBrainz + MLHD+ aggregate",
        "license_scope": (
            "private cache pending explicit redistribution rights proof for both inputs"
        ),
        "export_allowed": False,
        "serving_allowed": False,
        "model_input_allowed": False,
        "endpoint": API_URL,
        "request_started_at": requested_at,
        "fetched_at": dt.datetime.now(dt.UTC).isoformat(),
        "status_code": status,
        "request_count": 1,
        "requested_count": len(ids),
        "request_sha256": sha256(request_body),
        "request_bytes": len(request_body),
        "response_sha256": sha256(response_body),
        "response_bytes": len(response_body),
        "projection_sha256": sha256(projection_body),
        "missing_ids": projection["missing_ids"],
        "suppressed_ids": projection["suppressed_ids"],
        "display_rule": "public display only when total_user_count >= 5",
        "request_retries": 0,
        "request_redirects_followed": 0,
    }
    write_json(output / "receipt.json", receipt)
    sys.stdout.write(json.dumps(verify_pack(output), sort_keys=True) + "\n")


def main() -> None:
    """Run a fresh bounded capture or the offline replay check."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        sys.stdout.write(json.dumps(verify_pack(args.output), sort_keys=True) + "\n")
    else:
        capture(args.output)


if __name__ == "__main__":
    main()
