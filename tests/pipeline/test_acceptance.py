"""Acceptance testimony must not turn missing data into an automated pass."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from opennoise.pipeline.acceptance import GATES, SCOPE, inspect_acceptance
from scripts.check_foundation_acceptance import main


def _dossier(root: Path) -> dict[str, Any]:
    content = b"bounded test evidence"
    (root / "evidence.json").write_bytes(content)
    artifacts = [
        {
            "id": scope,
            "path": "evidence.json",
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
            "scope": scope,
            "role": "evaluation",
            "source": "synthetic-test",
            "license": "CC0-1.0",
            "pack": "unrestricted-core",
        }
        for scope in ("full-corpus", "actual-export")
    ]
    return {
        "version": 1,
        "scope": SCOPE,
        "artifacts": artifacts,
        "reviews": [
            {
                "gate": gate,
                "decision": "missing",
                "explanation": "independent review absent",
                "evidence": ["full-corpus", "actual-export"],
                "criteria_covered": [],
            }
            for gate in GATES
        ],
    }


class AcceptanceTests(unittest.TestCase):
    def test_present_verified_files_do_not_pass_unreviewed_gates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = cast("dict[str, Any]", inspect_acceptance(root, _dossier(root)))
            self.assertTrue(report["evidence_valid"])
            self.assertFalse(report["all_gates_recorded_pass"])
            self.assertFalse(report["automatic_semantic_pass"])
            self.assertTrue(all(gate["status"] == "missing" for gate in report["gates"]))

    def test_complete_reviews_remain_testimony(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dossier = _dossier(root)
            for review in dossier["reviews"]:
                review.update(
                    decision="recorded_pass",
                    reviewer="explicit test review",
                    reviewed_at="2026-10-02",
                    criteria_covered=list(GATES[review["gate"]]),
                )
            report = inspect_acceptance(root, dossier)
            self.assertTrue(report["all_gates_recorded_pass"])
            self.assertFalse(report["automatic_semantic_pass"])

    def test_fabricated_partial_review_and_portable_scope_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dossier = _dossier(root)
            dossier["artifacts"][0]["scope"] = "portable-example"
            for review in dossier["reviews"]:
                review.update(decision="recorded_pass")
            report = cast("dict[str, Any]", inspect_acceptance(root, dossier))
            self.assertFalse(report["all_gates_recorded_pass"])
            self.assertTrue(all(gate["status"] == "incomplete_review" for gate in report["gates"]))
            rebuild = next(
                gate for gate in report["gates"] if gate["gate"] == "full-corpus-rebuild"
            )
            self.assertIn(
                "full-corpus evidence required; portable/cohort evidence is insufficient",
                rebuild["binding_or_review_gaps"],
            )

    def test_missing_directory_changed_bytes_and_symlink_fail_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dossier = _dossier(root)
            artifact = dossier["artifacts"][0]
            artifact["path"] = "absent"
            self.assertFalse(inspect_acceptance(root, dossier)["evidence_valid"])
            (root / "directory").mkdir()
            artifact["path"] = "directory"
            self.assertFalse(inspect_acceptance(root, dossier)["evidence_valid"])
            artifact["path"] = "evidence.json"
            (root / "evidence.json").write_bytes(b"x" * artifact["size_bytes"])
            self.assertFalse(inspect_acceptance(root, dossier)["evidence_valid"])
            (root / "alias").symlink_to(root / "evidence.json")
            artifact["path"] = "alias"
            self.assertFalse(inspect_acceptance(root, dossier)["evidence_valid"])
            artifact["path"] = "../outside"
            self.assertFalse(inspect_acceptance(root, dossier)["evidence_valid"])

    def test_unknown_duplicates_and_dropped_gate_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dossier = _dossier(root)
            with self.assertRaises(ValueError):
                inspect_acceptance(root, {**dossier, "automatic_semantic_pass": True})
            with self.assertRaises(ValueError):
                inspect_acceptance(root, {**dossier, "version": True})
            with self.assertRaises(ValueError):
                inspect_acceptance(root, {**dossier, "reviews": dossier["reviews"][:-1]})
            with self.assertRaises(ValueError):
                inspect_acceptance(root, {**dossier, "artifacts": dossier["artifacts"] * 2})

    def test_historical_training_and_nc_core_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dossier = _dossier(root)
            dossier["artifacts"][0].update(source="Every Noise", role="construction")
            with self.assertRaises(ValueError):
                inspect_acceptance(root, dossier)
            dossier["artifacts"][0].update(source="MusicBrainz", license="CC-BY-NC-SA-3.0")
            with self.assertRaises(ValueError):
                inspect_acceptance(root, dossier)
            dossier["artifacts"][0].update(pack="optional-noncommercial")
            self.assertTrue(inspect_acceptance(root, dossier)["evidence_valid"])

    def test_cli_exit_distinguishes_gaps_and_invalid_evidence(self) -> None:
        import json  # noqa: PLC0415 - CLI fixture serialization only.

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dossier = _dossier(root)
            path = root / "dossier.json"
            path.write_text(json.dumps(dossier), encoding="utf-8")
            with (
                patch("sys.stdout"),
                patch("sys.argv", ["check", "--root", str(root), "--dossier", str(path), "--json"]),
            ):
                self.assertEqual(main(), 1)
                (root / "evidence.json").write_bytes(b"changed")
                self.assertEqual(main(), 2)


if __name__ == "__main__":
    unittest.main()
