"""Write a local-only exact-ID playlist and album evidence join report."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opennoise.analysis.listenbrainz_playlist_release_group_overlap import (
    ExactPlaylistReleaseGroupOverlapReport,
    overlap_report_sha256,
)
from opennoise.analysis.playlist_album_evidence_join import (
    PlaylistAlbumEvidenceJoinError,
    join_playlist_album_evidence,
)
from opennoise.ingest.musicbrainz.release_group_evidence import (
    ReleaseGroupEvidenceArtifact,
    verify_release_group_evidence,
)


def _require_overlap_hash(overlap: ExactPlaylistReleaseGroupOverlapReport) -> None:
    """Reject a changed overlap receipt before using its exact-ID paths."""
    if overlap_report_sha256(overlap) != overlap.output_sha256:
        raise PlaylistAlbumEvidenceJoinError("playlist overlap report hash does not replay")


def main() -> int:
    """Read existing local artifacts and write a create-only report under .cache."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overlap-report", type=Path, required=True)
    parser.add_argument("--evidence-database", type=Path, required=True)
    parser.add_argument("--evidence-artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if ".cache" not in arguments.output.resolve().parts:
        parser.error("output must resolve under .cache")
    if arguments.output.exists():
        parser.error("output already exists")
    try:
        overlap = ExactPlaylistReleaseGroupOverlapReport.model_validate_json(
            arguments.overlap_report.read_bytes()
        )
        _require_overlap_hash(overlap)
        artifact = ReleaseGroupEvidenceArtifact.model_validate_json(
            arguments.evidence_artifact.read_bytes()
        )
        verify_release_group_evidence(artifact)
        report = join_playlist_album_evidence(
            overlap.overlaps,
            playlist_overlap_report_sha256=overlap.output_sha256,
            evidence_database=arguments.evidence_database,
            evidence_artifact=artifact,
        )
    except (OSError, ValueError, PlaylistAlbumEvidenceJoinError) as error:
        sys.stderr.write(f"playlist album evidence join failed: {error}\n")
        return 1
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(f"wrote local-only playlist album evidence report: {arguments.output}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
