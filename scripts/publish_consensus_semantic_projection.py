"""Wrap a sealed consensus semantic projection in its UI-agnostic publication contract."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.projections.consensus_publication import (
    ConsensusSemanticPublicationInputs,
    build_consensus_semantic_publication,
    write_consensus_semantic_publication,
)


def main() -> int:
    """Publish from one explicit, sealed source-neutral projection artifact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    publication = build_consensus_semantic_publication(
        ConsensusSemanticPublicationInputs(projection_path=arguments.projection)
    )
    write_consensus_semantic_publication(arguments.output, publication)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
