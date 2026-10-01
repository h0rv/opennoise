"""Plan and validate declared OpenNoise research and release inputs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import cast

from opennoise.pipeline.foundation import FOUNDATION, inspect, render_plan, validate_manifest


def main() -> int:
    """Run the manifest plan or validation command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "validate"), nargs="?", default="plan")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="checkout root to inspect")
    parser.add_argument("--json", action="store_true", help="print machine-readable report")
    parser.add_argument("--stage", help="inspect or validate only the named stage")
    parser.add_argument(
        "--manifest",
        type=Path,
        help="validate a manifest JSON file instead of the built-in inventory",
    )
    args = parser.parse_args()
    try:
        manifest = (
            FOUNDATION
            if args.manifest is None
            else json.loads(args.manifest.read_text(encoding="utf-8"))
        )
        validate_manifest(manifest)
        if args.stage:
            declared = cast("list[dict[str, object]]", manifest["stages"])
            selected = [stage for stage in declared if stage["id"] == args.stage]
            if not selected:
                raise ValueError(f"unknown foundation stage: {args.stage}")  # noqa: TRY301 - CLI reports this boundary failure.
            manifest = {**manifest, "stages": selected}
        report = inspect(args.root.resolve(), manifest)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        sys.stderr.write(f"foundation manifest error: {error}\n")
        return 2
    if args.json:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(render_plan(args.root.resolve(), manifest) + "\n")
    stages = cast("list[dict[str, object]]", report["stages"])
    if args.command == "validate" and any(not stage["ready"] for stage in stages):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
