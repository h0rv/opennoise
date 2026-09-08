from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from musix.genre_hierarchy_candidates import (
    GenreHierarchyCandidatePolicy,
    build_genre_hierarchy_candidates,
    verify_genre_hierarchy_candidates,
)
from musix.genre_seed_taxonomy import (
    CompositionCalibration,
    GenreSeedPublicTaxonomyArtifact,
    PublicCatalogInput,
    PublicTaxonomyConfig,
    PublicTaxonomyNode,
    SeedTaxonomyInference,
    TaxonomyCoverageReport,
)
from musix.genre_seed_universe import SeedInput, SeedName
from musix.models.modeling import (
    DirectMembershipEvidence,
    GenreIdentity,
    PublicArtifact,
    PublicModelInput,
)
from musix.seed_reconciliation import (
    SeedReconciliationArtifact,
    SeedReconciliationCoverage,
    SeedReconciliationDisposition,
)
from musix.storage import LocalObjectStore
from musix.taxonomy_relation_expansion import (
    TaxonomyRelationExpansionPolicy,
    build_taxonomy_relation_expansion,
    catalog_wikidata_p279_feed,
)
from tests.test_taxonomy_relation_expansion import _write_catalog


def _inputs() -> tuple[
    SeedReconciliationArtifact, GenreSeedPublicTaxonomyArtifact, PublicModelInput
]:
    names = tuple(
        SeedName(source_item_id=f"item{index}", source_external_id=f"legacy:{index}", name=name)
        for index, name in enumerate(("Child", "Parent", "Pov Child"), start=1)
    )
    seed_input = SeedInput(
        source_id="legacy",
        source_content_sha256="a" * 64,
        artifact_sha256="b" * 64,
        names=names,
    )
    taxonomy = GenreSeedPublicTaxonomyArtifact(
        seed_input=seed_input,
        public_catalog=PublicCatalogInput(
            database_sha256="c" * 64,
            source_licenses=("CC0-1.0",),
        ),
        config=PublicTaxonomyConfig(expected_seed_count=3),
        calibration=CompositionCalibration(
            eligible_exact_name_count=2,
            observed_taxonomy_path_count=1,
            missing_taxonomy_path_count=1,
            laplace_precision=0.5,
            status="available",
            minimum_examples=1,
        ),
        inferences=(
            SeedTaxonomyInference(
                source_item_id="item1",
                source_external_id="legacy:1",
                seed_name="Child",
                normalized_name="child",
                status="canonical_exact",
                exact_candidates=(
                    PublicTaxonomyNode(
                        catalog_id="wikidata:genre:Q1", name="Child", match_kind="canonical"
                    ),
                ),
                structural_confidence=1.0,
            ),
            SeedTaxonomyInference(
                source_item_id="item2",
                source_external_id="legacy:2",
                seed_name="Parent",
                normalized_name="parent",
                status="canonical_exact",
                exact_candidates=(
                    PublicTaxonomyNode(
                        catalog_id="wikidata:genre:Q2", name="Parent", match_kind="canonical"
                    ),
                ),
                structural_confidence=1.0,
            ),
            SeedTaxonomyInference(
                source_item_id="item3",
                source_external_id="legacy:3",
                seed_name="Pov Child",
                normalized_name="pov child",
                status="anchored_compositional",
                lexical_modifier="pov",
                anchor=PublicTaxonomyNode(
                    catalog_id="wikidata:genre:Q1", name="Child", match_kind="canonical"
                ),
                structural_confidence=0.8,
            ),
        ),
        coverage=TaxonomyCoverageReport(
            seed_count=3,
            canonical_exact_count=2,
            canonical_alias_count=0,
            compositional_anchor_count=1,
            ambiguous_exact_count=0,
            ambiguous_compositional_count=0,
            abstained_count=0,
            covered_for_review_count=3,
            canonical_membership_count=2,
        ),
        output_sha256="d" * 64,
    )
    reconciliation = SeedReconciliationArtifact(
        seed_input_sha256="e" * 64,
        seed_source_id=seed_input.source_id,
        seed_source_content_sha256=seed_input.source_content_sha256,
        seed_identity_sha256=hashlib.sha256(
            json.dumps(
                [
                    {
                        "source_item_id": item.source_item_id,
                        "source_external_id": item.source_external_id,
                        "name": item.name,
                    }
                    for item in names
                ],
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest(),
        taxonomy_artifact_sha256=taxonomy.output_sha256,
        input_sha256="f" * 64,
        seed_count=3,
        dispositions=tuple(
            SeedReconciliationDisposition(
                source_item_id=name.source_item_id,
                source_external_id=name.source_external_id,
                seed_name=name.name,
                normalized_name=name.name.casefold(),
                disposition="unresolved",
                reason="fixture",
            )
            for name in names
        ),
        coverage=SeedReconciliationCoverage(
            seed_count=3,
            reconciled_count=0,
            public_only_count=0,
            musicbrainz_only_count=0,
            review_only_count=0,
            ambiguous_count=0,
            unresolved_count=3,
            public_identity_count=0,
            musicbrainz_identity_count=0,
            musicbrainz_genre_identity_count=0,
            musicbrainz_tag_identity_count=0,
            collision_seed_count=0,
        ),
        output_sha256="1" * 64,
    )
    public_input = PublicModelInput(
        artifacts=(
            PublicArtifact(
                source="wikidata",
                snapshot="fixture",
                artifact_key="fixture",
                content_sha256="2" * 64,
                export_allowed=True,
            ),
        ),
        genres=tuple(
            GenreIdentity(genre_id=f"item{index}", name=name, evidence_refs=(f"seed:{index}",))
            for index, name in enumerate(("Child", "Parent", "Pov Child"), start=1)
        ),
        direct_memberships=tuple(
            DirectMembershipEvidence(
                artist_id=artist,
                genre_id=genre_id,
                facet="wikidata_p136",
                value=1.0,
                evidence_ref=f"evidence:{artist}:{genre_id}",
            )
            for artist, genre_id in (
                ("artist-a", "item1"),
                ("artist-b", "item1"),
                ("artist-a", "item2"),
                ("artist-b", "item2"),
                ("artist-c", "item2"),
            )
        ),
    )
    return reconciliation, taxonomy, public_input


class GenreHierarchyCandidateTests(unittest.TestCase):
    def test_components_are_separate_and_parent_memberships_are_not_inherited(self) -> None:
        reconciliation, taxonomy, public_input = _inputs()
        artifact = build_genre_hierarchy_candidates(
            reconciliation,
            taxonomy,
            public_input,
            GenreHierarchyCandidatePolicy(expected_seed_count=3, accepted_score=0.2),
        )
        child_parent = next(
            row
            for row in artifact.candidates
            if (row.child_genre_id, row.parent_genre_id) == ("item1", "item2")
        )
        lexical = next(row for row in artifact.candidates if row.child_genre_id == "item3")
        self.assertEqual(child_parent.reason, "meets_artist_containment_policy")
        self.assertEqual(child_parent.components.child_artist_count, 2)
        self.assertEqual(child_parent.components.parent_artist_count, 3)
        self.assertEqual(child_parent.components.factual_public_taxonomy.normalized_value, 0.0)
        self.assertEqual(lexical.reason, "lexical_review_prior")
        self.assertEqual(artifact.coverage.seed_count, 3)
        self.assertEqual(artifact.coverage.isolated_seed_count, 1)
        verify_genre_hierarchy_candidates(artifact)

    def test_receipt_verified_relation_facts_merge_and_dedupe(self) -> None:
        reconciliation, taxonomy, public_input = _inputs()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = LocalObjectStore(root / "objects")
            catalog = root / "catalog.sqlite"
            _write_catalog(catalog, rows=((10, 1, 2),))
            feed = catalog_wikidata_p279_feed(catalog, store=store)
            relation = build_taxonomy_relation_expansion(
                taxonomy,
                feed,
                TaxonomyRelationExpansionPolicy(expected_seed_count=3),
                source_store=store,
            )
            artifact = build_genre_hierarchy_candidates(
                reconciliation,
                taxonomy,
                public_input,
                GenreHierarchyCandidatePolicy(expected_seed_count=3, accepted_score=0.2),
                taxonomy_relation_expansion=relation,
                taxonomy_relation_source_store=store,
            )
        child_parent = next(
            row
            for row in artifact.candidates
            if (row.child_genre_id, row.parent_genre_id) == ("item1", "item2")
        )
        self.assertEqual(artifact.taxonomy_relation_expansion_output_sha256, relation.output_sha256)
        self.assertEqual(artifact.coverage.candidate_count, 2)
        self.assertEqual(child_parent.reason, "factual_public_taxonomy")
        self.assertIn(
            f"taxonomy-relation-expansion:{relation.output_sha256}:"
            f"catalog:{feed.observations[0].source_response_sha256}:genre_hierarchy:10",
            child_parent.evidence_refs,
        )


if __name__ == "__main__":
    unittest.main()
