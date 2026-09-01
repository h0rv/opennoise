"""Verify the tracked, cache-first Phase 3 release manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from musix.pipeline.release_manifest import (
    load_release_manifest,
    verify_manifest_against_database,
)


def main() -> int:
    """Validate the manifest alone or compare it with a completed local database."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--release-directory",
        type=Path,
        default=Path("config/releases/phase3-public-20260831"),
    )
    parser.add_argument("--database", type=Path)
    arguments = parser.parse_args()
    if arguments.database is None:
        manifest = load_release_manifest(arguments.release_directory)
        result = {
            "release_id": manifest["release_id"],
            "input_artifacts": len(manifest["inputs"]),
            "qualification_selection_sha256": manifest["qualification"][
                "canonical_selection_sha256"
            ],
        }
    else:
        result = verify_manifest_against_database(arguments.release_directory, arguments.database)
    sys.stdout.write(f"{json.dumps(result, sort_keys=True)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
