"""Run the post-seal historical membership/peer coverage diagnostic."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from opennoise.ml.label_alignment.historical_diagnostic import (
    build_historical_diagnostic,
    write_historical_diagnostic,
)


def _shared_cache_root() -> Path:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required to locate the shared OpenNoise cache")
    result = subprocess.run(  # noqa: S603 - fixed git subcommand after absolute PATH lookup.
        [git, "rev-parse", "--path-format=absolute", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip()).parent / ".cache"


def main() -> int:
    """Write an after-the-fact diagnostic; it cannot affect alignment construction."""
    cache = _shared_cache_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("alignment", type=Path)
    parser.add_argument(
        "--historical-semantic",
        type=Path,
        default=cache / "historical-signal-final/historical-signal-semantic-v1.json",
    )
    parser.add_argument(
        "--output-root", type=Path, default=cache / "cold-label-alignment-historical-diagnostic-v1"
    )
    arguments = parser.parse_args()
    artifact = build_historical_diagnostic(arguments.alignment, arguments.historical_semantic)
    receipt, artifact_path, receipt_path = write_historical_diagnostic(
        artifact, arguments.output_root
    )
    sys.stdout.write(
        json.dumps(
            {
                "artifact": str(artifact_path),
                "receipt": str(receipt_path),
                "logical_output_sha256": artifact.output_sha256,
                "artifact_sha256": receipt.artifact_sha256,
                "partitions": {
                    "accepted": artifact.accepted.model_dump(mode="json"),
                    "review": artifact.review.model_dump(mode="json"),
                    "abstentions": artifact.abstentions.model_dump(mode="json"),
                },
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
