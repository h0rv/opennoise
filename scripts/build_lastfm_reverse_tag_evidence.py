"""Build fixture-replayable, review-only Last.fm reverse tag evidence."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from musix.ingest.lastfm.reverse_tag import (
    LastFmHttpClient,
    LastFmResponseCache,
    LastFmReverseTagAdapter,
    LastFmReverseTagSettings,
    ReverseTagAdapterRegistry,
    publish_lastfm_reverse_tag_evidence,
    write_lastfm_query_manifest,
)
from musix.storage import LocalObjectStore
from musix.taxonomy.seeds.reconciliation import load_seed_reconciliation


def build_parser() -> argparse.ArgumentParser:
    """Expose a bounded, cache-first Last.fm source claim collection contract."""
    parser = argparse.ArgumentParser(prog="build-lastfm-reverse-tag-evidence")
    parser.add_argument("--seed-reconciliation", type=Path, required=True)
    parser.add_argument("--query-manifest", type=Path, required=True)
    parser.add_argument("--response-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--maximum-seed-labels", type=int, default=6_291)
    parser.add_argument("--top-artists-per-tag", type=int, default=3)
    parser.add_argument("--maximum-tags-per-artist", type=int, default=100)
    parser.add_argument("--maximum-response-bytes", type=int, default=2 * 1024 * 1024)
    parser.add_argument("--maximum-concurrency", type=int, default=4)
    parser.add_argument("--requests-per-second", type=float, default=3.0)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=3)
    return parser


async def _run(arguments: argparse.Namespace) -> int:
    reconciliation = load_seed_reconciliation(arguments.seed_reconciliation)
    settings = LastFmReverseTagSettings(
        maximum_seed_labels=arguments.maximum_seed_labels,
        top_artists_per_tag=arguments.top_artists_per_tag,
        maximum_tags_per_artist=arguments.maximum_tags_per_artist,
        maximum_response_bytes=arguments.maximum_response_bytes,
        maximum_concurrency=arguments.maximum_concurrency,
        requests_per_second=arguments.requests_per_second,
        timeout_seconds=arguments.timeout_seconds,
        retries=arguments.retries,
    )
    adapter = ReverseTagAdapterRegistry((LastFmReverseTagAdapter(),)).resolve(
        "lastfm_reverse_tag_v1"
    )
    manifest = adapter.build_query_manifest(reconciliation, settings)
    manifest_sha256 = write_lastfm_query_manifest(manifest, arguments.query_manifest)
    api_key = os.environ.get("LASTFM_API_KEY") or None
    if api_key is None and not arguments.offline:
        sys.stderr.write(
            "Last.fm full fetch blocked: LASTFM_API_KEY is not set; "
            f"wrote query manifest {manifest_sha256}.\n"
        )
        return 2
    client = LastFmHttpClient(
        api_key=api_key,
        cache=LastFmResponseCache(arguments.response_cache),
        settings=settings,
        offline=arguments.offline,
    )
    collection = await adapter.collect(manifest, client)
    receipt = publish_lastfm_reverse_tag_evidence(
        collection,
        query_manifest_path=arguments.query_manifest,
        output_path=arguments.output,
        store=LocalObjectStore(arguments.object_store),
    )
    arguments.receipt.parent.mkdir(parents=True, exist_ok=True)
    arguments.receipt.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(collection.coverage.model_dump_json(indent=2) + "\n")
    return 0


def main() -> int:
    """Write a query manifest, then run only an authorized live or offline cache replay."""
    return asyncio.run(_run(build_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
