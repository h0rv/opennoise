"""Build a bounded local peer graph from the portable proper-genre custody source."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreCustodyReceipt,
)
from opennoise.peers.direct_custody_graph import (
    build_direct_custody_peer_graph,
    verify_direct_custody_peer_graph_receipt,
)

_PINNED_CUSTODY_RECEIPT_BYTE_SHA256 = (
    "41842340be1b661d3a12a55979f10771e5ce333282e34b92b959208028a4f615"
)


def main() -> int:
    """Build once and print the receipt-bound accounting report."""
    parser = argparse.ArgumentParser(prog="build-musicbrainz-direct-custody-peer-graph")
    parser.add_argument("--custody-receipt", type=Path, required=True)
    parser.add_argument("--custody-object-store", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--receipt-output", type=Path, required=True)
    arguments = parser.parse_args()
    receipt_bytes = arguments.custody_receipt.read_bytes()
    receipt_byte_sha256 = hashlib.sha256(receipt_bytes).hexdigest()
    if receipt_byte_sha256 != _PINNED_CUSTODY_RECEIPT_BYTE_SHA256:
        parser.error("custody receipt bytes differ from the pinned proper-genre receipt")
    custody = DirectProperGenreCustodyReceipt.model_validate_json(receipt_bytes)
    receipt = build_direct_custody_peer_graph(
        custody=custody,
        object_store=arguments.custody_object_store,
        custody_receipt_byte_sha256=receipt_byte_sha256,
        database=arguments.database,
        receipt_output=arguments.receipt_output,
    )
    verify_direct_custody_peer_graph_receipt(receipt, database=arguments.database)
    sys.stdout.write(json.dumps(receipt.model_dump(mode="json"), sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
