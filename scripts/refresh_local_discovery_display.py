"""Refresh only UI assets of a verified local discovery export."""

import argparse
import json
import sys
from pathlib import Path

from opennoise.deployment.discovery_display import refresh_discovery_display


def main() -> None:
    """Keep source/model bytes unchanged in a fresh hardlinked local output."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--representative-music", type=Path)
    args = parser.parse_args()
    receipt = refresh_discovery_display(
        source=args.source, output=args.output, representative_music=args.representative_music
    )
    sys.stdout.write(
        json.dumps(
            {
                "output_sha256": receipt["output_sha256"],
                "display_changed_files": sorted(receipt["display_changed_files"]),
                "unchanged_source_artifact_count": receipt["unchanged_source_artifact_count"],
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
