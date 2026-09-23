"""Verify the local Every Noise name projection against current semantic layout inputs."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.checkpoints.names_only_construction_boundary import (
    NamesOnlyConstructionBoundaryError,
    verify_names_only_construction_boundary,
    verify_names_only_construction_boundary_proof,
)


def main() -> int:
    """Print one local-only names-only construction proof."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-artifact", required=True, type=Path)
    parser.add_argument(
        "--peer-index",
        type=Path,
        default=Path(
            ".cache/musicbrainz-full-seed-targets/pipeline/peer-similarity-local-research.sqlite"
        ),
    )
    parser.add_argument(
        "--semantic-layout", type=Path, default=Path(".cache/semantic-map-layout-v3/artifact.json")
    )
    arguments = parser.parse_args()
    try:
        proof = verify_names_only_construction_boundary(
            seed_artifact=arguments.seed_artifact,
            peer_index=arguments.peer_index,
            semantic_layout=arguments.semantic_layout,
        )
        verify_names_only_construction_boundary_proof(proof)
    except NamesOnlyConstructionBoundaryError as error:
        parser.error(str(error))
    print(proof.model_dump_json(indent=2))  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
