"""Contracts for the fail-closed public static discovery v2 adapter."""

from __future__ import annotations

import unittest
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import ValidationError

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
    build_merged_public_direct_discovery_candidate,
)
from opennoise.deployment.public_direct_static_discovery import (
    build_sealed_qid_additive_static_discovery,
)
from opennoise.deployment.public_static_discovery_v2 import (
    PublicStaticDiscoveryV2Error,
    PublicStaticDiscoveryV2Membership,
    adapt_public_static_discovery_v2,
    public_static_discovery_v2_json,
    public_static_discovery_v2_sha256,
    verify_public_static_discovery_v2_payload,
)
from tests._pinned_v1_discovery import pinned_v1_discovery_path

_BASE = pinned_v1_discovery_path()
_ATLAS = Path(
    "dist/assets/semantic-atlas.730bca93300870d35b527f377eb883ae95a3f931aad7e820b013fa592c5bf4ac.json"
)
_DATABASE = Path("data/public.sqlite")
_LAYOUT = Path(".cache/semantic-map-layout-v3/artifact.json")
_PINNED_INPUTS = (_BASE, _ATLAS, _DATABASE, _LAYOUT)


def _candidate():  # noqa: ANN202
    with TemporaryDirectory() as temporary:
        qid_map_path = Path(temporary) / "qid-map.json"
        qid_map = build_public_qid_seed_map(
            PublicQidSeedMapInputs(public_database=_DATABASE, canonical_layout=_LAYOUT)
        )
        write_public_qid_seed_map(qid_map, qid_map_path)
        bridge = build_sealed_qid_direct_bridge(
            SealedQidDirectBridgeInputs(
                public_qid_seed_map=qid_map_path,
                public_database=_DATABASE,
                base_static_discovery=_BASE,
            )
        )
        additive = build_sealed_qid_additive_static_discovery(
            database=_DATABASE, base_static_discovery=_BASE, bridge=bridge
        )
        return build_merged_public_direct_discovery_candidate(
            base_static_discovery=_BASE, additive=additive
        )


class PublicStaticDiscoveryV2Tests(unittest.TestCase):
    """v2 is replayable, atlas-bound, and keeps v1 exact-label records intact."""

    @unittest.skipUnless(
        all(path.is_file() for path in _PINNED_INPUTS),
        "requires the pinned local public inputs",
    )
    def test_pinned_clean_chain_adapts_to_deterministic_reciprocal_payload(self) -> None:
        candidate = _candidate()
        payload = adapt_public_static_discovery_v2(candidate=candidate, semantic_atlas=_ATLAS)
        replay = adapt_public_static_discovery_v2(candidate=candidate, semantic_atlas=_ATLAS)

        self.assertEqual(payload, replay)
        self.assertEqual(payload.output_sha256, public_static_discovery_v2_sha256(payload))
        self.assertEqual(
            public_static_discovery_v2_json(payload), public_static_discovery_v2_json(replay)
        )
        self.assertEqual(
            payload.output_sha256,
            "c117658577413e8047503486077e3b50ebe31056340a9025897fa8645c716c22",
        )
        self.assertEqual(
            sha256(public_static_discovery_v2_json(payload)).hexdigest(),
            "4d8adac6b3a929addf4413b41ffcf13de10633f57b2a784bfbe0449f3bcede1c",
        )
        self.assertEqual(len(public_static_discovery_v2_json(payload)), 2_865_604)
        self.assertEqual(payload.revision, "static-direct-discovery-v2")
        self.assertEqual(len(payload.genres), 344)
        self.assertEqual(len(payload.artists), 1126)
        self.assertEqual(payload.coverage.bound_direct_observation_count, 3859)
        self.assertEqual(
            sum(genre.binding == "exact_casefolded_label" for genre in payload.genres), 260
        )
        self.assertEqual(
            sum(genre.binding == "one_to_one_qid_position_binding" for genre in payload.genres),
            84,
        )
        genre_by_id = {genre.node_id: genre for genre in payload.genres}
        for artist in payload.artists:
            for membership in artist.memberships:
                self.assertIn(artist.artist_id, genre_by_id[membership.node_id].artist_ids)
        for genre in payload.genres:
            for artist_id in genre.artist_ids:
                artist = next(artist for artist in payload.artists if artist.artist_id == artist_id)
                self.assertIn(genre.node_id, {item.node_id for item in artist.memberships})

        candidate_exact = {
            genre.node_id: genre.model_dump()
            for genre in candidate.discovery.genres
            if genre.binding == "exact_casefolded_label"
        }
        payload_exact = {
            genre.node_id: genre.model_dump()
            for genre in payload.genres
            if genre.binding == "exact_casefolded_label"
        }
        self.assertEqual(payload_exact, candidate_exact)

        tampered = payload.model_copy(update={"output_sha256": "0" * 64})
        with self.assertRaisesRegex(PublicStaticDiscoveryV2Error, "self-hash"):
            public_static_discovery_v2_json(tampered)

        related_index = next(
            index for index, artist in enumerate(payload.artists) if artist.shared_genre_artists
        )
        related_artist = payload.artists[related_index]
        dangling_peer = related_artist.shared_genre_artists[0].model_copy(
            update={"artist_id": "artist:999999999"}
        )
        dangling_artist = related_artist.model_copy(
            update={
                "shared_genre_artists": (dangling_peer, *related_artist.shared_genre_artists[1:])
            }
        )
        dangling_draft = payload.model_copy(
            update={
                "artists": (
                    *payload.artists[:related_index],
                    dangling_artist,
                    *payload.artists[related_index + 1 :],
                ),
                "output_sha256": "0" * 64,
            }
        )
        dangling = dangling_draft.model_copy(
            update={"output_sha256": public_static_discovery_v2_sha256(dangling_draft)}
        )
        with self.assertRaisesRegex(PublicStaticDiscoveryV2Error, "related artist"):
            verify_public_static_discovery_v2_payload(
                dangling, frozenset(genre.node_id for genre in dangling.genres)
            )

    @unittest.skipUnless(
        all(path.is_file() for path in _PINNED_INPUTS),
        "requires the pinned local public inputs",
    )
    def test_unpinned_atlas_is_rejected(self) -> None:
        candidate = _candidate()
        with TemporaryDirectory() as temporary:
            altered_atlas = Path(temporary) / "atlas.json"
            altered_atlas.write_bytes(_ATLAS.read_bytes() + b"\n")
            with self.assertRaisesRegex(PublicStaticDiscoveryV2Error, "atlas hash"):
                adapt_public_static_discovery_v2(candidate=candidate, semantic_atlas=altered_atlas)

    def test_v2_boundary_rejects_unknown_binding_without_touching_v1(self) -> None:
        with self.assertRaises(ValidationError):
            PublicStaticDiscoveryV2Membership.model_validate(
                {
                    "node_id": "item1",
                    "catalog_genre_id": 1,
                    "catalog_genre_name": "genre",
                    "binding": "unreviewed_binding",
                    "evidence": (),
                }
            )


if __name__ == "__main__":
    unittest.main()
