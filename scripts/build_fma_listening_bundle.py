"""Package an already verified local FMA listening site with a standalone launcher."""

import argparse
import json
from pathlib import Path

from opennoise.deployment.fma_listening_bundle import build_listening_bundle


def main() -> None:
    """Write a fresh local ZIP without acquisition or deployment."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_listening_bundle(args.site, args.output), indent=2))  # noqa: T201


if __name__ == "__main__":
    main()
