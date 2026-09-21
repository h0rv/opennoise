"""Export a source-bound, non-publishing packet for human bridge review."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.checkpoints.direct_bridge_audit import direct_bridge_review_packet


def main() -> int:
    """Write a deterministic review-only packet without touching its inputs."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--graph", type=Path, default=Path("data/model/open-construction-graph-v2.json")
    )
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=Path("data/public.sqlite"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    packet = direct_bridge_review_packet(args.graph, args.discovery, args.database)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sys.stdout.write(
        json.dumps(
            {
                "edge_count": packet["edge_count"],
                "potential_direct_observation_lift": packet["potential_direct_observation_lift"],
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
