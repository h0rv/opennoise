from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from opennoise.checkpoints.public_qid_seed_map import (
    InputReceipt,
    PublicQidSeedMap,
    PublicQidSeedMapCoverage,
    PublicQidSeedMapInputs,
    QidSeedMapEntry,
    build_public_qid_seed_map,
    write_public_qid_seed_map,
)
from opennoise.checkpoints.sealed_qid_direct_bridge import (
    BridgeEvidence,
    SealedQidDirectBridgeError,
    SealedQidDirectBridgeInputs,
    _group_memberships,
    _Observation,
    _require_unique_evidence_ids,
    _resolve_selected_qids,
    build_sealed_qid_direct_bridge,
    load_sealed_qid_direct_bridge,
    sealed_qid_direct_bridge_sha256,
    write_sealed_qid_direct_bridge,
)
from opennoise.deployment.static_discovery import StaticDiscoveryPayload

_DATABASE = Path("data/public.sqlite")
_LAYOUT = Path(".cache/semantic-map-layout-v3/artifact.json")
_STATIC = Path(
    ".cache/semantic-map-layout-v3-certification/site/assets/"
    "static-discovery.b4ff2b1bcebb0bb6b1fd63b78caf9a416dbf5bb0c3050c0fa05e434fd0c700e8.json"
)
_SEALED_PRESENT = _DATABASE.is_file() and _LAYOUT.is_file() and _STATIC.is_file()


