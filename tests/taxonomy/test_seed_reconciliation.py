import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from musix.evidence.reconstruction import GenreArtistEdge, ReconstructionInputs, VersionedInput
from musix.ingest.musicbrainz.musicbrainz_coverage import CoverageMatch, CoverageReport
from musix.storage import LocalObjectStore
from musix.taxonomy.genre_seed_taxonomy import (
    CompositionCalibration,
    GenreSeedPublicTaxonomyArtifact,
    PublicCatalogInput,
    PublicTaxonomyConfig,
    PublicTaxonomyNode,
    SeedTaxonomyInference,
    TaxonomyCoverageReport,
)
from musix.taxonomy.genre_seed_universe import SeedInput, SeedName
from musix.taxonomy.seed_reconciliation import (
    MusicBrainzGenreIdentity,
    build_seed_reconciliation,
    make_musicbrainz_identity_input,
    musicbrainz_identity_input_from_coverage,
    public_model_input_from_reconstruction_reconciliation,
    publish_seed_reconciliation,
    verify_seed_reconciliation,
)


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


class SeedReconciliationTests(unittest.TestCase):
    def _inputs(self) -> tuple[SeedInput, GenreSeedPublicTaxonomyArtifact]:
        names = (
            SeedName(source_item_id="1", source_external_id="legacy:1", name="Rock"),
            SeedName(source_item_id="2", source_external_id="legacy:2", name="rock!"),
            SeedName(source_item_id="3", source_external_id="legacy:3", name="Electronic"),
            SeedName(source_item_id="4", source_external_id="legacy:4", name="Canadian Rock"),
            SeedName(source_item_id="5", source_external_id="legacy:5", name="Unknown"),
        )
        seed = SeedInput(
            source_id="legacy",
            source_content_sha256="a" * 64,
            artifact_sha256="b" * 64,
            names=names,
        )
        inferences = (
            SeedTaxonomyInference(
                source_item_id="1",
                source_external_id="legacy:1",
                seed_name="Rock",
                normalized_name="rock",
                status="canonical_exact",
                exact_candidates=(
                    PublicTaxonomyNode(
                        catalog_id="wikidata:genre:Q1", name="Rock", match_kind="canonical"
                    ),
                ),
                structural_confidence=1.0,
            ),
            SeedTaxonomyInference(
                source_item_id="2",
                source_external_id="legacy:2",
                seed_name="rock!",
                normalized_name="rock",
                status="canonical_exact",
                exact_candidates=(
                    PublicTaxonomyNode(
                        catalog_id="wikidata:genre:Q1", name="Rock", match_kind="canonical"
                    ),
                ),
                structural_confidence=1.0,
            ),
            SeedTaxonomyInference(
                source_item_id="3",
                source_external_id="legacy:3",
                seed_name="Electronic",
                normalized_name="electronic",
                status="ambiguous_exact",
                exact_candidates=(
                    PublicTaxonomyNode(
                        catalog_id="wikidata:genre:Q2", name="Electronic", match_kind="canonical"
                    ),
                    PublicTaxonomyNode(
                        catalog_id="wikidata:genre:Q3", name="Electronic", match_kind="canonical"
                    ),
                ),
                structural_confidence=0.0,
                abstention_reason="duplicate public identities",
            ),
            SeedTaxonomyInference(
                source_item_id="4",
                source_external_id="legacy:4",
                seed_name="Canadian Rock",
                normalized_name="canadian rock",
                status="anchored_compositional",
                lexical_modifier="canadian",
                anchor=PublicTaxonomyNode(
                    catalog_id="wikidata:genre:Q1", name="Rock", match_kind="canonical"
                ),
                structural_confidence=0.8,
            ),
            SeedTaxonomyInference(
                source_item_id="5",
                source_external_id="legacy:5",
                seed_name="Unknown",
                normalized_name="unknown",
                status="abstained",
                structural_confidence=0.0,
                abstention_reason="no public identity",
            ),
        )
        coverage = TaxonomyCoverageReport(
            seed_count=5,
            canonical_exact_count=3,
            canonical_alias_count=0,
            compositional_anchor_count=1,
            ambiguous_exact_count=1,
            ambiguous_compositional_count=0,
            abstained_count=1,
            covered_for_review_count=4,
            canonical_membership_count=3,
        )
        taxonomy = GenreSeedPublicTaxonomyArtifact(
            seed_input=seed,
            public_catalog=PublicCatalogInput(
                database_sha256="c" * 64,
                source_licenses=("public",),
            ),
            config=PublicTaxonomyConfig(expected_seed_count=5),
            calibration=CompositionCalibration(
                eligible_exact_name_count=0,
                observed_taxonomy_path_count=0,
                missing_taxonomy_path_count=0,
                laplace_precision=0.5,
                status="insufficient_examples",
                minimum_examples=12,
            ),
            inferences=inferences,
            coverage=coverage,
            output_sha256="0" * 64,
        )
        taxonomy = taxonomy.model_copy(
            update={
                "output_sha256": _hash(taxonomy.model_dump(mode="json", exclude={"output_sha256"}))
            }
        )
        return seed, taxonomy

    def test_every_seed_gets_one_disposition_and_review_does_not_promote(self) -> None:
        seed, taxonomy = self._inputs()
        mb = make_musicbrainz_identity_input(
            "d" * 64,
            (
                MusicBrainzGenreIdentity(
                    source_item_id="1",
                    identifier="mb:rock",
                    name="Rock",
                    evidence_refs=("mb-row-1",),
                ),
                MusicBrainzGenreIdentity(
                    source_item_id="5",
                    identifier="mb:unknown",
                    name="Unknown",
                    evidence_refs=("mb-row-5",),
                ),
            ),
        )
        artifact = build_seed_reconciliation(seed, taxonomy, mb)
        self.assertEqual(len(artifact.dispositions), 5)
        self.assertEqual(
            {row.disposition for row in artifact.dispositions},
            {"reconciled", "public_only", "ambiguous", "review_only", "musicbrainz_only"},
        )
        self.assertEqual(artifact.coverage.seed_count, 5)
        self.assertEqual(artifact.coverage.collision_seed_count, 2)
        self.assertEqual(artifact.dispositions[3].public_identities, ())
        self.assertEqual(artifact.review_candidates_promoted_to_identity, 0)
        verify_seed_reconciliation(artifact)

    def test_duplicate_public_candidates_are_preserved(self) -> None:
        seed, taxonomy = self._inputs()
        artifact = build_seed_reconciliation(seed, taxonomy)
        rock_rows = [row for row in artifact.dispositions if row.source_item_id in {"1", "2"}]
        self.assertEqual(
            [row.public_identities[0].identifier for row in rock_rows],
            ["wikidata:genre:Q1", "wikidata:genre:Q1"],
        )
        electronic = artifact.dispositions[2]
        self.assertEqual(electronic.disposition, "ambiguous")
        self.assertEqual(
            tuple(item.identifier for item in electronic.public_identities),
            ("wikidata:genre:Q2", "wikidata:genre:Q3"),
        )

    def test_seed_identity_mismatch_fails_closed(self) -> None:
        seed, taxonomy = self._inputs()
        changed = taxonomy.seed_input.names[0].model_copy(update={"name": "Different"})
        changed_seed = taxonomy.seed_input.model_copy(
            update={"names": (changed, *taxonomy.seed_input.names[1:])}
        )
        mismatched = taxonomy.model_copy(update={"seed_input": changed_seed})
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            build_seed_reconciliation(seed, mismatched)

    def test_tamper_and_musicbrainz_out_of_universe_fail(self) -> None:
        seed, taxonomy = self._inputs()
        artifact = build_seed_reconciliation(seed, taxonomy)
        tampered = artifact.model_copy(update={"seed_count": 4})
        with self.assertRaises(ValueError):
            verify_seed_reconciliation(tampered)
        rebound = artifact.model_copy(
            update={
                "seed_identity_sha256": "f" * 64,
                "output_sha256": "0" * 64,
            }
        )
        rebound = rebound.model_copy(
            update={
                "output_sha256": _hash(rebound.model_dump(mode="json", exclude={"output_sha256"}))
            }
        )
        with self.assertRaisesRegex(ValueError, "stable seed identity hash"):
            verify_seed_reconciliation(rebound)
        mb = make_musicbrainz_identity_input(
            "e" * 64,
            (
                MusicBrainzGenreIdentity(
                    source_item_id="missing",
                    identifier="mb:x",
                    name="X",
                    evidence_refs=("mb-row-x",),
                ),
            ),
        )
        with self.assertRaisesRegex(ValueError, "outside the seed universe"):
            build_seed_reconciliation(seed, taxonomy, mb)

    def test_unsorted_musicbrainz_rows_have_one_replay_hash(self) -> None:
        first = make_musicbrainz_identity_input(
            "f" * 64,
            (
                MusicBrainzGenreIdentity(
                    source_item_id="5",
                    identifier="mb:unknown",
                    name="Unknown",
                    evidence_refs=("mb-row-5",),
                ),
                MusicBrainzGenreIdentity(
                    source_item_id="1",
                    identifier="mb:rock",
                    name="Rock",
                    evidence_refs=("mb-row-1",),
                ),
            ),
        )
        second = make_musicbrainz_identity_input(
            "f" * 64,
            tuple(reversed(first.rows)),
        )
        self.assertEqual(first.input_sha256, second.input_sha256)
        self.assertEqual(first.rows, second.rows)

    def test_publication_uses_typed_object_store_receipt(self) -> None:
        seed, taxonomy = self._inputs()
        artifact = build_seed_reconciliation(seed, taxonomy)
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, write = publish_seed_reconciliation(
                artifact,
                output_path=root / "artifact.json",
                store=LocalObjectStore(root / "objects"),
            )
            self.assertEqual(receipt.artifact_sha256, write.sha256)
            self.assertEqual(receipt.artifact_byte_size, write.byte_size)
            self.assertEqual(receipt.logical_output_sha256, artifact.output_sha256)

    def test_reconstruction_bridge_emits_stable_ids_and_rejects_noncanonical_rows(self) -> None:
        seed, taxonomy = self._inputs()
        musicbrainz = make_musicbrainz_identity_input(
            "d" * 64,
            (
                MusicBrainzGenreIdentity(
                    source_item_id="1",
                    identifier="mb:rock",
                    name="Rock",
                    evidence_refs=("mb-row-rock",),
                ),
                MusicBrainzGenreIdentity(
                    source_item_id="5",
                    identifier="mb:unknown",
                    name="Unknown",
                    evidence_refs=("mb-row-unknown",),
                ),
            ),
        )
        reconciliation = build_seed_reconciliation(seed, taxonomy, musicbrainz)
        reconstruction = ReconstructionInputs(
            membership_artifact=VersionedInput(
                artifact_key="musicbrainz-memberships",
                revision="fixture-v1",
                content_sha256="e" * 64,
            ),
            membership_edges=(
                GenreArtistEdge(
                    genre_id="musicbrainz:genre:mb:rock",
                    facet="genre",
                    artist_id="artist:a",
                    weight=2.0,
                    evidence_refs=("edge-rock",),
                ),
                GenreArtistEdge(
                    genre_id="musicbrainz:genre:mb:unknown",
                    facet="genre",
                    artist_id="artist:a",
                    weight=1.0,
                    evidence_refs=("edge-unknown",),
                ),
                GenreArtistEdge(
                    genre_id="musicbrainz:genre:mb:missing",
                    facet="genre",
                    artist_id="artist:a",
                    evidence_refs=("edge-missing",),
                ),
            ),
        )
        model_input, report = public_model_input_from_reconstruction_reconciliation(
            reconstruction, reconciliation
        )
        self.assertEqual(
            {(item.genre_id, item.name) for item in model_input.genres},
            {("1", "Rock"), ("5", "Unknown")},
        )
        self.assertEqual(
            {
                (item.genre_id, item.artist_id, item.value)
                for item in model_input.direct_memberships
            },
            {("1", "artist:a", 2.0), ("5", "artist:a", 1.0)},
        )
        self.assertEqual(
            {item.facet for item in model_input.direct_memberships}, {"musicbrainz_genre"}
        )
        self.assertNotIn("mb:rock", {item.name for item in model_input.genres})
        self.assertEqual(report.accepted_edge_count, 2)
        self.assertEqual(report.rejected_edge_count, 1)
        self.assertIn("missing_identity", report.rejected_edge_refs[0])

    def test_cross_facet_musicbrainz_evidence_reconciles_one_seed_and_bridges_both(self) -> None:
        seed, taxonomy = self._inputs()
        musicbrainz = make_musicbrainz_identity_input(
            "d" * 64,
            (
                MusicBrainzGenreIdentity(
                    source_item_id="5",
                    namespace="musicbrainz_genre_id",
                    identifier="mb:unknown-genre",
                    name="Unknown",
                    evidence_refs=("mb-genre-row",),
                ),
                MusicBrainzGenreIdentity(
                    source_item_id="5",
                    namespace="musicbrainz_tag_name",
                    identifier="tag:unknown",
                    name="Unknown",
                    evidence_refs=("mb-tag-row",),
                ),
            ),
        )
        reconciliation = build_seed_reconciliation(seed, taxonomy, musicbrainz)
        unknown = next(row for row in reconciliation.dispositions if row.source_item_id == "5")
        self.assertEqual(unknown.disposition, "musicbrainz_only")
        self.assertEqual(len(unknown.musicbrainz_identities), 2)

        reconstruction = ReconstructionInputs(
            membership_artifact=VersionedInput(
                artifact_key="musicbrainz-memberships",
                revision="fixture-v1",
                content_sha256="e" * 64,
            ),
            membership_edges=(
                GenreArtistEdge(
                    genre_id="musicbrainz:genre:mb:unknown-genre",
                    facet="genre",
                    artist_id="artist:genre",
                    evidence_refs=("edge-genre",),
                ),
                GenreArtistEdge(
                    genre_id="musicbrainz:tag:tag:unknown",
                    facet="tag",
                    artist_id="artist:tag",
                    evidence_refs=("edge-tag",),
                ),
            ),
        )
        model_input, report = public_model_input_from_reconstruction_reconciliation(
            reconstruction, reconciliation
        )
        self.assertEqual({item.genre_id for item in model_input.genres}, {"5"})
        self.assertEqual(
            {(item.artist_id, item.facet) for item in model_input.direct_memberships},
            {("artist:genre", "musicbrainz_genre"), ("artist:tag", "musicbrainz_tag")},
        )
        self.assertEqual(report.accepted_edge_count, 2)
        self.assertEqual(report.rejected_edge_count, 0)

    def test_same_facet_or_cross_seed_musicbrainz_targets_remain_ambiguous(self) -> None:
        seed, taxonomy = self._inputs()
        same_facet = make_musicbrainz_identity_input(
            "d" * 64,
            (
                MusicBrainzGenreIdentity(
                    source_item_id="5",
                    identifier="mb:unknown-a",
                    name="Unknown",
                    evidence_refs=("mb-row-a",),
                ),
                MusicBrainzGenreIdentity(
                    source_item_id="5",
                    identifier="mb:unknown-b",
                    name="Unknown",
                    evidence_refs=("mb-row-b",),
                ),
            ),
        )
        same_facet_artifact = build_seed_reconciliation(seed, taxonomy, same_facet)
        same_facet_unknown = next(
            row for row in same_facet_artifact.dispositions if row.source_item_id == "5"
        )
        self.assertEqual(same_facet_unknown.disposition, "ambiguous")
        self.assertIn("facet targets", same_facet_unknown.reason or "")

        conflicting_target = make_musicbrainz_identity_input(
            "e" * 64,
            (
                MusicBrainzGenreIdentity(
                    source_item_id="1",
                    identifier="mb:shared",
                    name="Rock",
                    evidence_refs=("mb-row-1",),
                ),
                MusicBrainzGenreIdentity(
                    source_item_id="5",
                    identifier="mb:shared",
                    name="Unknown",
                    evidence_refs=("mb-row-5",),
                ),
            ),
        )
        conflicting_artifact = build_seed_reconciliation(seed, taxonomy, conflicting_target)
        conflicting_rows = {
            row.source_item_id: row
            for row in conflicting_artifact.dispositions
            if row.source_item_id in {"1", "5"}
        }
        self.assertEqual({row.disposition for row in conflicting_rows.values()}, {"ambiguous"})
        self.assertTrue(
            all("multiple stable seeds" in (row.reason or "") for row in conflicting_rows.values())
        )

    def test_coverage_adapter_preserves_facets_and_abstains_without_positive_evidence(self) -> None:
        seed, _taxonomy = self._inputs()
        seed = seed.model_copy(
            update={
                "names": (
                    seed.names[0],
                    seed.names[1].model_copy(update={"name": "Rock Alias"}),
                    *seed.names[2:],
                )
            }
        )
        coverage = CoverageReport(
            research_database="research.sqlite",
            seed_database="seed.sqlite",
            source_key="musicbrainz-research",
            seed_name_count=5,
            imported_genre_count=1,
            imported_tag_count=1,
            imported_tag_name_count=1,
            imported_genre_alias_count=0,
            imported_name_count=1,
            imported_positive_genre_count=1,
            imported_positive_artist_count=2,
            imported_positive_evidence_count=2,
            imported_positive_weight_sum=2.0,
            imported_positive_weight_distribution={"1": 2},
            exact_match_count=1,
            normalized_match_count=1,
            exact_positive_match_count=1,
            normalized_positive_match_count=1,
            distinct_matched_genre_count=1,
            distinct_positive_artist_count=2,
            positive_evidence_count=2,
            positive_weight_sum=2.0,
            positive_weight_distribution={"1": 2},
            facet_metrics={},
            normalized_rule="test",
            matches=(
                CoverageMatch(
                    seed_name="Rock",
                    facet="genre",
                    match_kind="exact",
                    musicbrainz_genre_ids=("mb:g",),
                    positive_artist_count=2,
                    positive_evidence_count=2,
                ),
                CoverageMatch(
                    seed_name="Unknown",
                    facet="tag",
                    match_kind="normalized",
                    musicbrainz_genre_ids=("mb:t",),
                    positive_artist_count=0,
                    positive_evidence_count=0,
                ),
            ),
            unmatched_seed_names=("Electronic", "Canadian Rock", "Rock Alias"),
            runtime_seconds=0.0,
        )
        bridge = musicbrainz_identity_input_from_coverage(coverage, seed)
        self.assertEqual(len(bridge.rows), 1)
        self.assertEqual(bridge.rows[0].namespace, "musicbrainz_genre_id")
        self.assertEqual(bridge.rows[0].source_item_id, "1")
        self.assertEqual(bridge.coverage_report_sha256, bridge.source_artifact_sha256)

    def test_coverage_adapter_rejects_normalized_name_collision(self) -> None:
        seed, _taxonomy = self._inputs()
        coverage = CoverageReport(
            research_database="research.sqlite",
            seed_database="seed.sqlite",
            source_key="musicbrainz-research",
            seed_name_count=5,
            imported_genre_count=0,
            imported_genre_alias_count=0,
            imported_name_count=0,
            imported_positive_genre_count=0,
            imported_positive_artist_count=0,
            imported_positive_evidence_count=0,
            imported_positive_weight_sum=0.0,
            imported_positive_weight_distribution={},
            exact_match_count=0,
            normalized_match_count=0,
            exact_positive_match_count=0,
            normalized_positive_match_count=0,
            distinct_matched_genre_count=0,
            distinct_positive_artist_count=0,
            positive_evidence_count=0,
            positive_weight_sum=0.0,
            positive_weight_distribution={},
            normalized_rule="test",
            matches=(),
            unmatched_seed_names=tuple(item.name for item in seed.names),
            runtime_seconds=0.0,
        )
        with self.assertRaisesRegex(ValueError, "duplicate normalized"):
            musicbrainz_identity_input_from_coverage(coverage, seed)


if __name__ == "__main__":
    unittest.main()
