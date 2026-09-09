"""Evaluate a taxonomy relation expansion against held-out factual source taxonomy."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from musix.storage import LocalObjectStore
from musix.taxonomy.relations.expansion import (
    TaxonomyRelationEvaluationInputs,
    TaxonomyRelationExpansionArtifact,
    TaxonomyRelationHoldoutPolicy,
    catalog_wikidata_p279_feed,
    evaluate_taxonomy_relation_expansion,
    load_taxonomy_relation_feed,
    merge_taxonomy_relation_feeds,
)
from musix.taxonomy.seeds.taxonomy import GenreSeedPublicTaxonomyArtifact
from musix.taxonomy.structure.hierarchy_candidates import GenreHierarchyCandidateArtifact

_EDGE_ENDPOINT_COUNT = 2


def _edge_pairs(path: Path) -> frozenset[tuple[str, str]]:
    """Parse an explicitly labelled JSON list of two-string edge arrays."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise TypeError("defensible negative edge file must contain a JSON list")
    pairs: set[tuple[str, str]] = set()
    for item in raw:
        if (
            not isinstance(item, list)
            or len(item) != _EDGE_ENDPOINT_COUNT
            or not all(isinstance(value, str) and value for value in item)
        ):
            raise ValueError("each defensible negative edge must be a two-string JSON array")
        pairs.add((item[0], item[1]))
    return frozenset(pairs)


def main() -> None:
    """Hide known factual source rows deterministically and emit an honest report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expansion", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument(
        "--reference-candidates",
        type=Path,
        required=True,
        help=(
            "Existing candidate artifact; only accepted factual_public_taxonomy rows "
            "are reference facts."
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--relation-feed",
        type=Path,
        action="append",
        default=[],
        help="Original immutable relation feed used before the holdout split; may be repeated.",
    )
    parser.add_argument("--catalog-snapshot", type=Path)
    parser.add_argument("--source-object-store", type=Path, required=True)
    parser.add_argument("--defensible-negative-edges", type=Path)
    parser.add_argument("--edge-modulus", type=int, default=5)
    parser.add_argument("--edge-remainder", type=int, default=0)
    parser.add_argument("--node-modulus", type=int, default=7)
    parser.add_argument("--node-remainder", type=int, default=0)
    arguments = parser.parse_args()
    expansion = TaxonomyRelationExpansionArtifact.model_validate_json(
        arguments.expansion.read_bytes()
    )
    taxonomy = GenreSeedPublicTaxonomyArtifact.model_validate_json(arguments.taxonomy.read_bytes())
    source_store = LocalObjectStore(arguments.source_object_store)
    feeds = [load_taxonomy_relation_feed(path) for path in arguments.relation_feed]
    if arguments.catalog_snapshot is not None:
        feeds.append(catalog_wikidata_p279_feed(arguments.catalog_snapshot, store=source_store))
    if not feeds:
        parser.error("at least one --relation-feed or --catalog-snapshot is required")
    reference = GenreHierarchyCandidateArtifact.model_validate_json(
        arguments.reference_candidates.read_bytes()
    )
    if reference.coverage.seed_count != len(taxonomy.seed_input.names):
        raise ValueError("reference candidates and taxonomy do not share a seed universe")
    report = evaluate_taxonomy_relation_expansion(
        expansion,
        taxonomy,
        TaxonomyRelationEvaluationInputs(
            full_relation_feed=merge_taxonomy_relation_feeds(tuple(feeds)),
            reference_factual_edges=frozenset(
                (item.child_genre_id, item.parent_genre_id)
                for item in reference.candidates
                if item.status == "accepted" and item.reason == "factual_public_taxonomy"
            ),
            holdout_policy=TaxonomyRelationHoldoutPolicy(
                edge_modulus=arguments.edge_modulus,
                edge_remainder=arguments.edge_remainder,
                node_modulus=arguments.node_modulus,
                node_remainder=arguments.node_remainder,
            ),
            source_store=source_store,
            defensible_negative_edges=(
                _edge_pairs(arguments.defensible_negative_edges)
                if arguments.defensible_negative_edges is not None
                else None
            ),
        ),
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(report.model_dump_json(indent=2) + "\n")


if __name__ == "__main__":
    main()
