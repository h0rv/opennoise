"""Write one immutable sealed-QID direct bridge qualification receipt."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opennoise.checkpoints.sealed_qid_direct_bridge import (
    SealedQidDirectBridgeError,
    SealedQidDirectBridgeInputs,
    build_sealed_qid_direct_bridge,
    write_sealed_qid_direct_bridge,
)


def main() -> int:
    """Build and write one non-promoted local qualification receipt."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-qid-seed-map", type=Path, required=True)
    parser.add_argument("--public-database", type=Path, default=Path("data/public.sqlite"))
    parser.add_argument("--base-static-discovery", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        receipt = build_sealed_qid_direct_bridge(
            SealedQidDirectBridgeInputs(
                public_qid_seed_map=arguments.public_qid_seed_map,
                public_database=arguments.public_database,
                base_static_discovery=arguments.base_static_discovery,
            )
        )
        byte_sha256 = write_sealed_qid_direct_bridge(receipt, arguments.output)
    except (OSError, ValueError, SealedQidDirectBridgeError) as error:
        sys.stderr.write(f"sealed QID direct bridge build failed: {error}\n")
        return 2
    sys.stdout.write(
        f"logical output sha256: {receipt.output_sha256}\n"
        f"written byte sha256: {byte_sha256}\n"
        f"coverage: {receipt.coverage.model_dump_json()}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
