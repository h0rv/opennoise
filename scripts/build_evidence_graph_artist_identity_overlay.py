"""Build a receipt-bound exact artist-name sidecar for an evidence graph."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from time import monotonic

from opennoise.evidence.artist_identity_overlay import (
    ArtistIdentityOverlayInputs,
    build_artist_identity_overlay,
    write_artist_identity_overlay,
)


def main() -> None:
    """Parse sealed inputs, atomically build the sidecar, and write its receipt."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph-database", type=Path, required=True)
    parser.add_argument("--graph-receipt", type=Path, required=True)
    parser.add_argument("--metadata-database", type=Path, required=True)
    parser.add_argument("--metadata-receipt", type=Path, required=True)
    parser.add_argument("--output-database", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    started = monotonic()
    sys.stderr.write("artist identity overlay: verifying and hashing graph and metadata inputs\n")
    artifact = build_artist_identity_overlay(
        ArtistIdentityOverlayInputs(
            graph_database=args.graph_database,
            graph_receipt=args.graph_receipt,
            metadata_database=args.metadata_database,
            metadata_receipt=args.metadata_receipt,
            output_database=args.output_database,
        )
    )
    elapsed = monotonic() - started
    sys.stderr.write(
        f"artist identity overlay: database built in {elapsed:.1f}s; writing receipt\n"
    )
    write_artist_identity_overlay(args.receipt, artifact)
    sys.stdout.write(artifact.model_dump_json(indent=2) + "\n")


if __name__ == "__main__":
    main()
