"""Capture or independently replay a bounded source-selected Wikidata CC0 taxonomy."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.ingest.wikidata.open_genre_taxonomy import capture_pack, verify_pack


def main() -> int:
    """Preserve failures, report missingness, and never claim full taxonomy parity."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true", help="replay only; no network requests")
    args = parser.parse_args()
    try:
        report = verify_pack(args.output) if args.verify else capture_pack(args.output)
    except (OSError, TypeError, ValueError, AttributeError) as error:
        sys.stderr.write(f"open genre taxonomy error: {error}\n")
        return 2
    summary = {
        "class_verified": report["class_verified"],
        "selected_entities": len(report["entities"]),
        "taxonomy_claims": len(report["claims"]),
        "selection_possibly_truncated": report["selection_possibly_truncated"],
        "selection_error": report["selection_error"],
        "missing_taxonomy_qids": len(report["missing_taxonomy_qids"]),
        "taxonomy_complete_for_selected_cohort": report["taxonomy_complete_for_selected_cohort"],
        "missing_english_labels": len(report["missing_english_labels"]),
        "request_count": report["request_count"],
        "response_bytes": report["response_bytes"],
        "failed_request_count": report["failed_request_count"],
        "full_corpus_claim": False,
    }
    sys.stdout.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
