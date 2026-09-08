from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from musix.genre_hierarchy_candidates import GenreHierarchyCandidatePublicationReceipt
from musix.storage import LocalObjectStore, ObjectKey
from musix.taxonomy_relation_expansion import (
    TaxonomyRelationExpansionPolicy,
    build_taxonomy_relation_expansion,
)
from musix.taxonomy_relation_hierarchy_overlay import (
    OverlayBaseInputs,
    build_taxonomy_relation_hierarchy_overlay,
)
from tests.test_taxonomy_relation_expansion import _feed, _taxonomy


class TaxonomyRelationHierarchyOverlayTests(unittest.TestCase):
    def test_overlay_dedupes_upgrades_rejects_cycles_and_detects_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "base.json"
            document = {
                "revision": "genre-hierarchy-candidates-v1",
                "seed_reconciliation_output_sha256": "b" * 64,
                "taxonomy_output_sha256": "c" * 64,
                "taxonomy_relation_expansion_output_sha256": None,
                "public_model_input_sha256": "d" * 64,
                "policy_sha256": "e" * 64,
                "policy": {},
                "seed_coverage": [],
                "candidates": [
                    {
                        "child_genre_id": "item1",
                        "parent_genre_id": "item2",
                        "status": "review",
                    },
                    {
                        "child_genre_id": "item2",
                        "parent_genre_id": "item3",
                        "status": "accepted",
                    },
                    {
                        "child_genre_id": "item3",
                        "parent_genre_id": "item1",
                        "status": "accepted",
                    },
                ],
                "coverage": {},
                "historical_data_used_for_construction": False,
                "parent_artists_inherited_into_children": False,
            }
            logical = hashlib.sha256(
                json.dumps(
                    document, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                ).encode()
            ).hexdigest()
            base.write_text(json.dumps(document | {"output_sha256": logical}), encoding="utf-8")
            store = LocalObjectStore(root / "base-objects")
            write = store.push(base, ObjectKey(value="base.json"))
            receipt = GenreHierarchyCandidatePublicationReceipt(
                artifact=write,
                artifact_sha256=write.sha256,
                logical_output_sha256=logical,
            )
            feed, relation_store = _feed(root)
            relation = build_taxonomy_relation_expansion(
                _taxonomy(),
                feed,
                TaxonomyRelationExpansionPolicy(expected_seed_count=3),
                source_store=relation_store,
            )
            overlay = build_taxonomy_relation_hierarchy_overlay(
                OverlayBaseInputs(
                    hierarchy_path=base,
                    receipt=receipt,
                    receipt_sha256=hashlib.sha256(receipt.model_dump_json().encode()).hexdigest(),
                    expected_receipt_sha256=hashlib.sha256(
                        receipt.model_dump_json().encode()
                    ).hexdigest(),
                    object_store=store,
                ),
                relation,
                relation_source_store=relation_store,
            )
            self.assertEqual(len(overlay.edges), 0)
            self.assertEqual(overlay.net_new_accepted_count, 0)
            with self.assertRaises(ValueError):
                build_taxonomy_relation_hierarchy_overlay(
                    OverlayBaseInputs(
                        hierarchy_path=base,
                        receipt=receipt,
                        receipt_sha256=hashlib.sha256(
                            receipt.model_dump_json().encode()
                        ).hexdigest(),
                        expected_receipt_sha256="0" * 64,
                        object_store=store,
                    ),
                    relation,
                    relation_source_store=relation_store,
                )
            (root / "base-objects" / "base.json").write_text("substituted", encoding="utf-8")
            with self.assertRaises(ValueError):
                build_taxonomy_relation_hierarchy_overlay(
                    OverlayBaseInputs(
                        hierarchy_path=base,
                        receipt=receipt,
                        receipt_sha256=hashlib.sha256(
                            receipt.model_dump_json().encode()
                        ).hexdigest(),
                        expected_receipt_sha256=hashlib.sha256(
                            receipt.model_dump_json().encode()
                        ).hexdigest(),
                        object_store=store,
                    ),
                    relation,
                    relation_source_store=relation_store,
                )
            base.write_text("tampered", encoding="utf-8")
            with self.assertRaises(ValueError):
                build_taxonomy_relation_hierarchy_overlay(
                    OverlayBaseInputs(
                        hierarchy_path=base,
                        receipt=receipt,
                        receipt_sha256=hashlib.sha256(
                            receipt.model_dump_json().encode()
                        ).hexdigest(),
                        expected_receipt_sha256=hashlib.sha256(
                            receipt.model_dump_json().encode()
                        ).hexdigest(),
                        object_store=store,
                    ),
                    relation,
                    relation_source_store=relation_store,
                )


if __name__ == "__main__":
    unittest.main()
