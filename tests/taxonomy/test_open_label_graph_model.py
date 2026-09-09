from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from musix.ingest.musicbrainz_seed_targets import (
    ContextualArtistTag,
    MusicBrainzSeedTargetArtifact,
    SeedTargetCoverage,
    SeedTargetEvidence,
    SeedTargetExtractorCounters,
    SeedTargetExtractorSettings,
    artifact_sha256,
    settings_sha256,
)
from musix.taxonomy.open_label_graph_model import (
    OpenLabelGraphSettings,
    _split,
    build_open_label_graph_model,
    build_open_label_graph_model_from_path,
    verify_open_label_graph_model,
)
from musix.taxonomy.seed_reconciliation import (
    SeedReconciliationArtifact,
    SeedReconciliationCoverage,
    SeedReconciliationDisposition,
)


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


class OpenLabelGraphModelTests(unittest.TestCase):
    def _inputs(self) -> tuple[MusicBrainzSeedTargetArtifact, SeedReconciliationArtifact]:
        anchor_names = tuple(f"Style {index}" for index in range(12))
        rows = (
            *(
                SeedReconciliationDisposition(
                    source_item_id=f"anchor-{index}",
                    source_external_id=f"eno:anchor-{index}",
                    seed_name=name,
                    normalized_name=name.casefold(),
                    disposition="unresolved",
                    reason="fixture anchor retained for graph training",
                )
                for index, name in enumerate(anchor_names)
            ),
            SeedReconciliationDisposition(
                source_item_id="unanchored",
                source_external_id="eno:unanchored",
                seed_name="Style 4 Extended",
                normalized_name="style 4 extended",
                disposition="unresolved",
                reason="no direct open anchor",
            ),
        )
        identity = _sha(
            [
                {
                    "source_item_id": row.source_item_id,
                    "source_external_id": row.source_external_id,
                    "name": row.seed_name,
                }
                for row in sorted(rows, key=lambda row: row.source_item_id)
            ]
        )
        reconciliation = SeedReconciliationArtifact(
            seed_input_sha256="a" * 64,
            seed_source_id="fixture",
            seed_source_content_sha256="b" * 64,
            seed_identity_sha256=identity,
            taxonomy_artifact_sha256="c" * 64,
            input_sha256="d" * 64,
            seed_count=len(rows),
            dispositions=rows,
            coverage=SeedReconciliationCoverage(
                seed_count=len(rows),
                reconciled_count=0,
                public_only_count=0,
                musicbrainz_only_count=0,
                review_only_count=0,
                ambiguous_count=0,
                unresolved_count=len(rows),
                public_identity_count=0,
                musicbrainz_identity_count=0,
                musicbrainz_genre_identity_count=0,
                musicbrainz_tag_identity_count=0,
                collision_seed_count=0,
            ),
            output_sha256="0" * 64,
        )
        reconciliation = reconciliation.model_copy(
            update={
                "output_sha256": _sha(
                    reconciliation.model_dump(mode="json", exclude={"output_sha256"})
                )
            }
        )
        evidence = tuple(
            SeedTargetEvidence(
                seed_source_item_id=f"anchor-{index}",
                seed_source_external_id=f"eno:anchor-{index}",
                seed_name=name,
                seed_normalized_name=name.casefold(),
                facet="tag",
                target_namespace="musicbrainz_tag_name",
                target_identity=f"tag:style-{index}",
                target_name=name,
                artist_id=f"00000000-0000-0000-0000-{index:012d}",
                source_record_id=f"open:artist:{index}",
                source_record_ordinal=index + 1,
                source_record_sha256="e" * 64,
                source_record_byte_length=1,
                evidence_ref=f"open:evidence:{index}",
                positive_weight=1.0,
                match_kind="exact",
            )
            for index, name in enumerate(anchor_names)
        )
        context = tuple(
            ContextualArtistTag(
                artist_id=f"00000000-0000-0000-0000-{index:012d}",
                source_record_id=f"open:artist:{index}",
                source_record_ordinal=index + 1,
                source_record_sha256="f" * 64,
                source_record_byte_length=1,
                tag_name=name,
                tag_identity=f"tag:style-{index}",
                tag_count=1,
                matched_seed_source_item_ids=(f"anchor-{index}",),
                evidence_ref=f"open:context:{index}",
            )
            for index, name in enumerate(anchor_names)
        )
        settings = SeedTargetExtractorSettings()
        source = MusicBrainzSeedTargetArtifact(
            seed_input_sha256="1" * 64,
            seed_source_id="fixture",
            seed_source_content_sha256="b" * 64,
            seed_count=len(rows),
            archive_sha256="2" * 64,
            settings=settings,
            settings_sha256=settings_sha256(settings),
            counters=SeedTargetExtractorCounters(
                archive_member_count=0,
                member_over_limit_count=0,
                malformed_member_path_count=0,
                records_seen=0,
                records_parsed=0,
                records_with_matches=0,
                records_skipped_over_limit=0,
                record_over_limit_count=0,
                malformed_json_count=0,
                malformed_shape_count=0,
                malformed_claim_count=0,
                claim_over_limit_count=0,
                duplicate_claim_count=0,
                evidence_over_limit_count=0,
                contextual_over_limit_count=0,
                positive_evidence_count=len(evidence),
                contextual_tag_count=len(context),
            ),
            coverage=tuple(
                SeedTargetCoverage(
                    seed_source_item_id=row.source_item_id,
                    seed_source_external_id=row.source_external_id,
                    seed_name=row.seed_name,
                    normalized_name=row.normalized_name,
                    evidence_count=1 if row.source_item_id.startswith("anchor") else 0,
                    distinct_artist_count=1 if row.source_item_id.startswith("anchor") else 0,
                    distinct_target_identity_count=1
                    if row.source_item_id.startswith("anchor")
                    else 0,
                    genre_evidence_count=0,
                    tag_evidence_count=1 if row.source_item_id.startswith("anchor") else 0,
                )
                for row in rows
            ),
            evidence=evidence,
            contextual_tags=context,
            output_sha256="0" * 64,
        )
        return source.model_copy(update={"output_sha256": artifact_sha256(source)}), reconciliation

    def test_calibrates_without_heldout_labels_and_accounts_for_unanchored(self) -> None:
        source, reconciliation = self._inputs()
        settings = OpenLabelGraphSettings(
            split_seed=13,
            calibration_fraction=0.25,
            test_fraction=0.25,
            minimum_review_precision=0.5,
            minimum_lexical_score=0.05,
        )
        artifact = build_open_label_graph_model(source, reconciliation, settings)
        self.assertEqual(artifact.coverage.observed_anchor_count, 12)
        self.assertEqual(
            artifact.coverage.train_anchor_count
            + artifact.coverage.calibration_anchor_count
            + artifact.coverage.heldout_anchor_count,
            12,
        )
        self.assertEqual(artifact.coverage.true_unanchored_label_count, 1)
        self.assertEqual(
            artifact.coverage.proposed_unanchored_label_count
            + artifact.coverage.abstained_unanchored_label_count,
            1,
        )
        self.assertEqual(
            artifact.heldout_comparison.cold_label_anchor_count,
            artifact.coverage.heldout_anchor_count,
        )
        self.assertFalse(artifact.historical_inputs_read)
        self.assertFalse(artifact.coverage.observed_identities_created)
        verify_open_label_graph_model(artifact)
        self.assertEqual(
            artifact.output_sha256,
            build_open_label_graph_model(source, reconciliation, settings).output_sha256,
        )

    def test_tampered_output_fails_closed(self) -> None:
        source, reconciliation = self._inputs()
        artifact = build_open_label_graph_model(source, reconciliation)
        with self.assertRaisesRegex(ValueError, "hash"):
            verify_open_label_graph_model(artifact.model_copy(update={"output_sha256": "0" * 64}))

    def test_heldout_anchor_graph_mutation_cannot_change_fit_or_candidates(self) -> None:
        source, reconciliation = self._inputs()
        settings = OpenLabelGraphSettings(
            split_seed=13,
            calibration_fraction=0.25,
            test_fraction=0.25,
            minimum_review_precision=0.5,
            minimum_lexical_score=0.05,
        )
        heldout_ids = {
            f"anchor-{index}"
            for index in range(12)
            if _split(f"tag:style-{index}", settings) == "test"
        }
        self.assertTrue(heldout_ids)
        changed_evidence = tuple(
            row.model_copy(update={"artist_id": "99999999-0000-0000-0000-000000000000"})
            if row.seed_source_item_id in heldout_ids
            else row
            for row in source.evidence
        )
        changed_context = tuple(
            row.model_copy(update={"artist_id": "99999999-0000-0000-0000-000000000000"})
            if set(row.matched_seed_source_item_ids) & heldout_ids
            else row
            for row in source.contextual_tags
        )
        mutated = source.model_copy(
            update={
                "evidence": changed_evidence,
                "contextual_tags": changed_context,
                "output_sha256": "0" * 64,
            }
        )
        mutated = mutated.model_copy(update={"output_sha256": artifact_sha256(mutated)})
        baseline = build_open_label_graph_model(source, reconciliation, settings)
        changed = build_open_label_graph_model(mutated, reconciliation, settings)
        self.assertEqual(baseline.coefficients, changed.coefficients)
        self.assertEqual(baseline.calibrated_review_threshold, changed.calibrated_review_threshold)
        self.assertEqual(baseline.candidates, changed.candidates)
        self.assertEqual(baseline.abstentions, changed.abstentions)
        self.assertEqual(baseline.heldout_comparison, changed.heldout_comparison)

    def test_calibration_anchor_graph_mutation_cannot_change_fit_or_threshold(self) -> None:
        source, reconciliation = self._inputs()
        settings = OpenLabelGraphSettings(
            split_seed=13,
            calibration_fraction=0.25,
            test_fraction=0.25,
            minimum_review_precision=0.5,
            minimum_lexical_score=0.05,
        )
        calibration_ids = {
            f"anchor-{index}"
            for index in range(12)
            if _split(f"tag:style-{index}", settings) == "calibration"
        }
        self.assertTrue(calibration_ids)
        changed_evidence = tuple(
            row.model_copy(update={"artist_id": "88888888-0000-0000-0000-000000000000"})
            if row.seed_source_item_id in calibration_ids
            else row
            for row in source.evidence
        )
        changed_context = tuple(
            row.model_copy(update={"artist_id": "88888888-0000-0000-0000-000000000000"})
            if set(row.matched_seed_source_item_ids) & calibration_ids
            else row
            for row in source.contextual_tags
        )
        mutated = source.model_copy(
            update={
                "evidence": changed_evidence,
                "contextual_tags": changed_context,
                "output_sha256": "0" * 64,
            }
        )
        mutated = mutated.model_copy(update={"output_sha256": artifact_sha256(mutated)})
        baseline = build_open_label_graph_model(source, reconciliation, settings)
        changed = build_open_label_graph_model(mutated, reconciliation, settings)
        self.assertEqual(baseline.coefficients, changed.coefficients)
        self.assertEqual(baseline.calibrated_review_threshold, changed.calibrated_review_threshold)
        self.assertEqual(baseline.candidates, changed.candidates)
        self.assertEqual(baseline.abstentions, changed.abstentions)
        self.assertEqual(baseline.heldout_comparison, changed.heldout_comparison)

    def test_streaming_path_keeps_large_context_shape_out_of_model_state(self) -> None:
        """The streaming path retains anchor-attached context, not every raw context row."""
        source, reconciliation = self._inputs()
        expanded_context = tuple(
            source.contextual_tags[index % len(source.contextual_tags)].model_copy(
                update={
                    "tag_identity": f"tag:extra-{index % 80}",
                    "tag_name": f"Extra {index % 80}",
                    "matched_seed_source_item_ids": ("anchor-0",),
                    "evidence_ref": f"open:extra:{index}",
                }
            )
            for index in range(4_000)
        )
        expanded = source.model_copy(
            update={"contextual_tags": expanded_context, "output_sha256": "0" * 64}
        )
        expanded = expanded.model_copy(update={"output_sha256": artifact_sha256(expanded)})
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "large-shape-source.json"
            path.write_text(expanded.model_dump_json(), encoding="utf-8")
            artifact = build_open_label_graph_model_from_path(
                path,
                reconciliation,
                OpenLabelGraphSettings(
                    split_seed=13,
                    calibration_fraction=0.25,
                    test_fraction=0.25,
                    maximum_retrieval_candidates=50,
                    minimum_review_precision=0.5,
                    minimum_lexical_score=0.05,
                ),
            )
            self.assertEqual(artifact.coverage.vocabulary_count, 12)
            self.assertEqual(
                artifact.seed_target_file_sha256,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            verify_open_label_graph_model(artifact)

    def test_cli_builds_and_publishes_tiny_streaming_fixture(self) -> None:
        source, reconciliation = self._inputs()
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            source_path = directory / "source.json"
            reconciliation_path = directory / "reconciliation.json"
            output_path = directory / "output.json"
            receipt_path = directory / "receipt.json"
            object_store = directory / "objects"
            source_path.write_text(source.model_dump_json(), encoding="utf-8")
            reconciliation_path.write_text(reconciliation.model_dump_json(), encoding="utf-8")
            result = subprocess.run(  # noqa: S603 - fixed local CLI fixture under test.
                (
                    sys.executable,
                    "scripts/build_open_label_graph_model.py",
                    "--seed-target-artifact",
                    str(source_path),
                    "--seed-reconciliation",
                    str(reconciliation_path),
                    "--output",
                    str(output_path),
                    "--object-store",
                    str(object_store),
                    "--receipt",
                    str(receipt_path),
                    "--split-seed",
                    "13",
                    "--calibration-fraction",
                    "0.25",
                    "--test-fraction",
                    "0.25",
                    "--minimum-review-precision",
                    "0.5",
                    "--minimum-lexical-score",
                    "0.05",
                ),
                cwd=Path.cwd(),
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output_path.is_file())
            self.assertTrue(receipt_path.is_file())


if __name__ == "__main__":
    unittest.main()
