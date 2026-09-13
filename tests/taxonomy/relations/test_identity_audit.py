from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from musix.common import canonical_json, sha256_hex
from musix.evidence.graph_projection import (
    ArtifactInput,
    EvidenceGraphProjectionArtifact,
    EvidenceGraphProjectionError,
    artifact_sha256,
    verify_evidence_graph_projection,
    write_evidence_graph_projection,
)
from musix.taxonomy.relations.expansion import (
    RelationExpansionCoverage,
    TaxonomyRelationExpansionArtifact,
)
from musix.taxonomy.relations.identity_audit import (
    audit_taxonomy_relation_identity,
    qids_from_query,
)


def _expansion(seed_count: int) -> TaxonomyRelationExpansionArtifact:
    coverage = RelationExpansionCoverage.model_construct(
        seed_count=seed_count,
        exact_qid_mapped_seed_count=2,
        accepted_factual_edge_count=1,
        skipped_unknown_endpoint_count=0,
        skipped_ambiguous_exact_qid_count=0,
    )
    return TaxonomyRelationExpansionArtifact.model_construct(
        coverage=coverage, output_sha256="a" * 64
    )


def _receipt() -> EvidenceGraphProjectionArtifact:
    inputs = tuple(
        ArtifactInput(
            role=f"role-{index}",
            path=f"sealed/input-{index}.json",
            byte_sha256="c" * 64,
            byte_count=index + 1,
            logical_sha256="d" * 64,
        )
        for index in range(8)
    )
    base = EvidenceGraphProjectionArtifact.model_construct(
        revision="source-neutral-evidence-graph-v2",
        inputs=inputs,
        database_sha256="b" * 64,
        database_bytes=1,
        identity_count=6291,
        total_identity_count=6292,
        claim_count=0,
        abstention_count=0,
        factual_relation_count=0,
        candidate_relation_score_count=0,
        output_sha256="0" * 64,
    )
    return base.model_copy(update={"output_sha256": artifact_sha256(base)})


class TaxonomyRelationIdentityAuditTests(unittest.TestCase):
    def test_qids_from_query_extracts_only_qids(self) -> None:
        self.assertEqual(qids_from_query("wd:Q42 wd:Q7 Q99 Q0 wd:Q"), frozenset({"Q42", "Q7"}))

    def test_audit_rejects_partial_seed_universe(self) -> None:
        with self.assertRaisesRegex(ValueError, "6291"):
            audit_taxonomy_relation_identity(_expansion(3), current_query="wd:Q1", stale_query="x")

    def test_matching_audit_replays_output_sha256(self) -> None:
        audit = audit_taxonomy_relation_identity(
            _expansion(6291),
            current_query="VALUES ?x { wd:Q1 wd:Q2 }",
            stale_query="VALUES ?x { wd:Q1 }",
        )
        payload = canonical_json(audit.model_dump(mode="json", exclude={"output_sha256"}))
        self.assertEqual(audit.output_sha256, sha256_hex(payload))
        self.assertTrue(audit.stale_query_is_current_subset)

    def test_tampered_receipt_raises_and_write_round_trips(self) -> None:
        receipt = _receipt()
        verify_evidence_graph_projection(receipt)
        head = "0" if receipt.output_sha256[:1] != "0" else "1"
        with self.assertRaises(EvidenceGraphProjectionError):
            verify_evidence_graph_projection(
                receipt.model_copy(update={"output_sha256": head + receipt.output_sha256[1:]})
            )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "receipt.json"
            write_evidence_graph_projection(path, receipt)
            replayed = EvidenceGraphProjectionArtifact.model_validate_json(path.read_bytes())
            self.assertEqual(replayed, receipt)


if __name__ == "__main__":
    unittest.main()
