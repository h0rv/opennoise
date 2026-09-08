"""Materialize a local reviewed-alias model input from sealed small artifacts."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from musix.models.modeling import PublicModelInput
from musix.musicbrainz_model_adapter import MusicBrainzModelAdapterReport
from musix.musicbrainz_reviewed_alias_context import (
    ReviewedAliasContextArtifact,
    combine_reviewed_alias_context_model_input,
)


def _atomic_write(path: Path, payload: bytes) -> None:
    """Publish a completed JSON document without exposing partial output."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    """Write one independent combined input and a compact provenance receipt."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-model-input", type=Path, required=True)
    parser.add_argument("--adapter-report", type=Path, required=True)
    parser.add_argument("--reviewed-alias-context", type=Path, required=True)
    parser.add_argument("--model-input", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    arguments = parser.parse_args()
    baseline = PublicModelInput.model_validate_json(arguments.baseline_model_input.read_bytes())
    report = MusicBrainzModelAdapterReport.model_validate_json(
        arguments.adapter_report.read_bytes()
    )
    context = ReviewedAliasContextArtifact.model_validate_json(
        arguments.reviewed_alias_context.read_bytes()
    )
    combined, receipt = combine_reviewed_alias_context_model_input(baseline, report, context)
    _atomic_write(
        arguments.model_input,
        json.dumps(combined.model_dump(mode="json"), indent=2, sort_keys=True).encode() + b"\n",
    )
    _atomic_write(arguments.receipt, receipt.model_dump_json(indent=2).encode() + b"\n")
    sys.stdout.write(receipt.model_dump_json() + "\n")


if __name__ == "__main__":
    main()
