"""Build the separately pinned four-artist extension strictly offline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from opennoise.deployment.fma_four_artist_extension import build


def main() -> None:
    """Bind exact sources and decode additions before creating a fresh local view."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("original-audio", "parent-audio", "capture", "proposal", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.original_audio, args.parent_audio, args.capture, args.proposal, args.output)
    print(json.dumps({"clips": len(result["tracks"]), "audio_bytes": result["audio_bytes"]}))  # noqa: T201 -- CLI evidence.


if __name__ == "__main__":
    main()
