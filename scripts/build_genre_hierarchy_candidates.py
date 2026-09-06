"""Build and publish public multi-parent genre hierarchy candidates."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from musix.genre_hierarchy_candidates import (
    GenreHierarchyCandidatePolicy,
    build_genre_hierarchy_candidates,
    publish_genre_hierarchy_candidates,
)
from musix.genre_seed_taxonomy import GenreSeedPublicTaxonomyArtifact
from musix.models.modeling import PublicModelInput
from musix.public_taxonomy_expansion import PublicTaxonomyExpansionArtifact
from musix.seed_reconciliation import SeedReconciliationArtifact
from musix.storage import LocalObjectStore


def main() -> None:
    """Build one hash-bound artifact from explicit public-only inputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--taxonomy-expansion", type=Path)
    parser.add_argument("--public-model-input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--expected-seed-count", type=int, default=6291)
    arguments = parser.parse_args()
    reconciliation = SeedReconciliationArtifact.model_validate_json(
        arguments.reconciliation.read_bytes()
    )
    taxonomy = GenreSeedPublicTaxonomyArtifact.model_validate_json(arguments.taxonomy.read_bytes())
    taxonomy_expansion = (
        PublicTaxonomyExpansionArtifact.model_validate_json(
            arguments.taxonomy_expansion.read_bytes()
        )
        if arguments.taxonomy_expansion is not None
        else None
    )
    public_input = PublicModelInput.model_validate_json(arguments.public_model_input.read_bytes())
    artifact = build_genre_hierarchy_candidates(
        reconciliation,
        taxonomy,
        public_input,
        GenreHierarchyCandidatePolicy(expected_seed_count=arguments.expected_seed_count),
        taxonomy_expansion=taxonomy_expansion,
    )
    receipt = publish_genre_hierarchy_candidates(
        artifact,
        output=arguments.output,
        store=LocalObjectStore(arguments.object_store),
    )
    arguments.receipt.parent.mkdir(parents=True, exist_ok=True)
    arguments.receipt.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(receipt.model_dump_json(indent=2) + "\n")


if __name__ == "__main__":
    main()
