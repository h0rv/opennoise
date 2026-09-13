"""Build and custody bounded ListenBrainz-derived review candidates."""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from opennoise.ingest.listenbrainz.propagation import (
    ListenBrainzPropagationSettings,
    PropagationInputFingerprint,
    build_listenbrainz_propagation,
    merge_direct_memberships,
    musicbrainz_seed_target_memberships,
    publish_listenbrainz_propagation,
    wikidata_name_universe_memberships,
)
from opennoise.ingest.musicbrainz.seed_targets import load_seed_target_artifact
from opennoise.ml.repository import PublicInputLoadSettings, PublicModelRepository
from opennoise.serving.public.artist_membership import load_name_universe
from opennoise.storage import LocalObjectStore


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1_048_576):
            digest.update(chunk)
    return digest.hexdigest()


def _read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.resolve(strict=True).as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _require_qualified_snapshot(
    catalog_path: Path,
    catalog_sha256: str,
    listenbrainz_path: Path,
    listenbrainz_sha256: str,
) -> str:
    """Fail closed unless both repository inputs are one hash-locked snapshot."""
    if catalog_path.resolve(strict=True) != listenbrainz_path.resolve(strict=True):
        raise ValueError("catalog and ListenBrainz inputs must be the same qualified snapshot")
    if catalog_sha256 != listenbrainz_sha256:
        raise ValueError("catalog and ListenBrainz expected hashes must be identical")
    actual_sha256 = _sha256_file(catalog_path)
    if actual_sha256 != catalog_sha256:
        raise ValueError("qualified snapshot bytes do not match the expected SHA-256")
    return actual_sha256


def build_parser() -> argparse.ArgumentParser:
    """Expose only bounded local inputs and policy knobs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-artifact", type=Path, required=True)
    parser.add_argument("--musicbrainz-seed-target-artifact", type=Path, required=True)
    parser.add_argument("--catalog-db", type=Path, required=True)
    parser.add_argument("--catalog-db-sha256", required=True)
    parser.add_argument("--listenbrainz-db", type=Path, required=True)
    parser.add_argument("--listenbrainz-db-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--max-direct-memberships", type=int, default=100_000)
    parser.add_argument("--max-artist-pairs", type=int, default=250_000)
    parser.add_argument("--max-metadata-candidates", type=int, default=100_000)
    parser.add_argument("--minimum-listener-day-support", type=int, default=15)
    parser.add_argument("--minimum-supporting-windows", type=int, default=2)
    parser.add_argument("--maximum-artist-degree", type=int, default=250)
    parser.add_argument("--maximum-candidates-per-genre", type=int, default=2_500)
    parser.add_argument("--maximum-propagation-visits", type=int, default=2_000_000)
    parser.add_argument("--holdout-modulus", type=int, default=5)
    parser.add_argument("--holdout-bucket", type=int, default=0)
    parser.add_argument("--holdout-seed", type=int, default=20260906)
    return parser


def main() -> int:
    """Load typed catalog evidence, construct review candidates, and publish a receipt."""
    arguments = build_parser().parse_args()
    qualified_snapshot_sha256 = _require_qualified_snapshot(
        arguments.catalog_db,
        arguments.catalog_db_sha256,
        arguments.listenbrainz_db,
        arguments.listenbrainz_db_sha256,
    )
    universe = load_name_universe(arguments.seed_artifact)
    musicbrainz_source = load_seed_target_artifact(arguments.musicbrainz_seed_target_artifact)
    if musicbrainz_source.seed_source_content_sha256 != universe.source_content_sha256:
        raise ValueError("MusicBrainz seed-target artifact does not match the name-universe source")
    load_settings = PublicInputLoadSettings(
        max_direct_memberships=arguments.max_direct_memberships,
        max_artist_pairs=arguments.max_artist_pairs,
        max_metadata_candidates=arguments.max_metadata_candidates,
    )
    with (
        closing(_read_only(arguments.catalog_db)) as catalog,
        closing(_read_only(arguments.listenbrainz_db)) as listenbrainz,
    ):
        inputs = PublicModelRepository(catalog, listenbrainz).load(load_settings)
    listenbrainz_artist_ids = {
        artist_id
        for pair in inputs.artist_pairs
        for artist_id in (pair.left_artist_id, pair.right_artist_id)
    }
    musicbrainz_direct = musicbrainz_seed_target_memberships(
        musicbrainz_source, listenbrainz_artist_ids
    )
    wikidata_direct = wikidata_name_universe_memberships(inputs, universe)
    direct_memberships = merge_direct_memberships(musicbrainz_direct, wikidata_direct)
    fingerprint = PropagationInputFingerprint(
        catalog_database_sha256=qualified_snapshot_sha256,
        listenbrainz_database_sha256=qualified_snapshot_sha256,
        name_universe_source_sha256=universe.source_content_sha256,
        musicbrainz_seed_target_output_sha256=musicbrainz_source.output_sha256,
        musicbrainz_seed_target_file_sha256=_sha256_file(
            arguments.musicbrainz_seed_target_artifact
        ),
        public_input_sha256=hashlib.sha256(
            inputs.model_dump_json(exclude_none=True).encode("utf-8")
        ).hexdigest(),
    )
    settings = ListenBrainzPropagationSettings(
        minimum_listener_day_support=arguments.minimum_listener_day_support,
        minimum_supporting_windows=arguments.minimum_supporting_windows,
        maximum_artist_degree=arguments.maximum_artist_degree,
        maximum_candidates_per_genre=arguments.maximum_candidates_per_genre,
        maximum_propagation_visits=arguments.maximum_propagation_visits,
        holdout_modulus=arguments.holdout_modulus,
        holdout_bucket=arguments.holdout_bucket,
        holdout_seed=arguments.holdout_seed,
    )
    artifact = build_listenbrainz_propagation(
        inputs,
        universe,
        fingerprint,
        settings,
        direct_memberships=direct_memberships,
    )
    receipt, _write = publish_listenbrainz_propagation(
        artifact, output_path=arguments.output, store=LocalObjectStore(arguments.object_store)
    )
    arguments.receipt.parent.mkdir(parents=True, exist_ok=True)
    arguments.receipt.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(
        artifact.model_dump_json(
            include={"coverage", "heldout_anchor_recovery", "output_sha256"}, indent=2
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
