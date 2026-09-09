"""Build and publish public multi-parent genre hierarchy candidates."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from musix.taxonomy.structure.genre_hierarchy_candidates import (
    GenreHierarchyCandidatePolicy,
    build_genre_hierarchy_candidates,
    publish_genre_hierarchy_candidates,
)
from musix.taxonomy.seeds.genre_seed_taxonomy import GenreSeedPublicTaxonomyArtifact
from musix.models.modeling import PublicModelInput
from musix.public_taxonomy_expansion import PublicTaxonomyExpansionArtifact
from musix.taxonomy.seeds.seed_reconciliation import SeedReconciliationArtifact
from musix.storage import LocalObjectStore
from musix.taxonomy.relations.taxonomy_relation_expansion import (
    TaxonomyRelationExpansionArtifact,
    TaxonomyRelationExpansionReceipt,
)


def main() -> None:
    """Build one hash-bound artifact from explicit public-only inputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--taxonomy-expansion", type=Path)
    parser.add_argument("--taxonomy-relation-expansion", type=Path)
    parser.add_argument("--taxonomy-relation-expansion-receipt", type=Path)
    parser.add_argument("--taxonomy-relation-source-object-store", type=Path)
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
    relation_expansion = (
        TaxonomyRelationExpansionArtifact.model_validate_json(
            arguments.taxonomy_relation_expansion.read_bytes()
        )
        if arguments.taxonomy_relation_expansion is not None
        else None
    )
    if (arguments.taxonomy_relation_expansion_receipt is None) != (relation_expansion is None):
        parser.error("taxonomy relation expansion and its receipt must be supplied together")
    if relation_expansion is not None:
        receipt = TaxonomyRelationExpansionReceipt.model_validate_json(
            arguments.taxonomy_relation_expansion_receipt.read_bytes()
        )
        if receipt.logical_output_sha256 != relation_expansion.output_sha256:
            raise ValueError("taxonomy relation receipt does not bind the supplied artifact")
        if arguments.taxonomy_relation_source_object_store is None:
            parser.error("taxonomy relation expansion requires its source object store")
        relation_store = LocalObjectStore(arguments.taxonomy_relation_source_object_store)
        stored = relation_store.inspect(receipt.artifact.key)
        if (
            stored.sha256 != receipt.artifact_sha256
            or stored.byte_size != receipt.artifact.byte_size
        ):
            raise ValueError(
                "taxonomy relation receipt artifact is absent or has substituted bytes"
            )
    else:
        relation_store = None
    public_input = PublicModelInput.model_validate_json(arguments.public_model_input.read_bytes())
    artifact = build_genre_hierarchy_candidates(
        reconciliation,
        taxonomy,
        public_input,
        GenreHierarchyCandidatePolicy(expected_seed_count=arguments.expected_seed_count),
        taxonomy_expansion=taxonomy_expansion,
        taxonomy_relation_expansion=relation_expansion,
        taxonomy_relation_source_store=relation_store,
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
