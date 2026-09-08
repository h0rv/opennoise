from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from hashlib import sha256
from pathlib import Path

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
from musix.storage import LocalObjectStore, ObjectKey
from musix.taxonomy_relation_expansion import (
    ExactMusicBrainzGenreQidMapping,
    TaxonomyRelationEvaluationInputs,
    TaxonomyRelationExpansionPolicy,
    TaxonomyRelationHoldoutPolicy,
    TaxonomyRelationObservation,
    build_taxonomy_relation_expansion,
    build_taxonomy_relation_feed,
    catalog_wikidata_p279_feed,
    evaluate_taxonomy_relation_expansion,
    merge_taxonomy_relation_feeds,
    relation_source_custody_receipt,
    split_taxonomy_relation_feed_for_holdout,
    verify_taxonomy_relation_expansion,
)


def _taxonomy() -> GenreSeedPublicTaxonomyArtifact:
    names = tuple(
        SeedName(source_item_id=f"item{number}", source_external_id=f"legacy:{number}", name=name)
        for number, name in enumerate(("One", "Two", "Three"), start=1)
    )
    seed = SeedInput(
        source_id="legacy", source_content_sha256="a" * 64, artifact_sha256="b" * 64, names=names
    )
    return GenreSeedPublicTaxonomyArtifact(
        seed_input=seed,
        public_catalog=PublicCatalogInput(database_sha256="c" * 64, source_licenses=("CC0-1.0",)),
        config=PublicTaxonomyConfig(expected_seed_count=3),
        calibration=CompositionCalibration(
            eligible_exact_name_count=3,
            observed_taxonomy_path_count=2,
            missing_taxonomy_path_count=1,
            laplace_precision=0.5,
            status="available",
            minimum_examples=1,
        ),
        inferences=tuple(
            SeedTaxonomyInference(
                source_item_id=name.source_item_id,
                source_external_id=name.source_external_id,
                seed_name=name.name,
                normalized_name=name.name.casefold(),
                status="canonical_exact",
                exact_candidates=(
                    PublicTaxonomyNode(
                        catalog_id=f"wikidata:genre:Q{number}",
                        name=name.name,
                        match_kind="canonical",
                    ),
                ),
                structural_confidence=1.0,
            )
            for number, name in enumerate(names, start=1)
        ),
        coverage=TaxonomyCoverageReport(
            seed_count=3,
            canonical_exact_count=3,
            canonical_alias_count=0,
            compositional_anchor_count=0,
            ambiguous_exact_count=0,
            ambiguous_compositional_count=0,
            abstained_count=0,
            covered_for_review_count=3,
            canonical_membership_count=3,
        ),
        output_sha256="d" * 64,
    )


def _feed(root: Path):  # noqa: ANN202
    catalog = root / "catalog.sqlite"
    _write_catalog(catalog, rows=((10, 1, 2), (12, 3, 1)))
    store = LocalObjectStore(root / "objects")
    catalog_feed = catalog_wikidata_p279_feed(catalog, store=store)
    raw = root / "cached-source.json"
    raw.write_text('{"source":"fixture"}\n', encoding="utf-8")
    response = sha256(raw.read_bytes()).hexdigest()
    source = store.push(raw, ObjectKey(value=f"fixture-source/sha256/{response}.json"))
    review_feed = build_taxonomy_relation_feed(
        (relation_source_custody_receipt(response, source),),
        (
            ExactMusicBrainzGenreQidMapping(
                musicbrainz_genre_id="mb:three",
                wikidata_qid="Q3",
                evidence_ref="mb-qid:three",
                source_response_sha256=response,
            ),
            ExactMusicBrainzGenreQidMapping(
                musicbrainz_genre_id="mb:one",
                wikidata_qid="Q1",
                evidence_ref="mb-qid:one",
                source_response_sha256=response,
            ),
        ),
        (
            TaxonomyRelationObservation(
                observation_id="wd:2-3",
                source="wikidata",
                relation_kind="wikidata_p361_part_of",
                child_source_id="Q2",
                parent_source_id="Q3",
                evidence_ref="wd:Q2:P361:Q3",
                source_response_sha256=response,
            ),
            TaxonomyRelationObservation(
                observation_id="mb:3-1-review",
                source="musicbrainz",
                relation_kind="musicbrainz_related",
                child_source_id="mb:three",
                parent_source_id="mb:one",
                evidence_ref="mb:three:subgenre-of:one",
                source_response_sha256=response,
            ),
        ),
    )
    return merge_taxonomy_relation_feeds((catalog_feed, review_feed)), store


