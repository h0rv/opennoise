"""Build a sealed, local-only peer candidate from a declared metadata source."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from musix.peers.support.peer import (
    ReleaseGroupSupportPeerError,
    build_support_peer_artifact,
    write_artifact_and_receipt,
)


def main() -> int:
    """Build a bounded support artifact and its immutable byte-binding receipt."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument(
        "--membership-table",
        choices=("release_group_support", "direct_anchor"),
        default="release_group_support",
    )
    parser.add_argument("--exclude-artist-id", action="append", default=[])
    arguments = parser.parse_args()
    try:
        artifact = build_support_peer_artifact(
            database=arguments.database,
            reconciliation=arguments.reconciliation,
            membership_table=arguments.membership_table,
            excluded_artist_ids=frozenset(arguments.exclude_artist_id),
        )
        write_artifact_and_receipt(artifact, arguments.output, arguments.receipt)
    except (OSError, ReleaseGroupSupportPeerError, sqlite3.Error) as error:
        sys.stderr.write(f"release-group peer build failed: {error}\n")
        return 2
    sys.stdout.write(
        json.dumps(
            {
                "component_kind": artifact.component_kind,
                "candidate_count": len(artifact.candidates),
                "output_sha256": artifact.output_sha256,
            }
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
