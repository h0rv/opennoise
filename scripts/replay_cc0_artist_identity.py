"""Rebuild exact artist joins from retained CC0 core projections and Wikidata raw evidence."""

import argparse
import json
import os
import resource
import signal
from pathlib import Path


def main() -> None:
    """Run a bounded offline two-order catalog regression build, without acquisition."""
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"
    resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    signal.alarm(120)
    from opennoise.pipeline.artist_identity_replay import replay  # noqa: PLC0415

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-source", type=Path, required=True)
    parser.add_argument("--core-source-sha256", required=True)
    parser.add_argument("--cultural-pack", type=Path, required=True)
    parser.add_argument("--cultural-receipt-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = replay(
        args.core_source,
        args.core_source_sha256,
        args.cultural_pack,
        args.cultural_receipt_sha256,
        args.output,
    )
    print(json.dumps(result, sort_keys=True))  # noqa: T201


if __name__ == "__main__":
    main()
