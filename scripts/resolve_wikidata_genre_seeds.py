"""Resolve one bounded name-only Wikidata genre-seed batch and publish its evidence."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from musix.storage import LocalObjectStore
from musix.wikidata_seed_resolver import (
    WikidataResolverConfig,
    publish_wikidata_seed_resolution,
    resolve_wikidata_seed_batch,
)


def parser() -> argparse.ArgumentParser:
    """Build the bounded Wikidata resolver command line."""
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--seed-source", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--object-store", type=Path, required=True)
    command.add_argument("--cache-directory", type=Path, required=True)
    command.add_argument("--user-agent", required=True)
    command.add_argument("--batch-limit", type=int, default=250)
    command.add_argument("--sparql-terms-per-request", type=int, default=25)
    command.add_argument("--offline", action="store_true")
    command.add_argument("--expected-seed-count", type=int, default=6291)
    return command


async def _run(arguments: argparse.Namespace) -> int:
    config = WikidataResolverConfig(
        expected_seed_count=arguments.expected_seed_count,
        batch_limit=arguments.batch_limit,
        sparql_terms_per_request=arguments.sparql_terms_per_request,
        user_agent=arguments.user_agent,
    )
    artifact = await resolve_wikidata_seed_batch(
        arguments.seed_source,
        config=config,
        cache_directory=arguments.cache_directory,
        offline=arguments.offline,
    )
    publication = publish_wikidata_seed_resolution(
        artifact, output=arguments.output, store=LocalObjectStore(arguments.object_store)
    )
    sys.stdout.write(
        json.dumps(
            {
                "output_sha256": artifact.output_sha256,
                "counts": artifact.counts.model_dump(mode="json"),
                "runtime": artifact.runtime.model_dump(mode="json"),
                "publication": publication.model_dump(mode="json"),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return 0


def main() -> int:
    """Run the bounded resolver with a required descriptive User-Agent."""
    try:
        return asyncio.run(_run(parser().parse_args()))
    except (OSError, ValueError) as error:
        sys.stderr.write(f"Wikidata seed resolution failed: {error}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
