"""Run the bounded local-only MusicBrainz artist context metadata pilot."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from musix.serving.artist_metadata_context_pilot import PilotBuildInputs, run_pilot


def _report(message: str) -> None:
    """Emit one progress line without changing the callback return contract."""
    sys.stderr.write(message + "\n")


def main() -> int:
    """Parse explicit local paths and run the bounded pilot."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-db", type=Path, required=True)
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--user-agent", required=True)
    arguments = parser.parse_args()
    artifact = run_pilot(
        PilotBuildInputs(
            evidence_database=arguments.evidence_db,
            reconciliation=arguments.reconciliation,
            output_root=arguments.output_root,
            user_agent=arguments.user_agent,
        ),
        progress=_report,
    )
    sys.stdout.write(artifact.model_dump_json() + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
