from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from musix.peers.audit.strength_aware_peer_audit import (
    PeerAuditError,
    build_consensus_micro_neighborhood_audit,
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
            _write(
                support, "release_group_artist_overlap", [("a", "b", 0.03, 5), ("c", "d", 0.01, 3)]
            )
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

    def test_consensus_micro_neighborhood_is_deterministic(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            direct, support = root / "direct.json", root / "support.json"
            reconciliation = root / "reconciliation.json"
            _write_reconciliation(reconciliation, ("a", "b", "c", "d"))
            reconciliation_hash = _file_sha256(reconciliation)
            _write(
                direct,
                "direct_artist_overlap",
                [("a", "b", 0.03, 5), ("a", "c", 0.03, 5)],
                reconciliation_hash,
                4,
            )
            _write(
                support,
                "release_group_artist_overlap",
                [("a", "b", 0.02, 3), ("b", "c", 0.02, 3)],
                reconciliation_hash,
                4,
            )
            self.assertEqual(
                build_consensus_micro_neighborhood_audit(direct, support, reconciliation),
                build_consensus_micro_neighborhood_audit(direct, support, reconciliation),
            )

    def test_consensus_retains_endpoint_pairs_with_both_channel_frequencies(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            direct, support, reconciliation = (
                root / "direct.json",
                root / "support.json",
                root / "r.json",
            )
            _write_reconciliation(reconciliation, ("a", "b", "c"))
            reconciliation_hash = _file_sha256(reconciliation)
            _write(direct, "direct_artist_overlap", [("a", "b", 0.1, 4)], reconciliation_hash, 3)
            _write(
                support,
                "release_group_artist_overlap",
                [("a", "b", 0.2, 5)],
                reconciliation_hash,
                3,
            )
            artifact = build_consensus_micro_neighborhood_audit(direct, support, reconciliation)
        self.assertTrue(artifact.stable_pairs)
        pair = artifact.stable_pairs[0]
        self.assertGreaterEqual(pair.direct_coassignment_frequency, 0.8)
        self.assertGreaterEqual(pair.support_coassignment_frequency, 0.8)
        direct_evidence = pair.direct_source_evidence
        support_evidence = pair.support_source_evidence
        assert direct_evidence is not None
        assert support_evidence is not None
        self.assertEqual(direct_evidence.score, 0.1)
        self.assertEqual(support_evidence.shared_supported_artist_count, 5)

    def test_consensus_binds_input_bytes_and_rejects_tampering(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            direct, support, reconciliation = (
                root / "direct.json",
                root / "support.json",
                root / "r.json",
            )
            _write_reconciliation(reconciliation, ("a", "b"))
            reconciliation_hash = _file_sha256(reconciliation)
            _write(direct, "direct_artist_overlap", [("a", "b", 0.1, 4)], reconciliation_hash, 2)
            _write(
                support,
                "release_group_artist_overlap",
                [("a", "b", 0.2, 5)],
                reconciliation_hash,
                2,
            )
            artifact = build_consensus_micro_neighborhood_audit(direct, support, reconciliation)
            direct.write_text(direct.read_text() + " ")
            changed = build_consensus_micro_neighborhood_audit(direct, support, reconciliation)
            self.assertNotEqual(
                artifact.direct_input.artifact_bytes_sha256,
                changed.direct_input.artifact_bytes_sha256,
            )
            raw = json.loads(support.read_text())
            raw["candidates"][0]["score"] = 0.9
            support.write_text(json.dumps(raw))
            with self.assertRaisesRegex(PeerAuditError, "logical hash"):
                build_consensus_micro_neighborhood_audit(direct, support, reconciliation)

    def test_consensus_ego_memberships_overlap_and_every_seed_is_accounted_for(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            direct, support, reconciliation = (
                root / "direct.json",
                root / "support.json",
                root / "r.json",
            )
            _write_reconciliation(reconciliation, ("a", "b", "c", "d"))
            reconciliation_hash = _file_sha256(reconciliation)
            edges = [("a", "b", 0.1, 4), ("a", "c", 0.1, 4)]
            _write(direct, "direct_artist_overlap", edges, reconciliation_hash, 4)
            _write(support, "release_group_artist_overlap", edges, reconciliation_hash, 4)
            artifact = build_consensus_micro_neighborhood_audit(direct, support, reconciliation)
        memberships = {row.genre_id: set(row.member_genre_ids) for row in artifact.ego_affiliations}
        self.assertTrue(memberships["a"] & memberships["b"])
        self.assertEqual(artifact.covered_seed_count, 4)
        self.assertEqual(artifact.abstention_count, 2)
        abstentions = {row.genre_id: row.reason for row in artifact.abstentions}
        self.assertEqual(abstentions["c"], "no_cross_channel_stable_coassignment")
        self.assertEqual(abstentions["d"], "no_direct_candidate_endpoint")


def _write(
    path: Path,
    kind: str,
    edges: list[tuple[str, str, float, int]],
    reconciliation_sha256: str = "a" * 64,
    seed_count: int = 1,
) -> None:
    payload = {
        "component_kind": kind,
        "seed_count": seed_count,
        "support_genre_count": seed_count,
        "support_membership_count": len(edges),
        "empty_input_seed_count": 0,
        "seeds_without_qualifying_neighbors_count": 0,
        "reconciliation_sha256": reconciliation_sha256,
        "candidates": [
            {
                "source_genre_id": left,
                "target_genre_id": right,
                "score": score,
                "shared_supported_artist_count": shared,
            }
            for left, right, score, shared in edges
        ],
    }
    payload["output_sha256"] = _logical_sha256(payload)
    path.write_text(json.dumps(payload))


def _write_reconciliation(path: Path, seed_ids: tuple[str, ...]) -> None:
    dispositions = [
        {
            "source_item_id": seed_id,
            "source_external_id": f"test:{seed_id}",
            "seed_name": seed_id,
            "normalized_name": seed_id,
            "disposition": "unresolved",
            "public_identities": [],
            "musicbrainz_identities": [],
            "review_identity_names": [],
            "collision_source_item_ids": [],
            "reason": "test fixture",
        }
        for seed_id in seed_ids
    ]
    seed_identity = _logical_sha256(
        [
            {"source_item_id": seed_id, "source_external_id": f"test:{seed_id}", "name": seed_id}
            for seed_id in seed_ids
        ]
    )
    payload = {
        "revision": "seed-reconciliation-v3",
        "seed_input_sha256": "1" * 64,
        "seed_source_id": "test",
        "seed_source_content_sha256": "2" * 64,
        "seed_identity_sha256": seed_identity,
        "taxonomy_artifact_sha256": "3" * 64,
        "musicbrainz_input_sha256": None,
        "input_sha256": "4" * 64,
        "seed_count": len(seed_ids),
        "dispositions": dispositions,
        "coverage": {
            "seed_count": len(seed_ids),
            "reconciled_count": 0,
            "public_only_count": 0,
            "musicbrainz_only_count": 0,
            "review_only_count": 0,
            "ambiguous_count": 0,
            "unresolved_count": len(seed_ids),
            "public_identity_count": 0,
            "musicbrainz_identity_count": 0,
            "musicbrainz_genre_identity_count": 0,
            "musicbrainz_tag_identity_count": 0,
            "collision_seed_count": 0,
        },
        "review_candidates_promoted_to_identity": 0,
    }
    payload["output_sha256"] = _logical_sha256(payload)
    path.write_text(json.dumps(payload))


def _logical_sha256(value: object) -> str:
    if isinstance(value, dict):
        value = {key: item for key, item in value.items() if key != "output_sha256"}
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
