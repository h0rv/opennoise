"""Build the complete evidence frontier from sealed reconstruction artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from musix.evidence.frontier import (
    load_frontier_v4_source,
    publish_all_seed_evidence_frontier,
    upgrade_frontier_v4_with_listenbrainz_review,
)
from musix.ingest.listenbrainz.propagation import load_listenbrainz_propagation_frontier_summary
from musix.storage import LocalObjectStore


def build_parser() -> argparse.ArgumentParser:
    """Expose an explicit artifact-only frontier boundary."""
    parser = argparse.ArgumentParser(prog="build-all-seed-evidence-frontier")
    parser.add_argument(
        "--previous-frontier-v4",
        type=Path,
        required=True,
        help="Sealed Wikidata-fused v4 frontier whose direct/peer/hierarchy coverage v5 preserves.",
    )
    parser.add_argument(
        "--previous-frontier-v4-receipt",
        type=Path,
        required=True,
        help="Custody receipt whose byte and logical hashes bind the sealed v4 frontier.",
    )
    parser.add_argument(
        "--listenbrainz-propagation",
        type=Path,
        required=True,
        help="Sealed ListenBrainz v2 review artifact; candidates remain derived evidence.",
    )
    parser.add_argument(
        "--listenbrainz-propagation-receipt",
        type=Path,
        required=True,
        help="Custody receipt whose artifact and logical hashes bind ListenBrainz v2.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    return parser


def main() -> int:
    """Build, gate, and publish one all-seed frontier."""
    arguments = build_parser().parse_args()
    v4_source = load_frontier_v4_source(
        arguments.previous_frontier_v4, arguments.previous_frontier_v4_receipt
    )
    listenbrainz_review = load_listenbrainz_propagation_frontier_summary(
        arguments.listenbrainz_propagation,
        arguments.listenbrainz_propagation_receipt,
        seed_source_item_ids=frozenset(item.source_item_id for item in v4_source.rows),
    )
    artifact = upgrade_frontier_v4_with_listenbrainz_review(v4_source, listenbrainz_review)
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
