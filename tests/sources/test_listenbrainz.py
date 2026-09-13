import hashlib
import io
import json
import sqlite3
import tarfile
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import zstandard
from pydantic import HttpUrl

from opennoise.catalog.co_listens import ArtistCoListenProjector, ArtistCoListenRunProjector
from opennoise.catalog.registry import ProjectorRegistry
from opennoise.models.catalog import ArtistCoListenProjection, ArtistCoListenRunProjection
from opennoise.models.listenbrainz import JointListenArtifact, ListenBrainzAggregationConfig
from opennoise.models.pipeline import (
    ParsedSourceRecord,
    RejectedSourceRecord,
    SourceLimits,
    SourceRecord,
)
from opennoise.models.sources import DownloadSource
from opennoise.pipeline.runner import DeterministicPartition, PipelineOptions, run_source_pipeline
from opennoise.sources.listenbrainz import ListenBrainzIncrementalAdapter, ListenBrainzSourceError
from opennoise.sources.registry import AdapterRegistry
from tests._test_client import PollingIsolatedAsyncioTestCase

ARTIST_A = "30238ead-59fa-41e2-a7ab-b7f6e6363c4b"
ARTIST_B = "f59c5520-5f46-4d2c-b2c4-822eabf53419"
ARTIST_C = "cc197bad-dc9c-440d-a5b5-d52ba2e14234"


def _listen(user_id: int, timestamp: int, artist_ids: list[str]) -> bytes:
    return json.dumps(
        {
            "user_id": user_id,
            "user_name": "must-not-survive",
            "timestamp": timestamp,
            "track_metadata": {
                "track_name": "discarded",
                "artist_name": "discarded",
                "additional_info": {"artist_mbids": artist_ids},
            },
        },
        separators=(",", ":"),
    ).encode()


def _archive(
    path: Path, lines: tuple[bytes, ...], *, member_name: str = "dump/listens/8.listens"
) -> None:
    payload = b"\n".join(lines) + b"\n"
    tar_bytes = io.BytesIO()
    with tarfile.open(fileobj=tar_bytes, mode="w") as archive:
        member = tarfile.TarInfo(member_name)
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    path.write_bytes(zstandard.ZstdCompressor().compress(tar_bytes.getvalue()))


def _pipeline_source(path: Path, source_id: str = "listenbrainz_fixture") -> DownloadSource:
    payload = path.read_bytes()
    return DownloadSource(
        id=source_id,
        adapter="listenbrainz_incremental_listens_v1",
        snapshot="fixture-1",
        url=HttpUrl("https://example.test/listens.tar.zst"),
        discovery_url=HttpUrl("https://listenbrainz.org/"),
        expected_content_type="application/octet-stream",
        compression="tar.zst",
        expected_bytes=len(payload),
        checksum_algorithm="sha256",
        checksum=hashlib.sha256(payload).hexdigest(),
        data_license="CC0-1.0",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        rights_classification="public_domain",
        local_only=False,
        normalize=True,
        local_search=False,
        display=False,
        embed=True,
        train=True,
        export_metadata=True,
    )


def _records(
    path: Path,
    *,
    config: ListenBrainzAggregationConfig | None = None,
    limits: SourceLimits | None = None,
) -> list[SourceRecord]:
    adapter = ListenBrainzIncrementalAdapter(config)
    effective_limits = limits or SourceLimits(max_decompression_ratio=1024.0)
    return list(adapter.iter_records(path, effective_limits, start_after=-1))


