"""Emit a deterministic, metadata-only release-group and recording representative artifact."""

from __future__ import annotations

import argparse
from pathlib import Path

from musix.serving.metadata.metadata_representatives import MetadataRepresentativeSettings, metadata_representatives


def main() -> int:
    """Parse a bounded SQLite request and write one versioned JSON artifact."""
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-metadata-candidates", type=int, default=100_000)
    arguments = parser.parse_args()
    artifact = metadata_representatives(
        arguments.database,
        MetadataRepresentativeSettings(
            max_metadata_candidates=arguments.max_metadata_candidates,
        ),
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(artifact.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
