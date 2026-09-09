from __future__ import annotations

import hashlib
import json
import unittest

from musix.evidence.learned_label_alignment import (
    LearnedLabelAlignmentSettings,
    build_learned_label_alignment,
    verify_learned_label_alignment,
)
from musix.musicbrainz_seed_targets import (
    ContextualArtistTag,
    MusicBrainzSeedTargetArtifact,
    SeedTargetCoverage,
    SeedTargetEvidence,
    SeedTargetExtractorCounters,
    SeedTargetExtractorSettings,
    artifact_sha256,
    settings_sha256,
)
from musix.taxonomy.seed_reconciliation import (
    ReconciledIdentity,
    SeedReconciliationArtifact,
    SeedReconciliationCoverage,
    SeedReconciliationDisposition,
)


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


class LearnedLabelAlignmentTests(unittest.TestCase):
    def _reconciliation(self) -> SeedReconciliationArtifact:
        dispositions = (
            SeedReconciliationDisposition(
                source_item_id="known-rock",
                source_external_id="eno:known-rock",
                seed_name="Rock",
                normalized_name="rock",
                disposition="musicbrainz_only",
                musicbrainz_identities=(
                    ReconciledIdentity(
                        namespace="musicbrainz_tag_name",
                        identifier="tag:rock",
                        name="Rock",
                        match_kind="lexical_exact",
                    ),
                ),
            ),
            SeedReconciliationDisposition(
                source_item_id="known-jazz",
                source_external_id="eno:known-jazz",
                seed_name="Jazz",
                normalized_name="jazz",
                disposition="musicbrainz_only",
                musicbrainz_identities=(
                    ReconciledIdentity(
                        namespace="musicbrainz_tag_name",
                        identifier="tag:jazz",
                        name="Jazz",
                        match_kind="lexical_normalized",
                    ),
                ),
            ),
            SeedReconciliationDisposition(
                source_item_id="unknown-electronic",
                source_external_id="eno:unknown-electronic",
                seed_name="Electronic Rock",
                normalized_name="electronic rock",
                disposition="unresolved",
                reason="no identity evidence",
            ),
        )
        preliminary = SeedReconciliationArtifact(
            # The two producers intentionally seal different wrapper hashes;
            # learned alignment must bind their stable seed identity instead.
            seed_input_sha256="f" * 64,
            seed_source_id="fixture",
            seed_source_content_sha256="b" * 64,
            seed_identity_sha256=_sha(
                [
                    {
                        "source_item_id": item.source_item_id,
                        "source_external_id": item.source_external_id,
                        "name": item.seed_name,
                    }
                    for item in sorted(dispositions, key=lambda item: item.source_item_id)
                ]
            ),
            taxonomy_artifact_sha256="b" * 64,
            input_sha256="c" * 64,
            seed_count=3,
            dispositions=dispositions,
            coverage=SeedReconciliationCoverage(
                seed_count=3,
                reconciled_count=0,
                public_only_count=0,
                musicbrainz_only_count=2,
                review_only_count=0,
                ambiguous_count=0,
                unresolved_count=1,
                public_identity_count=0,
                musicbrainz_identity_count=2,
                musicbrainz_genre_identity_count=0,
                musicbrainz_tag_identity_count=2,
                collision_seed_count=0,
            ),
            output_sha256="0" * 64,
        )
        return preliminary.model_copy(
            update={
                "output_sha256": _sha(
                    preliminary.model_dump(mode="json", exclude={"output_sha256"})
                )
            }
        )

    def _target(self) -> MusicBrainzSeedTargetArtifact:
        settings = SeedTargetExtractorSettings()
        ids = {
            "rock": "00000000-0000-0000-0000-000000000001",
            "jazz": "00000000-0000-0000-0000-000000000002",
        }
        evidence = tuple(
            SeedTargetEvidence(
                seed_source_item_id=f"known-{name}",
                seed_source_external_id=f"eno:known-{name}",
                seed_name=name.title(),
                seed_normalized_name=name,
                facet="tag",
                target_namespace="musicbrainz_tag_name",
                target_identity=f"tag:{name}",
                target_name=name.title(),
                artist_id=artist_id,
                source_record_id=f"musicbrainz:artist:{artist_id}",
                source_record_ordinal=ordinal,
                source_record_sha256="d" * 64,
                source_record_byte_length=1,
                evidence_ref=f"evidence:{name}",
                positive_weight=1.0,
                match_kind="exact",
            )
            for ordinal, (name, artist_id) in enumerate(ids.items(), start=1)
        )
        context = (
            ContextualArtistTag(
                artist_id=ids["rock"],
                source_record_id=f"musicbrainz:artist:{ids['rock']}",
                source_record_ordinal=1,
                source_record_sha256="e" * 64,
                source_record_byte_length=1,
                tag_name="Electronic Rock",
                tag_identity="tag:electronic-rock",
                tag_count=4,
                matched_seed_source_item_ids=("known-rock",),
                evidence_ref="context:electronic-rock",
            ),
        )
        coverage = tuple(
            SeedTargetCoverage(
                seed_source_item_id=seed_id,
                seed_source_external_id=f"eno:{seed_id}",
                seed_name=name,
                normalized_name=name.casefold(),
                evidence_count=1 if seed_id.startswith("known") else 0,
                distinct_artist_count=1 if seed_id.startswith("known") else 0,
                distinct_target_identity_count=1 if seed_id.startswith("known") else 0,
                genre_evidence_count=0,
                tag_evidence_count=1 if seed_id.startswith("known") else 0,
            )
            for seed_id, name in (
                ("known-rock", "Rock"),
                ("known-jazz", "Jazz"),
                ("unknown-electronic", "Electronic Rock"),
            )
        )
        provisional = MusicBrainzSeedTargetArtifact(
            seed_input_sha256="a" * 64,
            seed_source_id="fixture",
            seed_source_content_sha256="b" * 64,
            seed_count=3,
            archive_sha256="c" * 64,
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
                positive_evidence_count=2,
                contextual_tag_count=1,
            ),
            coverage=coverage,
            evidence=evidence,
            contextual_tags=context,
            output_sha256="0" * 64,
        )
        return provisional.model_copy(update={"output_sha256": artifact_sha256(provisional)})

    def test_fits_review_only_candidates_with_seed_level_split(self) -> None:
        artifact = build_learned_label_alignment(
            self._target(),
            self._reconciliation(),
            LearnedLabelAlignmentSettings(
                validation_seed_fraction=0.5,
                hard_negatives_per_positive=2,
                review_score_threshold=0.01,
            ),
        )
        self.assertEqual(artifact.coverage.positive_supervision_count, 2)
        self.assertEqual(artifact.coverage.hard_negative_count, 4)
        self.assertEqual(artifact.coverage.reconciliation_unresolved_seed_count, 1)
        self.assertEqual(artifact.coverage.observed_tag_anchor_seed_count, 2)
        self.assertEqual(artifact.coverage.unresolved_seed_count, 1)
        self.assertEqual(artifact.target_seed_input_sha256, "a" * 64)
        self.assertEqual(artifact.reconciliation_seed_input_sha256, "f" * 64)
        self.assertEqual(len(artifact.coefficients), 6)
        self.assertTrue(artifact.candidates)
        self.assertFalse(artifact.coverage.observed_identities_created)
        self.assertFalse(artifact.coverage.memberships_created)
        verify_learned_label_alignment(artifact)
        self.assertEqual(
            artifact.output_sha256,
            build_learned_label_alignment(
                self._target(),
                self._reconciliation(),
                LearnedLabelAlignmentSettings(
                    validation_seed_fraction=0.5,
                    hard_negatives_per_positive=2,
                    review_score_threshold=0.01,
                ),
            ).output_sha256,
        )

    def test_full_target_tag_anchor_is_not_scored_as_unresolved(self) -> None:
        target = self._target()
        anchor = SeedTargetEvidence(
            seed_source_item_id="unknown-electronic",
            seed_source_external_id="eno:unknown-electronic",
            seed_name="Electronic Rock",
            seed_normalized_name="electronic rock",
            facet="tag",
            target_namespace="musicbrainz_tag_name",
            target_identity="tag:electronic-rock",
            target_name="Electronic Rock",
            artist_id="00000000-0000-0000-0000-000000000003",
            source_record_id="musicbrainz:artist:00000000-0000-0000-0000-000000000003",
            source_record_ordinal=3,
            source_record_sha256="d" * 64,
            source_record_byte_length=1,
            evidence_ref="evidence:electronic-rock",
            positive_weight=1.0,
            match_kind="exact",
        )
        coverage = tuple(
            row.model_copy(
                update={
                    "evidence_count": 1,
                    "distinct_artist_count": 1,
                    "distinct_target_identity_count": 1,
                    "tag_evidence_count": 1,
                }
            )
            if row.seed_source_item_id == "unknown-electronic"
            else row
            for row in target.coverage
        )
        provisional = target.model_copy(
            update={
                "coverage": coverage,
                "evidence": (*target.evidence, anchor),
                "output_sha256": "0" * 64,
            }
        )
        rebound = provisional.model_copy(update={"output_sha256": artifact_sha256(provisional)})
        artifact = build_learned_label_alignment(rebound, self._reconciliation())
        self.assertEqual(artifact.coverage.reconciliation_unresolved_seed_count, 1)
        self.assertEqual(artifact.coverage.observed_tag_anchor_seed_count, 3)
        self.assertEqual(artifact.coverage.unresolved_seed_count, 0)
        self.assertFalse(artifact.candidates)
        self.assertFalse(artifact.abstentions)

    def test_rejects_tampered_output_and_stable_seed_binding(self) -> None:
        target = self._target()
        reconciliation = self._reconciliation()
        artifact = build_learned_label_alignment(target, reconciliation)
        with self.assertRaisesRegex(ValueError, "output hash"):
            verify_learned_label_alignment(artifact.model_copy(update={"output_sha256": "0" * 64}))
        rebound = target.model_copy(update={"seed_source_content_sha256": "f" * 64})
        rebound = rebound.model_copy(update={"output_sha256": artifact_sha256(rebound)})
        with self.assertRaisesRegex(ValueError, "source content hashes"):
            build_learned_label_alignment(rebound, reconciliation)


if __name__ == "__main__":
    unittest.main()
