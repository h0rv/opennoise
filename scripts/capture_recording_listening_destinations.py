"""Bind recording-specific source listening destinations without acquiring media."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from opennoise.serving.metadata.listening_destinations import (
    MAX_RECORDINGS,
    MAX_RESPONSE_BYTES,
    REVISION,
    digest,
    replay,
    write,
)
from opennoise.serving.metadata.recording_facts import verify_recording_fact_pack


def main() -> int:
    """Capture into new output or independently replay exact existing output."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if not args.verify:
        source = verify_recording_fact_pack(args.facts)
        selected = sorted(
            {
                (a["artist_mbid"], r["recording_mbid"])
                for a in source["artists"]
                for r in a["recordings"]
            }
        )
        if len(selected) > MAX_RECORDINGS:
            raise ValueError("recording request budget exceeded")
        args.output.mkdir(parents=True, exist_ok=False)
        captures = []
        total = 0
        with httpx.Client(
            timeout=25, headers={"User-Agent": "OpenNoise/0.1 (https://github.com/h0rv/opennoise)"}
        ) as client:
            for i, (artist, recording) in enumerate(selected):
                if i:
                    time.sleep(1.1)
                url = f"https://musicbrainz.org/ws/2/recording/{recording}?inc=artist-credits+url-rels&fmt=json"
                response = client.get(url)
                total += len(response.content)
                if total > MAX_RESPONSE_BYTES:
                    raise ValueError("listening metadata byte budget exceeded")
                path = f"recording-{i:03d}.json"
                with (args.output / path).open("xb") as stream:
                    stream.write(response.content)
                captures.append(
                    {
                        "artist": artist,
                        "recording": recording,
                        "url": url,
                        "path": path,
                        "status": response.status_code,
                        "fetched_at": datetime.now(UTC).isoformat(),
                        "sha256": digest(response.content),
                        "bytes": len(response.content),
                    }
                )
        write(
            args.output / "receipt.json",
            {"revision": REVISION, "selection": selected, "captures": captures},
        )
        write(args.output / "listening-destinations.json", replay(args.output, args.facts))
    result = replay(args.output, args.facts)
    if result != json.loads((args.output / "listening-destinations.json").read_bytes()):
        raise ValueError("listening projection differs from native replay")
    sys.stdout.write(
        json.dumps(
            {
                "eligible": result["eligible_recordings"],
                "source_resolved": len(result["recordings"]),
                "with_destinations": sum(bool(r["destinations"]) for r in result["recordings"]),
                "destinations": sum(len(r["destinations"]) for r in result["recordings"]),
                "availability_checked": False,
            }
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
