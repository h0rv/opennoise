"""Build a landscape structural map from sealed open-evidence adapters."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.ml.semantic_layout import (
    SemanticLayoutInputs,
    build_semantic_map_layout,
    write_semantic_map_layout,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--peer-index", required=True, type=Path)
    parser.add_argument("--peer-manifold-artifact", required=True, type=Path)
    parser.add_argument("--hierarchy-artifact", required=True, type=Path)
    parser.add_argument("--colisten-artifact", required=True, type=Path)
    parser.add_argument("--colisten-cache", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    """Build one deterministic artifact and print its compact identity."""
    arguments = _arguments()
    artifact = build_semantic_map_layout(
        SemanticLayoutInputs(
            peer_index=arguments.peer_index,
            peer_manifold_artifact=arguments.peer_manifold_artifact,
            hierarchy_artifact=arguments.hierarchy_artifact,
            colisten_artifact=arguments.colisten_artifact,
            colisten_cache=arguments.colisten_cache,
        )
    )
    write_semantic_map_layout(arguments.output, artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
