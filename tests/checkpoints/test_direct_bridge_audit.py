from __future__ import annotations

import json
import subprocess
import sys
import unittest
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

from opennoise.checkpoints.direct_bridge_audit import (
    DirectBridgeAuditEdge,
    DirectBridgeAuditInputs,
    DirectBridgeAuditReport,
    DirectBridgeReviewArtifact,
    DirectBridgeReviewDecision,
    DirectBridgeReviewPolicy,
    audit_direct_bridges,
    build_direct_bridge_review_artifact,
    parse_direct_bridge_audit_report,
    verify_direct_bridge_review_artifact,
)


def _audit() -> DirectBridgeAuditReport:
    return DirectBridgeAuditReport(
        inputs=DirectBridgeAuditInputs(
            graph_sha256="a" * 64,
            discovery_sha256="b" * 64,
            public_database_sha256="c" * 64,
        ),
        edge_count=2,
        classification_counts={"review_only": 1, "safe_exact": 1},
        current_static_bridge_count=0,
        potential_direct_observation_lift=0,
        edges=(
            DirectBridgeAuditEdge(
                edge_id="edge:exact",
                legacy_id="legacy:exact",
                legacy_name="Exact",
                catalog_id="wikidata:genre:Q1",
                catalog_name="Exact",
                classification="safe_exact",
                direct_p136_observation_count=0,
                potential_direct_observation_lift=0,
            ),
            DirectBridgeAuditEdge(
                edge_id="edge:review",
                legacy_id="legacy:review",
                legacy_name="Questionable",
                catalog_id="wikidata:genre:Q2",
                catalog_name="Different",
                classification="review_only",
                direct_p136_observation_count=0,
                potential_direct_observation_lift=0,
            ),
        ),
    )


