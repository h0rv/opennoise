"""Build a compact receipt-rooted exact taxonomy relation hierarchy overlay."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from musix.taxonomy.structure.genre_hierarchy_candidates import GenreHierarchyCandidatePublicationReceipt
from musix.storage import LocalObjectStore
from musix.taxonomy.relations.taxonomy_relation_expansion import TaxonomyRelationExpansionArtifact
from musix.taxonomy.relations.taxonomy_relation_hierarchy_overlay import (
    OverlayBaseInputs,
    build_taxonomy_relation_hierarchy_overlay,
    publish_taxonomy_relation_hierarchy_overlay,
)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--base-hierarchy", type=Path, required=True)
parser.add_argument("--base-receipt", type=Path, required=True)
parser.add_argument("--base-object-store", type=Path, required=True)
parser.add_argument("--expected-base-receipt-sha256", required=True)
parser.add_argument("--relation-expansion", type=Path, required=True)
parser.add_argument("--relation-source-object-store", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--object-store", type=Path, required=True)
parser.add_argument("--receipt", type=Path, required=True)
args = parser.parse_args()
base_receipt_bytes = args.base_receipt.read_bytes()
overlay = build_taxonomy_relation_hierarchy_overlay(
    OverlayBaseInputs(
        hierarchy_path=args.base_hierarchy,
        receipt=GenreHierarchyCandidatePublicationReceipt.model_validate_json(base_receipt_bytes),
        receipt_sha256=hashlib.sha256(base_receipt_bytes).hexdigest(),
        expected_receipt_sha256=args.expected_base_receipt_sha256,
        object_store=LocalObjectStore(args.base_object_store),
    ),
    TaxonomyRelationExpansionArtifact.model_validate_json(args.relation_expansion.read_bytes()),
    relation_source_store=LocalObjectStore(args.relation_source_object_store),
)
receipt = publish_taxonomy_relation_hierarchy_overlay(
    overlay, output=args.output, store=LocalObjectStore(args.object_store)
)
args.receipt.parent.mkdir(parents=True, exist_ok=True)
args.receipt.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")
sys.stdout.write(receipt.model_dump_json(indent=2) + "\n")
