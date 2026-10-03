"""Report twelve full-foundation acceptance gates and verify dossier file bindings."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import cast

from opennoise.pipeline.acceptance import inspect_acceptance


def main() -> int:
    """Return 0 for complete recorded reviews, 1 for gaps, 2 for invalid evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--dossier", type=Path, default=Path("docs/foundation/acceptance-dossier.json")
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        root = args.root.resolve()
        dossier_path = args.dossier if args.dossier.is_absolute() else root / args.dossier
        dossier = json.loads(dossier_path.read_text(encoding="utf-8"))
        report = inspect_acceptance(root, dossier)
    except (OSError, TypeError, ValueError) as error:
        sys.stderr.write(f"acceptance dossier error: {error}\n")
        return 2
    if args.json:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(f"Acceptance scope: {report['scope']}\n{report['interpretation']}\n")
        for gate in cast("list[dict[str, object]]", report["gates"]):
            sys.stdout.write(f"  {gate['status']}: {gate['gate']} — {gate['explanation']}\n")
        sys.stdout.write("Automatic semantic pass: false\n")
    if not report["evidence_valid"]:
        return 2
    return 0 if report["all_gates_recorded_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
