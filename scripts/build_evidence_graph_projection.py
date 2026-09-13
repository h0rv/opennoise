"""Build the source-neutral, local evidence graph checkpoint."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from time import monotonic

from opennoise.evidence.graph_projection import (
    EvidenceGraphProjectionInputs,
    build_evidence_graph_projection,
    write_evidence_graph_projection,
)

_INPUT_OPTIONS: tuple[str, ...] = (
    "frontier",
    "musicbrainz-database",
    "musicbrainz-artifact",
    "reviewed-alias-context",
    "taxonomy-relation",
    "direct-peer",
    "support-peer",
    "filtered-support-peer",
)


def main() -> None:
    """Parse sealed inputs, write the SQLite graph, then atomically write its receipt."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in _INPUT_OPTIONS:
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--output-database", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    started = monotonic()
    sys.stderr.write("evidence graph: verifying and hashing inputs\n")
    artifact = build_evidence_graph_projection(
        EvidenceGraphProjectionInputs(
            frontier_path=args.frontier,
            musicbrainz_database=args.musicbrainz_database,
            musicbrainz_artifact_path=args.musicbrainz_artifact,
            reviewed_alias_context_path=args.reviewed_alias_context,
            taxonomy_relation_path=args.taxonomy_relation,
            direct_peer_path=args.direct_peer,
            support_peer_path=args.support_peer,
            filtered_support_peer_path=args.filtered_support_peer,
            output_database=args.output_database,
        )
    )
    elapsed = monotonic() - started
    sys.stderr.write(f"evidence graph: database built in {elapsed:.1f}s; writing receipt\n")
    write_evidence_graph_projection(args.receipt, artifact)
    sys.stdout.write(artifact.model_dump_json(indent=2) + "\n")


if __name__ == "__main__":
    main()
