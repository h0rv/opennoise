"""Build a separately bounded expanded listening collection strictly offline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from opennoise.deployment.fma_listening_collection import build_listening_collection


def main() -> None:
    """Preserve originals and assemble the verified new collection into a fresh directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("new-pack", "metadata-source", "baseline", "original-audio", "output"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    args = parser.parse_args()
    result = build_listening_collection(
        args.new_pack, args.metadata_source, args.baseline, args.original_audio, args.output
    )
    print(  # noqa: T201 -- CLI result.
        json.dumps(
            {
                "revision": result["revision"],
                "clips": len(result["tracks"]),
                "new_clips": len(result["expanded_track_ids"]),
                "original_clips": len(result["original_track_ids"]),
                "audio_bytes": result["audio_bytes"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
