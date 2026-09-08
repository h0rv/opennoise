from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from musix.strength_aware_peer_audit import (
    PeerAuditError,
    build_corroborated_peer_audit,
    build_strength_aware_peer_audit,
)


class StrengthAwarePeerAuditTests(unittest.TestCase):
    def test_grid_is_deterministic_and_channels_remain_separate(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            direct = root / "direct.json"
            support = root / "support.json"
            _write(direct, "direct_artist_overlap", [("a", "b", 0.03, 5), ("b", "c", 0.01, 2)])
            _write(support, "release_group_artist_overlap", [("a", "b", 0.03, 5), ("c", "d", 0.01, 3)])
            first = build_strength_aware_peer_audit(direct, support)
            second = build_strength_aware_peer_audit(direct, support)
        self.assertEqual(first, second)
        self.assertEqual(len(first.grid), 9)
        self.assertEqual(first.direct_support_corroborated_edge_count, 1)
        self.assertEqual(first.weak_navigation_edge_count, 0)

    def test_rejects_swapped_channel(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "wrong.json"
            _write(path, "release_group_artist_overlap", [])
            with self.assertRaises(PeerAuditError):
                build_strength_aware_peer_audit(path, path)

    def test_corroborated_core_requires_both_channels(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            direct = root / "direct.json"
            support = root / "support.json"
            _write(direct, "direct_artist_overlap", [("a", "b", 0.03, 5), ("b", "c", 0.03, 5)])
            _write(support, "release_group_artist_overlap", [("a", "b", 0.02, 3)])
            artifact = build_corroborated_peer_audit(direct, support)
        self.assertEqual(artifact.corroborated_edge_count, 1)
        self.assertEqual(artifact.covered_seed_count, 2)


def _write(path: Path, kind: str, edges: list[tuple[str, str, float, int]]) -> None:
    payload = {"output_sha256": "a" * 64, "component_kind": kind, "candidates": [
        {"source_genre_id": left, "target_genre_id": right, "score": score, "shared_supported_artist_count": shared}
        for left, right, score, shared in edges
    ]}
    path.write_text(json.dumps(payload))