class ListenBrainzIncrementalAdapterTests(unittest.TestCase):
    def test_joint_corpus_deduplicates_users_across_contiguous_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts: list[JointListenArtifact] = []
            first_date = date(2026, 8, 1)
            for offset in range(7):
                path = root / f"{offset}.tar.zst"
                _archive(
                    path,
                    (
                        _listen(1, 61, [ARTIST_A]),
                        _listen(1, 62, [ARTIST_B]),
                        _listen(2, 63, [ARTIST_A]),
                        _listen(2, 64, [ARTIST_B]),
                    ),
                    member_name=f"dump/listens/{offset}.listens",
                )
                snapshot_date = first_date + timedelta(days=offset)
                source = _pipeline_source(path, f"listenbrainz_joint_{offset}").model_copy(
                    update={
                        "snapshot": (f"{100 + offset}-{snapshot_date:%Y%m%d}-000003-incremental")
                    }
                )
                artifacts.append(
                    JointListenArtifact(
                        source=source,
                        path=path,
                        sequence=100 + offset,
                        snapshot_date=snapshot_date,
                    )
                )
            adapter = ListenBrainzIncrementalAdapter(
                ListenBrainzAggregationConfig(
                    window_seconds=60,
                    minimum_distinct_users=2,
                    minimum_window_start=60,
                    maximum_window_start=60,
                    max_active_windows=1,
                )
            )
            records = list(
                adapter.iter_joint_records(
                    tuple(artifacts),
                    SourceLimits(max_records=100, max_decompression_ratio=1024.0),
                )
            )

            pairs = [
                record.projection
                for record in records
                if isinstance(record, ParsedSourceRecord)
                and isinstance(record.projection, ArtistCoListenProjection)
            ]
            run_record = records[-1]
            assert isinstance(run_record, ParsedSourceRecord)
            run = run_record.projection
            assert isinstance(run, ArtistCoListenRunProjection)
            self.assertEqual(len(pairs), 1)
            self.assertEqual(pairs[0].distinct_user_count, 2)
            self.assertEqual(run.listens_seen, 28)
            self.assertEqual(run.user_windows, 2)
            with self.assertRaisesRegex(ListenBrainzSourceError, "ordered and contiguous"):
                list(
                    adapter.iter_joint_records(
                        tuple(reversed(artifacts)),
                        SourceLimits(max_records=100, max_decompression_ratio=1024.0),
                    )
                )

    def test_counts_each_pair_once_per_user_window_and_emits_no_user_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "listens.tar.zst"
            _archive(
                path,
                (
                    _listen(1, 119, [ARTIST_A]),
                    _listen(1, 118, [ARTIST_B]),
                    _listen(1, 117, [ARTIST_B]),
                    _listen(2, 116, [ARTIST_A]),
                    _listen(2, 115, [ARTIST_B]),
                    _listen(3, 114, [ARTIST_A]),
                    _listen(3, 113, [ARTIST_C]),
                ),
            )
            records = _records(
                path,
                config=ListenBrainzAggregationConfig(
                    window_seconds=60,
                    minimum_distinct_users=2,
                ),
            )

        pairs = [
            record.projection
            for record in records
            if hasattr(record, "projection")
            and isinstance(record.projection, ArtistCoListenProjection)
        ]
        runs = [
            record.projection
            for record in records
            if hasattr(record, "projection")
            and isinstance(record.projection, ArtistCoListenRunProjection)
        ]
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0].distinct_user_count, 2)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].listens_seen, 7)
        self.assertEqual(runs[0].distinct_artists, 3)
        self.assertEqual(runs[0].user_windows, 3)
        serialized = b"\n".join(record.model_dump_json().encode() for record in records)
        self.assertNotIn(b"must-not-survive", serialized)
        self.assertNotIn(b"user_id", serialized)
        self.assertNotIn(b"similarity", serialized)
        self.assertNotIn(b"weight", serialized)

    def test_quarantines_malformed_record_without_retaining_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "listens.tar.zst"
            _archive(path, (b'{"user_name":"private"}',))
            records = _records(path)

        rejected = [record for record in records if isinstance(record, RejectedSourceRecord)]
        self.assertEqual(len(rejected), 1)
        self.assertNotIn("private", rejected[0].model_dump_json())
        final_record = records[-1]
        assert isinstance(final_record, ParsedSourceRecord)
        run = final_record.projection
        assert isinstance(run, ArtistCoListenRunProjection)
        self.assertEqual(run.quarantined_records, 1)

    def test_rejects_order_and_all_adapter_state_limits(self) -> None:
        scenarios = (
            (
                "ordering",
                (_listen(1, 1, [ARTIST_A]), _listen(1, 2, [ARTIST_B])),
                ListenBrainzAggregationConfig(ordering="newest_first", window_seconds=1),
                SourceLimits(),
            ),
            (
                "records",
                (_listen(1, 2, [ARTIST_A]), _listen(1, 1, [ARTIST_B])),
                ListenBrainzAggregationConfig(),
                SourceLimits(max_records=1),
            ),
            (
                "users",
                (_listen(1, 2, [ARTIST_A]), _listen(2, 1, [ARTIST_B])),
                ListenBrainzAggregationConfig(max_users_per_window=1),
                SourceLimits(),
            ),
            (
                "artists",
                (_listen(1, 1, [ARTIST_A, ARTIST_B, ARTIST_C]),),
                ListenBrainzAggregationConfig(max_artists_per_user_window=2),
                SourceLimits(),
            ),
            (
                "pairs",
                (_listen(1, 1, [ARTIST_A, ARTIST_B, ARTIST_C]),),
                ListenBrainzAggregationConfig(max_pairs_per_window=2),
                SourceLimits(),
            ),
        )
        for label, lines, config, limits in scenarios:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "listens.tar.zst"
                _archive(path, lines)
                with self.assertRaises(ListenBrainzSourceError):
                    _records(path, config=config, limits=limits)

    def test_rejects_line_member_decompression_and_path_limits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            line_path = root / "line.tar.zst"
            _archive(line_path, (_listen(1, 1, [ARTIST_A]),))
            with self.assertRaises(ListenBrainzSourceError):
                _records(line_path, limits=SourceLimits(max_record_bytes=20))
            with self.assertRaises(ListenBrainzSourceError):
                _records(line_path, limits=SourceLimits(max_member_bytes=20))
            with self.assertRaises(ListenBrainzSourceError):
                _records(line_path, limits=SourceLimits(max_decompression_ratio=0.1))

            unsafe_path = root / "unsafe.tar.zst"
            _archive(unsafe_path, (_listen(1, 1, [ARTIST_A]),), member_name="../8.listens")
            with self.assertRaises(ListenBrainzSourceError):
                _records(unsafe_path)

    def test_checkpoint_replays_source_but_skips_committed_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "listens.tar.zst"
            _archive(path, (_listen(1, 2, [ARTIST_A]), _listen(1, 1, [ARTIST_B])))
            adapter = ListenBrainzIncrementalAdapter(
                ListenBrainzAggregationConfig(minimum_distinct_users=1)
            )
            limits = SourceLimits(max_decompression_ratio=1024.0)
            first = list(adapter.iter_records(path, limits, start_after=-1))
            resumed = list(adapter.iter_records(path, limits, start_after=0))

        self.assertEqual(len(first), 2)
        self.assertEqual(len(resumed), 1)
        resumed_record = resumed[0]
        assert isinstance(resumed_record, ParsedSourceRecord)
        self.assertIsInstance(resumed_record.projection, ArtistCoListenRunProjection)


