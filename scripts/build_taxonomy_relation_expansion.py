"""Build a provenance-bound taxonomy relation expansion from cached direct relations."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from musix.taxonomy.genre_hierarchy_candidates import GenreHierarchyCandidateArtifact
from musix.taxonomy.genre_seed_taxonomy import GenreSeedPublicTaxonomyArtifact
from musix.storage import LocalObjectStore
from musix.taxonomy.taxonomy_relation_expansion import (
    TaxonomyRelationExpansionPolicy,
    TaxonomyRelationHoldoutPolicy,
    build_taxonomy_relation_expansion,
    catalog_wikidata_p279_feed,
    load_taxonomy_relation_feed,
    merge_taxonomy_relation_feeds,
    publish_taxonomy_relation_expansion,
    split_taxonomy_relation_feed_for_holdout,
)


def main() -> None:
    """Read immutable source caches, project exact IDs, and publish one DAG artifact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument(
        "--relation-feed",
        type=Path,
        action="append",
        default=[],
        help=(
            "Hash-bound review-only relation feed; may be repeated. Generic feeds cannot "
            "produce accepted factual edges."
        ),
    )
    parser.add_argument(
        "--catalog-snapshot",
        type=Path,
        help=(
            "Optional CC0 catalog snapshot; the only checkpoint source that can replay "
            "accepted direct P279 facts locally."
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--expected-seed-count", type=int, default=6291)
    parser.add_argument(
        "--holdout-reference-candidates",
        type=Path,
        help="Optional evaluation oracle; its factual edges are removed from the training feed.",
    )
    parser.add_argument("--edge-modulus", type=int, default=5)
    parser.add_argument("--edge-remainder", type=int, default=0)
    parser.add_argument("--node-modulus", type=int, default=7)
    parser.add_argument("--node-remainder", type=int, default=0)
    arguments = parser.parse_args()
    store = LocalObjectStore(arguments.object_store)
    feeds = [load_taxonomy_relation_feed(path) for path in arguments.relation_feed]
    if arguments.catalog_snapshot is not None:
        feeds.append(catalog_wikidata_p279_feed(arguments.catalog_snapshot, store=store))
    if not feeds:
        parser.error("at least one --relation-feed or --catalog-snapshot is required")
    taxonomy = GenreSeedPublicTaxonomyArtifact.model_validate_json(arguments.taxonomy.read_bytes())
    feed = merge_taxonomy_relation_feeds(tuple(feeds))
    if arguments.holdout_reference_candidates is not None:
        reference = GenreHierarchyCandidateArtifact.model_validate_json(
            arguments.holdout_reference_candidates.read_bytes()
        )
        if reference.coverage.seed_count != len(taxonomy.seed_input.names):
            raise ValueError(
                "holdout reference candidates and taxonomy do not share a seed universe"
            )
        feed = split_taxonomy_relation_feed_for_holdout(
            taxonomy,
            feed,
            reference_factual_edges=frozenset(
                (item.child_genre_id, item.parent_genre_id)
                for item in reference.candidates
                if item.status == "accepted" and item.reason == "factual_public_taxonomy"
            ),
            policy=TaxonomyRelationHoldoutPolicy(
                edge_modulus=arguments.edge_modulus,
                edge_remainder=arguments.edge_remainder,
                node_modulus=arguments.node_modulus,
                node_remainder=arguments.node_remainder,
            ),
        )
    artifact = build_taxonomy_relation_expansion(
        taxonomy,
        feed,
        TaxonomyRelationExpansionPolicy(expected_seed_count=arguments.expected_seed_count),
        source_store=store,
    )
    receipt = publish_taxonomy_relation_expansion(artifact, output=arguments.output, store=store)
    arguments.receipt.parent.mkdir(parents=True, exist_ok=True)
    arguments.receipt.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(receipt.model_dump_json(indent=2) + "\n")


if __name__ == "__main__":
    main()
