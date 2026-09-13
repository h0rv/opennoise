"""Write deterministic, abstention-preserving consensus micro-neighborhoods."""

# ruff: noqa: D103

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.peers.audit.strength_aware_peer_audit import build_consensus_micro_neighborhood_audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--direct", type=Path, required=True)
    parser.add_argument("--support", type=Path, required=True)
    parser.add_argument("--seed-reconciliation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(
        build_consensus_micro_neighborhood_audit(
            args.direct, args.support, args.seed_reconciliation
        ).model_dump_json(indent=2)
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
