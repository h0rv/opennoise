"""Build a sealed, non-promoted public QID-to-positioned-seed receipt."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opennoise.checkpoints.public_qid_seed_map import (
    PublicQidSeedMapError,
    PublicQidSeedMapInputs,
    build_public_qid_seed_map,
    write_public_qid_seed_map,
)


def main() -> int:
    """Write a deterministic qualification receipt without exporting or promoting assets."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-database", type=Path, default=Path("data/public.sqlite"))
    parser.add_argument(
        "--canonical-layout", type=Path, default=Path(".cache/semantic-map-layout-v3/artifact.json")
    )
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        receipt = build_public_qid_seed_map(
            PublicQidSeedMapInputs(
                public_database=arguments.public_database,
                canonical_layout=arguments.canonical_layout,
            )
        )
        byte_sha256 = write_public_qid_seed_map(receipt, arguments.output)
    except (OSError, PublicQidSeedMapError, ValueError) as error:
        sys.stderr.write(f"public QID seed-map build failed: {error}\n")
        return 2
    sys.stdout.write(
        f"logical output sha256: {receipt.output_sha256}\n"
        f"written byte sha256: {byte_sha256}\n"
        f"coverage: {receipt.coverage.model_dump_json()}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
