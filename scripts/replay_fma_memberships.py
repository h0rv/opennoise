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
from opennoise.ml.fma_recording_query_bundle import lookup  # noqa: E402


def main() -> None:  # noqa: C901 - explicit mutually exclusive source and portable modes.
    """Replay thresholds, suggestions and metrics without fitting or obtaining audio."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--saved-pack", type=Path)
    parser.add_argument("--memberships", type=Path)
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
    parser.add_argument("--export-query-bundle", type=Path)
    parser.add_argument("--query-bundle", type=Path)
    parser.add_argument("--query-bundle-sha256")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.query_bundle is not None:
        source_args = (
            args.saved_pack,
            args.memberships,
            args.export_artists,
            args.rank_artists,
            args.artist_neighbors,
            args.saved_pack_receipt_sha256,
            args.membership_receipt_sha256,
            args.export_query_bundle,
        )
        if any(value is not None and value is not False for value in source_args):
            parser.error("bundle lookup rejects source/export flags")
        if not args.query_bundle_sha256 or args.query_track_id is None or args.output is None:
            parser.error(
                "bundle lookup requires --query-bundle-sha256, --query-track-id and --output"
            )
        result = lookup(
            args.query_bundle, args.query_bundle_sha256, args.query_track_id, args.output
        )
        sys.stdout.write(json.dumps(result, indent=2) + "\n")
        return
    if args.query_bundle_sha256 is not None or args.output is not None:
        parser.error("--query-bundle-sha256 and --output require --query-bundle")
    if args.saved_pack is None or args.memberships is None:
        parser.error("source replay requires --saved-pack and --memberships")
    if args.export_query_bundle is not None and (
        args.export_artists is None or not args.rank_artists
    ):
        parser.error("--export-query-bundle requires --export-artists and --rank-artists")
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
            query_bundle_output=args.export_query_bundle,
        )
    else:
        result = replay_membership_pack(args.saved_pack, args.memberships)
    sys.stdout.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
