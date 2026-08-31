"""Build and validate one joint, event-time ListenBrainz graph corpus."""

import argparse
import asyncio
import sqlite3
import sys
import tempfile
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path

from musix.clients.downloads import download_verified
from musix.ml.repository import PublicInputLoadSettings, PublicModelRepository
from musix.ml.validation import build_graph_validation
from musix.ml.validation_repository import GraphValidationRepository, ValidationLoadSettings
from musix.models.catalog import ArtistCoListenProjection, ArtistCoListenRunProjection
from musix.models.listenbrainz import JointListenArtifact, ListenBrainzAggregationConfig
from musix.models.modeling import ArtistPairEvidence, PublicArtifact, PublicModelSettings
from musix.models.pipeline import ParsedSourceRecord, SourceLimits
from musix.models.sources import DownloadResult, DownloadSource
from musix.models.validation import (
    GraphValidationInput,
    GraphValidationSettings,
    TemporalPairWindow,
)
from musix.pipeline.manifest import load_download_source
from musix.sources.listenbrainz import ListenBrainzIncrementalAdapter

_SOURCE_IDS = tuple(f"listenbrainz_incremental_202608{day:02d}" for day in range(24, 31))
_FIRST_WINDOW = datetime(2026, 8, 23, tzinfo=UTC)
_LAST_WINDOW = datetime(2026, 8, 29, tzinfo=UTC)
_WINDOW_SECONDS = 86_400
_MINIMUM_DISTINCT_USERS = 5


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("config/data_sources.toml"))
    parser.add_argument("--catalog-db", type=Path, default=Path("data/musix.sqlite"))
    parser.add_argument("--vault", type=Path, default=Path("data/vault"))
    parser.add_argument(
        "--output", type=Path, default=Path("data/model/public-graph-validation-v1.json")
    )
    parser.add_argument("--max-direct-memberships", type=int, default=100_000)
    parser.add_argument("--max-metadata-candidates", type=int, default=100_000)
    parser.add_argument("--neighbors-per-genre", type=int, default=10)
    return parser.parse_args()


def _read_only(path: Path) -> sqlite3.Connection:
    absolute = path.resolve(strict=True)
    return sqlite3.connect(f"file:{absolute.as_posix()}?mode=ro", uri=True)


