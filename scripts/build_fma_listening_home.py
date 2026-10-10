"""Create the local landing page after both listening collections are verified."""

import argparse
import json
from pathlib import Path

from opennoise.deployment.fma_listening_home import build_listening_home

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--root", type=Path, required=True)
args = parser.parse_args()
print(json.dumps(build_listening_home(args.root), indent=2))  # noqa: T201 -- offline receipt.
