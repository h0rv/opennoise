"""Tests for the local-only schema-12 candidate public projection boundary."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import override
from unittest.mock import patch

from opennoise.db import Database
from opennoise.ml.public_graph import build_public_model
from opennoise.ml.publish import PublicModelPublishSummary, PublishedLensSummary
from opennoise.models.modeling import (
    DirectMembershipEvidence,
    GenreIdentity,
    PublicArtifact,
    PublicModelInput,
    PublicModelSettings,
)
from opennoise.pipeline.candidate_public_projection import (
    CandidatePublicProjectionError,
    CandidatePublicProjectionSettings,
    _verify_candidate_boundary,
    project_candidate_public_model,
)
from opennoise.pipeline.source_vault_replay import (
    CandidateCombinedReplayReport,
    CandidateReplayObject,
)

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "config/releases/phase3-public-20260831"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CandidatePublicProjectionTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.candidate = self.root / "candidate.sqlite"
        self.receipt = self.root / "candidate.receipt.json"
        self._write_candidate()
        self._write_receipt()

    @override
    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_candidate(self) -> None:
        manifest = json.loads((RELEASE / "release-manifest.json").read_text())
        Database(self.candidate).initialize()
        with closing(sqlite3.connect(self.candidate)) as connection, connection:
            connection.execute(
                """INSERT INTO rights_policies
                   (id, policy_key, policy_version, classification, basis)
                   VALUES (1, 'fixture', 1, 'public_domain', 'fixture')"""
            )
            for ordinal, item in enumerate(manifest["inputs"], start=1):
                source_key = item["source_key"]
                connection.execute(
                    """INSERT INTO data_sources
                       (id, source_key, name, acquisition_kind, default_policy_id)
                       VALUES (?, ?, ?, 'public_download', 1)""",
                    (ordinal, source_key, source_key),
                )
                connection.execute(
                    """INSERT INTO source_snapshots
                       (id, source_id, snapshot_ref, snapshot_kind, manifest_sha256,
                        acquired_at, policy_id)
                       VALUES (?, ?, ?, 'single_artifact', ?, '2026-09-21T00:00:00Z', 1)""",
                    (ordinal, ordinal, f"candidate:{source_key}", "b" * 64),
                )
                connection.execute(
                    """INSERT INTO source_artifacts
                       (id, snapshot_id, artifact_ref, logical_name, media_type, byte_size,
                        sha256, vault_key, policy_id)
                       VALUES (?, ?, ?, ?, 'application/json', 1, ?, ?, 1)""",
                    (
                        ordinal,
                        ordinal,
                        source_key,
                        f"{source_key}.json",
                        item["artifact_sha256"],
                        item["artifact_sha256"],
                    ),
                )
        with closing(sqlite3.connect(self.candidate)) as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def _write_receipt(self) -> None:
        manifest = json.loads((RELEASE / "release-manifest.json").read_text())
        wikidata = tuple(
            CandidateReplayObject(
                source_key=item["source_key"],
                artifact_sha256=item["artifact_sha256"],
                byte_size=item["byte_size"],
                status="ingested",
                reason="fixture",
            )
            for item in manifest["inputs"]
            if item["source_key"].startswith("wikidata_phase3_")
        )
        daily = tuple(
            CandidateReplayObject(
                source_key=item["source_key"],
                artifact_sha256=item["artifact_sha256"],
                byte_size=item["byte_size"],
                status="ingested",
                reason="fixture",
            )
            for item in manifest["inputs"]
            if item["source_key"].startswith("listenbrainz_incremental_")
        )
        joint = next(
            item
            for item in manifest["inputs"]
            if item["source_key"].startswith("listenbrainz_joint_")
        )
        report = CandidateCombinedReplayReport(
            release_id=manifest["release_id"],
            manifest_sha256=_sha256(RELEASE / "release-manifest.json"),
            database_path=self.candidate,
            database_schema_version=12,
            verified_object_count=62,
            wikidata_objects=wikidata,
            listenbrainz_daily_objects=daily,
            sealed_joint_artifact_sha256=joint["artifact_sha256"],
            sealed_joint_artifact_byte_size=joint["byte_size"],
            accepted_record_count=30_904,
            quarantined_record_count=1,
            blockers=("fixture remains uncertified",),
        )
        self.receipt.write_text(report.model_dump_json(), encoding="utf-8")

    def _settings(self) -> CandidatePublicProjectionSettings:
        return CandidatePublicProjectionSettings(
            release_directory=RELEASE,
            candidate_database=self.candidate,
            replay_receipt=self.receipt,
            expected_candidate_sha256=_sha256(self.candidate),
            expected_replay_receipt_sha256=_sha256(self.receipt),
            output_database=self.root / "output.sqlite",
            model_output=self.root / "model.json",
            report_output=self.root / "report.json",
        )

    def _small_artifact(self):  # noqa: ANN202
        source = PublicArtifact(
            source="wikidata",
            snapshot="fixture",
            artifact_key=f"fixture:{'a' * 64}",
            content_sha256="a" * 64,
            export_allowed=True,
        )
        inputs = PublicModelInput(
            artifacts=(source,),
            genres=(
                GenreIdentity(genre_id="wikidata:genre:Q1", name="One", evidence_refs=("x",)),
                GenreIdentity(genre_id="wikidata:genre:Q2", name="Two", evidence_refs=("y",)),
            ),
            direct_memberships=(
                DirectMembershipEvidence(
                    artist_id="musicbrainz:artist:11111111-1111-4111-8111-111111111111",
                    genre_id="wikidata:genre:Q1",
                    facet="wikidata_p136",
                    value=1,
                    evidence_ref="x",
                ),
                DirectMembershipEvidence(
                    artist_id="musicbrainz:artist:11111111-1111-4111-8111-111111111111",
                    genre_id="wikidata:genre:Q2",
                    facet="wikidata_p136",
                    value=1,
                    evidence_ref="y",
                ),
            ),
        )
        return build_public_model(inputs, PublicModelSettings())

    def test_accepts_current_candidate_source_keys_and_artifact_hashes_without_old_snapshot_hashes(
        self,
    ) -> None:
        manifest, receipt, manifest_hash, candidate_hash = _verify_candidate_boundary(
            self._settings()
        )
        self.assertEqual(receipt.database_schema_version, 12)
        self.assertEqual(manifest["release_id"], "phase3-public-20260831-qualified")
        self.assertEqual(manifest_hash, _sha256(RELEASE / "release-manifest.json"))
        self.assertEqual(candidate_hash, _sha256(self.candidate))

    def test_rejects_boundary_failure_before_creating_outputs(self) -> None:
        settings = self._settings().model_copy(update={"expected_candidate_sha256": "0" * 64})
        with self.assertRaisesRegex(CandidatePublicProjectionError, "candidate database hash"):
            project_candidate_public_model(settings)
        self.assertFalse(settings.output_database.exists())
        self.assertFalse(settings.model_output.exists())
        self.assertFalse(settings.report_output.exists())

    def test_projects_only_to_fresh_outputs_and_preserves_input_candidate(self) -> None:
        settings = self._settings()
        input_hash = _sha256(self.candidate)
        artifact = self._small_artifact()
        summary = PublicModelPublishSummary(
            output_sha256=artifact.output_sha256,
            layouts=tuple(
                PublishedLensSummary(layout_key=key, layout_revision=1, coordinate_genres=count)
                for key, count in {
                    "public": 468,
                    "public-direct": 468,
                    "public-community": 468,
                    "public-taxonomy": 598,
                }.items()
            ),
            representative_items=3_344,
            profile_memberships=26_525,
            neighbor_rows=34_348,
            duplicate=False,
        )
        with (
            patch(
                "opennoise.pipeline.candidate_public_projection._build_model",
                return_value=(artifact.model_dump_json().encode(), artifact),
            ),
            patch("opennoise.pipeline.candidate_public_projection._require_manifest_model"),
            patch(
                "opennoise.pipeline.candidate_public_projection._release_policy_id", return_value=1
            ),
            patch(
                "opennoise.pipeline.candidate_public_projection.publish_public_model",
                return_value=summary,
            ),
            patch(
                "opennoise.pipeline.candidate_public_projection.require_public_model_gate",
                return_value=SimpleNamespace(passed=True),
            ),
        ):
            report = project_candidate_public_model(settings)
        self.assertEqual(_sha256(self.candidate), input_hash)
        self.assertTrue(settings.output_database.is_file())
        self.assertTrue(settings.model_output.is_file())
        self.assertTrue(settings.report_output.is_file())
        self.assertFalse(report.certified_database)
        self.assertFalse(report.byte_identical_database_replay)
        with self.assertRaisesRegex(CandidatePublicProjectionError, "already exists"):
            project_candidate_public_model(settings)


if __name__ == "__main__":
    unittest.main()
