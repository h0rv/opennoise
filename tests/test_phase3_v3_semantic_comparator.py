from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from opennoise.pipeline.phase3_v3_semantic_comparator import (
    Phase3V3SemanticComparison,
    Phase3V3SemanticComparisonError,
    Phase3V3SemanticInputs,
    compare_phase3_v3_semantics,
)


class Phase3V3SemanticComparatorTests(unittest.TestCase):
    def test_equal_inputs_compare_every_contract_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            v3_model = root / "v3.json"
            sealed_model = root / "sealed.json"
            v3_database = root / "v3.sqlite"
            sealed_database = root / "sealed.sqlite"
            _write_model(v3_model)
            _write_model(sealed_model)
            _write_database(v3_database)
            _write_database(sealed_database)
            report = _compare(v3_model, sealed_model, v3_database, sealed_database)
        self.assertTrue(report.equal)
        rows = {item.name: item for item in report.projections}
        self.assertEqual(rows["artist_pair_supports_and_windows"].v3_rows, 1)
        self.assertEqual(rows["layout_coordinates"].v3_rows, 2)
        self.assertEqual(rows["normalized_provenance_bindings"].v3_rows, 1)
        self.assertIn('"equal": true', report.to_json())

    def test_one_hop_reference_representation_is_the_only_ignored_difference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            v3_model = root / "v3.json"
            sealed_model = root / "sealed.json"
            v3_database = root / "v3.sqlite"
            sealed_database = root / "sealed.sqlite"
            _write_model(v3_model, one_hop_ref="compact:v3")
            _write_model(sealed_model, one_hop_ref="expanded:sealed")
            _write_database(v3_database)
            _write_database(sealed_database)
            report = _compare(v3_model, sealed_model, v3_database, sealed_database)
        self.assertTrue(report.equal)

    def test_pair_and_provenance_drift_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            v3_model = root / "v3.json"
            sealed_model = root / "sealed.json"
            v3_database = root / "v3.sqlite"
            sealed_database = root / "sealed.sqlite"
            _write_model(v3_model)
            _write_model(sealed_model)
            _write_database(v3_database, support=3, record_fingerprint="a" * 64)
            _write_database(sealed_database, support=4, record_fingerprint="b" * 64)
            report = _compare(v3_model, sealed_model, v3_database, sealed_database)
        rows = {item.name: item for item in report.projections}
        self.assertFalse(report.equal)
        self.assertFalse(rows["colisten_raw_windows"].equal)
        self.assertFalse(rows["artist_pair_supports_and_windows"].equal)
        self.assertFalse(rows["normalized_provenance_bindings"].equal)
        self.assertEqual(rows["normalized_provenance_bindings"].v3_only_rows, 1)
        self.assertEqual(rows["normalized_provenance_bindings"].sealed_only_rows, 1)

    def test_rejects_an_unpinned_input_before_opening_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "model.json"
            database = root / "database.sqlite"
            _write_model(model)
            _write_database(database)
            with self.assertRaisesRegex(Phase3V3SemanticComparisonError, "SHA-256 mismatch"):
                compare_phase3_v3_semantics(
                    Phase3V3SemanticInputs(
                        v3_model=model,
                        sealed_model=model,
                        v3_database=database,
                        sealed_database=database,
                        expected_v3_model_sha256="0" * 64,
                        expected_sealed_model_sha256=_sha256(model),
                        expected_v3_database_sha256=_sha256(database),
                        expected_sealed_database_sha256=_sha256(database),
                    )
                )

    def test_rejects_database_run_with_a_different_model_input_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            v3_model = root / "v3.json"
            sealed_model = root / "sealed.json"
            v3_database = root / "v3.sqlite"
            sealed_database = root / "sealed.sqlite"
            _write_model(v3_model)
            _write_model(sealed_model)
            _write_database(v3_database, model_input_sha256="b" * 64)
            _write_database(sealed_database)
            with self.assertRaisesRegex(Phase3V3SemanticComparisonError, "does not bind"):
                _compare(v3_model, sealed_model, v3_database, sealed_database)

    def test_rejects_coerced_model_tuple_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            v3_model = root / "v3.json"
            sealed_model = root / "sealed.json"
            v3_database = root / "v3.sqlite"
            sealed_database = root / "sealed.sqlite"
            _write_model(v3_model)
            payload = json.loads(v3_model.read_text(encoding="utf-8"))
            payload["profiles"][0]["memberships"][0]["score"] = "1.0"
            v3_model.write_text(json.dumps(payload), encoding="utf-8")
            _write_model(sealed_model)
            _write_database(v3_database)
            _write_database(sealed_database)
            with self.assertRaisesRegex(Phase3V3SemanticComparisonError, "cannot parse model"):
                _compare(v3_model, sealed_model, v3_database, sealed_database)

    def test_cli_writes_unequal_report_and_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            v3_model = root / "v3.json"
            sealed_model = root / "sealed.json"
            v3_database = root / "v3.sqlite"
            sealed_database = root / "sealed.sqlite"
            report_path = root / "report.json"
            _write_model(v3_model)
            _write_model(sealed_model)
            _write_database(v3_database, record_fingerprint="a" * 64)
            _write_database(sealed_database, record_fingerprint="b" * 64)
            result = subprocess.run(  # noqa: S603 -- fixed local test command and paths
                [
                    sys.executable,
                    "scripts/compare_phase3_v3_semantics.py",
                    "--v3-model",
                    str(v3_model),
                    "--sealed-model",
                    str(sealed_model),
                    "--v3-database",
                    str(v3_database),
                    "--sealed-database",
                    str(sealed_database),
                    "--v3-model-sha256",
                    _sha256(v3_model),
                    "--sealed-model-sha256",
                    _sha256(sealed_model),
                    "--v3-database-sha256",
                    _sha256(v3_database),
                    "--sealed-database-sha256",
                    _sha256(sealed_database),
                    "--report",
                    str(report_path),
                ],
                check=False,
                cwd=Path.cwd(),
            )
            self.assertEqual(result.returncode, 1)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            provenance = next(
                item
                for item in report["projections"]
                if item["name"] == "normalized_provenance_bindings"
            )
            self.assertFalse(report["equal"])
            self.assertEqual(provenance["v3_only_rows"], 1)
            self.assertEqual(provenance["sealed_only_rows"], 1)

    def test_rejects_projection_that_exceeds_its_row_cap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            v3_model = root / "v3.json"
            sealed_model = root / "sealed.json"
            v3_database = root / "v3.sqlite"
            sealed_database = root / "sealed.sqlite"
            _write_model(v3_model)
            _write_model(sealed_model)
            _write_database(v3_database)
            _write_database(sealed_database)
            with self.assertRaisesRegex(Phase3V3SemanticComparisonError, "layout_coordinates"):
                compare_phase3_v3_semantics(
                    _inputs(v3_model, sealed_model, v3_database, sealed_database),
                    maximum_rows_per_projection=1,
                )


