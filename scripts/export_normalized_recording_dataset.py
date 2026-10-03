"""Create or independently replay normalized, compressed native recording observations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from opennoise.serving.metadata.normalized_recording_dataset import export_dataset, replay_dataset


def main() -> None:
    """Export or verify reusable data without browser, audio or site composition."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["export", "verify"])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    result = (export_dataset if args.command == "export" else replay_dataset)(
        args.source, args.root, args.output
    )
    print(json.dumps(result, sort_keys=True))  # noqa: T201 - bounded machine data receipt.


if __name__ == "__main__":
    main()