def _write_atomic(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary.flush()
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


async def _download_sources(
    sources: tuple[DownloadSource, ...], vault: Path
) -> tuple[DownloadResult, ...]:
    async with asyncio.TaskGroup() as group:
        tasks = tuple(group.create_task(download_verified(source, vault)) for source in sources)
    return tuple(task.result() for task in tasks)


def _joint_artifact(source: DownloadSource, result: DownloadResult) -> JointListenArtifact:
    parts = source.snapshot.split("-")
    return JointListenArtifact(
        source=source,
        path=result.path,
        sequence=int(parts[0]),
        snapshot_date=date.fromisoformat(f"{parts[1][:4]}-{parts[1][4:6]}-{parts[1][6:8]}"),
    )


def _aggregate_joint_corpus(
    artifacts: tuple[JointListenArtifact, ...],
) -> tuple[tuple[TemporalPairWindow, ...], ArtistCoListenRunProjection]:
    adapter = ListenBrainzIncrementalAdapter(
        ListenBrainzAggregationConfig(
            minimum_distinct_users=_MINIMUM_DISTINCT_USERS,
            max_users_per_window=500_000,
            max_distinct_artists=500_000,
            max_pairs_per_window=2_000_000,
            max_active_windows=7,
            max_total_user_windows=3_500_000,
            minimum_window_start=int(_FIRST_WINDOW.timestamp()),
            maximum_window_start=int(_LAST_WINDOW.timestamp()),
        )
    )
    limits = SourceLimits(
        max_archive_bytes=300_000_000,
        max_record_bytes=2 * 1024 * 1024,
        max_records=50_000_000,
        timeout_seconds=2 * 60 * 60,
    )
    grouped: dict[int, list[ArtistPairEvidence]] = defaultdict(list)
    run: ArtistCoListenRunProjection | None = None
    for record in adapter.iter_joint_records(artifacts, limits):
        if not isinstance(record, ParsedSourceRecord):
            continue
        projection = record.projection
        if isinstance(projection, ArtistCoListenProjection):
            grouped[projection.window_start].append(
                ArtistPairEvidence(
                    left_artist_id=projection.left_artist_source_id,
                    right_artist_id=projection.right_artist_source_id,
                    listener_day_support=projection.distinct_user_count,
                    supporting_windows=1,
                    evidence_refs=(f"listenbrainz:joint-window:{projection.external_id}",),
                )
            )
        elif isinstance(projection, ArtistCoListenRunProjection):
            if run is not None:
                raise RuntimeError("joint aggregation emitted more than one completion record")
            run = projection
    if run is None:
        raise RuntimeError("joint aggregation did not emit a completion record")
    expected_starts = tuple(
        range(
            int(_FIRST_WINDOW.timestamp()),
            int(_LAST_WINDOW.timestamp()) + _WINDOW_SECONDS,
            _WINDOW_SECONDS,
        )
    )
    windows = tuple(
        TemporalPairWindow(
            window_start=window_start,
            window_end=window_start + _WINDOW_SECONDS,
            pairs=tuple(
                sorted(
                    grouped[window_start],
                    key=lambda pair: (
                        -pair.listener_day_support,
                        pair.left_artist_id,
                        pair.right_artist_id,
                    ),
                )
            ),
        )
        for window_start in expected_starts
    )
    return windows, run


def _public_artifacts(
    sources: tuple[DownloadSource, ...], results: tuple[DownloadResult, ...]
) -> tuple[PublicArtifact, ...]:
    return tuple(
        PublicArtifact(
            source="listenbrainz",
            snapshot=source.snapshot,
            artifact_key=f"{source.id}:{result.sha256}",
            content_sha256=result.sha256,
            export_allowed=source.export_metadata,
        )
        for source, result in zip(sources, results, strict=True)
    )


def main() -> None:
    """Download, jointly aggregate, validate, and atomically write one report."""
    arguments = _arguments()
    sources = tuple(
        load_download_source(arguments.manifest, source_id) for source_id in _SOURCE_IDS
    )
    results = asyncio.run(_download_sources(sources, arguments.vault))
    joint_artifacts = tuple(
        _joint_artifact(source, result) for source, result in zip(sources, results, strict=True)
    )
    windows, corpus_run = _aggregate_joint_corpus(joint_artifacts)
    load_settings = PublicInputLoadSettings(
        max_direct_memberships=arguments.max_direct_memberships,
        max_artist_pairs=1,
        max_metadata_candidates=arguments.max_metadata_candidates,
    )
    model_settings = PublicModelSettings(
        neighbors_per_genre=max(arguments.neighbors_per_genre, 25),
        layout_profile="one_hop",
        max_genres=2_000,
        max_artists=250_000,
        max_direct_memberships=arguments.max_direct_memberships,
        max_artist_pairs=2_000_000,
        max_propagation_visits=10_000_000,
        max_similarity_pair_visits=10_000_000,
    )
    validation_settings = GraphValidationSettings(neighbors_per_genre=arguments.neighbors_per_genre)
    with _read_only(arguments.catalog_db) as catalog:
        base_inputs = PublicModelRepository(catalog).load_catalog_only(load_settings)
        hierarchy = GraphValidationRepository(catalog).hierarchy_edges(ValidationLoadSettings())
    artifact = build_graph_validation(
        GraphValidationInput(
            base_inputs=base_inputs,
            source_artifacts=_public_artifacts(sources, results),
            event_windows=windows,
            corpus_run=corpus_run,
            hierarchy=hierarchy,
            input_database_bytes=arguments.catalog_db.stat().st_size,
            input_artifact_bytes=sum(result.byte_size for result in results),
        ),
        model_settings,
        validation_settings,
    )
    _write_atomic(arguments.output, artifact.model_dump_json(indent=2))
    summary = artifact.model_dump_json(
        include={
            "output_sha256",
            "export_allowed",
            "event_windows",
            "corpus_run",
            "hierarchy_edges",
            "community_stability",
            "neighborhood",
            "temporal",
            "source_holdout",
            "deterministic_rerun",
            "resources",
        },
        indent=2,
    )
    sys.stdout.write(f"{summary}\n")


if __name__ == "__main__":
    main()
