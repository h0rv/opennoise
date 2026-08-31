"""Verify and jointly aggregate the pinned seven-day ListenBrainz corpus."""

import argparse
import asyncio
import hashlib
import sys
from collections.abc import Iterator
from datetime import date
from pathlib import Path

from musix.catalog.co_listens import ArtistCoListenProjector, ArtistCoListenRunProjector
from musix.catalog.registry import ProjectorRegistry
from musix.models.listenbrainz import JointListenArtifact, ListenBrainzAggregationConfig
from musix.models.pipeline import SourceLimits, SourceRecord
from musix.models.sources import DownloadResult, DownloadSource
from musix.pipeline.manifest import load_download_source
from musix.pipeline.multi_source import MultiArtifactOptions, run_multi_artifact_pipeline
from musix.sources.listenbrainz import ListenBrainzIncrementalAdapter

SOURCE_IDS = tuple(f"listenbrainz_incremental_202608{day:02d}" for day in range(24, 31))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("config/data_sources.toml"))
    parser.add_argument("--database", type=Path, default=Path("data/public.sqlite"))
    parser.add_argument("--vault", type=Path, default=Path("data/vault"))
    parser.add_argument("--source-id", action="append", dest="source_ids")
    return parser.parse_args()


def _joint_artifacts(
    sources: tuple[DownloadSource, ...], downloads: tuple[DownloadResult, ...]
) -> tuple[JointListenArtifact, ...]:
    result: list[JointListenArtifact] = []
    for source, download in zip(sources, downloads, strict=True):
        parts = source.snapshot.split("-")
        result.append(
            JointListenArtifact(
                source=source,
                path=download.path,
                sequence=int(parts[0]),
                snapshot_date=date.fromisoformat(f"{parts[1][:4]}-{parts[1][4:6]}-{parts[1][6:8]}"),
            )
        )
    return tuple(result)


async def _run(args: argparse.Namespace) -> str:
    source_ids = tuple(args.source_ids or SOURCE_IDS)
    sources = tuple(load_download_source(args.manifest, source_id) for source_id in source_ids)
    config = ListenBrainzAggregationConfig(
        ordering="unordered_bounded",
        window_seconds=86_400,
        minimum_distinct_users=5,
        minimum_window_start=1_787_443_200,
        maximum_window_start=1_787_961_600,
        max_users_per_window=500_000,
        max_distinct_artists=500_000,
        max_pairs_per_window=2_000_000,
        max_active_windows=7,
        max_total_user_windows=3_500_000,
    )
    adapter = ListenBrainzIncrementalAdapter(config)

    def records(downloads: tuple[DownloadResult, ...]) -> Iterator[SourceRecord]:
        return adapter.iter_joint_records(
            _joint_artifacts(sources, downloads),
            SourceLimits(
                max_archive_bytes=300_000_000,
                max_record_bytes=2_097_152,
                max_records=50_000_000,
                timeout_seconds=7_200,
            ),
        )

    limits = SourceLimits(
        max_archive_bytes=300_000_000,
        max_record_bytes=2_097_152,
        max_records=50_000_000,
        timeout_seconds=7_200,
    )
    summary = await run_multi_artifact_pipeline(
        sources,
        adapter,
        ProjectorRegistry((ArtistCoListenProjector(), ArtistCoListenRunProjector())),
        records,
        MultiArtifactOptions(
            manifest_path=args.manifest,
            database_path=args.database,
            vault_path=args.vault,
            aggregate_source_id="listenbrainz_joint_20260824_20260830",
            configuration_sha256=hashlib.sha256(config.model_dump_json().encode()).hexdigest(),
            limits=limits,
        ),
    )
    return summary.model_dump_json(indent=2)


def main() -> int:
    """Run the exact joint aggregation without retaining listener identifiers."""
    sys.stdout.write(f"{asyncio.run(_run(_arguments()))}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
