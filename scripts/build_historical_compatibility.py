"""Build and publish a bounded historical compatibility manifest from retained HTML."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from musix.historical_compatibility import (
    build_historical_compatibility,
    coverage_quality_report,
    publish_historical_compatibility,
)
from musix.storage import LocalObjectStore


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source", type=Path, required=True, help="Verified retained Every Noise HTML"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/historical/historical-compatibility-v1.json"),
    )
    parser.add_argument("--database", type=Path, default=Path("data/musix.sqlite"))
    parser.add_argument("--object-store", type=Path, default=Path("data/objects"))
    return parser.parse_args()


def main() -> int:
    """Publish a complete H1/H2 compatibility snapshot and explicit H3-H6 gaps."""
    arguments = _arguments()
    try:
        manifest = build_historical_compatibility(arguments.source.read_bytes())
        summary = publish_historical_compatibility(
            manifest=manifest,
            output_path=arguments.output,
            store=LocalObjectStore(arguments.object_store),
            database_path=arguments.database,
        )
    except (OSError, ValueError, RuntimeError) as error:
        sys.stderr.write(f"historical compatibility build failed: {error}\n")
        return 2
    sys.stdout.write(summary.model_dump_json(indent=2) + "\n")
    sys.stdout.write(f"{coverage_quality_report(manifest)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
