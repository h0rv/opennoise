"""Write one local-only matched direct-custody and co-listen holdout receipt."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.peers.direct_custody_colisten_holdout import evaluate_direct_custody_colisten_holdout


def main() -> int:
    """Refuse replacement and write one receipt-bound local-only comparison."""
    parser = argparse.ArgumentParser(prog="evaluate-musicbrainz-direct-custody-colisten-holdout")
    parser.add_argument("--direct-database", type=Path, required=True)
    parser.add_argument("--direct-receipt", type=Path, required=True)
    parser.add_argument("--colisten-database", type=Path, required=True)
    parser.add_argument("--colisten-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite evaluation: {args.output}")
    report = evaluate_direct_custody_colisten_holdout(
        direct_database=args.direct_database,
        direct_receipt_path=args.direct_receipt,
        colisten_database=args.colisten_database,
        colisten_receipt_path=args.colisten_receipt,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        output.write(report.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
