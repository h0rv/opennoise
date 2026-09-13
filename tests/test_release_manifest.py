import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from opennoise.pipeline.release_manifest import (
    ReleaseManifestError,
    load_release_manifest,
    verify_manifest_against_database,
)
from opennoise.taxonomy.structure.hierarchy import HierarchyError, coverage_report

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "config/releases/phase3-public-20260831"


class ReleaseManifestTests(unittest.TestCase):
    def test_checked_in_release_closes_every_required_input_group(self) -> None:
        manifest = load_release_manifest(RELEASE)

        self.assertEqual(len(manifest["inputs"]), 62)
        self.assertEqual(
            manifest["qualification"]["canonical_selection_sha256"],
            hashlib.sha256((RELEASE / "qualification-selection.json").read_bytes()).hexdigest(),
        )
        self.assertEqual(manifest["qualification"]["policy"]["accepted_genres"], 603)

    def test_rejects_a_missing_qualification_shard(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            for source in RELEASE.iterdir():
                target = temporary / source.name
                target.write_bytes(source.read_bytes())
            (temporary / "music-genres-07.rq").unlink()

            with self.assertRaises(ReleaseManifestError):
                load_release_manifest(temporary)

    def test_checked_in_hierarchy_coverage_keeps_electronic_and_all_parents(self) -> None:
        coverage = json.loads(
            (ROOT / "docs/reports/PHASE3_HIERARCHY_COVERAGE_20260831.json").read_text()
        )

        self.assertEqual((coverage["node_count"], coverage["direct_edge_count"]), (603, 712))
        self.assertEqual(coverage["focus"]["qid"], "Q9778")
        self.assertEqual(coverage["focus"]["closure_node_count"], 61)
        self.assertEqual(coverage["focus"]["closure_direct_edge_count"], 62)
        self.assertEqual(
            coverage["display_parent_policy"],
            "not_selected; preserve every exact direct Wikidata parent",
        )

    def test_database_verification_requires_the_exact_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Path(temporary_directory) / "release.sqlite"
            manifest = load_release_manifest(RELEASE)
            with sqlite3.connect(database) as connection:
                connection.execute("PRAGMA user_version = 10")
                connection.executescript(
                    """CREATE TABLE data_sources (id INTEGER PRIMARY KEY, source_key TEXT);
                       CREATE TABLE source_snapshots (
                           id INTEGER PRIMARY KEY, source_id INTEGER, manifest_sha256 TEXT
                       );
                       CREATE TABLE source_artifacts (snapshot_id INTEGER, sha256 TEXT);"""
                )
                for ordinal, item in enumerate(manifest["inputs"], start=1):
                    connection.execute(
                        "INSERT INTO data_sources VALUES (?, ?)",
                        (ordinal, item["source_key"]),
                    )
                    connection.execute(
                        "INSERT INTO source_snapshots VALUES (?, ?, ?)",
                        (ordinal, ordinal, item["source_manifest_sha256"]),
                    )
                    connection.execute(
                        "INSERT INTO source_artifacts VALUES (?, ?)",
                        (ordinal, item["artifact_sha256"]),
                    )
            result = verify_manifest_against_database(RELEASE, database)
            self.assertEqual(result["input_artifacts"], 62)

            with sqlite3.connect(database) as connection:
                connection.execute("DELETE FROM source_artifacts WHERE snapshot_id = 1")
            with self.assertRaisesRegex(ReleaseManifestError, "source boundary differs"):
                verify_manifest_against_database(RELEASE, database)


class HierarchyCoverageTests(unittest.TestCase):
    def test_roots_and_multiple_parents_are_deterministic_without_a_display_parent(self) -> None:
        report = coverage_report(
            ("Q1", "Q2", "Q3", "Q4"),
            (("Q2", "Q1"), ("Q3", "Q1"), ("Q3", "Q4")),
            focus_qid="Q1",
        )

        self.assertEqual(
            report["root_candidates"],
            ({"qid": "Q1", "direct_children": 2}, {"qid": "Q4", "direct_children": 1}),
        )
        self.assertEqual(
            report["multi_parent_nodes"],
            ({"qid": "Q3", "parent_qids": ("Q1", "Q4")},),
        )
        focus = report["focus"]
        self.assertIsInstance(focus, dict)
        assert isinstance(focus, dict)
        self.assertEqual(focus["closure_node_count"], 3)
        self.assertEqual(
            report["display_parent_policy"],
            "not_selected; preserve every exact direct Wikidata parent",
        )

    def test_rejects_cycles(self) -> None:
        with self.assertRaisesRegex(HierarchyError, "acyclic"):
            coverage_report(("Q1", "Q2"), (("Q1", "Q2"), ("Q2", "Q1")))
