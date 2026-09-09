from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

from musix.evidence.evidence_frontier import (
    AllSeedEvidenceFrontierArtifact,
    EvidenceFrontierCoverage,
    EvidenceFrontierGate,
    EvidenceFrontierReceipt,
)
from musix.storage import LocalObjectStore, ObjectKey
from musix.taxonomy.relations.taxonomy_relation_frontier_v6 import (
    FrontierV6Inputs,
    build_taxonomy_relation_frontier_v6,
)
from musix.taxonomy.relations.taxonomy_relation_hierarchy_overlay import (
    TaxonomyRelationHierarchyOverlay,
    TaxonomyRelationHierarchyOverlayEdge,
    TaxonomyRelationHierarchyOverlayReceipt,
)
from tests.evidence.test_evidence_frontier import EvidenceFrontierTests


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _coverage() -> EvidenceFrontierCoverage:
    return EvidenceFrontierCoverage(
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
        observed_musicbrainz_only_seed_count=0,
        observed_wikidata_only_seed_count=0,
        observed_cross_source_seed_count=0,
        listenbrainz_review_candidate_seed_count=0,
        listenbrainz_review_candidate_count=0,
        listenbrainz_review_overlap_direct_observed_seed_count=0,
        listenbrainz_review_only_seed_count=0,
        direct_observed_only_seed_count=0,
        direct_observed_or_listenbrainz_review_seed_count=0,
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
    )


class TaxonomyRelationFrontierV6Tests(unittest.TestCase):
    def _inputs(self, root: Path) -> tuple[FrontierV6Inputs, EvidenceFrontierCoverage]:
        rows = tuple(
            EvidenceFrontierTests()._row(number)  # noqa: SLF001 - shared sealed-v5 fixture row
            for number in range(1, 6292)
        )
        coverage = _coverage()
        v5 = AllSeedEvidenceFrontierArtifact(
            seed_reconciliation_output_sha256="a" * 64,
            taxonomy_expansion_output_sha256="b" * 64,
            public_model_input_sha256="c" * 64,
            peer_similarity_output_sha256="d" * 64,
            hierarchy_candidate_input_state="not_provided",
            previous_frontier_output_sha256="e" * 64,
            listenbrainz_propagation_output_sha256="f" * 64,
            listenbrainz_propagation_file_sha256="1" * 64,
            listenbrainz_propagation_receipt_artifact_sha256="2" * 64,
            rows=rows,
            coverage=coverage,
            output_sha256="3" * 64,
        )
        v5_path = root / "v5.json"
        v5_path.write_text(v5.model_dump_json(), encoding="utf-8")
        v5_store = LocalObjectStore(root / "v5-objects")
        v5_write = v5_store.push(v5_path, ObjectKey(value="v5.json"))
        v5_receipt = EvidenceFrontierReceipt(
            artifact_sha256=v5_write.sha256,
            artifact_byte_size=v5_write.byte_size,
            object_key=v5_write.key.value,
            logical_output_sha256=v5.output_sha256,
            gate=EvidenceFrontierGate(artifact_output_sha256=v5.output_sha256),
        )
        v5_receipt_sha = _sha(v5_receipt.model_dump(mode="json"))
        edge = TaxonomyRelationHierarchyOverlayEdge(
            child_genre_id="item1", parent_genre_id="item2", action="add", evidence_refs=("fact:1",)
        )
        overlay_payload: dict[str, Any] = {
            "base_hierarchy_logical_output_sha256": "4" * 64,
            "base_hierarchy_receipt_sha256": "5" * 64,
            "base_hierarchy_object_key": ObjectKey(value="base.json"),
            "base_hierarchy_object_sha256": "6" * 64,
            "base_hierarchy_object_byte_size": 1,
            "taxonomy_relation_expansion_output_sha256": "7" * 64,
            "maximum_base_candidate_pair_count": 250000,
            "edges": (edge,),
            "base_candidate_count": 10,
            "base_accepted_count": 2,
            "union_candidate_count": 11,
            "union_accepted_count": 3,
            "net_new_accepted_count": 1,
            "isolated_seed_reduction": 2,
            "union_pair_sha256": "8" * 64,
            "output_sha256": "0" * 64,
        }
        provisional = TaxonomyRelationHierarchyOverlay.model_construct(**overlay_payload)
        overlay_payload["output_sha256"] = _sha(
            provisional.model_dump(mode="json", exclude={"output_sha256"})
        )
        overlay = TaxonomyRelationHierarchyOverlay.model_validate(overlay_payload)
        overlay_path = root / "overlay.json"
        overlay_path.write_text(overlay.model_dump_json(), encoding="utf-8")
        overlay_store = LocalObjectStore(root / "overlay-objects")
        overlay_write = overlay_store.push(overlay_path, ObjectKey(value="overlay.json"))
        overlay_receipt = TaxonomyRelationHierarchyOverlayReceipt(
            artifact=overlay_write,
            artifact_sha256=overlay_write.sha256,
            logical_output_sha256=overlay.output_sha256,
        )
        overlay_receipt_sha = _sha(overlay_receipt.model_dump(mode="json"))
        return (
            FrontierV6Inputs(
                v5_path=v5_path,
                v5_receipt=v5_receipt,
                v5_receipt_sha256=v5_receipt_sha,
                expected_v5_receipt_sha256=v5_receipt_sha,
                v5_object_store=v5_store,
                overlay_path=overlay_path,
                overlay_receipt=overlay_receipt,
                overlay_receipt_sha256=overlay_receipt_sha,
                expected_overlay_receipt_sha256=overlay_receipt_sha,
                overlay_object_store=overlay_store,
            ),
            coverage,
        )

    def test_receipts_monotonic_coverage_and_complete_support(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            inputs, coverage = self._inputs(Path(temporary))
            artifact = build_taxonomy_relation_frontier_v6(inputs)
            self.assertEqual(artifact.preserved_v5_coverage, coverage)
            self.assertEqual(len(artifact.support_rows), 6291)
            self.assertEqual(artifact.hierarchy_union_candidate_count, 11)
            self.assertEqual(artifact.hierarchy_union_accepted_count, 3)
            item1 = next(row for row in artifact.support_rows if row.source_item_id == "item1")
            item2 = next(row for row in artifact.support_rows if row.source_item_id == "item2")
            self.assertEqual((item1.factual_parent_count, item2.factual_child_count), (1, 1))

    def test_rejects_forged_receipt_root_and_substituted_object(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            inputs, _coverage_value = self._inputs(Path(temporary))
            forged = replace(inputs, expected_v5_receipt_sha256="0" * 64)
            with self.assertRaises(ValueError):
                build_taxonomy_relation_frontier_v6(forged)
            (Path(temporary) / "overlay-objects" / "overlay.json").write_text(
                "substituted", encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                build_taxonomy_relation_frontier_v6(inputs)


if __name__ == "__main__":
    unittest.main()
