"""Build an immutable local reverse artist-to-seed SQLite sidecar."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from time import monotonic
from uuid import uuid4

from musix.serving.local.local_musicbrainz_artist_evidence import load_release_group_evidence_artifact
from musix.serving.local.local_musicbrainz_artist_reverse_lookup import (
    ArtistReverseLookupBuildInputs,
    build_artist_reverse_lookup,
)


def main() -> int:
    """Write one source-bound reverse projection and its small receipt."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-db", type=Path, required=True)
    parser.add_argument("--evidence-artifact", type=Path, required=True)
    parser.add_argument("--output-db", type=Path, required=True)
    parser.add_argument("--output-artifact", type=Path, required=True)
    arguments = parser.parse_args()
    started = monotonic()
    try:
        artifact = build_artist_reverse_lookup(
            ArtistReverseLookupBuildInputs(
                evidence_database=arguments.evidence_db,
                evidence_artifact=load_release_group_evidence_artifact(arguments.evidence_artifact),
                output_database=arguments.output_db,
            )
        )
    except (OSError, ValueError) as error:
        sys.stderr.write(f"reverse lookup build failed: {error}\n")
        return 2
    arguments.output_artifact.parent.mkdir(parents=True, exist_ok=True)
    temporary_artifact = arguments.output_artifact.with_name(
        f".{arguments.output_artifact.name}.{uuid4().hex}.partial"
    )
    try:
        temporary_artifact.write_text(artifact.model_dump_json(indent=2) + "\n", encoding="utf-8")
        temporary_artifact.replace(arguments.output_artifact)
    finally:
        temporary_artifact.unlink(missing_ok=True)
    sys.stdout.write(
        artifact.model_dump_json()[:-1] + f',"elapsed_seconds":{monotonic() - started:.6f}' + "}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
