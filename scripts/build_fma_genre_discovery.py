"""Install a local genre-first entry page over two previously verified collections."""

import argparse
import json
from pathlib import Path

from opennoise.deployment.fma_genre_discovery import build_genre_discovery

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--root", type=Path, required=True)
args = parser.parse_args()
print(json.dumps(build_genre_discovery(args.root)["counts"], indent=2))  # noqa: T201 -- offline build receipt.
