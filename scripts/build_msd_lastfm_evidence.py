"""Build offline MSD Last.fm tag and similarity evidence from three SQLite files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from musix.msd_lastfm import (
    build_msd_lastfm_evidence,
    cache_msd_lastfm_sqlite_files,
    load_msd_lastfm_source_cache,
    publish_msd_lastfm_evidence,
    targets_from_seed_reconciliation,
)
from musix.storage import LocalObjectStore


def parser() -> argparse.ArgumentParser:
    """Describe the cache-first, SQLite-only MSD evidence build."""
    command = argparse.ArgumentParser(prog="build-msd-lastfm-evidence")
    source = command.add_mutually_exclusive_group(required=True)
    source.add_argument("--reuse-source-cache-receipt", type=Path)
    source.add_argument("--metadata-db", type=Path)
    command.add_argument("--tags-db", type=Path)
    command.add_argument("--similarity-db", type=Path)
    command.add_argument("--cache-root", type=Path, required=True)
    command.add_argument("--source-cache-receipt", type=Path, required=True)
    command.add_argument("--seed-reconciliation", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--object-store", type=Path, required=True)
    command.add_argument("--receipt", type=Path, required=True)
    command.add_argument("--maximum-similarity-rows", type=int, default=200_000)
    command.add_argument("--maximum-similarity-edges", type=int, default=1_000_000)
    command.add_argument("--maximum-tag-rows", type=int, default=2_000_000)
    command.add_argument("--maximum-tag-supports", type=int, default=2_000_000)
    command.add_argument("--maximum-name-only-reviews", type=int, default=2_000_000)
    return command


def run(arguments: argparse.Namespace) -> int:
    """Materialize a local immutable source cache before streaming evidence from it."""
    if arguments.reuse_source_cache_receipt is not None:
        if arguments.tags_db is not None or arguments.similarity_db is not None:
            raise ValueError(
                "reuse-source-cache-receipt cannot be combined with SQLite input paths"
            )
        cache = load_msd_lastfm_source_cache(arguments.reuse_source_cache_receipt)
        cache_payload = arguments.reuse_source_cache_receipt.read_bytes()
    else:
        if arguments.tags_db is None or arguments.similarity_db is None:
            raise ValueError("metadata-db requires tags-db and similarity-db")
        cache = cache_msd_lastfm_sqlite_files(
            metadata_db=arguments.metadata_db,
            tags_db=arguments.tags_db,
            similarity_db=arguments.similarity_db,
            cache_root=arguments.cache_root,
        )
        cache_payload = (cache.model_dump_json(indent=2) + "\n").encode()
    arguments.source_cache_receipt.parent.mkdir(parents=True, exist_ok=True)
    arguments.source_cache_receipt.write_bytes(cache_payload)
    artifact = build_msd_lastfm_evidence(
        cache,
        targets_from_seed_reconciliation(arguments.seed_reconciliation),
        maximum_similarity_rows=arguments.maximum_similarity_rows,
        maximum_similarity_edges=arguments.maximum_similarity_edges,
        maximum_tag_rows=arguments.maximum_tag_rows,
        maximum_tag_supports=arguments.maximum_tag_supports,
        maximum_name_only_reviews=arguments.maximum_name_only_reviews,
    )
    receipt = publish_msd_lastfm_evidence(
        artifact,
        source_cache_receipt=arguments.source_cache_receipt,
        output=arguments.output,
        store=LocalObjectStore(arguments.object_store),
    )
    arguments.receipt.parent.mkdir(parents=True, exist_ok=True)
    arguments.receipt.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(artifact.coverage.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(run(parser().parse_args()))
