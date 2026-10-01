"""Build the cache-only named style atlas from exact feature and prediction caches."""

import argparse
import json
import sys
from pathlib import Path

from opennoise.deployment.style_atlas import build_style_atlas, refresh_style_atlas_display


def main() -> None:
    """Export separately typed complete source and inferred artist cohorts."""
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("source", "features", "enrichment"):
        parser.add_argument(f"--{flag}", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--refresh-from", type=Path)
    args = parser.parse_args()
    if args.refresh_from:
        if any((args.source, args.features, args.enrichment)):
            parser.error("--refresh-from cannot be combined with construction inputs")
        receipt = refresh_style_atlas_display(source=args.refresh_from, output=args.output)
    else:
        if not all((args.source, args.features, args.enrichment)):
            parser.error("construction requires --source, --features and --enrichment")
        receipt = build_style_atlas(
            source=args.source,
            features=args.features,
            enrichment_directory=args.enrichment,
            output=args.output,
        )
    sys.stdout.write(
        json.dumps(
            {"coverage": receipt["coverage"], "output_sha256": receipt["output_sha256"]}, indent=2
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
