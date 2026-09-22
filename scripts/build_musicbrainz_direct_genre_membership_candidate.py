"""Write a local-only exact-MBID MusicBrainz proper-genre candidate."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from opennoise.checkpoints.musicbrainz_direct_genre_frontier import (
    build_direct_genre_membership_candidate,
    verify_direct_genre_membership_candidate,
)


def _write_fresh_output(path: Path, payload: bytes) -> None:
    """Atomically create a candidate artifact without replacing a prior receipt."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise FileExistsError(
                f"refusing to replace existing candidate artifact: {path}"
            ) from error
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    """Build one source-bound candidate without touching serving or catalog data."""
    parser = argparse.ArgumentParser(prog="build-musicbrainz-direct-genre-membership-candidate")
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--frontier", type=Path, required=True)
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--seed-target", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    candidate = build_direct_genre_membership_candidate(
        layout_path=arguments.layout,
        frontier_path=arguments.frontier,
        reconciliation_path=arguments.reconciliation,
        seed_target_path=arguments.seed_target,
    )
    verify_direct_genre_membership_candidate(candidate)
    _write_fresh_output(
        arguments.output,
        (
            json.dumps(candidate.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode(),
    )
    sys.stdout.write(
        json.dumps(
            {
                "candidate_revision": candidate.candidate_revision,
                "output_sha256": candidate.output_sha256,
                "membership_count": candidate.membership_count,
                "seed_count": candidate.seed_count,
                "artist_mbid_count": candidate.artist_mbid_count,
                "public_export_authorized": candidate.public_export_authorized,
            }
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
