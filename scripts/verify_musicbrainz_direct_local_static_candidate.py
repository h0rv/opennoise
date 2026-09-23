"""Replay local direct MusicBrainz candidate rows against their pinned sources."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opennoise.checkpoints.musicbrainz_direct_local_static_candidate import (
    LocalMusicBrainzStaticCandidateError,
    verify_local_musicbrainz_direct_static_candidate_from_inputs,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--direct-custody-receipt", type=Path, required=True)
    parser.add_argument("--direct-custody-receipt-sha256", required=True)
    parser.add_argument("--direct-object-store", type=Path, required=True)
    parser.add_argument("--canonical-name-receipt", type=Path, required=True)
    parser.add_argument("--canonical-name-receipt-sha256", required=True)
    parser.add_argument("--canonical-name-object-store", type=Path, required=True)
    parser.add_argument("--recovered-name-receipt", type=Path, required=True)
    parser.add_argument("--recovered-name-receipt-sha256", required=True)
    parser.add_argument("--recovered-name-object-store", type=Path, required=True)
    parser.add_argument("--static-discovery", type=Path, required=True)
    parser.add_argument("--certified-manifest", type=Path, required=True)
    parser.add_argument("--certified-layout", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    """Verify an existing ignored-cache candidate without writing an artifact."""
    arguments = _arguments()
    try:
        manifest = verify_local_musicbrainz_direct_static_candidate_from_inputs(
            output_directory=arguments.output_directory,
            direct_custody_receipt_path=arguments.direct_custody_receipt,
            direct_custody_receipt_sha256=arguments.direct_custody_receipt_sha256,
            direct_object_store=arguments.direct_object_store,
            canonical_name_receipt_path=arguments.canonical_name_receipt,
            canonical_name_receipt_sha256=arguments.canonical_name_receipt_sha256,
            canonical_name_object_store=arguments.canonical_name_object_store,
            recovered_name_receipt_path=arguments.recovered_name_receipt,
            recovered_name_receipt_sha256=arguments.recovered_name_receipt_sha256,
            recovered_name_object_store=arguments.recovered_name_object_store,
            static_discovery_path=arguments.static_discovery,
            certified_manifest_path=arguments.certified_manifest,
            certified_layout_path=arguments.certified_layout,
        )
    except (LocalMusicBrainzStaticCandidateError, OSError, ValueError) as error:
        sys.stderr.write(f"local MusicBrainz static candidate replay failed: {error}\n")
        return 1
    sys.stdout.write(f"replayed local-only candidate: {manifest.output_sha256}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