class SealedQidDirectBridgeTests(unittest.TestCase):
    @staticmethod
    def _observation(*, evidence_id: int, seed_id: str = "item1") -> _Observation:
        return _Observation(
            catalog_genre_id=1,
            genre_qid="Q1",
            seed_id=seed_id,
            artist_catalog_id=2,
            artist_name="Artist",
            artist_musicbrainz_id="00000000-0000-0000-0000-000000000001",
            artist_wikidata_id="Q2",
            evidence=BridgeEvidence(
                evidence_id=evidence_id,
                source_key="wikidata",
                source_record_id=f"record-{evidence_id}",
                source_name="Wikidata",
                policy_key="public",
                policy_version=1,
                provenance_id=1,
            ),
        )

    def test_changed_database_fails_before_receipt_construction(self) -> None:
        with self.assertRaisesRegex(SealedQidDirectBridgeError, "public database"):
            build_sealed_qid_direct_bridge(
                SealedQidDirectBridgeInputs(
                    public_qid_seed_map=Path(__file__),
                    public_database=Path(__file__),
                    base_static_discovery=Path(__file__),
                )
            )

    def test_grouping_preserves_all_evidence_and_rejects_identity_drift(self) -> None:
        memberships = _group_memberships(
            (self._observation(evidence_id=1), self._observation(evidence_id=2))
        )
        self.assertEqual(len(memberships), 1)
        self.assertEqual([item.evidence_id for item in memberships[0].evidence], [1, 2])
        with self.assertRaisesRegex(SealedQidDirectBridgeError, "does not share"):
            _group_memberships(
                (
                    self._observation(evidence_id=1),
                    self._observation(evidence_id=2, seed_id="item2"),
                )
            )

    def test_duplicate_evidence_id_is_rejected_before_grouping(self) -> None:
        with self.assertRaisesRegex(SealedQidDirectBridgeError, "evidence IDs"):
            _require_unique_evidence_ids(
                (self._observation(evidence_id=1), self._observation(evidence_id=1))
            )

    def test_duplicate_qid_or_catalog_resolution_is_rejected_hermetically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "catalog.sqlite"
            connection = sqlite3.connect(database)
            try:
                connection.executescript(
                    """CREATE TABLE entity_identifiers (
                        entity_id INTEGER, identifier_type_id INTEGER,
                        namespace TEXT, normalized_value TEXT
                    );
                    CREATE TABLE identifier_types (id INTEGER, type_key TEXT);
                    CREATE TABLE catalog_entities (id INTEGER, entity_kind TEXT);
                    INSERT INTO identifier_types VALUES (1, 'wikidata_genre_qid');
                    INSERT INTO catalog_entities VALUES (1, 'genre'), (2, 'genre');
                    INSERT INTO entity_identifiers VALUES
                        (1, 1, 'wikidata', 'Q1'),
                        (2, 1, 'wikidata', 'Q1');"""
                )
            finally:
                connection.close()
            receipt = PublicQidSeedMap(
                source_receipts=(
                    InputReceipt(role="public_database", byte_sha256="a" * 64, byte_count=1),
                    InputReceipt(role="canonical_layout", byte_sha256="b" * 64, byte_count=1),
                ),
                seed_links=(),
                ambiguous_label_abstentions=(),
                reverse_qid_abstentions=(),
                mappings=(QidSeedMapEntry(qid="Q1", catalog_genre_id=1, seed_id="item1"),),
                coverage=PublicQidSeedMapCoverage(
                    layout_seed_count=1,
                    positioned_seed_count=1,
                    unique_seed_qid_link_count=1,
                    ambiguous_label_count=0,
                    positioned_seed_qid_link_count=1,
                    positioned_qid_count=1,
                    reverse_qid_abstention_count=0,
                    one_to_one_positioned_qid_count=1,
                ),
                output_sha256="c" * 64,
            )
            with self.assertRaisesRegex(SealedQidDirectBridgeError, "exactly one"):
                _resolve_selected_qids(database, receipt)

    def test_base_seed_collision_is_rejected_before_observation_replay(self) -> None:
        base = StaticDiscoveryPayload.model_validate(
            {
                "revision": "static-direct-discovery-v1",
                "availability": "ready",
                "genres": (
                    {
                        "node_id": "item1",
                        "catalog_genre_id": 2,
                        "catalog_genre_name": "base",
                        "binding": "exact_casefolded_label",
                        "artist_ids": (),
                    },
                ),
            }
        )
        qid_map = SimpleNamespace(output_sha256="a" * 64)
        with (
            patch("opennoise.checkpoints.sealed_qid_direct_bridge._require_hash"),
            patch(
                "opennoise.checkpoints.sealed_qid_direct_bridge._load_pinned_qid_map",
                return_value=qid_map,
            ),
            patch(
                "opennoise.checkpoints.sealed_qid_direct_bridge._load_base_static",
                return_value=base,
            ),
            patch(
                "opennoise.checkpoints.sealed_qid_direct_bridge._resolve_selected_qids",
                return_value={1: ("Q1", "item1")},
            ),
            self.assertRaisesRegex(SealedQidDirectBridgeError, "seed is already"),
        ):
            build_sealed_qid_direct_bridge(
                SealedQidDirectBridgeInputs(
                    public_qid_seed_map=Path("map"),
                    public_database=Path("database"),
                    base_static_discovery=Path("static"),
                )
            )

    @unittest.skipUnless(_SEALED_PRESENT, "sealed inputs are not present")
    def test_real_pinned_replay_is_direct_authorized_and_base_disjoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            map_path = Path(directory) / "qid-map.json"
            qid_map = build_public_qid_seed_map(
                PublicQidSeedMapInputs(public_database=_DATABASE, canonical_layout=_LAYOUT)
            )
            write_public_qid_seed_map(qid_map, map_path)
            receipt = build_sealed_qid_direct_bridge(
                SealedQidDirectBridgeInputs(
                    public_qid_seed_map=map_path,
                    public_database=_DATABASE,
                    base_static_discovery=_STATIC,
                )
            )
        self.assertEqual(receipt.coverage.positioned_genre_count, 84)
        self.assertEqual(receipt.coverage.grouped_membership_count, 862)
        self.assertEqual(receipt.coverage.direct_observation_count, 959)
        self.assertEqual(receipt.coverage.artist_count, 536)
        self.assertEqual(receipt.coverage.net_new_artist_count, 118)
        self.assertEqual(receipt.output_sha256, sealed_qid_direct_bridge_sha256(receipt))
        self.assertTrue(all(item.evidence for item in receipt.memberships))
        self.assertTrue(
            all(
                evidence.method_key == "wikidata_p136" and evidence.method_version == "1"
                for membership in receipt.memberships
                for evidence in membership.evidence
            )
        )

    @unittest.skipUnless(_SEALED_PRESENT, "sealed inputs are not present")
    def test_writer_is_no_replace_and_loader_rejects_same_count_row_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            map_path = Path(directory) / "qid-map.json"
            write_public_qid_seed_map(
                build_public_qid_seed_map(
                    PublicQidSeedMapInputs(public_database=_DATABASE, canonical_layout=_LAYOUT)
                ),
                map_path,
            )
            receipt = build_sealed_qid_direct_bridge(
                SealedQidDirectBridgeInputs(
                    public_qid_seed_map=map_path,
                    public_database=_DATABASE,
                    base_static_discovery=_STATIC,
                )
            )
            output = Path(directory) / "bridge.json"
            write_sealed_qid_direct_bridge(receipt, output)
            self.assertEqual(load_sealed_qid_direct_bridge(output), receipt)
            with self.assertRaisesRegex(SealedQidDirectBridgeError, "refusing to overwrite"):
                write_sealed_qid_direct_bridge(receipt, output)
            changed = receipt.memberships[0].model_copy(update={"artist_name": "tampered"})
            drifted = receipt.model_copy(
                update={
                    "memberships": (changed, *receipt.memberships[1:]),
                    "output_sha256": "0" * 64,
                }
            )
            drifted = drifted.model_copy(
                update={"output_sha256": sealed_qid_direct_bridge_sha256(drifted)}
            )
            drifted_path = Path(directory) / "drifted.json"
            drifted_path.write_bytes(drifted.model_dump_json().encode())
            with self.assertRaisesRegex(SealedQidDirectBridgeError, "output hash"):
                load_sealed_qid_direct_bridge(drifted_path)

    def test_construction_does_not_import_old_bridge_or_reconciliation(self) -> None:
        source = Path("src/opennoise/checkpoints/sealed_qid_direct_bridge.py").read_text()
        self.assertNotIn("public_direct_bridge_candidate", source)
        self.assertNotIn("seed-reconciliation", source)
        self.assertNotIn("public_direct_production_bridge", source)
