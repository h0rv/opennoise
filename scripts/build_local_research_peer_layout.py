"""Build a non-exportable spectral layout from the compact local peer index."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from opennoise.serving.local.research_peer_layout import (
    LocalResearchPeerLayoutSettings,
    build_local_research_peer_layout,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-seed-count", type=int, default=6291)
    parser.add_argument("--neighbors-per-genre", type=int, default=10)
    parser.add_argument(
        "--layout-method",
        choices=("normalized_laplacian_spectral", "community_packed_spectral"),
        default="community_packed_spectral",
    )
    return parser.parse_args()


def main() -> int:
    """Write one deterministic local-only artifact from an explicit index path."""
    arguments = _arguments()
    try:
        artifact = build_local_research_peer_layout(
            arguments.index,
            settings=LocalResearchPeerLayoutSettings(
                expected_seed_count=arguments.expected_seed_count,
                neighbors_per_genre=arguments.neighbors_per_genre,
                layout_method=arguments.layout_method,
            ),
        )
        payload = artifact.model_dump_json(indent=2) + "\n"
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(payload, encoding="utf-8")
        byte_hash = hashlib.sha256(payload.encode()).hexdigest()
    except (OSError, ValueError) as error:
        sys.stderr.write(f"local research peer layout failed: {error}\n")
        return 2
    sys.stdout.write(f"logical sha256: {artifact.output_sha256}\n")
    sys.stdout.write(f"byte sha256: {byte_hash}\n")
    sys.stdout.write(
        "coverage: "
        f"coordinates={artifact.coverage.coordinate_count} "
        f"unplaced={artifact.coverage.unplaced_seed_count} "
        f"retained_edges={artifact.coverage.retained_peer_edge_count}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
