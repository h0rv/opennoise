"""Write a new local core-note candidate; never install or publish it implicitly."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.pipeline.artist_identity_notes import project
from opennoise.pipeline.catalog_demo import write


def main() -> None:
    """Reconstruct notes and their complete accounting in an unused directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    output = args.output.resolve()
    if not output.is_relative_to(root / ".cache"):
        raise ValueError("Identity-note candidates must remain in the local cache")
    output.mkdir(parents=True, exist_ok=False)
    payload, report = project(root)
    write(output / "notes.json", payload)
    write(output / "report.json", report)
    print(payload["counts"])  # noqa: T201 -- Bounded local candidate summary.


if __name__ == "__main__":
    main()
