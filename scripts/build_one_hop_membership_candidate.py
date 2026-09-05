"""Seal a conservative, non-production one-hop membership candidate."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from musix.ml.repository import PublicInputLoadSettings, PublicModelRepository
from musix.one_hop_membership_candidate import (
    OneHopMembershipCandidatePolicy,
    build_one_hop_membership_candidate,
)


def _read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.resolve(strict=True).as_posix()}?mode=ro", uri=True)


def main() -> None:
    """Read public inputs, seal the candidate, and write its summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-db", type=Path, required=True)
    parser.add_argument("--listenbrainz-db", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-direct-memberships", type=int, default=100_000)
    parser.add_argument("--max-artist-pairs", type=int, default=250_000)
    parser.add_argument("--max-metadata-candidates", type=int, default=100_000)
    arguments = parser.parse_args()
    policy = OneHopMembershipCandidatePolicy.model_validate_json(arguments.policy.read_bytes())
    settings = PublicInputLoadSettings(
        max_direct_memberships=arguments.max_direct_memberships,
        max_artist_pairs=arguments.max_artist_pairs,
        max_metadata_candidates=arguments.max_metadata_candidates,
    )
    with (
        closing(_read_only(arguments.catalog_db)) as catalog,
        closing(_read_only(arguments.listenbrainz_db)) as listenbrainz,
    ):
        inputs = PublicModelRepository(catalog, listenbrainz).load(settings)
    artifact = build_one_hop_membership_candidate(inputs, policy)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(artifact.model_dump_json(indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(
        artifact.model_dump_json(include={"output_sha256", "coverage"}, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
