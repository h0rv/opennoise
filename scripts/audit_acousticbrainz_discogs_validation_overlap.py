"""Write a local-only counts-only exact-ID AcousticBrainz overlap receipt."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.analysis.acousticbrainz_discogs_overlap import (
    audit_acousticbrainz_discogs_validation_overlap,
)


def main() -> int:
    """Refuse output replacement and never expose source label columns."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.output.exists():
        raise FileExistsError(f"refusing to overwrite audit receipt: {arguments.output}")
    report = audit_acousticbrainz_discogs_validation_overlap(
        arguments.source,
        arguments.catalog,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("x", encoding="utf-8") as output:
        output.write(report.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