def _write_catalog(path: Path, *, rows: tuple[tuple[int, int, int], ...]) -> None:
    with closing(sqlite3.connect(path)) as db:
        db.executescript(
            """
            CREATE TABLE identifier_types (id INTEGER PRIMARY KEY, type_key TEXT NOT NULL);
            CREATE TABLE entity_identifiers (entity_id INTEGER, identifier_type_id INTEGER,
                normalized_value TEXT);
            CREATE TABLE genre_hierarchy (relation_id INTEGER, child_genre_id INTEGER,
                parent_genre_id INTEGER, provenance_id INTEGER);
            CREATE TABLE provenance_records (id INTEGER PRIMARY KEY, source_id INTEGER,
                policy_id INTEGER);
            CREATE TABLE data_sources (id INTEGER PRIMARY KEY, license_name TEXT);
            CREATE TABLE rights_policies (id INTEGER PRIMARY KEY, local_only INTEGER);
            CREATE TABLE rights_policy_permissions (policy_id INTEGER, use_kind TEXT,
                decision TEXT);
            INSERT INTO identifier_types VALUES (1, 'wikidata_genre_qid');
            INSERT INTO entity_identifiers VALUES (1, 1, 'Q1'), (2, 1, 'Q2'), (3, 1, 'Q3');
            INSERT INTO data_sources VALUES (1, 'CC0-1.0'), (2, 'proprietary');
            INSERT INTO rights_policies VALUES (1, 0);
            INSERT INTO rights_policy_permissions VALUES (1, 'export', 'allow');
            INSERT INTO provenance_records VALUES (1, 1, 1), (2, 2, 1);
            """
        )
        db.executemany("INSERT INTO genre_hierarchy VALUES (?, ?, ?, 1)", rows)
        db.commit()


def _policy_hiding_only(
    pair: tuple[str, str], seed_ids: frozenset[str]
) -> TaxonomyRelationHoldoutPolicy:
    """Choose fixture policy values that hide one edge and no fixture seed nodes."""
    for modulus in range(2, 1_001):
        target = (
            int.from_bytes(sha256(f"{pair[0]}\x00{pair[1]}".encode()).digest()[:8], "big") % modulus
        )
        if all(
            target
            != int.from_bytes(sha256(f"{other[0]}\x00{other[1]}".encode()).digest()[:8], "big")
            % modulus
            for other in {("item3", "item1")}
        ):
            occupied = {
                int.from_bytes(sha256(seed.encode()).digest()[:8], "big") % modulus
                for seed in seed_ids
            }
            node_remainder = next(value for value in range(modulus) if value not in occupied)
            return TaxonomyRelationHoldoutPolicy(
                edge_modulus=modulus,
                edge_remainder=target,
                node_modulus=modulus,
                node_remainder=node_remainder,
            )
    raise AssertionError("fixture could not select a one-edge holdout policy")


