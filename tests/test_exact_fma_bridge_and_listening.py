"""Exercise identity conflicts, full denominators, byte custody and provider boundaries."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from opennoise.serving.metadata import fma_identity_bridge as bridge
from opennoise.serving.metadata import listening_destinations as listening


class ExactBridgeTests(unittest.TestCase):
    """Never infer identities, permissions or playability from plausible names."""

    def test_conflict_and_unresolved_denominator(self) -> None:
        """Duplicated assertions abstain; schemes and entity kinds are never guessed."""
        facts = {"artist": {"rows": 4}, "recording": {"rows": 5}}
        index = {"artist": {"http://freemusicarchive.org/music/A/": {1}}, "recording": {}}
        urls = [
            {
                "id": "00000000-0000-4000-8000-000000000001",
                "resource": "http://freemusicarchive.org/music/A/",
                "relation-list": [
                    {
                        "relations": [
                            {
                                "direction": "backward",
                                "artist": {"id": "00000000-0000-4000-8000-000000000003"},
                            },
                            {
                                "direction": "backward",
                                "artist": {"id": "00000000-0000-4000-8000-000000000004"},
                            },
                            {
                                "direction": "backward",
                                "recording": {"id": "00000000-0000-4000-8000-000000000006"},
                            },
                        ]
                    }
                ],
            },
            {
                "id": "00000000-0000-4000-8000-000000000002",
                "resource": "https://freemusicarchive.org/music/A/",
                "relation-list": [
                    {
                        "relations": [
                            {
                                "direction": "backward",
                                "artist": {"id": "00000000-0000-4000-8000-000000000005"},
                            }
                        ]
                    }
                ],
            },
        ]
        body = json.dumps({"offset": 0, "count": 2, "urls": urls}).encode()
        with (
            tempfile.TemporaryDirectory() as name,
            patch.object(bridge, "native_fma", return_value=(facts, index)),
        ):
            path = Path(name)
            (path / "page-000.json").write_bytes(body)
            receipt = {
                "revision": bridge.REVISION,
                "query": bridge.QUERY,
                "captures": [
                    {
                        "offset": 0,
                        "url": "https://musicbrainz.org/ws/2/url/?"
                        + urlencode(
                            {"query": bridge.QUERY, "limit": 100, "offset": 0, "fmt": "json"}
                        ),
                        "status": 200,
                        "path": "page-000.json",
                        "sha256": bridge.digest(body),
                        "bytes": len(body),
                    }
                ],
            }
            (path / "receipt.json").write_text(json.dumps(receipt))
            result = bridge.project(path, path)
            self.assertEqual(result["artist"]["resolved"], [])
            self.assertEqual(len(result["artist"]["conflicts"]), 1)
            self.assertEqual(result["artist"]["unresolved"], facts["artist"]["rows"])
            self.assertEqual(result["recording"]["unresolved"], facts["recording"]["rows"])
            original = receipt["captures"][0].copy()
            for key, value, message in (
                ("url", "https://musicbrainz.org/ws/2/url/?query=artist", "endpoint or query"),
                ("path", "../page-000.json", "path or symlink"),
                ("bytes", bridge.MAX_BYTES + 1, "byte budget"),
            ):
                receipt["captures"][0] = {**original, key: value}
                (path / "receipt.json").write_text(json.dumps(receipt))
                with self.assertRaisesRegex(ValueError, message):
                    bridge.project(path, path)
            receipt["captures"][0] = original
            (path / "receipt.json").write_text(json.dumps(receipt))
            (path / "page-000.json").write_bytes(body + b" ")
            with self.assertRaisesRegex(ValueError, "byte binding"):
                bridge.project(path, path)

    def test_provider_boundaries(self) -> None:
        """No script URLs, hostname spoofing or embedded credentials enter external links."""
        for url in ("https://youtu.be/real-id", "https://artist.bandcamp.com/track/example"):
            self.assertTrue(listening.approved_url(url))
        for url in (
            "javascript:alert(1)",
            "https://bandcamp.com.evil.test/a",
            "https://u:p@youtu.be/a",
        ):
            self.assertFalse(listening.approved_url(url))

    def test_credit_required_and_availability_not_invented(self) -> None:
        """A source link is neither a playability proof nor a popularity judgment."""
        payload = {
            "id": "00000000-0000-4000-8000-000000000006",
            "title": "Example",
            "artist-credit": [{"artist": {"id": "00000000-0000-4000-8000-000000000003"}}],
            "relations": [
                {
                    "target-type": "url",
                    "type": "free streaming",
                    "url": {
                        "id": "00000000-0000-4000-8000-000000000001",
                        "resource": "https://youtu.be/a",
                    },
                }
            ],
        }
        body = json.dumps(payload).encode()
        result = listening.projection(
            body, "00000000-0000-4000-8000-000000000006", "00000000-0000-4000-8000-000000000003"
        )
        self.assertEqual(result["destinations"][0]["availability"], "not_checked")
        with self.assertRaisesRegex(ValueError, "exact artist credit"):
            listening.projection(
                body, "00000000-0000-4000-8000-000000000006", "00000000-0000-4000-8000-000000000007"
            )
