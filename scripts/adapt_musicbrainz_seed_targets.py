"""Adapt a verified MusicBrainz seed-target artifact into public model input."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from musix.musicbrainz_model_adapter import (
    MusicBrainzModelAdapterPolicy,
    adapt_musicbrainz_seed_targets,
)
from musix.musicbrainz_seed_targets import load_seed_target_artifact
from musix.taxonomy.seed_reconciliation import load_seed_reconciliation


def _atomic_write_text(path: Path, payload: str) -> None:
    """Commit a completed adapter artifact without exposing a partial JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    """Write the model input and hash-bound adapter report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-target-artifact", type=Path, required=True)
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--model-input", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expected-seed-count", type=int, default=6291)
    arguments = parser.parse_args()
    result = adapt_musicbrainz_seed_targets(
        load_seed_target_artifact(arguments.seed_target_artifact),
        load_seed_reconciliation(arguments.reconciliation),
        MusicBrainzModelAdapterPolicy(expected_seed_count=arguments.expected_seed_count),
    )
    _atomic_write_text(
        arguments.model_input,
        json.dumps(result.model_input.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
    )
    _atomic_write_text(arguments.report, result.report.model_dump_json(indent=2) + "\n")


if __name__ == "__main__":
    main()
