"""Build the complete evidence frontier from sealed reconstruction artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from musix.evidence_frontier import (
    build_all_seed_evidence_frontier,
    publish_all_seed_evidence_frontier,
)
from musix.genre_hierarchy_candidates import GenreHierarchyCandidateArtifact
from musix.models.modeling import PublicModelInput
from musix.peer_similarity import GenrePeerSimilarityArtifact
from musix.public_taxonomy_expansion import PublicTaxonomyExpansionArtifact
from musix.seed_reconciliation import load_seed_reconciliation
from musix.storage import LocalObjectStore


def build_parser() -> argparse.ArgumentParser:
    """Expose an explicit artifact-only frontier boundary."""
    parser = argparse.ArgumentParser(prog="build-all-seed-evidence-frontier")
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--taxonomy-expansion", type=Path, required=True)
    parser.add_argument("--public-input", type=Path, required=True)
    parser.add_argument("--peer-similarity", type=Path, required=True)
    parser.add_argument(
        "--hierarchy-candidates",
        type=Path,
        help="Optional sealed hierarchy-candidate artifact; absence remains explicit in output.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    return parser


def main() -> int:
    """Build, gate, and publish one all-seed frontier."""
    arguments = build_parser().parse_args()
    reconciliation = load_seed_reconciliation(arguments.reconciliation)
    taxonomy = PublicTaxonomyExpansionArtifact.model_validate_json(
        arguments.taxonomy_expansion.read_bytes()
    )
    public_input = PublicModelInput.model_validate_json(arguments.public_input.read_bytes())
    peers = GenrePeerSimilarityArtifact.model_validate_json(arguments.peer_similarity.read_bytes())
    hierarchy_candidates = (
        GenreHierarchyCandidateArtifact.model_validate_json(
            arguments.hierarchy_candidates.read_bytes()
        )
        if arguments.hierarchy_candidates is not None
        else None
    )
    artifact = build_all_seed_evidence_frontier(
        reconciliation,
        taxonomy,
        public_input,
        peers,
        hierarchy_candidates,
    )
    receipt, _write = publish_all_seed_evidence_frontier(
        artifact, output_path=arguments.output, store=LocalObjectStore(arguments.object_store)
    )
    arguments.receipt.parent.mkdir(parents=True, exist_ok=True)
    arguments.receipt.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(
        json.dumps(
            {"coverage": artifact.coverage.model_dump(), "receipt": receipt.model_dump()}, indent=2
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
