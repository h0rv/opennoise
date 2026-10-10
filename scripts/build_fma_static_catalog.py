"""Build the separate native FMA source catalog after full offline custody replay."""

import argparse
import json
import sys
from pathlib import Path

from opennoise.deployment.fma_static import build_fma_static


def main() -> None:
    """Build only into a fresh local destination."""
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("source", "projected", "output"):
        parser.add_argument(f"--{flag}", required=True, type=Path)
    parser.add_argument("--source-genres", type=Path, help="optional verified Wikidata genre pack")
    parser.add_argument(
        "--artist-context-root", type=Path, help="repository with retained artist packs"
    )
    parser.add_argument("--related-music", type=Path, help="verified frozen descriptor suggestions")
    parser.add_argument(
        "--playback", type=Path, help="verified adjacent audio directory; offline attachment"
    )
    parser.add_argument("--descriptor-map", type=Path, help="verified fresh descriptor map")
    args = parser.parse_args()
    receipt = build_fma_static(
        source=args.source,
        projected=args.projected,
        output=args.output,
        source_genres=args.source_genres,
        artist_context_root=args.artist_context_root,
        related_music=args.related_music,
        playback=args.playback,
        descriptor_map=args.descriptor_map,
    )
    sys.stdout.write(
        json.dumps({key: value for key, value in receipt.items() if key != "files"}, indent=2)
        + "\n"
    )


if __name__ == "__main__":
    main()
