"""Bind a retained ListenBrainz user-playlist listing to a route-only local cohort."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from pydantic import HttpUrl

from opennoise.analysis.listenbrainz_playlist_artist_bridge import (
    ListenBrainzPlaylistArtistBridgeArtifact,
)
from opennoise.analysis.listenbrainz_playlist_user_created_cohort import (
    ListenBrainzUserCreatedCohortError,
    build_user_created_playlist_cohort,
)
from opennoise.ingest.listenbrainz.playlist_source_roles import (
    make_playlist_discovery_route_receipt,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listing-url", type=HttpUrl, required=True)
    parser.add_argument("--listing-payload", type=Path, required=True)
    parser.add_argument("--snapshot-bundle", type=Path, required=True)
    parser.add_argument("--raw-object-directory", type=Path, required=True)
    parser.add_argument("--artist-bridge", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    """Write one new receipt-bound cohort audit without replacing existing custody."""
    arguments = _arguments()
    listing_payload = arguments.listing_payload.read_bytes()
    snapshot_bundle = arguments.snapshot_bundle.read_bytes()
    bridge = ListenBrainzPlaylistArtistBridgeArtifact.model_validate_json(
        arguments.artist_bridge.read_bytes()
    )
    listing_receipt = make_playlist_discovery_route_receipt(
        arguments.listing_url,
        payload_sha256=hashlib.sha256(listing_payload).hexdigest(),
        payload_bytes=len(listing_payload),
    )
    cohort = build_user_created_playlist_cohort(
        listing_payload=listing_payload,
        listing_route_receipt=listing_receipt,
        snapshot_bundle_bytes=snapshot_bundle,
        raw_object_directory=arguments.raw_object_directory,
        artist_bridge=bridge,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with arguments.output.open("x", encoding="utf-8") as output:
            output.write(cohort.model_dump_json(indent=2))
    except FileExistsError as error:
        raise ListenBrainzUserCreatedCohortError("cohort output already exists") from error


if __name__ == "__main__":
    main()
