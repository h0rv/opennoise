"""Write one bounded, local-only artist-session approximation receipt."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.analysis.listenbrainz_artist_session import run_artist_session_approximation


def main() -> int:
    """Write one new aggregate-only receipt after archive hash verification."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        raise FileExistsError("output already exists")
    artifact = run_artist_session_approximation(
        archive_path=arguments.archive, source_artifact_sha256=arguments.sha256
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(artifact.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
