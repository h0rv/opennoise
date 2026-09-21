"""Emit a local-only static-discovery review candidate to stdout."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opennoise.checkpoints.public_direct_bridge_candidate import CandidateInputs
from opennoise.checkpoints.public_direct_static_discovery_candidate import (
    build_public_direct_static_discovery_review_candidate,
)


def main() -> int:
    """Build a review candidate without writing or promoting a static asset."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-database", type=Path, required=True)
    parser.add_argument("--static-discovery", type=Path, required=True)
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--canonical-layout", type=Path, required=True)
    args = parser.parse_args()
    candidate = build_public_direct_static_discovery_review_candidate(
        CandidateInputs(
            public_database=args.public_database,
            static_discovery=args.static_discovery,
            reconciliation=args.reconciliation,
            canonical_layout=args.canonical_layout,
        )
    )
    sys.stdout.write(candidate.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
