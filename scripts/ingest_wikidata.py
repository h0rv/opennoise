"""Fetch and ingest the checked-in bounded Wikidata music query."""

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

from pydantic import HttpUrl, TypeAdapter

from opennoise.catalog.entities import EntityProjector
from opennoise.catalog.registry import ProjectorRegistry
from opennoise.clients.wikidata import WikidataQueryRequest, fetch_wikidata_query
from opennoise.models.pipeline import SourceLimits
from opennoise.models.sources import DownloadSource
from opennoise.pipeline.runner import DeterministicPartition, PipelineOptions, run_source_pipeline
from opennoise.sources.registry import AdapterRegistry
from opennoise.sources.wikidata import WikidataSourceAdapter
from opennoise.types import SourceId


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _publish_artifact(staging_path: Path, vault_path: Path, sha256: str) -> Path:
    destination = vault_path / "raw" / "sha256" / sha256
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if _sha256_file(destination) != sha256:
            raise RuntimeError("existing Wikidata vault object failed its hash check")
        staging_path.unlink()
    else:
        staging_path.replace(destination)
    return destination


async def _run(args: argparse.Namespace) -> dict[str, object]:
    source_id = TypeAdapter(SourceId).validate_python(args.source_id, strict=True)
    staging_path = args.vault / "staging" / f"{source_id}.json"
    result = await fetch_wikidata_query(
        WikidataQueryRequest(
            query_path=args.query,
            destination=staging_path,
            user_agent=args.user_agent,
            max_response_bytes=args.max_archive_bytes,
            timeout_seconds=args.timeout_seconds,
        )
    )
    _publish_artifact(result.path, args.vault, result.sha256)
    source = DownloadSource(
        id=source_id,
        adapter="wikidata_music_sparql_slice_v1",
        snapshot=f"query:{result.query_sha256}:artifact:{result.sha256}",
        url=HttpUrl("https://query.wikidata.org/sparql"),
        discovery_url=HttpUrl("https://www.wikidata.org/wiki/Wikidata:Data_access"),
        expected_content_type="application/sparql-results+json",
        compression="none",
        expected_bytes=result.byte_size,
        checksum_algorithm="sha256",
        checksum=result.sha256,
        data_license="CC0-1.0",
        license_url="https://www.wikidata.org/wiki/Wikidata:Licensing",
        rights_classification="public_domain",
        local_only=False,
        normalize=True,
        local_search=True,
        display=True,
        embed=True,
        train=True,
        export_metadata=True,
    )
    summary = await run_source_pipeline(
        source,
        AdapterRegistry((WikidataSourceAdapter(),)),
        ProjectorRegistry((EntityProjector(),)),
        PipelineOptions(
            manifest_path=Path("config/data_sources.toml"),
            source_id=source.id,
            database_path=args.database,
            vault_path=args.vault,
            partition=DeterministicPartition(sha256_prefix=""),
            limits=SourceLimits(
                max_archive_bytes=args.max_archive_bytes,
                max_records=args.max_records,
                timeout_seconds=args.timeout_seconds,
            ),
            checkpoint_every=args.checkpoint_every,
        ),
    )
    return {
        "query_sha256": result.query_sha256,
        "artifact_sha256": result.sha256,
        "artifact_bytes": result.byte_size,
        "pipeline": summary.model_dump(mode="json"),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", type=Path, default=Path("config/wikidata_music_slice.rq"))
    parser.add_argument("--source-id", default="wikidata_music_sparql_slice")
    parser.add_argument("--database", type=Path, default=Path("data/opennoise.sqlite"))
    parser.add_argument("--vault", type=Path, default=Path("data/vault"))
    parser.add_argument(
        "--user-agent",
        default="opennoise/0.1 (https://github.com/h0rv/opennoise)",
    )
    parser.add_argument("--max-archive-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--max-records", type=int, default=20_000)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--checkpoint-every", type=int, default=25)
    return parser


def main() -> int:
    """Run the bounded acquisition and shared ingestion pipeline."""
    output = asyncio.run(_run(_parser().parse_args()))
    sys.stdout.write(f"{json.dumps(output, indent=2, sort_keys=True)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
