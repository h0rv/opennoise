import unittest

from musix.ingest.musicbrainz.seed_targets import (
    ContextualArtistTag,
    MusicBrainzSeedTargetArtifact,
    SeedTargetCoverage,
    SeedTargetEvidence,
    SeedTargetExtractorCounters,
    SeedTargetExtractorSettings,
    artifact_sha256,
    settings_sha256,
)
from musix.serving.sparse_genre_prototype import (
    SparsePrototypeSettings,
    _bounded_cosine,
    build_sparse_genre_prototype,
    verify_sparse_genre_prototype,
)


class SparseGenrePrototypeTests(unittest.TestCase):
    def test_clamps_sparse_cosine_rounding_overshoot(self) -> None:
        self.assertEqual(_bounded_cosine(1.0000000000000004), 1.0)

    def _source(self) -> MusicBrainzSeedTargetArtifact:
        settings = SeedTargetExtractorSettings()
        evidence = tuple(
            SeedTargetEvidence(
                seed_source_item_id=seed,
                seed_source_external_id=f"legacy:{seed}",
                seed_name=seed,
                seed_normalized_name=seed,
                facet="tag",
                target_namespace="musicbrainz_tag_name",
                target_identity=f"tag:{seed}",
                target_name=seed,
                artist_id=artist,
                source_record_id=f"musicbrainz:artist:{artist}",
                source_record_ordinal=ordinal,
                source_record_sha256="a" * 64,
                source_record_byte_length=1,
                evidence_ref=f"evidence:{seed}:{artist}",
                positive_weight=1.0,
                match_kind="exact",
            )
            for ordinal, (seed, artist) in enumerate(
                (
                    ("seed-a", "00000000-0000-0000-0000-000000000001"),
                    ("seed-a", "00000000-0000-0000-0000-000000000002"),
                    ("seed-b", "00000000-0000-0000-0000-000000000003"),
                    ("seed-b", "00000000-0000-0000-0000-000000000004"),
                ),
                start=1,
            )
        )
        context = tuple(
            ContextualArtistTag(
                artist_id=artist,
                source_record_id=f"musicbrainz:artist:{artist}",
                source_record_ordinal=ordinal,
                source_record_sha256="b" * 64,
                source_record_byte_length=1,
                tag_name=tag,
                tag_identity=f"tag:{tag}",
                tag_count=1,
                matched_seed_source_item_ids=(seed,),
                evidence_ref=f"context:{artist}:{tag}",
            )
            for ordinal, (seed, artist, tag) in enumerate(
                (
                    ("seed-a", "00000000-0000-0000-0000-000000000001", "shared"),
                    ("seed-a", "00000000-0000-0000-0000-000000000002", "shared"),
                    ("seed-b", "00000000-0000-0000-0000-000000000003", "shared"),
                    ("seed-b", "00000000-0000-0000-0000-000000000004", "shared"),
                ),
                start=1,
            )
        )
        provisional = MusicBrainzSeedTargetArtifact(
            seed_input_sha256="c" * 64,
            seed_source_id="test",
            seed_source_content_sha256="d" * 64,
            seed_count=2,
            archive_sha256="e" * 64,
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
                positive_evidence_count=0,
                contextual_tag_count=0,
            ),
            coverage=(
                SeedTargetCoverage(
                    seed_source_item_id="seed-a",
                    seed_source_external_id="legacy:seed-a",
                    seed_name="seed-a",
                    normalized_name="seed-a",
                    evidence_count=2,
                    distinct_artist_count=2,
                    distinct_target_identity_count=1,
                    genre_evidence_count=0,
                    tag_evidence_count=2,
                ),
                SeedTargetCoverage(
                    seed_source_item_id="seed-b",
                    seed_source_external_id="legacy:seed-b",
                    seed_name="seed-b",
                    normalized_name="seed-b",
                    evidence_count=2,
                    distinct_artist_count=2,
                    distinct_target_identity_count=1,
                    genre_evidence_count=0,
                    tag_evidence_count=2,
                ),
            ),
            evidence=evidence,
            contextual_tags=context,
            output_sha256="0" * 64,
        )
        return provisional.model_copy(update={"output_sha256": artifact_sha256(provisional)})

    def test_heldout_direct_positives_are_not_features_and_replay(self) -> None:
        artifact = build_sparse_genre_prototype(
            self._source(), SparsePrototypeSettings(holdout_fraction=0.99, retrieval_k=2)
        )
        self.assertEqual(artifact.coverage.direct_positive_count, 4)
        self.assertEqual(artifact.coverage.train_positive_count, 2)
        self.assertEqual(artifact.heldout_evaluation.heldout_positive_count, 2)
        self.assertFalse(artifact.coverage.direct_target_features_used)
        self.assertFalse(artifact.coverage.historical_inputs_read)
        self.assertEqual(len(artifact.candidates), 1)
        verify_sparse_genre_prototype(artifact)

    def test_tampered_output_fails_closed(self) -> None:
        artifact = build_sparse_genre_prototype(self._source())
        with self.assertRaisesRegex(ValueError, "hash"):
            verify_sparse_genre_prototype(artifact.model_copy(update={"output_sha256": "0" * 64}))

    def test_missing_sparse_retrieval_score_is_an_abstention(self) -> None:
        source = self._source()
        contextual_tags = tuple(
            row.model_copy(
                update={
                    "tag_name": f"unique-{index}",
                    "tag_identity": f"tag:unique-{index}",
                }
            )
            for index, row in enumerate(source.contextual_tags)
        )
        rebound = source.model_copy(
            update={"contextual_tags": contextual_tags, "output_sha256": "0" * 64}
        )
        rebound = rebound.model_copy(update={"output_sha256": artifact_sha256(rebound)})
        artifact = build_sparse_genre_prototype(
            rebound, SparsePrototypeSettings(holdout_fraction=0.99, retrieval_k=2)
        )
        self.assertEqual(artifact.heldout_evaluation.heldout_positive_count, 2)
        self.assertEqual(artifact.heldout_evaluation.evaluated_positive_count, 0)
        self.assertEqual(artifact.heldout_evaluation.abstained_positive_count, 2)
        self.assertIsNone(artifact.heldout_evaluation.retrieval_recall_at_k)


if __name__ == "__main__":
    unittest.main()