class DirectBridgeAuditTests(unittest.TestCase):
    def test_current_inputs_are_verified_and_source_bound(self) -> None:
        report = audit_direct_bridges(
            Path("data/model/open-construction-graph-v2.json"),
            Path(
                "dist/assets/static-discovery.8310a95109d9f33d08c0f2b6bc934c8e84246d1bf911d986395f84a2ed49c0fc.json"
            ),
            Path("data/public.sqlite"),
        )
        self.assertEqual(report["edge_count"], 441)
        self.assertEqual(report["current_static_bridge_count"], 244)
        self.assertEqual(report["potential_direct_observation_lift"], 1520)
        self.assertEqual(
            report["classification_counts"],
            {
                "conflicting_or_ambiguous": 95,
                "review_only": 101,
                "safe_exact": 245,
            },
        )
        inputs = report["inputs"]
        if not isinstance(inputs, dict):
            self.fail("audit report inputs must be a dictionary")
        self.assertEqual(
            inputs.get("public_database_sha256"),
            "240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc",
        )
        parsed = parse_direct_bridge_audit_report(report)
        self.assertEqual(parsed.edge_count, report["edge_count"])
        legacy_counts = Counter(edge.legacy_id for edge in parsed.edges)
        catalog_counts = Counter(edge.catalog_id for edge in parsed.edges)
        for edge in parsed.edges:
            if edge.classification.startswith("safe_"):
                self.assertEqual(legacy_counts[edge.legacy_id], 1)
                self.assertEqual(catalog_counts[edge.catalog_id], 1)

    def test_exact_edges_stay_pending_until_append_only_review_is_sealed(self) -> None:
        audit = _audit()
        initial = build_direct_bridge_review_artifact(audit, ())
        repeated = build_direct_bridge_review_artifact(audit, ())

        self.assertEqual(initial.output_sha256, repeated.output_sha256)
        self.assertEqual(initial.review_rows[0].state, "pending_review")
        self.assertFalse(initial.catalog_mutated)
        self.assertFalse(initial.static_discovery_mutated)
        self.assertFalse(initial.static_bridge_published)

        decisions = (
            DirectBridgeReviewDecision(
                decision_id="decision:one",
                edge_id="edge:exact",
                reviewer_ref="reviewer:alice",
                review_revision="direct-bridge-guide-v1",
                disposition="approve",
                rationale="The one-to-one exact labels and retained evidence agree.",
            ),
            DirectBridgeReviewDecision(
                decision_id="decision:two",
                edge_id="edge:exact",
                reviewer_ref="reviewer:bob",
                review_revision="direct-bridge-guide-v1",
                disposition="approve",
                rationale="An independent reviewer reached the same conclusion.",
            ),
        )
        reviewed = build_direct_bridge_review_artifact(audit, decisions, predecessor=initial)

        self.assertEqual(reviewed.review_rows[0].state, "ready_for_separate_publication")
        gate = verify_direct_bridge_review_artifact(reviewed)
        self.assertTrue(gate.approved_edges_require_separate_publication)
        with self.assertRaisesRegex(ValueError, "must append"):
            build_direct_bridge_review_artifact(audit, decisions[:1], predecessor=reviewed)
        with self.assertRaisesRegex(ValueError, "policy must match"):
            build_direct_bridge_review_artifact(
                audit,
                (*decisions, decisions[0].model_copy(update={"decision_id": "decision:three"})),
                DirectBridgeReviewPolicy(required_independent_approvals=3),
                reviewed,
            )

    def test_rejects_unknown_or_repeated_review_events(self) -> None:
        audit = _audit()
        unknown = DirectBridgeReviewDecision(
            decision_id="decision:unknown",
            edge_id="edge:missing",
            reviewer_ref="reviewer:alice",
            review_revision="direct-bridge-guide-v1",
            disposition="reject",
            rationale="This deliberately references no audited edge.",
        )
        with self.assertRaisesRegex(ValueError, "unknown audit edge"):
            build_direct_bridge_review_artifact(audit, (unknown,))

    def test_review_cli_queues_verified_audit_then_appends_decision(self) -> None:
        discovery = Path(
            "dist/assets/static-discovery.8310a95109d9f33d08c0f2b6bc934c8e84246d1bf911d986395f84a2ed49c0fc.json"
        )
        report = audit_direct_bridges(
            Path("data/model/open-construction-graph-v2.json"),
            discovery,
            Path("data/public.sqlite"),
        )
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            audit_path = root / "audit.json"
            queue_path = root / "queue.json"
            decisions_path = root / "decisions.json"
            reviewed_path = root / "reviewed.json"
            audit_path.write_text(json.dumps(report), encoding="utf-8")
            queue_command = [
                sys.executable,
                "scripts/manage_direct_bridge_review.py",
                "queue",
                "--audit",
                str(audit_path),
                "--discovery",
                str(discovery),
                "--output",
                str(queue_path),
            ]
            subprocess.run(queue_command, check=True, capture_output=True, text=True)  # noqa: S603
            queue = DirectBridgeReviewArtifact.model_validate_json(queue_path.read_bytes())
            self.assertEqual(queue.coverage.pending_review_count, report["edge_count"])
            decisions_path.write_text(
                json.dumps(
                    [
                        {
                            "decision_id": "decision:cli",
                            "edge_id": queue.audit.edges[0].edge_id,
                            "reviewer_ref": "reviewer:cli",
                            "review_revision": "direct-bridge-guide-v1",
                            "disposition": "needs_evidence",
                            "rationale": "The reviewer requests retained identity evidence.",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            apply_command = [
                sys.executable,
                "scripts/manage_direct_bridge_review.py",
                "apply",
                "--audit",
                str(audit_path),
                "--discovery",
                str(discovery),
                "--predecessor",
                str(queue_path),
                "--decisions",
                str(decisions_path),
                "--output",
                str(reviewed_path),
            ]
            subprocess.run(apply_command, check=True, capture_output=True, text=True)  # noqa: S603
            reviewed = DirectBridgeReviewArtifact.model_validate_json(reviewed_path.read_bytes())
            self.assertEqual(reviewed.coverage.review_decision_count, 1)
            self.assertEqual(reviewed.predecessor_output_sha256, queue.output_sha256)
            self.assertFalse(reviewed.static_bridge_published)
