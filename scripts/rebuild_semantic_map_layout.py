"""Rebuild semantic-map-layout-v2 from the sealed local evidence inputs."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.ml.semantic_layout import (
    SemanticLayoutInputs,
    build_semantic_map_layout,
    write_semantic_map_layout,
)

_PEER_INDEX = Path(
    ".cache/musicbrainz-full-seed-targets/pipeline/peer-similarity-local-research.sqlite"
)
_PEER_MANIFOLD = Path(".cache/musicbrainz-full-seed-targets/pipeline/peer-community-layout-v1.json")
_HIERARCHY = Path(".cache/hierarchy-fusion-v1/artifact.json")
_COLISTEN_ROOT = Path(
    ".cache/genre-colisten-neighborhoods-v1/"
    "32017c0a2cff27485671151663dfc9f184e8b2f9e354ba73d712e3ca8140b141"
)
_OUTPUT = Path(".cache/semantic-map-layout-v2/artifact.json")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=_OUTPUT)
    return parser.parse_args()


def main() -> int:
    """Produce a new v2 artifact; never reinterpret or relabel a v1 artifact."""
    arguments = _arguments()
    artifact = build_semantic_map_layout(
        SemanticLayoutInputs(
            peer_index=_PEER_INDEX,
            peer_manifold_artifact=_PEER_MANIFOLD,
            hierarchy_artifact=_HIERARCHY,
            colisten_artifact=_COLISTEN_ROOT / "artifact.json",
            colisten_cache=_COLISTEN_ROOT / "genre-neighborhoods.sqlite",
        )
    )
    write_semantic_map_layout(arguments.output, artifact)
    print(artifact.output_sha256)  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
