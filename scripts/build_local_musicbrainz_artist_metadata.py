"""Build local-only exact artist-name metadata from release-group credits."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from time import monotonic

from musix.serving.local.local_musicbrainz_artist_evidence import load_release_group_evidence_artifact
from musix.serving.local.local_musicbrainz_artist_metadata import (
    ArtistMetadataBuildInputs,
    ArtistMetadataProgress,
    ArtistMetadataSettings,
    build_artist_metadata,
)


def main() -> int:
    """Stream one verified local archive into a separate metadata database."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--evidence-db", type=Path, required=True)
    parser.add_argument("--evidence-artifact", type=Path, required=True)
    parser.add_argument("--output-db", type=Path, required=True)
    parser.add_argument("--output-artifact", type=Path, required=True)
    parser.add_argument("--progress-every-records", type=int, default=100_000)
    arguments = parser.parse_args()
    last_reported = 0

    def report(progress: ArtistMetadataProgress) -> None:
        nonlocal last_reported
        if progress.records_seen <= last_reported:
            return
        last_reported = progress.records_seen
        sys.stderr.write(
            "artist metadata progress "
            f"records_seen={progress.records_seen} "
            f"elapsed_seconds={progress.elapsed_seconds:.3f}\n"
        )
        sys.stderr.flush()

    started = monotonic()
    artifact = build_artist_metadata(
        ArtistMetadataBuildInputs(
            archive=arguments.archive,
            evidence_database=arguments.evidence_db,
            evidence_artifact=load_release_group_evidence_artifact(arguments.evidence_artifact),
            output_database=arguments.output_db,
        ),
        settings=ArtistMetadataSettings(progress_every_records=arguments.progress_every_records),
        progress_callback=report,
    )
    arguments.output_artifact.parent.mkdir(parents=True, exist_ok=True)
    arguments.output_artifact.write_text(
        artifact.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    sys.stdout.write(
        artifact.model_dump_json()[:-1] + f',"elapsed_seconds":{monotonic() - started:.6f}' + "}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
