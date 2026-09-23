import hashlib
import io
import json
import sqlite3
import tarfile
import tempfile
import unittest
from pathlib import Path

import zstandard

from opennoise.analysis.listenbrainz_recording_co_listen import (
    RecordingCoListenExperimentError,
    RecordingCoListenExperimentSettings,
    build_recording_id_cohort,
    load_catalog_recording_ids,
    recording_id_set_sha256,
    run_recording_co_listen_experiment,
)

MAPPING_RECORDING = "413c57fc-a41d-4bbe-bc3d-4f86e9e97598"
SUBMITTED_RECORDING = "6e2c5a33-39ca-4df6-8200-311a6a17a9a0"


def _listen(
    user_id: int,
    timestamp: int,
    *,
    mapping: str | None = None,
    additional: str | None = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "artist_name": "must not survive",
        "track_name": "must not survive",
    }
    if mapping is not None:
        metadata["mbid_mapping"] = {"recording_mbid": mapping}
    if additional is not None:
        metadata["additional_info"] = {"recording_mbid": additional}
    return {"user_id": user_id, "timestamp": timestamp, "track_metadata": metadata}


def _write_archive(path: Path, records: list[dict[str, object]]) -> None:
    payload = b"".join(json.dumps(record).encode() + b"\n" for record in records)
    tar_stream = io.BytesIO()
    with tarfile.open(fileobj=tar_stream, mode="w") as archive:
        info = tarfile.TarInfo("2026/8.listens")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    path.write_bytes(zstandard.ZstdCompressor().compress(tar_stream.getvalue()))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RecordingCoListenExperimentTests(unittest.TestCase):
    def test_builds_deterministic_local_id_cohort_without_listener_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "listens.tar.zst"
            _write_archive(
                archive,
                [
                    _listen(1, 1_800_000_001, additional=SUBMITTED_RECORDING),
                    _listen(2, 1_800_000_002, additional=SUBMITTED_RECORDING),
                    _listen(3, 1_800_000_003, mapping=MAPPING_RECORDING),
                ],
            )
            cohort = build_recording_id_cohort(
                archive_path=archive,
                source_artifact_sha256=_sha256(archive),
            )
        self.assertEqual(
            tuple(map(str, cohort.recording_ids)), (MAPPING_RECORDING, SUBMITTED_RECORDING)
        )
        self.assertEqual(cohort.coverage.selected_resolved_mapping_recording_count, 1)
        self.assertEqual(cohort.coverage.selected_submitted_additional_recording_count, 2)
        serialized = cohort.model_dump_json()
        self.assertNotIn("user_id", serialized)
        self.assertNotIn("must not survive", serialized)

    def test_uses_mapping_before_submitted_fallback_and_emits_only_counts(self) -> None:
        records: list[dict[str, object]] = []
        for user_id in range(1, 6):
            records.append(
                _listen(
                    user_id,
                    1_800_000_001,
                    mapping=MAPPING_RECORDING,
                    additional=SUBMITTED_RECORDING,
                )
            )
            records.append(_listen(user_id, 1_800_000_002, additional=SUBMITTED_RECORDING))
        records.append(_listen(99, 1_800_000_003, mapping="not-a-uuid"))

        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "listens.tar.zst"
            _write_archive(archive, records)
            artifact = run_recording_co_listen_experiment(
                archive_path=archive,
                source_artifact_sha256=_sha256(archive),
                catalog_recording_ids=frozenset({f"musicbrainz:recording:{MAPPING_RECORDING}"}),
                catalog_database_sha256="b" * 64,
            )

        self.assertEqual(artifact.coverage.raw_records_seen, 11)
        self.assertEqual(artifact.coverage.mapping_recording_mbid_present, 6)
        self.assertEqual(artifact.coverage.mapping_recording_mbid_valid_uuid, 5)
        self.assertEqual(artifact.coverage.additional_recording_mbid_present, 10)
        self.assertEqual(artifact.coverage.selected_resolved_mapping_recording_count, 5)
        self.assertEqual(artifact.coverage.selected_submitted_additional_recording_count, 5)
        self.assertEqual(artifact.aggregation.unique_selected_recording_count, 2)
        self.assertEqual(artifact.aggregation.candidate_pair_count, 1)
        self.assertEqual(artifact.aggregation.privacy_filtered_pair_count, 1)
        self.assertEqual(artifact.aggregation.catalog_recording_overlap_count, 1)
        self.assertEqual(artifact.catalog_database_sha256, "b" * 64)
        self.assertEqual(
            artifact.catalog_recording_id_set_sha256,
            recording_id_set_sha256(frozenset({f"musicbrainz:recording:{MAPPING_RECORDING}"})),
        )
        serialized = artifact.model_dump_json()
        self.assertNotIn(MAPPING_RECORDING, serialized)
        self.assertNotIn(SUBMITTED_RECORDING, serialized)
        self.assertNotIn("user_id", serialized)
        self.assertNotIn("must not survive", serialized)

    def test_stops_at_explicit_prefix_bound(self) -> None:
        records = [
            _listen(1, 1_800_000_001, additional=SUBMITTED_RECORDING),
            _listen(2, 1_800_000_002, additional=SUBMITTED_RECORDING),
        ]
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "listens.tar.zst"
            _write_archive(archive, records)
            artifact = run_recording_co_listen_experiment(
                archive_path=archive,
                source_artifact_sha256=_sha256(archive),
                catalog_recording_ids=frozenset(),
                catalog_database_sha256="b" * 64,
                settings=RecordingCoListenExperimentSettings(maximum_records=1),
            )
        self.assertEqual(artifact.coverage.raw_records_seen, 1)
        self.assertEqual(artifact.coverage.selected_submitted_additional_recording_count, 1)

    def test_rejects_an_archive_that_does_not_match_its_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "listens.tar.zst"
            _write_archive(archive, [_listen(1, 1_800_000_001, additional=SUBMITTED_RECORDING)])
            with self.assertRaises(RecordingCoListenExperimentError):
                run_recording_co_listen_experiment(
                    archive_path=archive,
                    source_artifact_sha256="a" * 64,
                    catalog_recording_ids=frozenset(),
                    catalog_database_sha256="b" * 64,
                )

    def test_rejects_an_archive_over_its_explicit_byte_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "listens.tar.zst"
            _write_archive(archive, [_listen(1, 1_800_000_001, additional=SUBMITTED_RECORDING)])
            with self.assertRaises(RecordingCoListenExperimentError):
                run_recording_co_listen_experiment(
                    archive_path=archive,
                    source_artifact_sha256=_sha256(archive),
                    catalog_recording_ids=frozenset(),
                    catalog_database_sha256="b" * 64,
                    settings=RecordingCoListenExperimentSettings(maximum_archive_bytes=1),
                )

    def test_loads_only_exact_catalog_recording_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / "catalog.sqlite"
            with sqlite3.connect(catalog) as connection:
                connection.executescript(
                    """CREATE TABLE recordings (id INTEGER PRIMARY KEY);
                       CREATE TABLE entity_identifiers (
                           entity_id INTEGER, identifier_type_id INTEGER, value TEXT
                       );
                       CREATE TABLE identifier_types (id INTEGER PRIMARY KEY, type_key TEXT);"""
                )
                connection.execute("INSERT INTO recordings VALUES (1)")
                connection.execute(
                    "INSERT INTO identifier_types VALUES (1, 'musicbrainz_recording_id')"
                )
                connection.execute(
                    "INSERT INTO entity_identifiers VALUES (1, 1, ?)", (MAPPING_RECORDING,)
                )
            self.assertEqual(
                load_catalog_recording_ids(catalog),
                frozenset({f"musicbrainz:recording:{MAPPING_RECORDING}"}),
            )
