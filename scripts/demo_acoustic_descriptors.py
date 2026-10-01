"""Replay a small receipt-bound, numeric-only acoustic descriptor example."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from opennoise.analysis.acoustic_representation import (
    ArtistDescriptors,
    fit_scales,
    sonic_neighbors,
)


def main() -> int:
    """Verify the projection receipt and print a small neighbor result."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "projection",
        nargs="?",
        type=Path,
        default=Path("data/examples/acoustic-descriptors/acoustic-descriptors.json"),
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=Path("data/examples/acoustic-descriptors/receipt.json"),
    )
    args = parser.parse_args()
    body = args.projection.read_bytes()
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    if hashlib.sha256(body).hexdigest() != receipt["projection_sha256"]:
        raise ValueError("acoustic projection does not match its receipt")
    artifact = json.loads(body)
    if (
        receipt["license"] != "CC0-1.0"
        or receipt["source_summary_sha256"] != artifact["source_summary_sha256"]
        or receipt["source_receipt_sha256"] != artifact["source_receipt_sha256"]
        or artifact["scope"]["license"] != "CC0-1.0"
    ):
        raise ValueError("acoustic source or license provenance differs from the receipt")
    artists = tuple(
        ArtistDescriptors(
            artist_id=row["artist_id"],
            recording_count=row["recording_count"],
            values=row["values"],
            observed_counts=row["observed_counts"],
        )
        for row in artifact["artists"]
    )
    features = artifact["features"]
    scales = fit_scales(artists, features)
    result = {
        "attribution": artifact["scope"]["attribution"],
        "license": artifact["scope"]["license"],
        "scope": (
            "small numeric descriptor example; not calibrated or a claim about Every Noise axes"
        ),
        "source_summary_sha256": artifact["source_summary_sha256"],
        "neighbors": {
            artist.artist_id: sonic_neighbors(artist, artists, scales)[:3] for artist in artists[:3]
        },
    }
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
