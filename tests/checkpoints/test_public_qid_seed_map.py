from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from opennoise.checkpoints.public_qid_seed_map import (
    PublicQidIdentity,
    PublicQidSeedMapError,
    PublicQidSeedMapInputs,
    _load_public_labels,
    _resolve_positioned_qids,
    _resolve_seed_links,
    build_public_qid_seed_map,
    load_public_qid_seed_map,
    public_qid_seed_map_sha256,
    write_public_qid_seed_map,
)

_INPUTS = PublicQidSeedMapInputs(
    public_database=Path("data/public.sqlite"),
    canonical_layout=Path(".cache/semantic-map-layout-v3/artifact.json"),
)
_SEALED_INPUTS_PRESENT = _INPUTS.public_database.is_file() and _INPUTS.canonical_layout.is_file()


class PublicQidSeedMapTests(unittest.TestCase):
    @unittest.skipUnless(_SEALED_INPUTS_PRESENT, "sealed public inputs are not present")
    def test_pinned_receipt_preserves_all_ambiguity_boundaries(self) -> None:
        receipt = build_public_qid_seed_map(_INPUTS)

        self.assertEqual(receipt.coverage.layout_seed_count, 6291)
        self.assertEqual(receipt.coverage.positioned_seed_count, 2945)
        self.assertEqual(receipt.coverage.unique_seed_qid_link_count, 441)
        self.assertEqual(receipt.coverage.ambiguous_label_count, 37)
        self.assertEqual(receipt.coverage.positioned_seed_qid_link_count, 409)
        self.assertEqual(receipt.coverage.positioned_qid_count, 380)
        self.assertEqual(receipt.coverage.reverse_qid_abstention_count, 25)
        self.assertEqual(receipt.coverage.one_to_one_positioned_qid_count, 355)
        self.assertEqual(len(receipt.mappings), 355)
        self.assertEqual(receipt.output_sha256, public_qid_seed_map_sha256(receipt))
        self.assertFalse(receipt.experimental_reconciliation_used)
        self.assertFalse(receipt.static_output_written)
        self.assertTrue(
            all(item.binding == "one_to_one_qid_position_binding" for item in receipt.mappings)
        )

    def test_same_identity_duplicate_is_one_candidate_but_distinct_targets_abstain(self) -> None:
        rock = PublicQidIdentity(qid="Q1", catalog_genre_id=1)
        metal = PublicQidIdentity(qid="Q2", catalog_genre_id=2)
        links, ambiguous = _resolve_seed_links(
            (("item1", "Röck"), ("item2", "metal")),
            {
                "rock": ((rock, "alias"), (rock, "canonical")),
                "metal": ((metal, "alias"), (rock, "canonical")),
            },
        )

        self.assertEqual([(item.seed_id, item.qid) for item in links], [("item1", "Q1")])
        self.assertEqual(ambiguous[0].normalized_label, "metal")
        self.assertEqual(ambiguous[0].identities, (rock, metal))

    def test_unplaced_and_multi_seed_qids_are_not_auto_mapped(self) -> None:
        links, ambiguous = _resolve_seed_links(
            (("item1", "one"), ("item2", "one"), ("item3", "two")),
            {
                "one": ((PublicQidIdentity(qid="Q1", catalog_genre_id=1), "canonical"),),
                "two": ((PublicQidIdentity(qid="Q2", catalog_genre_id=2), "canonical"),),
            },
        )
        mappings, abstentions = _resolve_positioned_qids(links, {"item1", "item2"})

        self.assertEqual(ambiguous, ())
        self.assertEqual(mappings, ())
        self.assertEqual(abstentions[0].qid, "Q1")
        self.assertEqual(abstentions[0].seed_ids, ("item1", "item2"))

    def test_changed_sealed_input_bytes_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            changed_database = Path(directory) / "public.sqlite"
            changed_database.write_bytes(b"not a sealed database")
            with self.assertRaisesRegex(PublicQidSeedMapError, "public database hash"):
                build_public_qid_seed_map(
                    _INPUTS.model_copy(update={"public_database": changed_database})
                )

            changed_layout = Path(directory) / "layout.json"
            changed_layout.write_bytes(b"not a sealed layout")
            with self.assertRaisesRegex(PublicQidSeedMapError, "canonical layout hash"):
                build_public_qid_seed_map(
                    _INPUTS.model_copy(update={"canonical_layout": changed_layout})
                )

    @unittest.skipUnless(_SEALED_INPUTS_PRESENT, "sealed public inputs are not present")
    def test_receipt_write_never_replaces_and_read_rejects_same_count_drift(self) -> None:
        receipt = build_public_qid_seed_map(_INPUTS)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receipt.json"
            write_public_qid_seed_map(receipt, output)
            self.assertEqual(load_public_qid_seed_map(output), receipt)
            with self.assertRaisesRegex(PublicQidSeedMapError, "refusing to overwrite"):
                write_public_qid_seed_map(receipt, output)

            changed_mapping = receipt.mappings[0].model_copy(update={"seed_id": "item999999"})
            drifted = receipt.model_copy(
                update={
                    "mappings": (changed_mapping, *receipt.mappings[1:]),
                    "output_sha256": "0" * 64,
                }
            )
            drifted = drifted.model_copy(
                update={"output_sha256": public_qid_seed_map_sha256(drifted)}
            )
            drifted_path = Path(directory) / "same-count-drift.json"
            drifted_path.write_bytes(drifted.model_dump_json().encode())
            with self.assertRaisesRegex(PublicQidSeedMapError, "selection hash"):
                load_public_qid_seed_map(drifted_path)

    def test_local_only_alias_is_not_admissible_for_an_otherwise_public_genre(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "catalog.sqlite"
            database = sqlite3.connect(database_path)
            try:
                database.executescript(
                    """
                    CREATE TABLE genres (id INTEGER PRIMARY KEY, entity_kind TEXT, name TEXT);
                    CREATE TABLE entity_identifiers (
                        entity_id INTEGER, identifier_type_id INTEGER, namespace TEXT,
                        normalized_value TEXT, provenance_id INTEGER
                    );
                    CREATE TABLE identifier_types (id INTEGER PRIMARY KEY, type_key TEXT);
                    CREATE TABLE entity_provenance (entity_id INTEGER, provenance_id INTEGER);
                    CREATE TABLE provenance_records (
                        id INTEGER PRIMARY KEY, source_id INTEGER, policy_id INTEGER
                    );
                    CREATE TABLE data_sources (id INTEGER PRIMARY KEY, license_name TEXT);
                    CREATE TABLE rights_policies (id INTEGER PRIMARY KEY, local_only INTEGER);
                    CREATE TABLE rights_policy_permissions (
                        policy_id INTEGER, use_kind TEXT, decision TEXT
                    );
                    CREATE TABLE rights_policy_seals (policy_id INTEGER);
                    CREATE VIEW active_rights_policy_permissions AS
                        SELECT permission.policy_id, permission.use_kind, permission.decision
                        FROM rights_policy_permissions AS permission
                        JOIN rights_policy_seals AS seal ON seal.policy_id = permission.policy_id;
                    CREATE TABLE entity_names (entity_id INTEGER, name TEXT, provenance_id INTEGER);
                    INSERT INTO genres VALUES
                        (1, 'genre', 'Public Name'), (2, 'genre', 'Excluded QID');
                    INSERT INTO identifier_types VALUES (1, 'wikidata_genre_qid');
                    INSERT INTO entity_identifiers VALUES
                        (1, 1, 'wikidata', 'Q1', 1), (2, 1, 'wikidata', 'Q2', 2);
                    INSERT INTO data_sources VALUES (1, 'CC0-1.0'), (2, 'CC0-1.0');
                    INSERT INTO rights_policies VALUES (1, 0), (2, 1);
                    INSERT INTO provenance_records VALUES (1, 1, 1), (2, 2, 2);
                    INSERT INTO entity_provenance VALUES (1, 1), (2, 1);
                    INSERT INTO rights_policy_seals VALUES (1), (2);
                    INSERT INTO rights_policy_permissions VALUES
                        (1, 'export', 'allow'), (1, 'display', 'allow'),
                        (2, 'export', 'allow'), (2, 'display', 'allow');
                    INSERT INTO entity_names VALUES
                        (1, 'Public Name', 1), (1, 'Private Alias', 2),
                        (2, 'Excluded QID', 1);
                    """
                )
            finally:
                database.close()
            labels = _load_public_labels(database_path)

            self.assertIn("public name", labels)
            self.assertNotIn("private alias", labels)
            self.assertNotIn("excluded qid", labels)

            database = sqlite3.connect(database_path)
            try:
                database.executescript(
                    """
                    INSERT INTO genres VALUES (3, 'genre', 'Duplicate QID');
                    INSERT INTO entity_identifiers VALUES (3, 1, 'wikidata', 'Q1', 1);
                    INSERT INTO entity_provenance VALUES (3, 1);
                    INSERT INTO entity_names VALUES (3, 'Duplicate QID', 1);
                    """
                )
            finally:
                database.close()
            with self.assertRaisesRegex(PublicQidSeedMapError, "exactly one catalog genre"):
                _load_public_labels(database_path)

    def test_positioned_resolution_rejects_a_qid_with_two_catalog_identities(self) -> None:
        links, _ = _resolve_seed_links(
            (("item1", "one"), ("item2", "two")),
            {
                "one": ((PublicQidIdentity(qid="Q1", catalog_genre_id=1), "canonical"),),
                "two": ((PublicQidIdentity(qid="Q1", catalog_genre_id=2), "canonical"),),
            },
        )

        with self.assertRaisesRegex(PublicQidSeedMapError, "exactly one catalog genre"):
            _resolve_positioned_qids(links, {"item1", "item2"})

    def test_construction_module_has_no_reconciliation_or_candidate_input(self) -> None:
        source = Path("src/opennoise/checkpoints/public_qid_seed_map.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("seed-reconciliation", source)
        self.assertNotIn("public_direct_bridge_candidate", source)
        self.assertNotIn("static_discovery", source)
