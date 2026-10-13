"""Build the separately pinned eight-excerpt extension strictly offline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from opennoise.deployment.fma_eight_extension import build


def main() -> None:
    """Replay source pins and full decodes before producing a fresh local collection."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("parent-audio", "capture", "output"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    args = parser.parse_args()
    result = build(args.parent_audio, args.capture, args.output)
    print(json.dumps({"clips": len(result["tracks"]), "audio_bytes": result["audio_bytes"]}))  # noqa: T201 -- CLI evidence.


if __name__ == "__main__":
    main()
