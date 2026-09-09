from __future__ import annotations

import hashlib
import json
import unittest
from typing import Literal

from musix.ingest.musicbrainz.model_adapter import (
    MusicBrainzModelAdapterPolicy,
    adapt_musicbrainz_seed_targets,
    verify_musicbrainz_model_adapter_report,
)
from musix.ingest.musicbrainz.seed_targets import (
    MusicBrainzSeedTargetArtifact,
    SeedTargetCoverage,
    SeedTargetEvidence,
    SeedTargetExtractorCounters,
    SeedTargetExtractorSettings,
    artifact_sha256,
    settings_sha256,
)
from musix.models.modeling import PublicModelInput
from musix.taxonomy.seeds.reconciliation import (
    SeedReconciliationArtifact,
    SeedReconciliationCoverage,
    SeedReconciliationDisposition,
)


class MusicBrainzModelAdapterTests(unittest.TestCase):
    def _source(
        self, *, first_seed: str = "seed-a", second_seed: str = "seed-b"
    ) -> tuple[MusicBrainzSeedTargetArtifact, SeedReconciliationArtifact]:
        settings = SeedTargetExtractorSettings()
        artists = (
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
        )
        source_rows: tuple[tuple[str, Literal["genre", "tag"], str], ...] = (
            (first_seed, "genre", artists[0]),
            (first_seed, "tag", artists[0]),
            (first_seed, "tag", artists[1]),
            (second_seed, "genre", artists[1]),
        )
        evidence = tuple(
            SeedTargetEvidence(
                seed_source_item_id=seed,
                seed_source_external_id=f"legacy:{seed}",
                seed_name=seed,
                seed_normalized_name=seed,
                facet=facet,
                target_namespace=(
                    "musicbrainz_genre_id" if facet == "genre" else "musicbrainz_tag_name"
                ),
                target_identity=f"target:{seed}",
                target_name=seed,
                artist_id=artist,
                source_record_id=f"artist:{artist}",
                source_record_ordinal=ordinal,
                source_record_sha256="a" * 64,
                source_record_byte_length=1,
                evidence_ref=f"evidence:{seed}:{facet}:{artist}",
                positive_weight=1.0,
                match_kind="exact",
            )
            for ordinal, (seed, facet, artist) in enumerate(source_rows, start=1)
        )
        counters = SeedTargetExtractorCounters(
            **dict.fromkeys(SeedTargetExtractorCounters.model_fields, 0)
        )
        target = MusicBrainzSeedTargetArtifact(
            seed_input_sha256="c" * 64,
            seed_source_id="test",
            seed_source_content_sha256="d" * 64,
            seed_count=2,
            archive_sha256="e" * 64,
            settings=settings,
            settings_sha256=settings_sha256(settings),
            counters=counters,
            coverage=tuple(
                SeedTargetCoverage(
                    seed_source_item_id=seed,
                    seed_source_external_id=f"legacy:{seed}",
                    seed_name=seed,
                    normalized_name=seed,
                    evidence_count=sum(row.seed_source_item_id == seed for row in evidence),
                    distinct_artist_count=len(
                        {row.artist_id for row in evidence if row.seed_source_item_id == seed}
                    ),
                    distinct_target_identity_count=2,
                    genre_evidence_count=sum(
                        row.seed_source_item_id == seed and row.facet == "genre" for row in evidence
                    ),
                    tag_evidence_count=sum(
                        row.seed_source_item_id == seed and row.facet == "tag" for row in evidence
                    ),
                )
                for seed in (first_seed, second_seed)
            ),
            evidence=evidence,
            output_sha256="0" * 64,
        )
        target = target.model_copy(update={"output_sha256": artifact_sha256(target)})
        dispositions = tuple(
            SeedReconciliationDisposition(
                source_item_id=seed,
                source_external_id=f"legacy:{seed}",
                seed_name=seed,
                normalized_name=seed,
                disposition="unresolved",
                reason="fixture",
            )
            for seed in (first_seed, second_seed)
        )
        seed_identity_sha256 = hashlib.sha256(
            json.dumps(
                [
                    {
                        "source_item_id": row.source_item_id,
                        "source_external_id": row.source_external_id,
                        "name": row.seed_name,
                    }
                    for row in sorted(dispositions, key=lambda item: item.source_item_id)
                ],
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        reconciliation = SeedReconciliationArtifact(
            seed_input_sha256=target.seed_input_sha256,
            seed_source_id=target.seed_source_id,
            seed_source_content_sha256=target.seed_source_content_sha256,
            seed_identity_sha256=seed_identity_sha256,
            taxonomy_artifact_sha256="f" * 64,
            input_sha256="1" * 64,
            seed_count=2,
            dispositions=dispositions,
            coverage=SeedReconciliationCoverage(
                seed_count=2,
                reconciled_count=0,
                public_only_count=0,
                musicbrainz_only_count=0,
                review_only_count=0,
                ambiguous_count=0,
                unresolved_count=2,
                public_identity_count=0,
                musicbrainz_identity_count=0,
                musicbrainz_genre_identity_count=0,
                musicbrainz_tag_identity_count=0,
                collision_seed_count=0,
            ),
            output_sha256="0" * 64,
        )
        reconciliation_hash = hashlib.sha256(
            json.dumps(
                reconciliation.model_dump(mode="json", exclude={"output_sha256"}),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return target, reconciliation.model_copy(update={"output_sha256": reconciliation_hash})

    def test_reviewed_alias_evidence_reaches_the_stable_seed_membership(self) -> None:
        """The adapter retains reviewed source provenance without replacing item887."""
        target, reconciliation = self._source(first_seed="item887", second_seed="item2")
        evidence = list(target.evidence)
        evidence[1] = evidence[1].model_copy(
            update={
                "target_identity": "tag:idm",
                "target_name": "IDM",
                "evidence_ref": "source:tag:idm:reviewed-alias:reviewed:idm-v1:abc",
                "match_kind": "reviewed_alias",
            }
        )
        target = target.model_copy(update={"evidence": tuple(evidence)})
        target = target.model_copy(update={"output_sha256": artifact_sha256(target)})

        result = adapt_musicbrainz_seed_targets(
            target, reconciliation, MusicBrainzModelAdapterPolicy(expected_seed_count=2)
        )

        membership = next(
            item
            for item in result.model_input.direct_memberships
            if item.genre_id == "item887" and item.facet == "musicbrainz_tag"
        )
        self.assertEqual(
            membership.artist_id,
            "musicbrainz:artist:00000000-0000-0000-0000-000000000001",
        )
        aggregate = next(
            item
            for item in result.aggregates
            if item.seed_source_item_id == "item887"
            and item.artist_id.endswith("00000000-0000-0000-0000-000000000001")
            and item.facet == "musicbrainz_tag"
        )
        self.assertIn("target:musicbrainz_tag_name:tag:idm", aggregate.source_evidence_refs[0])
        self.assertIn("reviewed:idm-v1", aggregate.source_evidence_refs[0])

    def test_adapts_facets_and_aggregates_without_lexical_resolution(self) -> None:
        target, reconciliation = self._source()
        result = adapt_musicbrainz_seed_targets(
            target,
            reconciliation,
            MusicBrainzModelAdapterPolicy(expected_seed_count=2),
        )
        self.assertIsInstance(result.model_input, PublicModelInput)
        self.assertEqual(len(result.model_input.genres), 2)
        self.assertEqual(
            {row.facet for row in result.model_input.direct_memberships},
            {"musicbrainz_genre", "musicbrainz_tag"},
        )
        self.assertEqual(len(result.model_input.direct_memberships), 4)
        self.assertFalse(result.report.lexical_identity_resolution_rerun)
        self.assertEqual(result.report.aggregate_membership_count, 4)
        rock = next(item for item in result.model_input.genres if item.genre_id == "seed-a")
        self.assertEqual(len(rock.evidence_refs), 2)
        self.assertTrue(rock.evidence_refs[0].startswith("seed-reconciliation:"))
        self.assertTrue(rock.evidence_refs[1].startswith("mb-seed-target-evidence-set:"))
        verify_musicbrainz_model_adapter_report(result.report)

    def test_accepts_distinct_seed_wrapper_hashes_for_the_same_seed_identities(self) -> None:
        target, reconciliation = self._source()
        target = target.model_copy(update={"seed_input_sha256": "a" * 64})
        target = target.model_copy(update={"output_sha256": artifact_sha256(target)})
        result = adapt_musicbrainz_seed_targets(
            target,
            reconciliation,
            MusicBrainzModelAdapterPolicy(expected_seed_count=2),
        )
        self.assertEqual(result.report.target_seed_input_sha256, "a" * 64)
        self.assertEqual(
            result.report.reconciliation_seed_input_sha256,
            reconciliation.seed_input_sha256,
        )
        self.assertEqual(len(result.report.seed_identity_fingerprint), 64)

    def test_rejects_tampered_source_provenance_with_matching_seed_rows(self) -> None:
        target, reconciliation = self._source()
        target = target.model_copy(update={"seed_source_id": "other-source"})
        target = target.model_copy(update={"output_sha256": artifact_sha256(target)})
        with self.assertRaisesRegex(ValueError, "source IDs do not match"):
            adapt_musicbrainz_seed_targets(
                target,
                reconciliation,
                MusicBrainzModelAdapterPolicy(expected_seed_count=2),
            )

    def test_rejects_tampered_seed_external_identity_even_when_ids_and_names_match(self) -> None:
        target, reconciliation = self._source()
        coverage = list(target.coverage)
        coverage[0] = coverage[0].model_copy(update={"seed_source_external_id": "other:seed-a"})
        target = target.model_copy(update={"coverage": tuple(coverage)})
        target = target.model_copy(update={"output_sha256": artifact_sha256(target)})
        with self.assertRaisesRegex(ValueError, "seed identities do not match"):
            adapt_musicbrainz_seed_targets(
                target,
                reconciliation,
                MusicBrainzModelAdapterPolicy(expected_seed_count=2),
            )

    def test_seed_evidence_commitment_changes_when_direct_evidence_changes(self) -> None:
        target, reconciliation = self._source()
        original = adapt_musicbrainz_seed_targets(
            target,
            reconciliation,
            MusicBrainzModelAdapterPolicy(expected_seed_count=2),
        )
        evidence = list(target.evidence)
        evidence[0] = evidence[0].model_copy(update={"evidence_ref": "tampered-evidence"})
        tampered = target.model_copy(update={"evidence": tuple(evidence)})
        tampered = tampered.model_copy(update={"output_sha256": artifact_sha256(tampered)})
        rebuilt = adapt_musicbrainz_seed_targets(
            tampered,
            reconciliation,
            MusicBrainzModelAdapterPolicy(expected_seed_count=2),
        )
        original_ref = next(
            item for item in original.model_input.genres if item.genre_id == "seed-a"
        ).evidence_refs[1]
        rebuilt_ref = next(
            item for item in rebuilt.model_input.genres if item.genre_id == "seed-a"
        ).evidence_refs[1]
        self.assertNotEqual(original_ref, rebuilt_ref)

    def test_coverage_counts_are_accumulated_per_seed_once(self) -> None:
        target, reconciliation = self._source()
        result = adapt_musicbrainz_seed_targets(
            target,
            reconciliation,
            MusicBrainzModelAdapterPolicy(expected_seed_count=2),
        )
        coverage = {item.source_item_id: item for item in result.report.coverage}
        self.assertEqual(coverage["seed-a"].accepted_evidence_count, 3)
        self.assertEqual(coverage["seed-a"].aggregate_membership_count, 3)
        self.assertEqual(coverage["seed-a"].genre_membership_count, 1)
        self.assertEqual(coverage["seed-a"].tag_membership_count, 2)


if __name__ == "__main__":
    unittest.main()
