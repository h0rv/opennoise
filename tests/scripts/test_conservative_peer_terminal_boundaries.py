"""Focused boundaries for conservative peer construction and terminal evaluation."""

from __future__ import annotations

import importlib.util
import json
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


class ConservativePeerTerminalBoundaryTests(unittest.TestCase):
    """Ensure stored direct evidence and historical joins stay exact and bounded."""

    def test_target_memberships_deduplicate_exact_evidence_refs(self) -> None:
        module = _module(
            "conservative_peer_materializer",
            "scripts/materialize_conservative_musicbrainz_peer_candidate.py",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text(
                json.dumps(
                    {
                        "direct_memberships": [
                            {"artist_id": "artist:a", "genre_id": "seed:a", "evidence_ref": "x"},
                            {"artist_id": "artist:a", "genre_id": "seed:a", "evidence_ref": "x"},
                            {"artist_id": "artist:a", "genre_id": "seed:b", "evidence_ref": "y"},
                            {
                                "artist_id": "artist:ignored",
                                "genre_id": "seed:c",
                                "evidence_ref": "z",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            result = module._target_memberships(path, frozenset({"artist:a"}))  # noqa: SLF001
        self.assertEqual(result, {"artist:a": {"seed:a": ("x",), "seed:b": ("y",)}})

    def test_terminal_requirements_reject_non_musicbrainz_artist_identifier(self) -> None:
        module = _module(
            "conservative_peer_terminal_evaluation",
            "scripts/evaluate_conservative_peer_lastfm_positive_only.py",
        )
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "candidate.json"
            candidate.write_text(
                json.dumps(
                    {
                        "output_sha256": "a" * 64,
                        "edges": [
                            {
                                "edge_id": "edge",
                                "source_genre_id": "seed:a",
                                "target_genre_id": "seed:b",
                                "evidence": {"artist_id": "not-an-mbid"},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(module.EvaluationError):
                module._candidate_requirements(  # noqa: SLF001
                    candidate, {"seed:a": "a", "seed:b": "b"}
                )

    def test_terminal_requirements_reject_duplicate_edge_ids(self) -> None:
        module = _module(
            "conservative_peer_terminal_duplicate_evaluation",
            "scripts/evaluate_conservative_peer_lastfm_positive_only.py",
        )
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "candidate.json"
            candidate.write_text(
                json.dumps(
                    {
                        "output_sha256": "a" * 64,
                        "edges": [
                            {
                                "edge_id": "edge",
                                "source_genre_id": "seed:a",
                                "target_genre_id": "seed:b",
                                "evidence": {"artist_id": "musicbrainz:artist:abc"},
                            },
                            {
                                "edge_id": "edge",
                                "source_genre_id": "seed:c",
                                "target_genre_id": "seed:d",
                                "evidence": {"artist_id": "musicbrainz:artist:def"},
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(module.EvaluationError):
                module._candidate_requirements(  # noqa: SLF001
                    candidate,
                    {"seed:a": "a", "seed:b": "b", "seed:c": "c", "seed:d": "d"},
                )

    def test_terminal_gate_rejects_unpinned_candidate_bytes(self) -> None:
        module = _module(
            "conservative_peer_terminal_byte_gate",
            "scripts/evaluate_conservative_peer_lastfm_positive_only.py",
        )
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "candidate.json"
            reconciliation = Path(directory) / "reconciliation.json"
            candidate.write_text("{}", encoding="utf-8")
            reconciliation.write_text("{}", encoding="utf-8")
            with self.assertRaises(module.EvaluationError):
                module._validate_candidate(candidate, reconciliation)  # noqa: SLF001

    def test_terminal_gate_accepts_the_pinned_candidate_replay(self) -> None:
        module = _module(
            "conservative_peer_terminal_positive_gate",
            "scripts/evaluate_conservative_peer_lastfm_positive_only.py",
        )
        output_hash, requirements = module._validate_candidate(  # noqa: SLF001
            Path(
                ".cache/musicbrainz-peer-threshold-sensitivity-v1/conservative-peer-candidate-v2.json"
            ),
            Path(".cache/musicbrainz-full-seed-targets/pipeline/seed-reconciliation.json"),
        )
        self.assertEqual(
            output_hash, "05eae8b22a94fffddd30e25c29d4629257a611956d9b59a21440e862c80436d2"
        )
        self.assertEqual(len(requirements), 1_497)

    def test_materializer_gate_rejects_baseline_bytes_not_in_pinned_receipt(self) -> None:
        module = _module(
            "conservative_peer_materializer_receipt_gate",
            "scripts/materialize_conservative_musicbrainz_peer_candidate.py",
        )
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory) / "baseline.json"
            layout = Path(directory) / "layout.json"
            baseline.write_text("{}", encoding="utf-8")
            layout.write_text("{}", encoding="utf-8")
            with self.assertRaises(module.MaterializationError):
                module._validate_pinned_receipt(  # noqa: SLF001
                    Path(".cache/musicbrainz-peer-threshold-sensitivity-v1/report.json"),
                    baseline,
                    layout,
                    "853353cfdc4d9ad1ea2a6faaaf58eff372b760133f70d3512e8d6de185838f76",
                )
