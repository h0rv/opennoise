"""Construct or independently replay one selected-150 native recording catalog view."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from opennoise.serving.metadata.recording_catalog_export import export_catalog, replay_catalog


def main() -> None:
    """Every output directory is new; native metadata has no audio playback permissions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["export", "verify"])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    result = (export_catalog if args.command == "export" else replay_catalog)(
        args.source, args.root, args.output
    )
    print(json.dumps(result, sort_keys=True))  # noqa: T201 - bounded machine receipt.


if __name__ == "__main__":
    main()
