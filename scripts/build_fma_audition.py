"""Build a new frozen two-listener audition from verified local data; no network."""

import argparse
import json
from pathlib import Path

from opennoise.deployment.fma_audition import build_audition

parser = argparse.ArgumentParser(description=__doc__)
for flag in ("site", "metadata-source", "output"):
    parser.add_argument(f"--{flag}", type=Path, required=True)
args = parser.parse_args()
result = build_audition(args.site, args.metadata_source, args.output)
print(json.dumps(result, indent=2))  # noqa: T201 -- frozen offline protocol receipt.
