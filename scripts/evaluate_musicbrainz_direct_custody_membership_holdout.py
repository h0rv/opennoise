"""Write a receipt-bound, local-only direct-custody membership holdout."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.peers.direct_custody_membership_holdout import (
    evaluate_direct_custody_membership_holdout,
)


def main() -> int:
    """Refuse replacement and evaluate only a verified local peer graph."""
    parser = argparse.ArgumentParser(prog="evaluate-musicbrainz-direct-custody-membership-holdout")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        raise FileExistsError(f"refusing to overwrite evaluation: {arguments.output}")
    report = evaluate_direct_custody_membership_holdout(
        database=arguments.database, receipt_path=arguments.receipt
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("x", encoding="utf-8") as output:
        output.write(report.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
