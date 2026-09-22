"""Verify the portable custody object, optionally against retained local inputs."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreCustodyReceipt,
    verify_portable_direct_proper_genre_custody,
    verify_portable_direct_proper_genre_custody_from_inputs,
)


def main() -> int:
    """Verify portable custody bytes alone or replay them from retained inputs."""
    parser = argparse.ArgumentParser(prog="verify-musicbrainz-direct-proper-genre-custody")
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--object-store", required=True, type=Path)
    parser.add_argument("--seed-target", type=Path)
    parser.add_argument("--reconciliation", type=Path)
    arguments = parser.parse_args()
    receipt = DirectProperGenreCustodyReceipt.model_validate_json(arguments.receipt.read_bytes())
    if (arguments.seed_target is None) != (arguments.reconciliation is None):
        parser.error("--seed-target and --reconciliation must be supplied together")
    if arguments.seed_target is None:
        verify_portable_direct_proper_genre_custody(receipt, object_store=arguments.object_store)
    else:
        verify_portable_direct_proper_genre_custody_from_inputs(
            receipt,
            object_store=arguments.object_store,
            seed_target=arguments.seed_target,
            reconciliation=arguments.reconciliation,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
