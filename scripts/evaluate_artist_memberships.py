"""Evaluate direct and one-hop public memberships against held-out judgments."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opennoise.ml.publish import load_public_model
from opennoise.serving.artist_membership_evaluation import (
    ArtistMembershipEvaluationStore,
    evaluate_artist_memberships,
    load_judgment_set,
    publish_evaluation_evidence,
)
from opennoise.storage import LocalObjectStore


def main() -> int:
    """Write a typed calibration report and optionally custody it immutably."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path, help="Public model artifact to evaluate")
    parser.add_argument("--judgments", type=Path, required=True, help="Held-out judgment JSON")
    parser.add_argument("--report", type=Path, required=True, help="Output report JSON")
    parser.add_argument("--database", type=Path, help="Optional stdlib SQLite evaluation ledger")
    parser.add_argument("--object-store", type=Path, help="Optional immutable evidence store")
    arguments = parser.parse_args()
    try:
        loaded = load_public_model(arguments.artifact)
        judgments, judgment_file_sha256 = load_judgment_set(arguments.judgments)
        report = evaluate_artist_memberships(
            loaded.artifact,
            judgments,
            judgment_file_sha256=judgment_file_sha256,
            model_file_sha256=loaded.artifact_sha256,
        )
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
        if arguments.database is not None:
            arguments.database.parent.mkdir(parents=True, exist_ok=True)
            ArtistMembershipEvaluationStore(arguments.database).record(report)
        if arguments.object_store is not None:
            publish_evaluation_evidence(
                LocalObjectStore(arguments.object_store),
                arguments.judgments,
                arguments.report,
                report,
            )
    except (OSError, ValueError) as error:
        sys.stderr.write(f"artist membership evaluation failed: {error}\n")
        return 2
    sys.stdout.write(report.model_dump_json(indent=2) + "\n")
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