class TaxonomyRelationExpansionTests(unittest.TestCase):
    def test_facts_reviews_exact_mappings_and_cycles_stay_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            feed, store = _feed(Path(temporary))
            artifact = build_taxonomy_relation_expansion(
                _taxonomy(),
                feed,
                TaxonomyRelationExpansionPolicy(expected_seed_count=3),
                source_store=store,
            )
            rows = {(edge.child_seed_id, edge.parent_seed_id): edge for edge in artifact.edges}
            self.assertEqual(rows[("item1", "item2")].disposition, "accepted_factual")
            self.assertEqual(rows[("item3", "item1")].disposition, "accepted_factual")
            self.assertEqual(rows[("item2", "item3")].disposition, "abstained_cycle")
            self.assertEqual(
                rows[("item2", "item3")].review_evidence[0].relation_kind,
                "wikidata_p361_part_of",
            )
            self.assertEqual(artifact.coverage.accepted_factual_edge_count, 2)
            self.assertEqual(artifact.coverage.cycle_abstained_edge_count, 1)
            self.assertEqual(artifact.coverage.factual_isolated_seed_reduction, 3)
            verify_taxonomy_relation_expansion(artifact, source_store=store)

    def test_holdout_split_blocks_hidden_source_leakage_and_precision_stays_honest(self) -> None:
        taxonomy = _taxonomy()
        with tempfile.TemporaryDirectory() as temporary:
            feed, store = _feed(Path(temporary))
            seed_ids = frozenset({"item1", "item2", "item3"})
            reference = frozenset({("item1", "item2"), ("item3", "item1")})
            policy = _policy_hiding_only(("item1", "item2"), seed_ids)
            training = split_taxonomy_relation_feed_for_holdout(
                taxonomy, feed, reference_factual_edges=reference, policy=policy
            )
            artifact = build_taxonomy_relation_expansion(
                taxonomy,
                training,
                TaxonomyRelationExpansionPolicy(expected_seed_count=3),
                source_store=store,
            )
            report = evaluate_taxonomy_relation_expansion(
                artifact,
                taxonomy,
                TaxonomyRelationEvaluationInputs(
                    full_relation_feed=feed,
                    reference_factual_edges=reference,
                    holdout_policy=policy,
                    source_store=store,
                ),
            )
            self.assertEqual(report.precision_status, "not_evaluable_without_negatives")
            self.assertIsNone(report.precision)
            self.assertEqual(report.hidden_factual_edge_count, 1)
            self.assertEqual(report.recovered_hidden_factual_edge_count, 0)
            self.assertEqual(report.training_relation_feed_output_sha256, training.output_sha256)
            self.assertGreaterEqual(report.isolated_seed_reduction, 0)
            hidden = next(
                row
                for row in feed.observations
                if row.relation_kind == "wikidata_p279_subclass_of" and row.child_source_id == "Q1"
            ).model_copy(update={"evidence_ref": "mutated-hidden"})
            mutated = build_taxonomy_relation_feed(
                feed.source_custodies,
                feed.musicbrainz_qid_mappings,
                tuple(
                    hidden if row.observation_id == hidden.observation_id else row
                    for row in feed.observations
                ),
            )
            mutated_training = split_taxonomy_relation_feed_for_holdout(
                taxonomy, mutated, reference_factual_edges=reference, policy=policy
            )
            self.assertEqual(mutated_training.output_sha256, training.output_sha256)
            self.assertEqual(
                build_taxonomy_relation_expansion(
                    taxonomy,
                    mutated_training,
                    TaxonomyRelationExpansionPolicy(expected_seed_count=3),
                    source_store=store,
                ).output_sha256,
                artifact.output_sha256,
            )

    def test_catalog_extractor_only_reads_cc0_exportable_hierarchy_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "catalog.sqlite"
            with closing(sqlite3.connect(path)) as db:
                db.executescript(
                    """
                    CREATE TABLE identifier_types (id INTEGER PRIMARY KEY, type_key TEXT NOT NULL);
                    CREATE TABLE entity_identifiers (entity_id INTEGER, identifier_type_id INTEGER,
                        normalized_value TEXT);
                    CREATE TABLE genre_hierarchy (relation_id INTEGER, child_genre_id INTEGER,
                        parent_genre_id INTEGER, provenance_id INTEGER);
                    CREATE TABLE provenance_records (id INTEGER PRIMARY KEY, source_id INTEGER,
                        policy_id INTEGER);
                    CREATE TABLE data_sources (id INTEGER PRIMARY KEY, license_name TEXT);
                    CREATE TABLE rights_policies (id INTEGER PRIMARY KEY, local_only INTEGER);
                    CREATE TABLE rights_policy_permissions (policy_id INTEGER, use_kind TEXT,
                        decision TEXT);
                    INSERT INTO identifier_types VALUES (1, 'wikidata_genre_qid');
                    INSERT INTO entity_identifiers VALUES (1, 1, 'Q1'), (2, 1, 'Q2');
                    INSERT INTO data_sources VALUES (1, 'CC0-1.0'), (2, 'proprietary');
                    INSERT INTO rights_policies VALUES (1, 0);
                    INSERT INTO rights_policy_permissions VALUES (1, 'export', 'allow');
                    INSERT INTO provenance_records VALUES (1, 1, 1), (2, 2, 1);
                    INSERT INTO genre_hierarchy VALUES (10, 1, 2, 1), (11, 2, 1, 2);
                    """
                )
            feed = catalog_wikidata_p279_feed(path, store=LocalObjectStore(root / "objects"))
            self.assertEqual(len(feed.observations), 1)
            self.assertEqual(feed.observations[0].relation_kind, "wikidata_p279_subclass_of")

    def test_generic_envelope_cannot_promote_made_up_factual_relation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "unrelated.json"
            raw.write_text('{"unrelated": true}\n', encoding="utf-8")
            source_hash = sha256(raw.read_bytes()).hexdigest()
            store = LocalObjectStore(root / "objects")
            write = store.push(raw, ObjectKey(value="fixtures/unrelated.json"))
            feed = build_taxonomy_relation_feed(
                (relation_source_custody_receipt(source_hash, write),),
                (),
                (
                    TaxonomyRelationObservation(
                        observation_id="forged:Q1:P279:Q2",
                        source="wikidata",
                        relation_kind="wikidata_p279_subclass_of",
                        child_source_id="Q1",
                        parent_source_id="Q2",
                        evidence_ref="forged",
                        source_response_sha256=source_hash,
                    ),
                ),
            )
            with self.assertRaisesRegex(ValueError, "require replayable catalog_wikidata_p279"):
                build_taxonomy_relation_expansion(
                    _taxonomy(),
                    feed,
                    TaxonomyRelationExpansionPolicy(expected_seed_count=3),
                    source_store=store,
                )

    def test_catalog_row_binding_rejects_a_fact_not_in_the_receipted_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            feed, store = _feed(Path(temporary))
            factual = next(
                row
                for row in feed.observations
                if row.relation_kind == "wikidata_p279_subclass_of" and row.child_source_id == "Q1"
            )
            forged = factual.model_copy(update={"parent_source_id": "Q3"})
            forged_feed = build_taxonomy_relation_feed(
                feed.source_custodies,
                feed.musicbrainz_qid_mappings,
                tuple(
                    forged if row.observation_id == factual.observation_id else row
                    for row in feed.observations
                ),
            )
            with self.assertRaisesRegex(ValueError, "does not replay from its catalog source row"):
                build_taxonomy_relation_expansion(
                    _taxonomy(),
                    forged_feed,
                    TaxonomyRelationExpansionPolicy(expected_seed_count=3),
                    source_store=store,
                )

    def test_source_substitution_and_unreceipted_feed_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            feed, _trusted_store = _feed(root)
            substituted_store = LocalObjectStore(root / "substituted-objects")
            replacement = root / "replacement.json"
            replacement.write_text('{"source":"substituted"}\n', encoding="utf-8")
            custody = feed.source_custodies[0]
            substituted_store.push(replacement, custody.object_key)
            with self.assertRaisesRegex(ValueError, "does not match its custody receipt"):
                build_taxonomy_relation_expansion(
                    _taxonomy(),
                    feed,
                    TaxonomyRelationExpansionPolicy(expected_seed_count=3),
                    source_store=substituted_store,
                )
            raw_feed = feed.model_construct(
                source_custodies=(),
                musicbrainz_qid_mappings=feed.musicbrainz_qid_mappings,
                observations=feed.observations,
                output_sha256=feed.output_sha256,
            )
            with self.assertRaisesRegex(ValueError, "unreceipted"):
                build_taxonomy_relation_expansion(
                    _taxonomy(),
                    raw_feed,
                    TaxonomyRelationExpansionPolicy(expected_seed_count=3),
                    source_store=LocalObjectStore(root / "empty-objects"),
                )


if __name__ == "__main__":
    unittest.main()
