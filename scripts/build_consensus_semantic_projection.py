"""Build the abstention-preserving local consensus semantic projection."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.projections.consensus_semantic import (
    ConsensusSemanticProjectionInputs,
    build_consensus_semantic_projection,
    write_consensus_semantic_projection,
)


def main() -> int:
    """Build from two explicit sealed inputs and write one deterministic artifact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--consensus", type=Path, required=True)
    parser.add_argument("--exact-qid-taxonomy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    projection = build_consensus_semantic_projection(
        ConsensusSemanticProjectionInputs(
            consensus_path=arguments.consensus,
            exact_qid_taxonomy_path=arguments.exact_qid_taxonomy,
        )
    )
    write_consensus_semantic_projection(arguments.output, projection)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
