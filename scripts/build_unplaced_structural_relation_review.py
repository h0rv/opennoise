"""Create one local review packet for unplaced genre structural relations."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.checkpoints.unplaced_structural_relation_review import (
    build_unplaced_structural_relation_review_packet,
    write_unplaced_structural_relation_review_packet,
)


def main() -> int:
    """Build the packet from three existing immutable local artifacts."""
    parser = argparse.ArgumentParser(prog="build-unplaced-structural-relation-review")
    parser.add_argument("--hierarchy", type=Path, required=True)
    parser.add_argument("--colisten", type=Path, required=True)
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    packet = build_unplaced_structural_relation_review_packet(
        hierarchy_path=arguments.hierarchy,
        colisten_path=arguments.colisten,
        layout_path=arguments.layout,
    )
    write_unplaced_structural_relation_review_packet(arguments.output, packet)
    print(packet.model_dump_json())  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
