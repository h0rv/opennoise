"""Create a no-replace detached binding for one local historical Phase 3 candidate."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opennoise.pipeline.historical_candidate_binding import (
    HistoricalCandidateBindingError,
    HistoricalCandidateBindingSettings,
    create_historical_candidate_binding,
)


def main() -> int:
    """Attest only local candidate inputs; this never replays the source vault."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-directory", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--replay-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        binding = create_historical_candidate_binding(
            HistoricalCandidateBindingSettings(
                release_directory=arguments.release_directory,
                candidate_database=arguments.candidate,
                replay_receipt=arguments.replay_receipt,
                output=arguments.output,
            )
        )
    except HistoricalCandidateBindingError as error:
        sys.stderr.write(f"historical candidate binding failed: {error}\n")
        return 2
    sys.stdout.write(binding.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
