"""Write the retained AcousticBrainz overlap's permanent source-isolation no-go receipt."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opennoise.evidence.acousticbrainz_recording_gold_isolation import (
    audit_acousticbrainz_recording_gold_isolation,
    load_overlap_receipt,
)


def main() -> int:
    """Write a source-isolated no-go receipt without accepting caller-declared lineage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overlap-receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        overlap, receipt_sha256 = load_overlap_receipt(arguments.overlap_receipt)
        report = audit_acousticbrainz_recording_gold_isolation(
            overlap, overlap_receipt_sha256=receipt_sha256
        )
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as error:
        sys.stderr.write(f"AcousticBrainz source-isolation audit failed: {error}\n")
        return 2
    sys.stdout.write(report.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
