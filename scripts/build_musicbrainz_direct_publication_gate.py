"""Write a local-only, exact-MBID MusicBrainz direct-claim policy gate."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from opennoise.checkpoints.musicbrainz_direct_genre_frontier import (
    build_direct_musicbrainz_publication_gate,
    verify_direct_musicbrainz_publication_gate,
)


def _write_fresh_output(path: Path, payload: bytes) -> None:
    """Create a gate receipt once, without replacing an earlier review artifact."""
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
            raise FileExistsError(f"refusing to replace existing gate artifact: {path}") from error
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    """Build a source-replayable policy gate without invoking public delivery."""
    parser = argparse.ArgumentParser(prog="build-musicbrainz-direct-publication-gate")
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--seed-target", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    gate = build_direct_musicbrainz_publication_gate(
        layout_path=arguments.layout,
        reconciliation_path=arguments.reconciliation,
        seed_target_path=arguments.seed_target,
    )
    verify_direct_musicbrainz_publication_gate(gate)
    _write_fresh_output(
        arguments.output,
        (
            json.dumps(gate.model_dump(mode="json"), sort_keys=True, separators=(",", ":")) + "\n"
        ).encode(),
    )
    sys.stdout.write(
        json.dumps(
            {
                "output_sha256": gate.output_sha256,
                "proper_genre_membership_count": gate.proper_genre_membership_count,
                "proper_genre_frontier_seed_count": gate.proper_genre_frontier_seed_count,
                "placed_frontier_seed_count": gate.placed_frontier_seed_count,
                "unplaced_frontier_seed_count": gate.unplaced_frontier_seed_count,
                "public_export_authorized": gate.public_export_authorized,
            }
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
