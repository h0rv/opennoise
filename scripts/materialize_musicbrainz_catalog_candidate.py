"""Materialize a hash-bound, local-only MusicBrainz catalog candidate."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.ingest.musicbrainz.catalog_candidate import materialize_candidate, sha256_file


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    """Write only the supplied candidate database and its deterministic replay receipt."""
    arguments = _arguments()
    artifact_sha256 = sha256_file(arguments.artifact)
    if artifact_sha256 != arguments.artifact_sha256:
        raise ValueError("hydration artifact SHA-256 does not match expected source")
    report = materialize_candidate(
        source_artifact_path=arguments.artifact,
        candidate_database_path=arguments.database,
    )
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(artifact_sha256)  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
