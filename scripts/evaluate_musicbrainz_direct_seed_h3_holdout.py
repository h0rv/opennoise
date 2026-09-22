"""Write an evaluation-only direct-seed/H3 positive-only receipt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from opennoise.checkpoints.direct_genre_seed_holdout import build_direct_genre_seed_holdout


def main() -> int:
    """Require fixed inputs and refuse to replace an existing evaluation receipt."""
    parser = argparse.ArgumentParser(prog="evaluate-musicbrainz-direct-seed-h3-holdout")
    parser.add_argument("--custody-receipt", type=Path, required=True)
    parser.add_argument("--custody-object-store", type=Path, required=True)
    parser.add_argument("--public-static-discovery", type=Path, required=True)
    parser.add_argument("--historical-semantic", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        raise FileExistsError(f"refusing to overwrite evaluation: {arguments.output}")
    report = build_direct_genre_seed_holdout(
        custody_receipt_path=arguments.custody_receipt,
        custody_object_store=arguments.custody_object_store,
        public_static_discovery_path=arguments.public_static_discovery,
        historical_semantic_path=arguments.historical_semantic,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
