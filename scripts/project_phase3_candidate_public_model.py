"""Project one receipt-bound schema-12 Phase 3 candidate locally without replacement."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opennoise.pipeline.candidate_public_projection import (
    CandidatePublicProjectionError,
    CandidatePublicProjectionSettings,
    CandidatePublicProjectionV2Settings,
    CandidatePublicProjectionV3Settings,
    project_candidate_public_model,
    project_candidate_public_model_v2,
    project_candidate_public_model_v3,
)


def main() -> int:
    """Run the explicit local-only candidate projection."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-directory", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--replay-receipt", type=Path, required=True)
    parser.add_argument("--historical-candidate-binding", type=Path, required=True)
    parser.add_argument("--expected-candidate-sha256", required=True)
    parser.add_argument("--expected-replay-receipt-sha256", required=True)
    parser.add_argument("--expected-historical-candidate-binding-sha256", required=True)
    parser.add_argument("--output-database", type=Path, required=True)
    parser.add_argument("--model-output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    parser.add_argument(
        "--source-artifacts-v2",
        action="store_true",
        help="run the isolated local-only source-artifact-v2 projector",
    )
    parser.add_argument(
        "--source-artifacts-v3",
        action="store_true",
        help="run the isolated local-only compact source-artifact-v3 projector",
    )
    arguments = parser.parse_args()
    if arguments.source_artifacts_v2 and arguments.source_artifacts_v3:
        parser.error("choose only one source-artifact projector version")
    try:
        settings_kwargs = {
            "release_directory": arguments.release_directory,
            "candidate_database": arguments.candidate,
            "replay_receipt": arguments.replay_receipt,
            "historical_candidate_binding": arguments.historical_candidate_binding,
            "expected_candidate_sha256": arguments.expected_candidate_sha256,
            "expected_replay_receipt_sha256": arguments.expected_replay_receipt_sha256,
            "expected_historical_candidate_binding_sha256": (
                arguments.expected_historical_candidate_binding_sha256
            ),
            "output_database": arguments.output_database,
            "model_output": arguments.model_output,
            "report_output": arguments.report_output,
        }
        report = (
            project_candidate_public_model_v3(
                CandidatePublicProjectionV3Settings(**settings_kwargs)
            )
            if arguments.source_artifacts_v3
            else (
                project_candidate_public_model_v2(
                    CandidatePublicProjectionV2Settings(**settings_kwargs)
                )
                if arguments.source_artifacts_v2
                else project_candidate_public_model(
                    CandidatePublicProjectionSettings(**settings_kwargs)
                )
            )
        )
    except CandidatePublicProjectionError as error:
        sys.stderr.write(f"candidate public projection failed: {error}\n")
        return 2
    sys.stdout.write(report.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
