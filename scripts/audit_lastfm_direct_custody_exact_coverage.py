"""Write a non-overwriting, local-only exact-MBID coverage receipt."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.analysis.lastfm_direct_custody_coverage import (
    LastFmDirectCustodyCoverageInputs,
    audit_lastfm_direct_custody_exact_coverage,
)


def main() -> int:
    """Refuse output replacement and keep the count-only audit local."""
    parser = argparse.ArgumentParser(prog="audit-lastfm-direct-custody-exact-coverage")
    parser.add_argument("--lastfm-artifact", type=Path, required=True)
    parser.add_argument("--lastfm-companion-receipt", type=Path, required=True)
    parser.add_argument("--lastfm-database", type=Path, required=True)
    parser.add_argument("--direct-custody-receipt", type=Path, required=True)
    parser.add_argument("--direct-custody-receipt-sha256", required=True)
    parser.add_argument("--direct-custody-object-store", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite local coverage report: {args.output}")
    inputs = LastFmDirectCustodyCoverageInputs(
        lastfm_artifact_path=args.lastfm_artifact,
        lastfm_companion_receipt_path=args.lastfm_companion_receipt,
        lastfm_database_path=args.lastfm_database,
        direct_custody_receipt_path=args.direct_custody_receipt,
        expected_direct_custody_receipt_sha256=args.direct_custody_receipt_sha256,
        direct_custody_object_store=args.direct_custody_object_store,
    )
    report = audit_lastfm_direct_custody_exact_coverage(inputs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        output.write(report.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
