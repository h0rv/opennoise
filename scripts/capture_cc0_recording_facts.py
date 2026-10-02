"""Capture or replay bounded exact recording credits without supplementary tag responses."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from opennoise.serving.metadata.artist_works import verify_projected_artist_work_examples
from opennoise.serving.metadata.recording_facts import (
    LICENSE,
    LICENSE_URL,
    MAX_BYTES,
    MAX_REQUESTS,
    REVISION,
    project_recording_fact,
    recording_source_url,
    replay_recording_facts,
    selection_pairs,
    verify_recording_fact_pack,
)


def write_json(path: Path, value: object) -> bytes:
    """Write new readable provenance, refusing existing destinations."""
    body = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(body)
    return body


def capture_pack(output: Path, projection: Path, receipt: Path) -> dict[str, object]:  # noqa: C901, PLR0912 — bounded request/retention custody stays together.
    """Freeze source-only selections before requests and retain only validated core bytes."""
    source = verify_projected_artist_work_examples(projection, receipt)
    selection = {
        "revision": REVISION,
        "selection_method": (
            "First three bounded metadata examples per artist; "
            "first six for Aphex Twin and Four Tet. No new representative or historical rank claim."
        ),
        "source_projection_sha256": hashlib.sha256(projection.read_bytes()).hexdigest(),
        "artists": [
            {
                "artist_mbid": artist["artist_mbid"],
                "name": artist["name"],
                "recording_mbids": [
                    row["entity_id"].removeprefix("musicbrainz:recording:")
                    for row in artist["recordings"][
                        : 6 if artist["name"] in {"Aphex Twin", "Four Tet"} else 3
                    ]
                ],
            }
            for artist in source["artists"]
        ],
    }
    pairs = selection_pairs(selection)
    output.mkdir(parents=True, exist_ok=False)
    (output / "raw").mkdir()
    selection_body = write_json(output / "selection.json", selection)
    captures = []
    response_bytes = 0
    with httpx.Client(
        timeout=20,
        follow_redirects=False,
        headers={
            "User-Agent": "OpenNoise/0.1 (bounded CC0 metadata research; https://github.com/h0rv/opennoise)"
        },
    ) as client:
        for index, (artist, recording) in enumerate(pairs):
            if index:
                time.sleep(1.1)
            url = recording_source_url(recording)
            capture = {
                "artist_mbid": artist,
                "recording_mbid": recording,
                "url": url,
                "fetched_at": datetime.now(UTC).isoformat(),
                "status_code": None,
                "outcome": "network_error",
            }
            body = bytearray()
            try:
                with client.stream("GET", url) as response:
                    capture["status_code"] = response.status_code
                    if response.status_code != httpx.codes.OK:
                        capture["outcome"] = "http_status"
                    else:
                        for chunk in response.iter_bytes():
                            if response_bytes + len(chunk) > MAX_BYTES:
                                capture["outcome"] = "byte_budget"
                                break
                            response_bytes += len(chunk)
                            body.extend(chunk)
                        else:
                            capture["outcome"] = "accepted_core"
            except httpx.HTTPError:
                capture["outcome"] = "network_error"
            if capture["outcome"] == "accepted_core":
                try:
                    project_recording_fact(bytes(body), recording, artist)
                except (ValueError, KeyError, TypeError):
                    capture["outcome"] = "unapproved_payload"
                else:
                    path = f"raw/{recording}.json"
                    if (output / path).exists():
                        if (output / path).read_bytes() != body:
                            raise ValueError("repeated native recording lookup changed bytes")
                    else:
                        with (output / path).open("xb") as stream:
                            stream.write(body)
                    capture.update(
                        {
                            "path": path,
                            "sha256": hashlib.sha256(body).hexdigest(),
                            "bytes": len(body),
                        }
                    )
            captures.append(capture)
            sys.stderr.write(f"Recording {index + 1}/{len(pairs)}: {capture['outcome']}\n")
    artifact = replay_recording_facts(output, selection, captures)
    projection_body = write_json(output / "recording-facts.json", artifact)
    proof = {
        "revision": REVISION,
        "license": LICENSE,
        "license_url": LICENSE_URL,
        "scope": "portable_core_metadata_only",
        "metadata_only": True,
        "tags_or_genres_requested": False,
        "native_raw_policy": (
            "Only exact lookup responses passing recording/credit/artist core field allowlists "
            "retained. Mixed or unexpected responses contribute missingness only."
        ),
        "max_requests": MAX_REQUESTS,
        "max_response_bytes": MAX_BYTES,
        "request_count": len(captures),
        "response_bytes": response_bytes,
        "selection_sha256": hashlib.sha256(selection_body).hexdigest(),
        "projection_sha256": hashlib.sha256(projection_body).hexdigest(),
        "captures": captures,
    }
    write_json(output / "receipt.json", proof)
    verify_recording_fact_pack(output)
    return proof


def main() -> int:
    """Capture to a fresh directory, or independently verify an existing pack offline."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--projection",
        type=Path,
        default=Path("data/examples/representative-music/credited-examples.json"),
    )
    parser.add_argument(
        "--receipt", type=Path, default=Path("data/examples/representative-music/receipt.json")
    )
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        artifact = verify_recording_fact_pack(args.output)
        sys.stdout.write(
            json.dumps(
                {
                    "artists": len(artifact["artists"]),
                    "recordings": sum(len(a["recordings"]) for a in artifact["artists"]),
                    "missing": sum(a["missing_recordings"] for a in artifact["artists"]),
                }
            )
            + "\n"
        )
    else:
        proof = capture_pack(args.output, args.projection, args.receipt)
        sys.stdout.write(
            json.dumps(
                {"requests": proof["request_count"], "response_bytes": proof["response_bytes"]}
            )
            + "\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