def _compare(
    v3_model: Path, sealed_model: Path, v3_database: Path, sealed_database: Path
) -> Phase3V3SemanticComparison:
    return compare_phase3_v3_semantics(
        _inputs(v3_model, sealed_model, v3_database, sealed_database)
    )


def _inputs(
    v3_model: Path, sealed_model: Path, v3_database: Path, sealed_database: Path
) -> Phase3V3SemanticInputs:
    return Phase3V3SemanticInputs(
        v3_model=v3_model,
        sealed_model=sealed_model,
        v3_database=v3_database,
        sealed_database=sealed_database,
        expected_v3_model_sha256=_sha256(v3_model),
        expected_sealed_model_sha256=_sha256(sealed_model),
        expected_v3_database_sha256=_sha256(v3_database),
        expected_sealed_database_sha256=_sha256(sealed_database),
    )


def _write_model(path: Path, *, one_hop_ref: str = "one-hop") -> None:
    payload = {
        "input_sha256": "a" * 64,
        "settings_sha256": "b" * 64,
        "output_sha256": "z" * 64,
        "artifacts": [
            {
                "source": "listenbrainz",
                "snapshot": "snapshot",
                "artifact_key": "artifact",
                "content_sha256": "a" * 64,
                "export_allowed": True,
            }
        ],
        "genres": [{"genre_id": "genre", "name": "Genre"}],
        "profiles": [
            {
                "genre_id": "genre",
                "profile_kind": "direct",
                "memberships": [_membership("artist", "direct")],
            },
            {
                "genre_id": "genre",
                "profile_kind": "one_hop",
                "memberships": [_membership("peer", one_hop_ref)],
            },
        ],
        "neighbors": [
            {
                "genre_id": "genre",
                "neighbor_genre_id": "other",
                "profile_kind": "direct",
                "metric": "weighted_jaccard",
                "score": 0.5,
                "shared_artist_count": 1,
                "rank": 1,
            }
        ],
        "representatives": [
            {
                "genre_id": "genre",
                "entity_kind": "artist",
                "entity_id": "artist",
                "name": "Artist",
                "rank": 1,
                "direct_evidence_value": 1.0,
                "source_count": 1,
            }
        ],
        "layouts": [
            {
                "layout_key": "public",
                "is_default": True,
                "method": "normalized_laplacian_spectral",
                "method_version": "1",
                "input_kind": "one_hop",
                "metric": "weighted_jaccard",
                "seed": 1,
                "coordinates": [
                    {"genre_id": "genre", "x": 0.1, "y": 0.2, "component": 0},
                    {"genre_id": "other", "x": 0.3, "y": 0.4, "component": 0},
                ],
                "unplaced": [{"genre_id": "missing", "reason": "no_direct_membership"}],
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _membership(artist_id: str, reference: str) -> dict[str, object]:
    return {
        "artist_id": artist_id,
        "score": 1.0,
        "evidence_refs": [reference],
        "components": [
            {
                "component_kind": "listenbrainz_one_hop",
                "raw_value": 2.0,
                "normalized_value": 1.0,
                "evidence_refs": [reference],
            }
        ],
    }


def _write_database(
    path: Path,
    *,
    support: int = 3,
    record_fingerprint: str = "a" * 64,
    model_input_sha256: str = "a" * 64,
    model_settings_sha256: str = "b" * 64,
) -> None:
    with sqlite3.connect(path) as connection, connection:
        connection.executescript(
            """
            CREATE TABLE normalizable_artist_co_listen_evidence (
                left_artist_source_id TEXT, right_artist_source_id TEXT,
                window_start INTEGER, window_end INTEGER, distinct_user_count INTEGER
            );
            CREATE TABLE public_model_runs (
                id INTEGER PRIMARY KEY,
                output_sha256 TEXT,
                input_sha256 TEXT,
                settings_sha256 TEXT
            );
            CREATE TABLE public_model_input_provenance (
                model_run_id INTEGER, provenance_id INTEGER, artifact_id INTEGER
            );
            CREATE TABLE provenance_records (
                id INTEGER PRIMARY KEY, source_id INTEGER, snapshot_ref TEXT,
                artifact_sha256 TEXT, record_fingerprint TEXT, parser_release_ref TEXT
            );
            CREATE TABLE data_sources (id INTEGER PRIMARY KEY, source_key TEXT);
            CREATE TABLE source_artifacts (id INTEGER PRIMARY KEY, sha256 TEXT);
            """
        )
        connection.execute(
            "INSERT INTO normalizable_artist_co_listen_evidence VALUES (?, ?, ?, ?, ?)",
            ("artist:a", "artist:b", 1, 2, support),
        )
        connection.execute(
            "INSERT INTO public_model_runs VALUES (1, ?, ?, ?)",
            ("z" * 64, model_input_sha256, model_settings_sha256),
        )
        connection.execute(
            "INSERT INTO public_model_runs VALUES (2, ?, ?, ?)", ("y" * 64, "c" * 64, "d" * 64)
        )
        connection.execute("INSERT INTO data_sources VALUES (1, 'source')")
        connection.execute(
            "INSERT INTO provenance_records VALUES (1, 1, 'snapshot', ?, ?, 'parser')",
            ("a" * 64, record_fingerprint),
        )
        connection.execute("INSERT INTO source_artifacts VALUES (1, ?)", ("a" * 64,))
        connection.execute("INSERT INTO public_model_input_provenance VALUES (1, 1, 1)")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
