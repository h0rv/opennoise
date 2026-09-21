"""Boundary checks for the local-only peer layout holdout scripts."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType


def _module(name: str, path: str) -> ModuleType:
    specification = importlib.util.spec_from_file_location(name, Path(path))
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


class PeerLayoutHoldoutBoundaryTests(unittest.TestCase):
    def test_fixed_candidate_mutation_is_rejected_before_evaluation(self) -> None:
        module = _module(
            "conservative_peer_holdout_mutation",
            "scripts/evaluate_conservative_musicbrainz_peer_layout_holdout.py",
        )
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "candidate.json"
            candidate.write_bytes(b"{}")
            with self.assertRaises(ValueError):
                module.build_report(
                    layout=Path(".cache/semantic-map-layout-v3/artifact.json"), candidate=candidate
                )

    def test_zero_holdout_remains_an_abstention_without_proposals(self) -> None:
        module = _module(
            "conservative_peer_holdout_abstention",
            "scripts/evaluate_conservative_musicbrainz_peer_layout_holdout.py",
        )
        report = module.build_report(
            layout=Path(".cache/semantic-map-layout-v3/artifact.json"),
            candidate=Path(
                ".cache/musicbrainz-peer-threshold-sensitivity-v1/"
                "conservative-peer-candidate-v2.json"
            ),
        )
        self.assertFalse(report["holdout"]["available"])
        self.assertEqual(
            report["unplaced_projection"]["directly_reachable_unplaced_seed_count"], 405
        )
        self.assertEqual(report["unplaced_projection"]["proposal_count"], 0)
        self.assertEqual(report["unplaced_projection"]["abstained_unplaced_seed_count"], 3_346)
        self.assertEqual(report["unplaced_projection"]["proposals"], [])

    def test_atomic_writers_refuse_an_existing_output(self) -> None:
        conservative = _module(
            "conservative_peer_holdout_atomic",
            "scripts/evaluate_conservative_musicbrainz_peer_layout_holdout.py",
        )
        baseline = _module(
            "baseline_peer_holdout_atomic",
            "scripts/evaluate_musicbrainz_baseline_peer_placed_holdout.py",
        )
        with tempfile.TemporaryDirectory() as directory:
            for module in (conservative, baseline):
                output = Path(directory) / f"{module.__name__}.json"
                module._write_no_replace(output, b"first")  # noqa: SLF001
                with self.assertRaises(FileExistsError):
                    module._write_no_replace(output, b"second")  # noqa: SLF001
                self.assertEqual(output.read_bytes(), b"first")

    def test_baseline_mutation_is_rejected_before_large_stream(self) -> None:
        module = _module(
            "baseline_peer_holdout_mutation",
            "scripts/evaluate_musicbrainz_baseline_peer_placed_holdout.py",
        )
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "candidate.json"
            candidate.write_bytes(b"{}")
            with self.assertRaises(ValueError):
                module.build_report(
                    layout=Path(".cache/semantic-map-layout-v3/artifact.json"),
                    baseline_candidate=candidate,
                )
