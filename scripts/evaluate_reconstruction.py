"""Run a versioned reconstruction experiment manifest and print JSON results."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from musix.evidence.reconstruction import (
    ReconstructionExperimentManifest,
    run_reconstruction_experiment,
)

MAX_MANIFEST_BYTES = 16 * 1024 * 1024


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate deterministic reconstruction baselines from a JSON manifest."
    )
    parser.add_argument("manifest", type=Path, help="Path to a reconstruction manifest JSON file")
    return parser


def main() -> int:
    """Validate one manifest, run it without writes, and emit typed JSON."""
    arguments = _parser().parse_args()
    try:
        manifest_text = read_manifest(arguments.manifest)
        manifest = ReconstructionExperimentManifest.model_validate_json(manifest_text)
        result = run_reconstruction_experiment(manifest)
    except (OSError, ValidationError, ValueError) as error:
        sys.stderr.write(f"reconstruction evaluation failed: {error}\n")
        return 2
    sys.stdout.write(result.model_dump_json(indent=2) + "\n")
    return 0


def read_manifest(path: Path) -> str:
    """Read one UTF-8 manifest without accepting an unbounded file."""
    with path.open("rb") as manifest_file:
        manifest_bytes = manifest_file.read(MAX_MANIFEST_BYTES + 1)
    if len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise ValueError(f"manifest exceeds {MAX_MANIFEST_BYTES} bytes")
    return manifest_bytes.decode("utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
