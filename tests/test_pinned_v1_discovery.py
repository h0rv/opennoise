"""Contract for the regenerated, sealed v1 discovery test fixture."""

from __future__ import annotations

import unittest
from pathlib import Path

from opennoise.common import sha256_file
from tests._pinned_v1_discovery import pinned_v1_discovery_path

_PINNED_V1_SHA256 = "b4ff2b1bcebb0bb6b1fd63b78caf9a416dbf5bb0c3050c0fa05e434fd0c700e8"
_SEALED_INPUTS = (
    Path(".cache/semantic-map-layout-v3/artifact.json"),
    Path("data/public.sqlite"),
)


@unittest.skipUnless(
    all(path.is_file() for path in _SEALED_INPUTS),
    "requires sealed layout and public database",
)
class PinnedV1DiscoveryTests(unittest.TestCase):
    def test_fixture_is_retained_and_independent_of_dist(self) -> None:
        first = pinned_v1_discovery_path()
        second = pinned_v1_discovery_path()

        self.assertEqual(first, second)
        self.assertTrue(first.is_file())
        self.assertFalse(first.resolve().is_relative_to(Path("dist").resolve()))
        self.assertEqual(sha256_file(first)[0], _PINNED_V1_SHA256)
