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
from opennoise.ml.public_graph import build_public_model, public_model_output_sha256
from opennoise.ml.publish import PublicModelPublishSummary, PublishedLensSummary
from opennoise.models.modeling import (
    ArtistPairEvidence,
    DirectMembershipEvidence,
    GenreIdentity,
    PublicArtifact,
    PublicModelInput,
    PublicModelSettings,
)
from opennoise.pipeline.candidate_public_projection import (
    CandidatePublicProjectionError,
    CandidatePublicProjectionSettings,
    CandidatePublicProjectionV2Settings,
    _v2_receipt_logical_sha256,
    _v2_settings,
    _verify_candidate_boundary,
    _verify_v2_graph_attestation,
    project_candidate_public_model,
    project_candidate_public_model_v2,
)
from opennoise.pipeline.historical_candidate_binding import (
    HistoricalCandidateBindingError,
    HistoricalCandidateBindingSettings,
    create_historical_candidate_binding,
    verify_historical_candidate_binding,
)
from opennoise.pipeline.source_vault_replay import (
    CandidateCombinedReplayReport,
    CandidateReplayObject,
    HistoricalDeclarationCombinedReplayReport,
    HistoricalDeclarationReplayObject,
    HistoricalDeclarationReplayReport,
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
        self.binding = self.root / "candidate.binding.json"
        self._write_candidate()
        self._write_receipt()
        self._write_binding()

    @override
    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_candidate(
        self,
        *,
        local_only: bool = False,
        first_policy_version: int = 1,
        mismatched_snapshot: bool = False,
    ) -> None:
        manifest = json.loads((RELEASE / "release-manifest.json").read_text())
        Database(self.candidate).initialize()
        with closing(sqlite3.connect(self.candidate)) as connection, connection:
            for ordinal, item in enumerate(manifest["inputs"], start=1):
                source_key = item["source_key"]
                is_local_only = local_only and ordinal == 1
                permissions = (
                    {
                        "normalize": "allow",
                        "local_search": "allow",
                        "display": "allow",
                        "embed": "allow",
                        "train": "allow",
                        "export": "allow",
                    }
                    if source_key.startswith("wikidata_phase3_")
                    else {
                        "normalize": "allow",
                        "local_search": "deny",
                        "display": "deny",
                        "embed": "allow",
                        "train": "allow",
                        "export": "allow",
                    }
                )
                if is_local_only:
                    permissions["export"] = "deny"
                connection.execute(
                    """INSERT INTO rights_policies
                       (id, policy_key, policy_version, classification, local_only, basis)
                       VALUES (?, ?, ?, 'public_domain', ?, 'fixture')""",
                    (
                        ordinal,
                        f"manifest:{source_key}:{item['artifact_sha256']}",
                        first_policy_version if ordinal == 1 else 1,
                        int(is_local_only),
                    ),
                )
                connection.executemany(
                    """INSERT INTO rights_policy_permissions
                       (policy_id, use_kind, decision, reason) VALUES (?, ?, ?, 'fixture')""",
                    [(ordinal, use_kind, decision) for use_kind, decision in permissions.items()],
                )
                connection.execute(
                    "INSERT INTO rights_policy_seals (policy_id, sealed_at) VALUES (?, 'fixture')",
                    (ordinal,),
                )
                connection.execute(
                    """INSERT INTO data_sources
                       (id, source_key, name, acquisition_kind, default_policy_id)
                       VALUES (?, ?, ?, 'public_download', ?)""",
                    (ordinal, source_key, source_key, ordinal),
                )
                connection.execute(
                    """INSERT INTO source_snapshots
                       (id, source_id, snapshot_ref, snapshot_kind, manifest_sha256,
                        acquired_at, policy_id)
                       VALUES (?, ?, ?, 'single_artifact', ?, '2026-09-21T00:00:00Z', ?)""",
                    (
                        ordinal,
                        ordinal,
                        "tampered"
                        if mismatched_snapshot and ordinal == 1
                        else item["snapshot_ref"],
                        "b" * 64,
                        ordinal,
                    ),
                )
                connection.execute(
                    """INSERT INTO source_artifacts
                       (id, snapshot_id, artifact_ref, logical_name, media_type, byte_size,
                        sha256, vault_key, policy_id)
                       VALUES (?, ?, ?, ?, 'application/json', 1, ?, ?, ?)""",
                    (
                        ordinal,
                        ordinal,
                        source_key,
                        f"{source_key}.json",
                        item["artifact_sha256"],
                        item["artifact_sha256"],
                        ordinal,
                    ),
                )
                connection.execute(
                    """INSERT INTO provenance_records
                       (source_id, policy_id, snapshot_ref, artifact_sha256, record_fingerprint,
                        parser_release_ref, ingest_attempt_ref, observed_at)
                       VALUES (?, ?, ?, ?, ?, 'fixture', 'fixture', 'fixture')""",
                    (
                        ordinal,
                        ordinal,
                        "tampered"
                        if mismatched_snapshot and ordinal == 1
                        else item["snapshot_ref"],
                        item["artifact_sha256"],
                        f"{ordinal:064x}",
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
        historical_declarations = HistoricalDeclarationReplayReport(
            release_id=manifest["release_id"],
            manifest_sha256=_sha256(RELEASE / "release-manifest.json"),
            object_count=len(manifest["inputs"]),
            objects=tuple(
                HistoricalDeclarationReplayObject(
                    source_key=item["source_key"],
                    expected_sha256=item["source_manifest_sha256"],
                    replayed_sha256=item["source_manifest_sha256"],
                )
                for item in manifest["inputs"]
            ),
        )
        report = HistoricalDeclarationCombinedReplayReport(
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
            historical_declarations=historical_declarations,
        )
        self.receipt.write_text(report.model_dump_json(), encoding="utf-8")

    def _settings(self) -> CandidatePublicProjectionSettings:
        return CandidatePublicProjectionSettings(
            release_directory=RELEASE,
            candidate_database=self.candidate,
            replay_receipt=self.receipt,
            historical_candidate_binding=self.binding,
            expected_candidate_sha256=_sha256(self.candidate),
            expected_replay_receipt_sha256=_sha256(self.receipt),
            expected_historical_candidate_binding_sha256=_sha256(self.binding),
            output_database=self.root / "output.sqlite",
            model_output=self.root / "model.json",
            report_output=self.root / "report.json",
        )

    def _v2_settings(self) -> CandidatePublicProjectionV2Settings:
        return CandidatePublicProjectionV2Settings(**self._settings().model_dump())

    def _write_binding(self) -> None:
        create_historical_candidate_binding(
            HistoricalCandidateBindingSettings(
                release_directory=RELEASE,
                candidate_database=self.candidate,
                replay_receipt=self.receipt,
                output=self.binding,
            )
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

    def _v2_artifact(self):  # noqa: ANN202
        manifest = json.loads((RELEASE / "release-manifest.json").read_text())
        artifact = self._small_artifact().model_copy(
            update={
                "artifacts": tuple(
                    PublicArtifact(
                        source=(
                            "listenbrainz" if "listenbrainz" in item["source_key"] else "wikidata"
                        ),
                        snapshot=item["snapshot_ref"],
                        artifact_key=f"{item['source_key']}:{item['artifact_sha256']}",
                        content_sha256=item["artifact_sha256"],
                        export_allowed=True,
                    )
                    for item in manifest["inputs"]
                )
            }
        )
        return artifact.model_copy(update={"output_sha256": public_model_output_sha256(artifact)})

    def _v2_graph_artifact(self):  # noqa: ANN202
        manifest = json.loads((RELEASE / "release-manifest.json").read_text())
        pair_ref = (
            "listenbrainz:v2:source_key=listenbrainz_joint_20260824_20260830&"
            "snapshot_ref=listenbrainz_joint_20260824_20260830%3Ajoint%3A"
            "6c30524486b47af9fe0fe554830b50639f716ba39e265c7560d60b84124208b7&"
            "artifact_sha256=6c30524486b47af9fe0fe554830b50639f716ba39e265c7560d60b84124208b7"
        )
        direct_ref = "catalog:artist-genre:1:fixture"
        artist_a = "musicbrainz:artist:11111111-1111-4111-8111-111111111111"
        artist_b = "musicbrainz:artist:22222222-2222-4222-8222-222222222222"
        inputs = PublicModelInput(
            artifacts=(
                PublicArtifact(
                    source="wikidata",
                    snapshot="fixture",
                    artifact_key=f"fixture:{'a' * 64}",
                    content_sha256="a" * 64,
                    export_allowed=True,
                ),
            ),
            genres=(GenreIdentity(genre_id="wikidata:genre:Q1", name="One", evidence_refs=("x",)),),
            direct_memberships=(
                DirectMembershipEvidence(
                    artist_id=artist_a,
                    genre_id="wikidata:genre:Q1",
                    facet="wikidata_p136",
                    value=1,
                    evidence_ref=direct_ref,
                ),
            ),
            artist_pairs=(
                ArtistPairEvidence(
                    left_artist_id=artist_a,
                    right_artist_id=artist_b,
                    listener_day_support=2,
                    supporting_windows=1,
                    evidence_refs=(pair_ref,),
                ),
            ),
        )
        artifact = build_public_model(inputs, PublicModelSettings())
        artifacts = tuple(
            PublicArtifact(
                source="listenbrainz" if "listenbrainz" in item["source_key"] else "wikidata",
                snapshot=item["snapshot_ref"],
                artifact_key=f"{item['source_key']}:{item['artifact_sha256']}",
                content_sha256=item["artifact_sha256"],
                export_allowed=True,
            )
            for item in manifest["inputs"]
        )
        artifact = artifact.model_copy(update={"artifacts": artifacts})
        return artifact.model_copy(update={"output_sha256": public_model_output_sha256(artifact)})

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

    def test_rejects_missing_binding_before_creating_outputs(self) -> None:
        settings = self._settings().model_copy(
            update={"historical_candidate_binding": self.root / "missing.binding.json"}
        )
        with self.assertRaisesRegex(CandidatePublicProjectionError, "binding.*invalid"):
            project_candidate_public_model(settings)
        self.assertFalse(settings.output_database.exists())
        self.assertFalse(settings.model_output.exists())
        self.assertFalse(settings.report_output.exists())

    def test_rejects_tampered_binding_before_creating_outputs(self) -> None:
        settings = self._settings()
        self.binding.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(CandidatePublicProjectionError, "binding.*hash does not match"):
            project_candidate_public_model(settings)
        self.assertFalse(settings.output_database.exists())
        self.assertFalse(settings.model_output.exists())
        self.assertFalse(settings.report_output.exists())

    def test_rejects_old_local_only_combined_receipt_before_creating_outputs(self) -> None:
        historical = HistoricalDeclarationCombinedReplayReport.model_validate_json(
            self.receipt.read_bytes()
        )
        old_receipt = CandidateCombinedReplayReport(
            **historical.model_dump(exclude={"revision", "historical_declarations"})
        )
        self.receipt.write_text(old_receipt.model_dump_json(), encoding="utf-8")
        settings = self._settings()
        with self.assertRaisesRegex(CandidatePublicProjectionError, "historical candidate binding"):
            project_candidate_public_model(settings)
        self.assertFalse(settings.output_database.exists())
        self.assertFalse(settings.model_output.exists())
        self.assertFalse(settings.report_output.exists())

    def test_rejects_tampered_historical_declaration_before_creating_outputs(self) -> None:
        payload = json.loads(self.receipt.read_text(encoding="utf-8"))
        payload["historical_declarations"]["objects"][0]["replayed_sha256"] = "0" * 64
        self.receipt.write_text(json.dumps(payload), encoding="utf-8")
        settings = self._settings()
        with self.assertRaisesRegex(CandidatePublicProjectionError, "historical candidate binding"):
            project_candidate_public_model(settings)
        self.assertFalse(settings.output_database.exists())
        self.assertFalse(settings.model_output.exists())
        self.assertFalse(settings.report_output.exists())

    def test_rejects_missing_historical_declaration_before_creating_outputs(self) -> None:
        receipt = HistoricalDeclarationCombinedReplayReport.model_validate_json(
            self.receipt.read_bytes()
        )
        declarations = receipt.historical_declarations
        replacement = HistoricalDeclarationReplayObject(
            source_key="missing-from-manifest",
            expected_sha256=declarations.objects[0].expected_sha256,
            replayed_sha256=declarations.objects[0].replayed_sha256,
        )
        altered_declarations = declarations.model_copy(
            update={"objects": (replacement, *declarations.objects[1:])}
        )
        altered = receipt.model_copy(update={"historical_declarations": altered_declarations})
        self.receipt.write_text(altered.model_dump_json(), encoding="utf-8")
        settings = self._settings()
        with self.assertRaisesRegex(CandidatePublicProjectionError, "historical candidate binding"):
            project_candidate_public_model(settings)
        self.assertFalse(settings.output_database.exists())
        self.assertFalse(settings.model_output.exists())
        self.assertFalse(settings.report_output.exists())

    def test_rejects_local_only_candidate_policy_before_creating_outputs(self) -> None:
        self.candidate.unlink()
        self._write_candidate(local_only=True)
        settings = self._settings()
        with self.assertRaisesRegex(CandidatePublicProjectionError, "historical candidate binding"):
            project_candidate_public_model(settings)
        self.assertFalse(settings.output_database.exists())
        self.assertFalse(settings.model_output.exists())
        self.assertFalse(settings.report_output.exists())

    def test_rejects_non_v1_candidate_policy_before_creating_outputs(self) -> None:
        self.candidate.unlink()
        self._write_candidate(first_policy_version=2)
        settings = self._settings()
        with self.assertRaisesRegex(CandidatePublicProjectionError, "historical candidate binding"):
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

    def test_v2_projects_with_release_bounds_and_records_new_hashes(self) -> None:
        settings = self._v2_settings()
        artifact = self._v2_artifact()
        summary = PublicModelPublishSummary(
            output_sha256=artifact.output_sha256,
            layouts=tuple(
                PublishedLensSummary(
                    layout_key=item.layout_key,
                    layout_revision=1,
                    coordinate_genres=len(item.coordinates),
                )
                for item in artifact.layouts
            ),
            representative_items=len(artifact.representatives),
            profile_memberships=sum(len(item.memberships) for item in artifact.profiles),
            neighbor_rows=len(artifact.neighbors),
            duplicate=False,
        )
        load_settings, model_settings = _v2_settings()
        with (
            patch(
                "opennoise.pipeline.candidate_public_projection._build_model_v2",
                return_value=(
                    artifact.model_dump_json().encode(),
                    artifact,
                    load_settings,
                    model_settings,
                ),
            ),
            patch(
                "opennoise.pipeline.candidate_public_projection._release_policy_id", return_value=1
            ),
            patch(
                "opennoise.pipeline.candidate_public_projection.publish_public_model",
                return_value=summary,
            ),
            patch(
                "opennoise.pipeline.candidate_public_projection._verify_v2_graph_attestation",
                return_value=0,
            ),
        ):
            report = project_candidate_public_model_v2(settings)
        self.assertEqual(report.revision, "phase3-candidate-public-projection-v2")
        self.assertEqual(report.source_artifact_count, 62)
        self.assertEqual(report.model_logical_sha256, artifact.output_sha256)
        self.assertEqual(
            report.input_load_settings["artist_pair_evidence_ref_version"], "source_artifacts_v2"
        )
        self.assertEqual(report.model_settings["max_direct_memberships"], 100_000)
        self.assertEqual(report.model_settings["max_artist_pairs"], 250_000)
        self.assertEqual(report.model_settings["neighbors_per_genre"], 25)
        self.assertEqual(report.receipt_logical_sha256, _v2_receipt_logical_sha256(report))

    def test_v2_graph_permits_attested_pair_and_direct_seed_refs(self) -> None:
        artifact = self._v2_graph_artifact()
        with patch(
            "opennoise.pipeline.candidate_public_projection._v2_direct_evidence_refs",
            return_value={"catalog:artist-genre:1:fixture"},
        ):
            self.assertGreater(
                _verify_v2_graph_attestation(
                    artifact,
                    json.loads((RELEASE / "release-manifest.json").read_text()),
                    self.candidate,
                ),
                0,
            )

    def test_v2_graph_rejects_unknown_one_hop_reference(self) -> None:
        artifact = self._v2_graph_artifact()
        profile = next(item for item in artifact.profiles if item.profile_kind == "one_hop")
        membership = profile.memberships[0]
        component = membership.components[0].model_copy(
            update={"evidence_refs": (*membership.components[0].evidence_refs, "unknown:ref")}
        )
        replacement = membership.model_copy(
            update={
                "components": (component,),
                "evidence_refs": (*membership.evidence_refs, "unknown:ref"),
            }
        )
        replacement_profile = profile.model_copy(update={"memberships": (replacement,)})
        tampered = artifact.model_copy(
            update={
                "profiles": tuple(
                    replacement_profile if item == profile else item for item in artifact.profiles
                )
            }
        )
        with (
            patch(
                "opennoise.pipeline.candidate_public_projection._v2_direct_evidence_refs",
                return_value={"catalog:artist-genre:1:fixture"},
            ),
            self.assertRaisesRegex(
                CandidatePublicProjectionError, "outside the release source attestation"
            ),
        ):
            _verify_v2_graph_attestation(
                tampered,
                json.loads((RELEASE / "release-manifest.json").read_text()),
                self.candidate,
            )

    def test_v2_graph_rejects_unknown_catalog_seed_reference(self) -> None:
        artifact = self._v2_graph_artifact()
        profile = next(item for item in artifact.profiles if item.profile_kind == "one_hop")
        membership = profile.memberships[0]
        original = membership.components[0]
        replacement_refs = tuple(
            "catalog:artist-genre:999:unknown"
            if reference.startswith("catalog:artist-genre:")
            else reference
            for reference in original.evidence_refs
        )
        component = original.model_copy(update={"evidence_refs": replacement_refs})
        replacement = membership.model_copy(
            update={"components": (component,), "evidence_refs": replacement_refs}
        )
        replacement_profile = profile.model_copy(update={"memberships": (replacement,)})
        tampered = artifact.model_copy(
            update={
                "profiles": tuple(
                    replacement_profile if item == profile else item for item in artifact.profiles
                )
            }
        )
        with (
            patch(
                "opennoise.pipeline.candidate_public_projection._v2_direct_evidence_refs",
                return_value={"catalog:artist-genre:1:fixture"},
            ),
            self.assertRaisesRegex(
                CandidatePublicProjectionError, "outside the release source attestation"
            ),
        ):
            _verify_v2_graph_attestation(
                tampered,
                json.loads((RELEASE / "release-manifest.json").read_text()),
                self.candidate,
            )

    def test_v2_graph_rejects_membership_without_v2_pair_reference(self) -> None:
        artifact = self._v2_graph_artifact()
        profile = next(item for item in artifact.profiles if item.profile_kind == "one_hop")
        membership = profile.memberships[0]
        direct_refs = tuple(
            reference
            for reference in membership.components[0].evidence_refs
            if reference.startswith("catalog:artist-genre:")
        )
        component = membership.components[0].model_copy(update={"evidence_refs": direct_refs})
        replacement = membership.model_copy(
            update={"components": (component,), "evidence_refs": direct_refs}
        )
        replacement_profile = profile.model_copy(update={"memberships": (replacement,)})
        tampered = artifact.model_copy(
            update={
                "profiles": tuple(
                    replacement_profile if item == profile else item for item in artifact.profiles
                )
            }
        )
        with (
            patch(
                "opennoise.pipeline.candidate_public_projection._v2_direct_evidence_refs",
                return_value={"catalog:artist-genre:1:fixture"},
            ),
            self.assertRaisesRegex(CandidatePublicProjectionError, "lacks source_artifacts_v2"),
        ):
            _verify_v2_graph_attestation(
                tampered,
                json.loads((RELEASE / "release-manifest.json").read_text()),
                self.candidate,
            )

    def test_v2_graph_rejects_no_one_hop_evidence(self) -> None:
        with self.assertRaisesRegex(
            CandidatePublicProjectionError, "contains no source_artifacts_v2"
        ):
            _verify_v2_graph_attestation(
                self._v2_artifact(),
                json.loads((RELEASE / "release-manifest.json").read_text()),
                self.candidate,
            )

    def test_v2_rejects_database_snapshot_not_in_release_before_outputs(self) -> None:
        self.candidate.unlink()
        self.binding.unlink()
        self._write_candidate(mismatched_snapshot=True)
        self._write_binding()
        settings = self._v2_settings()
        with self.assertRaisesRegex(CandidatePublicProjectionError, "source/snapshot/artifact"):
            project_candidate_public_model_v2(settings)
        self.assertFalse(settings.output_database.exists())
        self.assertFalse(settings.model_output.exists())
        self.assertFalse(settings.report_output.exists())

    def test_binding_rejects_candidate_path_substitution(self) -> None:
        substituted = self.root / "substituted.sqlite"
        substituted.write_bytes(self.candidate.read_bytes())
        with self.assertRaisesRegex(
            HistoricalCandidateBindingError, "does not match current inputs"
        ):
            verify_historical_candidate_binding(
                self.binding,
                _sha256(self.binding),
                release_directory=RELEASE,
                candidate_database=substituted,
                replay_receipt=self.receipt,
            )

    def test_binding_refuses_to_replace_existing_output(self) -> None:
        with self.assertRaisesRegex(HistoricalCandidateBindingError, "output already exists"):
            self._write_binding()

    def test_binding_rejects_receipt_tampering(self) -> None:
        payload = json.loads(self.receipt.read_text(encoding="utf-8"))
        payload["accepted_record_count"] = 0
        self.receipt.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(
            HistoricalCandidateBindingError, "does not match current inputs"
        ):
            verify_historical_candidate_binding(
                self.binding,
                _sha256(self.binding),
                release_directory=RELEASE,
                candidate_database=self.candidate,
                replay_receipt=self.receipt,
            )


if __name__ == "__main__":
    unittest.main()
