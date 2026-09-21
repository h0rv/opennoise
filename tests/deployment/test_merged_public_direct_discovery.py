"""Contracts for the local-only complete public-direct discovery candidate."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from opennoise.checkpoints.public_qid_seed_map import (
    PublicQidSeedMapInputs,
    build_public_qid_seed_map,
    write_public_qid_seed_map,
)
from opennoise.checkpoints.sealed_qid_direct_bridge import (
    SealedQidDirectBridgeInputs,
    build_sealed_qid_direct_bridge,
)
from opennoise.deployment.merged_public_direct_discovery import (
    LocalMergedDiscoveryArtistPayload,
    LocalMergedDiscoveryMembershipPayload,
    MergedPublicDirectDiscoveryError,
    _require_merged_memberships,
    build_merged_public_direct_discovery_candidate,
)
from opennoise.deployment.public_direct_static_discovery import (
    SealedQidAdditiveStaticDiscovery,
    build_sealed_qid_additive_static_discovery,
    sealed_qid_additive_static_discovery_sha256,
)

_BASE = Path(
    "dist/assets/static-discovery.b4ff2b1bcebb0bb6b1fd63b78caf9a416dbf5bb0c3050c0fa05e434fd0c700e8.json"
)
_DATABASE = Path("data/public.sqlite")
_LAYOUT = Path(".cache/semantic-map-layout-v3/artifact.json")
_PINNED_INPUTS = (_BASE, _DATABASE, _LAYOUT)


def _additive() -> SealedQidAdditiveStaticDiscovery:
    with TemporaryDirectory() as temporary:
        qid_map_path = Path(temporary) / "qid-map.json"
        qid_map = build_public_qid_seed_map(
            PublicQidSeedMapInputs(
                public_database=_DATABASE,
                canonical_layout=_LAYOUT,
            )
        )
        write_public_qid_seed_map(qid_map, qid_map_path)
        bridge = build_sealed_qid_direct_bridge(
            SealedQidDirectBridgeInputs(
                public_qid_seed_map=qid_map_path,
                public_database=_DATABASE,
                base_static_discovery=_BASE,
            )
        )
        return build_sealed_qid_additive_static_discovery(
            database=_DATABASE,
            base_static_discovery=_BASE,
            bridge=bridge,
        )


class MergedPublicDirectDiscoveryTests(unittest.TestCase):
    """The merged candidate is complete, pinned, and remains local-only."""

    @unittest.skipUnless(
        all(path.is_file() for path in _PINNED_INPUTS),
        "requires the pinned local public inputs",
    )
    def test_real_pinned_sidecar_replays_complete_truthful_candidate(self) -> None:
        before = _BASE.read_bytes()
        additive = _additive()
        candidate = build_merged_public_direct_discovery_candidate(
            base_static_discovery=_BASE,
            additive=additive,
        )
        discovery = candidate.discovery
        coverage = discovery.coverage
        source = discovery.source
        if coverage is None or source is None:
            self.fail("merged ready discovery must retain source and coverage")

        self.assertEqual(_BASE.read_bytes(), before)
        self.assertEqual(
            candidate.base_static_discovery_sha256, additive.base_static_discovery_sha256
        )
        self.assertEqual(
            candidate.sealed_qid_additive_static_discovery_sha256, additive.output_sha256
        )
        self.assertFalse(candidate.canonical_release_modified)
        self.assertFalse(candidate.deployment_performed)
        self.assertEqual(len(discovery.genres), 344)
        self.assertEqual(len(discovery.artists), 1126)
        self.assertEqual(coverage.exact_label_bound_catalog_genre_count, 294)
        self.assertEqual(coverage.genres_with_direct_artists, 344)
        self.assertEqual(coverage.artists_with_direct_map_genres, 1126)
        self.assertEqual(coverage.direct_catalog_observation_count, 4948)
        self.assertEqual(coverage.bound_direct_observation_count, 3859)
        self.assertEqual(
            sum(item.observation_count for item in source.sources),
            3859,
        )
        self.assertEqual(
            {genre.binding for genre in discovery.genres},
            {"exact_casefolded_label", "one_to_one_qid_position_binding"},
        )
        merged_genres = {genre.node_id: genre for genre in discovery.genres}
        for base_genre in additive.base.genres:
            self.assertEqual(
                merged_genres[base_genre.node_id].model_dump(),
                base_genre.model_dump(),
            )
        base_evidence_ids = {
            evidence.evidence_id
            for artist in additive.base.artists
            for membership in artist.memberships
            for evidence in membership.evidence
        }
        additive_evidence_ids = {
            evidence.evidence_id
            for artist in additive.artists
            for membership in artist.memberships
            for evidence in membership.evidence
        }
        merged_evidence_ids = [
            evidence.evidence_id
            for artist in discovery.artists
            for membership in artist.memberships
            for evidence in membership.evidence
        ]
        self.assertFalse(base_evidence_ids & additive_evidence_ids)
        self.assertEqual(set(merged_evidence_ids), base_evidence_ids | additive_evidence_ids)
        self.assertEqual(len(merged_evidence_ids), len(set(merged_evidence_ids)))
        artists = {artist.artist_id: artist for artist in discovery.artists}
        genres = {genre.node_id: genre for genre in discovery.genres}
        for artist in discovery.artists:
            membership_nodes = {membership.node_id for membership in artist.memberships}
            for node_id in membership_nodes:
                self.assertIn(artist.artist_id, genres[node_id].artist_ids)
            for peer in artist.shared_genre_artists:
                self.assertLessEqual(peer.shared_genre_count, len(peer.shared_genre_ids))
                self.assertTrue(
                    membership_nodes & {m.node_id for m in artists[peer.artist_id].memberships}
                )

    @unittest.skipUnless(
        all(path.is_file() for path in _PINNED_INPUTS),
        "requires the pinned local public inputs",
    )
    def test_same_count_sidecar_drift_fails_even_when_its_self_hash_is_recomputed(self) -> None:
        additive = _additive()
        changed_artist = additive.artists[0].model_copy(update={"name": "Tampered"})
        draft = additive.model_copy(
            update={"artists": (changed_artist, *additive.artists[1:]), "output_sha256": "0" * 64}
        )
        tampered = draft.model_copy(
            update={"output_sha256": sealed_qid_additive_static_discovery_sha256(draft)}
        )

        with self.assertRaisesRegex(MergedPublicDirectDiscoveryError, "self-hash"):
            build_merged_public_direct_discovery_candidate(
                base_static_discovery=_BASE,
                additive=tampered,
            )

    def test_duplicate_membership_is_rejected_without_pinned_artifacts(self) -> None:
        membership = LocalMergedDiscoveryMembershipPayload(
            node_id="item1",
            catalog_genre_id=1,
            catalog_genre_name="genre",
            binding="one_to_one_qid_position_binding",
            evidence=(),
        )
        artist = LocalMergedDiscoveryArtistPayload(
            artist_id="artist:1",
            name="Artist",
            memberships=(membership, membership),
            shared_genre_artists=(),
        )

        with self.assertRaisesRegex(MergedPublicDirectDiscoveryError, "duplicate memberships"):
            _require_merged_memberships([artist])


if __name__ == "__main__":
    unittest.main()
