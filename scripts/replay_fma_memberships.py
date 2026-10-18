"""Verify source-only FMA memberships against every frozen query and calibration component."""

from __future__ import annotations

import argparse
import json
import os
import resource
import signal
import sys
from pathlib import Path

os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))
resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
signal.alarm(120)

from opennoise.ml.fma_artist_evidence import export_artist_evidence  # noqa: E402
from opennoise.ml.fma_memberships import replay_membership_pack  # noqa: E402


def main() -> None:
    """Replay thresholds, suggestions and metrics without fitting or obtaining audio."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--saved-pack", type=Path, required=True)
    parser.add_argument("--memberships", type=Path, required=True)
    parser.add_argument("--export-artists", type=Path)
    parser.add_argument("--rank-artists", action="store_true")
    parser.add_argument(
        "--artist-neighbors",
        action="store_true",
        help="attach six component-distinct neighbors within each historical rank-profile pool",
    )
    parser.add_argument(
        "--query-track-id",
        type=int,
        action="append",
        help="query saved recording ranks against same-partition artist profiles",
    )
    parser.add_argument("--saved-pack-receipt-sha256")
    parser.add_argument("--membership-receipt-sha256")
    args = parser.parse_args()
    if args.query_track_id is not None and (not args.rank_artists or args.export_artists is None):
        parser.error("--query-track-id requires --export-artists and --rank-artists")
    if args.artist_neighbors and (not args.rank_artists or args.export_artists is None):
        parser.error("--artist-neighbors requires --export-artists and --rank-artists")
    if args.rank_artists and args.export_artists is None:
        parser.error("--rank-artists requires --export-artists")
    if args.export_artists is not None:
        if not args.saved_pack_receipt_sha256 or not args.membership_receipt_sha256:
            parser.error("artist export requires both external receipt SHA256 pins")
        result = export_artist_evidence(
            args.saved_pack,
            args.saved_pack_receipt_sha256,
            args.memberships,
            args.membership_receipt_sha256,
            args.export_artists,
            rank_artists=args.rank_artists,
            artist_neighbors=args.artist_neighbors,
            query_track_ids=args.query_track_id,
        )
    else:
        result = replay_membership_pack(args.saved_pack, args.memberships)
    sys.stdout.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