class ListenBrainzPipelineTests(PollingIsolatedAsyncioTestCase):
    async def test_ingests_only_aggregate_evidence_and_reuses_complete_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "listens.tar.zst"
            _archive(
                archive,
                (
                    b'{"user_name":"private-malformed"}',
                    _listen(1, 119, [ARTIST_A]),
                    _listen(1, 118, [ARTIST_B]),
                    _listen(2, 117, [ARTIST_A]),
                    _listen(2, 116, [ARTIST_B]),
                ),
            )
            payload = archive.read_bytes()
            source = _pipeline_source(archive)
            vault_object = root / "vault" / "raw" / "sha256" / source.checksum
            vault_object.parent.mkdir(parents=True)
            vault_object.write_bytes(payload)
            options = PipelineOptions(
                manifest_path=root / "manifest.toml",
                source_id=source.id,
                database_path=root / "catalog.sqlite",
                vault_path=root / "vault",
                partition=DeterministicPartition(sha256_prefix=""),
                limits=SourceLimits(max_decompression_ratio=1024.0),
                checkpoint_every=1,
            )
            adapters = AdapterRegistry((ListenBrainzIncrementalAdapter(),))
            projectors = ProjectorRegistry(
                (ArtistCoListenProjector(), ArtistCoListenRunProjector())
            )

            summary = await run_source_pipeline(source, adapters, projectors, options)
            reused = await run_source_pipeline(source, adapters, projectors, options)

            self.assertEqual(
                (summary.raw, summary.accepted, summary.quarantined),
                (3, 2, 1),
            )
            self.assertTrue(reused.reused_attempt)
            with sqlite3.connect(options.database_path) as connection:
                pair = connection.execute(
                    """SELECT distinct_user_count FROM artist_co_listen_evidence"""
                ).fetchone()
                run = connection.execute(
                    """SELECT listens_seen, listens_with_artist_mbid, distinct_artists,
                              user_windows, emitted_pairs, quarantined_records
                       FROM artist_co_listen_runs"""
                ).fetchone()
                staged_json = " ".join(
                    str(row[0])
                    for row in connection.execute(
                        "SELECT coalesce(parsed_json, '') FROM staged_records"
                    )
                )

        self.assertEqual(pair, (2,))
        self.assertEqual(run, (5, 4, 2, 2, 1, 1))
        self.assertNotIn("private", staged_json)
        self.assertNotIn("user_id", staged_json)

    async def test_fail_closed_error_rolls_back_and_quarantines_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "unordered.tar.zst"
            _archive(archive, (_listen(1, 1, [ARTIST_A]), _listen(1, 2, [ARTIST_B])))
            source = _pipeline_source(archive, "listenbrainz_unordered_fixture")
            vault_object = root / "vault" / "raw" / "sha256" / source.checksum
            vault_object.parent.mkdir(parents=True)
            vault_object.write_bytes(archive.read_bytes())
            options = PipelineOptions(
                manifest_path=root / "manifest.toml",
                source_id=source.id,
                database_path=root / "catalog.sqlite",
                vault_path=root / "vault",
                partition=DeterministicPartition(sha256_prefix=""),
                limits=SourceLimits(max_decompression_ratio=1024.0),
            )
            adapters = AdapterRegistry(
                (
                    ListenBrainzIncrementalAdapter(
                        ListenBrainzAggregationConfig(
                            ordering="newest_first",
                            window_seconds=1,
                        )
                    ),
                )
            )
            projectors = ProjectorRegistry(
                (ArtistCoListenProjector(), ArtistCoListenRunProjector())
            )

            with self.assertRaises(ListenBrainzSourceError):
                await run_source_pipeline(source, adapters, projectors, options)

            with sqlite3.connect(options.database_path) as connection:
                failed = connection.execute(
                    """SELECT count(*) FROM ingest_attempt_events
                       WHERE event_kind = 'failed'"""
                ).fetchone()
                quarantine = connection.execute(
                    """SELECT count(*) FROM quarantine_events
                       WHERE artifact_id IS NOT NULL AND staged_record_id IS NULL"""
                ).fetchone()
                evidence = connection.execute(
                    "SELECT count(*) FROM artist_co_listen_evidence"
                ).fetchone()

        self.assertEqual(failed, (1,))
        self.assertEqual(quarantine, (1,))
        self.assertEqual(evidence, (0,))


if __name__ == "__main__":
    unittest.main()
