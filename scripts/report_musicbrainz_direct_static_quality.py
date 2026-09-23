"""Write a local-only quality report for the pending MusicBrainz static candidate."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opennoise.checkpoints.musicbrainz_direct_static_quality_report import (
    MusicBrainzDirectStaticQualityReportError,
    build_musicbrainz_direct_static_quality_report,
    write_musicbrainz_direct_static_quality_report,
)


def main() -> int:
    """Write one pending-review report without exporting or serving candidate data."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--direct-custody-receipt", required=True, type=Path)
    parser.add_argument("--direct-custody-object-store", required=True, type=Path)
    parser.add_argument("--local-candidate-directory", required=True, type=Path)
    parser.add_argument("--policy-review-input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        report = build_musicbrainz_direct_static_quality_report(
            direct_custody_receipt_path=arguments.direct_custody_receipt,
            direct_custody_object_store=arguments.direct_custody_object_store,
            local_candidate_directory=arguments.local_candidate_directory,
            policy_review_input_path=arguments.policy_review_input,
        )
        byte_sha256 = write_musicbrainz_direct_static_quality_report(arguments.output, report)
    except (MusicBrainzDirectStaticQualityReportError, OSError, ValueError) as error:
        sys.stderr.write(f"local MusicBrainz static quality report failed: {error}\n")
        return 1
    sys.stdout.write(f"wrote local-only quality report: {byte_sha256}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
