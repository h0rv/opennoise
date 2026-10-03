"""Build or independently replay the partial portable CC0 foundation offline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.pipeline.portable_foundation import (
    build_portable_foundation,
    inspect_legacy_inputs,
    validate_portable_foundation,
)
from opennoise.pipeline.portable_taxonomy import (
    build_portable_taxonomy,
    validate_portable_taxonomy,
)


def main() -> int:
    """Require a fresh output and keep legacy release inputs independently named."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "validate", "legacy-inputs"))
    parser.add_argument(
        "--profile",
        choices=("portable-cc0", "portable-taxonomy"),
        default="portable-cc0",
        help="partial selected-cohort profile; full foundation acceptance stays incomplete",
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path(".cache/open-foundation-portable-v1"))
    args = parser.parse_args()
    try:
        if args.command == "legacy-inputs":
            result = inspect_legacy_inputs(args.root)
        elif args.command == "build":
            builder = (
                build_portable_taxonomy
                if args.profile == "portable-taxonomy"
                else build_portable_foundation
            )
            result = builder(args.root, args.output)
        else:
            validator = (
                validate_portable_taxonomy
                if args.profile == "portable-taxonomy"
                else validate_portable_foundation
            )
            result = validator(args.root, args.output)
    except (OSError, ValueError, KeyError, TypeError) as error:
        sys.stderr.write(f"open foundation {args.command} failed: {error}\n")
        return 2
    sys.stdout.write(json.dumps(result, sort_keys=True, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
