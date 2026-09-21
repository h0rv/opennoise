"""Project one receipt-bound schema-12 Phase 3 candidate locally without replacement."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opennoise.pipeline.candidate_public_projection import (
    CandidatePublicProjectionError,
    CandidatePublicProjectionSettings,
    project_candidate_public_model,
)


def main() -> int:
    """Run the explicit local-only candidate projection."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-directory", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--replay-receipt", type=Path, required=True)
    parser.add_argument("--expected-candidate-sha256", required=True)
    parser.add_argument("--expected-replay-receipt-sha256", required=True)
    parser.add_argument("--output-database", type=Path, required=True)
    parser.add_argument("--model-output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        report = project_candidate_public_model(
            CandidatePublicProjectionSettings(
                release_directory=arguments.release_directory,
                candidate_database=arguments.candidate,
                replay_receipt=arguments.replay_receipt,
                expected_candidate_sha256=arguments.expected_candidate_sha256,
                expected_replay_receipt_sha256=arguments.expected_replay_receipt_sha256,
                output_database=arguments.output_database,
                model_output=arguments.model_output,
                report_output=arguments.report_output,
            )
        )
    except CandidatePublicProjectionError as error:
        sys.stderr.write(f"candidate public projection failed: {error}\n")
        return 2
    sys.stdout.write(report.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
