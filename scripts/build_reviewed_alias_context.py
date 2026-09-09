"""Build a local retained-context enrichment for reviewed MusicBrainz aliases."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from musix.ingest.musicbrainz_reviewed_alias_context import (
    ReviewedAliasContextError,
    build_reviewed_alias_context,
    write_reviewed_alias_context,
)


def main() -> int:
    """Write one bounded, source-bound reviewed alias context artifact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--aliases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        artifact = build_reviewed_alias_context(
            baseline_path=arguments.baseline, alias_config_path=arguments.aliases
        )
        write_reviewed_alias_context(arguments.output, artifact)
    except (OSError, ReviewedAliasContextError, ValueError) as error:
        sys.stderr.write(f"reviewed alias context build failed: {error}\n")
        return 2
    sys.stdout.write(f"reviewed alias context memberships={len(artifact.memberships)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
