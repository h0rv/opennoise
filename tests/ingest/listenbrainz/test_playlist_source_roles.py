"""Route-only source-role contracts for local ListenBrainz playlist research."""

from __future__ import annotations

import unittest

from pydantic import HttpUrl

from opennoise.ingest.listenbrainz.playlist_source_roles import (
    ListenBrainzPlaylistSourceRoleError,
    PlaylistDiscoveryRouteReceipt,
    classify_playlist_discovery_route,
    make_playlist_discovery_route_receipt,
)

_SHA256 = "a" * 64


class ListenBrainzPlaylistSourceRoleTests(unittest.TestCase):
    """Ensure route provenance never becomes a human-curation inference."""

    def test_only_the_proven_created_listing_route_is_user_created(self) -> None:
        receipt = make_playlist_discovery_route_receipt(
            HttpUrl("https://api.listenbrainz.org/1/user/example/playlists?count=20"),
            payload_sha256=_SHA256,
            payload_bytes=10,
        )

        self.assertEqual(
            (receipt.route, receipt.source_role), ("user_playlists_created", "user_created")
        )
        self.assertFalse(receipt.human_curation_established)

    def test_createdfor_and_recommendations_preserve_route_but_not_origin(self) -> None:
        expected_routes = {
            "createdfor": "user_playlists_createdfor",
            "recommendations": "user_playlists_recommendations",
        }
        for suffix, route in expected_routes.items():
            receipt = make_playlist_discovery_route_receipt(
                HttpUrl(f"https://api.listenbrainz.org/1/user/example/playlists/{suffix}"),
                payload_sha256=_SHA256,
                payload_bytes=10,
            )
            self.assertEqual((receipt.route, receipt.source_role), (route, "unknown"))
            self.assertFalse(receipt.human_curation_established)

    def test_creator_text_is_not_an_input_and_direct_playlist_is_unknown(self) -> None:
        route, role = classify_playlist_discovery_route(
            HttpUrl("https://api.listenbrainz.org/1/playlist/00000000-0000-4000-8000-000000000001")
        )

        self.assertEqual((route, role), ("direct_playlist_endpoint", "unknown"))

    def test_rejects_nonofficial_route_and_a_forged_role(self) -> None:
        with self.assertRaises(ListenBrainzPlaylistSourceRoleError):
            classify_playlist_discovery_route(
                HttpUrl("https://example.org/1/user/example/playlists")
            )
        with self.assertRaisesRegex(ValueError, "does not match"):
            PlaylistDiscoveryRouteReceipt(
                source_url=HttpUrl(
                    "https://api.listenbrainz.org/1/user/example/playlists/createdfor"
                ),
                payload_sha256=_SHA256,
                payload_bytes=10,
                route="user_playlists_created",
                source_role="user_created",
            )
