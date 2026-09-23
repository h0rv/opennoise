"""Print a source-only exact-signature shadow-graph audit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.peers.signature_ablation import build_exact_signature_ablation_report


def main() -> int:
    """Verify the baseline receipt and print a deterministic local-only report."""
    parser = argparse.ArgumentParser(
        prog="audit-musicbrainz-direct-custody-exact-signature-ablation"
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    arguments = parser.parse_args()
    report = build_exact_signature_ablation_report(
        database=arguments.database, receipt_path=arguments.receipt
    )
    sys.stdout.write(json.dumps(report.model_dump(mode="json"), sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
