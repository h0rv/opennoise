"""Capture or replay eight native per-track licensed FMA excerpts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.serving.metadata.fma_listening import capture_audio, verify_fma_listening_pack


def main() -> int:
    """Capture to new output or independently replay exact existing source artifacts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--probe", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if not args.verify:
        if args.probe is None:
            parser.error("--probe is required for acquisition")
        capture_audio(args.source, args.probe, args.output)
    result = verify_fma_listening_pack(args.output, args.source)
    sys.stdout.write(
        json.dumps({"tracks": len(result["tracks"]), "audio_bytes": result["audio_bytes"]}) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
