"""Evaluate the independent public-model publication gate."""

import argparse
import sys
from pathlib import Path

from musix.ml.public_model_gate import evaluate_public_model
from musix.ml.publish import load_public_model


def main() -> int:
    """Validate one bounded model artifact and emit its typed proof report."""
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--report", type=Path)
    arguments = parser.parse_args()
    loaded = load_public_model(arguments.artifact)
    report = evaluate_public_model(
        loaded.artifact,
        artifact_file_sha256=loaded.artifact_sha256,
        artifact_byte_size=loaded.byte_size,
    )
    payload = report.model_dump_json(indent=2) + "\n"
    if arguments.report is None:
        sys.stdout.write(payload)
    else:
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_text(payload, encoding="utf-8")
    if not report.passed:
        for failure in report.failures:
            sys.stderr.write(f"public-model gate failed: {failure}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
