"""Adapt one certified public SQLite release into approved candidate input."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from musix.serving.public.artist_membership_adapter import (
    CertifiedPublicMembershipAdapterPolicy,
    adapt_certified_public_membership_input,
)


def main() -> int:
    """Adapt certified rows and write the approved input plus replay receipt."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--approved-input", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    arguments = parser.parse_args()
    policy = CertifiedPublicMembershipAdapterPolicy.model_validate_json(
        arguments.policy.read_bytes()
    )
    adaptation = adapt_certified_public_membership_input(arguments.database, policy)
    arguments.approved_input.parent.mkdir(parents=True, exist_ok=True)
    arguments.approved_input.write_text(
        adaptation.approved_input.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    arguments.receipt.parent.mkdir(parents=True, exist_ok=True)
    arguments.receipt.write_text(
        adaptation.receipt.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    sys.stdout.write(
        json.dumps(
            {
                "database_file_sha256": adaptation.receipt.database_file_sha256,
                "approved_input_sha256": adaptation.receipt.approved_input_sha256,
                "adapter_receipt_sha256": adaptation.receipt.output_sha256,
                "direct_row_count": adaptation.receipt.direct_row_count,
                "aggregate_pair_count": adaptation.receipt.aggregate_pair_count,
                "aggregate_emitted_pairs": adaptation.receipt.aggregate_emitted_pairs,
            },
            indent=2,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
