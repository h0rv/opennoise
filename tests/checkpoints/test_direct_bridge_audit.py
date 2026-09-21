from __future__ import annotations

import unittest
from pathlib import Path

from opennoise.checkpoints.direct_bridge_audit import audit_direct_bridges


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
            {"review_only": 164, "safe_exact": 277},
        )
        inputs = report["inputs"]
        if not isinstance(inputs, dict):
            self.fail("audit report inputs must be a dictionary")
        self.assertEqual(
            inputs.get("public_database_sha256"),
            "240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc",
        )
