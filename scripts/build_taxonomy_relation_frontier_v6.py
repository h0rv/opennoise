"""Seal a compact v6 all-seed frontier wrapper over v5 and taxonomy overlay receipts."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from opennoise.evidence.frontier import EvidenceFrontierReceipt
from opennoise.storage import LocalObjectStore
from opennoise.taxonomy.relations.frontier_v6 import (
    FrontierV6Inputs,
    build_taxonomy_relation_frontier_v6,
    publish_taxonomy_relation_frontier_v6,
)
from opennoise.taxonomy.relations.hierarchy_overlay import TaxonomyRelationHierarchyOverlayReceipt


def main() -> int:
    """Build one compact, receipt-rooted v6 wrapper without reconstructing hierarchy."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v5-frontier", type=Path, required=True)
    parser.add_argument("--v5-receipt", type=Path, required=True)
    parser.add_argument("--v5-object-store", type=Path, required=True)
    parser.add_argument("--expected-v5-receipt-sha256", required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--overlay-receipt", type=Path, required=True)
    parser.add_argument("--overlay-object-store", type=Path, required=True)
    parser.add_argument("--expected-overlay-receipt-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    arguments = parser.parse_args()
    v5_receipt_bytes = arguments.v5_receipt.read_bytes()
    overlay_receipt_bytes = arguments.overlay_receipt.read_bytes()
    artifact = build_taxonomy_relation_frontier_v6(
        FrontierV6Inputs(
            v5_path=arguments.v5_frontier,
            v5_receipt=EvidenceFrontierReceipt.model_validate_json(v5_receipt_bytes),
            v5_receipt_sha256=hashlib.sha256(v5_receipt_bytes).hexdigest(),
            expected_v5_receipt_sha256=arguments.expected_v5_receipt_sha256,
            v5_object_store=LocalObjectStore(arguments.v5_object_store),
            overlay_path=arguments.overlay,
            overlay_receipt=TaxonomyRelationHierarchyOverlayReceipt.model_validate_json(
                overlay_receipt_bytes
            ),
            overlay_receipt_sha256=hashlib.sha256(overlay_receipt_bytes).hexdigest(),
            expected_overlay_receipt_sha256=arguments.expected_overlay_receipt_sha256,
            overlay_object_store=LocalObjectStore(arguments.overlay_object_store),
        )
    )
    receipt = publish_taxonomy_relation_frontier_v6(
        artifact, output=arguments.output, store=LocalObjectStore(arguments.object_store)
    )
    arguments.receipt.parent.mkdir(parents=True, exist_ok=True)
    arguments.receipt.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(receipt.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
