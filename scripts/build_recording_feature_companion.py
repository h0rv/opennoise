"""Build or replay exact recording features without downloads, fitting or imputation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from opennoise.pipeline.recording_feature_companion import build_companion, replay_companion


def main() -> None:
    """Require original native sources when joining normalized recording observations."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "replay"))
    parser.add_argument("--observations", required=True, type=Path)
    parser.add_argument("--sonic", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--native-source", type=Path)
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    if (args.native_source is None) != (args.root is None):
        parser.error("normalized observations require both --native-source and --root")
    operation = build_companion if args.action == "build" else replay_companion
    report = operation(
        args.observations,
        args.sonic,
        args.output,
        native_source=args.native_source,
        root=args.root,
    )
    print(json.dumps(report, indent=2, sort_keys=True))  # noqa: T201 - CLI evidence.


if __name__ == "__main__":
    main()
