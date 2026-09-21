"""Audit catalog identity edges without changing any serving artifact."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.checkpoints.direct_bridge_audit import audit_direct_bridges


def main() -> int:
    """Write a deterministic direct-bridge audit report."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--graph", type=Path, default=Path("data/model/open-construction-graph-v2.json")
    )
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=Path("data/public.sqlite"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit_direct_bridges(args.graph, args.discovery, args.database)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        key: report[key]
        for key in ("edge_count", "classification_counts", "potential_direct_observation_lift")
    }
    sys.stdout.write(f"{json.dumps(summary, indent=2, sort_keys=True)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
