import unittest
from pathlib import Path

from musix.evidence_frontier import (
    AllSeedEvidenceFrontierArtifact,
    EvidenceFrontierCoverage,
    EvidenceFrontierRow,
    FrontierHierarchy,
    FrontierHierarchyCandidates,
    FrontierObservedArtists,
)
from scripts.build_all_seed_evidence_frontier import build_parser


class EvidenceFrontierTests(unittest.TestCase):
    def _row(self, number: int) -> EvidenceFrontierRow:
        source_id = f"item{number}"
        return EvidenceFrontierRow(
            source_item_id=source_id,
            source_external_id=f"legacy:{number}",
            seed_name=f"Seed {number}",
            normalized_name=f"seed {number}",
            reconciliation_disposition="unresolved",
            hierarchy=FrontierHierarchy(),
            hierarchy_candidates=FrontierHierarchyCandidates(
                input_state="not_provided",
                proposed_edge_count=0,
                accepted_count=0,
                review_count=0,
                abstained_count=0,
                disposition="not_provided",
            ),
            observed_artists=FrontierObservedArtists(
                musicbrainz_genre=0,
                musicbrainz_tag=0,
                wikidata_p136=0,
                distinct_total=0,
            ),
            peer_count=0,
            source_scope=("cc0_public_taxonomy",),
            signal_scope=(),
            missing_or_abstention_reasons=(
                "no_public_identity",
                "no_musicbrainz_identity",
                "no_factual_hierarchy",
                "no_review_hierarchy",
                "no_direct_observed_membership",
                "no_peer_candidate",
                "reconciliation_unresolved",
            ),
            reconciliation_reason="no identity evidence",
        )

    def test_frontier_requires_one_explicit_row_per_seed(self) -> None:
        rows = tuple(self._row(number) for number in range(1, 6292))
        artifact = AllSeedEvidenceFrontierArtifact(
            seed_reconciliation_output_sha256="a" * 64,
            taxonomy_expansion_output_sha256="b" * 64,
            public_model_input_sha256="c" * 64,
            peer_similarity_output_sha256="d" * 64,
            hierarchy_candidate_input_state="not_provided",
            rows=rows,
            coverage=EvidenceFrontierCoverage(
                reconciled_count=0,
                public_only_count=0,
                musicbrainz_only_count=0,
                review_only_count=0,
                ambiguous_count=0,
                unresolved_count=6291,
                factual_hierarchy_seed_count=0,
                review_hierarchy_seed_count=0,
                reconciliation_musicbrainz_identity_seed_count=0,
                direct_observed_seed_count=0,
                observed_musicbrainz_seed_count=0,
                observed_wikidata_seed_count=0,
                peer_seed_count=0,
                hierarchy_candidate_input_state="not_provided",
                hierarchy_candidate_count=0,
                hierarchy_candidate_accepted_count=0,
                hierarchy_candidate_review_count=0,
                hierarchy_candidate_abstained_count=0,
                hierarchy_candidate_supported_seed_count=0,
                hierarchy_candidate_review_seed_count=0,
                hierarchy_candidate_abstained_seed_count=0,
                hierarchy_candidate_isolated_seed_count=0,
            ),
            output_sha256="0" * 64,
        )
        self.assertEqual(len(artifact.rows), 6291)
        with self.assertRaisesRegex(ValueError, "exactly one row"):
            AllSeedEvidenceFrontierArtifact(
                seed_reconciliation_output_sha256="a" * 64,
                taxonomy_expansion_output_sha256="b" * 64,
                public_model_input_sha256="c" * 64,
                peer_similarity_output_sha256="d" * 64,
                hierarchy_candidate_input_state="not_provided",
                rows=(rows[0],) * 6291,
                coverage=artifact.coverage,
                output_sha256="0" * 64,
            )

    def test_review_and_observed_state_are_explicit_and_distinct(self) -> None:
        row = self._row(1).model_copy(
            update={
                "hierarchy": FrontierHierarchy(review_catalog_candidate_ids=("wikidata:genre:Q1",)),
                "observed_artists": FrontierObservedArtists(
                    musicbrainz_genre=2,
                    musicbrainz_tag=1,
                    wikidata_p136=0,
                    distinct_total=2,
                ),
                "source_scope": ("cc0_public_taxonomy", "local_musicbrainz_research"),
                "signal_scope": ("review_hierarchy", "direct_observed_membership"),
                "missing_or_abstention_reasons": (
                    "no_public_identity",
                    "no_musicbrainz_identity",
                    "no_factual_hierarchy",
                    "no_peer_candidate",
                    "reconciliation_unresolved",
                ),
            }
        )
        self.assertEqual(row.hierarchy.factual_catalog_identity_ids, ())
        self.assertEqual(row.observed_artists.distinct_total, 2)

    def test_hierarchy_candidate_input_remains_separate_from_public_taxonomy(self) -> None:
        row = self._row(1).model_copy(
            update={
                "hierarchy": FrontierHierarchy(factual_parent_source_item_ids=("item2",)),
                "hierarchy_candidates": FrontierHierarchyCandidates(
                    input_state="verified",
                    proposed_edge_count=3,
                    accepted_count=1,
                    review_count=1,
                    abstained_count=1,
                    disposition="supported",
                ),
            }
        )
        self.assertEqual(row.hierarchy.factual_parent_source_item_ids, ("item2",))
        self.assertEqual(row.hierarchy_candidates.accepted_count, 1)
        with self.assertRaisesRegex(ValueError, "partition proposals"):
            FrontierHierarchyCandidates(
                input_state="verified",
                proposed_edge_count=2,
                accepted_count=1,
                review_count=1,
                abstained_count=1,
                disposition="supported",
            )

    def test_cli_requires_every_sealed_frontier_boundary(self) -> None:
        arguments = build_parser().parse_args(
            [
                "--reconciliation",
                "reconciliation.json",
                "--taxonomy-expansion",
                "taxonomy.json",
                "--public-input",
                "input.json",
                "--peer-similarity",
                "peers.json",
                "--hierarchy-candidates",
                "hierarchy-candidates.json",
                "--output",
                "frontier.json",
                "--object-store",
                "objects",
                "--receipt",
                "receipt.json",
            ]
        )
        self.assertEqual(arguments.output, Path("frontier.json"))
        self.assertEqual(arguments.hierarchy_candidates, Path("hierarchy-candidates.json"))


if __name__ == "__main__":
    unittest.main()
