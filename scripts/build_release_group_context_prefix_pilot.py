"""Build a 100k-record, target-masked release-group context sample; no training."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.serving.release_group_context_prefix import (
    DEFAULT_ARCHIVE_SHA256,
    DEFAULT_RECORD_CAP,
    build_context_prefix,
)


def main() -> int:
    """Write exact-credit, non-target source tokens from an explicit archive prefix."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--seed-target", type=Path, required=True)
    parser.add_argument(
        "--alias-config",
        type=Path,
        default=Path("config/reviewed_musicbrainz_seed_aliases_v1.json"),
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--record-cap", type=int, default=DEFAULT_RECORD_CAP)
    parser.add_argument("--expected-archive-sha256", default=DEFAULT_ARCHIVE_SHA256)
    arguments = parser.parse_args()
    report = build_context_prefix(
        archive=arguments.archive,
        reconciliation=arguments.reconciliation,
        seed_target=arguments.seed_target,
        alias_config=arguments.alias_config,
        output_root=arguments.output_root,
        record_cap=arguments.record_cap,
        expected_archive_sha256=arguments.expected_archive_sha256,
    )
    sys.stdout.write(json.dumps(report, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
