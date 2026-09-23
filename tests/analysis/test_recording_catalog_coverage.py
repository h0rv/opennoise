import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from opennoise.analysis.listenbrainz_recording_co_listen import (
    RecordingCoListenExperimentSettings,
    RecordingIdCohortArtifact,
    RecordingMbidCoverage,
)
from opennoise.analysis.recording_catalog_coverage import (
    LocalCatalogInput,
    RecordingCatalogCoverageError,
    assess_recording_catalog_coverage,
)

RECORDING_A = UUID("413c57fc-a41d-4bbe-bc3d-4f86e9e97598")
RECORDING_B = UUID("6e2c5a33-39ca-4df6-8200-311a6a17a9a0")


def _cohort() -> RecordingIdCohortArtifact:
    return RecordingIdCohortArtifact(
        source_artifact_sha256="a" * 64,
        source_artifact_byte_size=1,
        settings=RecordingCoListenExperimentSettings(),
        coverage=RecordingMbidCoverage(
            raw_records_seen=2,
            valid_listen_records=2,
            malformed_listen_records=0,
            mapping_recording_mbid_present=1,
            mapping_recording_mbid_valid_uuid=1,
            additional_recording_mbid_present=1,
            additional_recording_mbid_valid_uuid=1,
            selected_resolved_mapping_recording_count=1,
            selected_submitted_additional_recording_count=1,
        ),
        recording_ids=(RECORDING_A, RECORDING_B),
        recording_id_set_sha256=hashlib.sha256(
            f"{RECORDING_A}\n{RECORDING_B}".encode()
        ).hexdigest(),
    )


def _catalog(path: Path, recordings: tuple[UUID, ...]) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(
            """CREATE TABLE recordings (id INTEGER PRIMARY KEY);
               CREATE TABLE entity_identifiers (
                   entity_id INTEGER, identifier_type_id INTEGER, value TEXT
               );
               CREATE TABLE identifier_types (id INTEGER PRIMARY KEY, type_key TEXT);"""
        )
        connection.execute("INSERT INTO identifier_types VALUES (1, 'musicbrainz_recording_id')")
        for index, recording in enumerate(recordings, start=1):
            connection.execute("INSERT INTO recordings VALUES (?)", (index,))
            connection.execute(
                "INSERT INTO entity_identifiers VALUES (?, 1, ?)", (index, str(recording))
            )
        connection.commit()


class RecordingCatalogCoverageTests(unittest.TestCase):
    def test_binds_each_catalog_and_reports_exact_union_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.sqlite"
            second = root / "second.sqlite"
            _catalog(first, (RECORDING_A,))
            _catalog(second, (RECORDING_B,))
            artifact = assess_recording_catalog_coverage(
                _cohort(),
                (
                    LocalCatalogInput(label="second", database_path=second),
                    LocalCatalogInput(label="first", database_path=first),
                ),
            )
        self.assertEqual(tuple(item.label for item in artifact.catalogs), ("first", "second"))
        self.assertEqual(tuple(item.cohort_overlap_count for item in artifact.catalogs), (1, 1))
        self.assertEqual(artifact.union_catalog_recording_id_count, 2)
        self.assertEqual(artifact.union_catalog_overlap_count, 2)
        self.assertNotIn(str(RECORDING_A), artifact.model_dump_json())
        self.assertNotIn(str(RECORDING_B), artifact.model_dump_json())

    def test_rejects_a_symlinked_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.sqlite"
            link = root / "link.sqlite"
            _catalog(target, (RECORDING_A,))
            link.symlink_to(target)
            with self.assertRaises(RecordingCatalogCoverageError):
                assess_recording_catalog_coverage(
                    _cohort(), (LocalCatalogInput(label="linked", database_path=link),)
                )

    def test_rejects_a_catalog_mutated_between_hash_and_query(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / "catalog.sqlite"
            _catalog(catalog, (RECORDING_A,))

            def mutate_after_read(_: Path) -> frozenset[str]:
                catalog.write_bytes(b"changed")
                return frozenset({f"musicbrainz:recording:{RECORDING_A}"})

            with (
                patch(
                    "opennoise.analysis.recording_catalog_coverage.load_catalog_recording_ids",
                    side_effect=mutate_after_read,
                ),
                self.assertRaises(RecordingCatalogCoverageError),
            ):
                assess_recording_catalog_coverage(
                    _cohort(), (LocalCatalogInput(label="mutable", database_path=catalog),)
                )
