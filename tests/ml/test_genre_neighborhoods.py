"""Focused contract tests for the separate-channel co-listen checkpoint."""

import unittest

from opennoise.ml.genre_neighborhoods.builder import _channel_observed_states


class GenreNeighborhoodStateTest(unittest.TestCase):
    """Channel-local state coverage."""

    def test_channel_state_does_not_leak_an_observation_between_evidence_channels(self) -> None:
        """A direct-only claim must not mark the reviewed-alias channel observed."""
        base = {"direct-only": "isolated", "alias-only": "abstained", "neither": "isolated"}
        memberships = {
            "artist_direct": {"artist-a": ("direct-only",)},
            "reviewed_alias_context": {"artist-b": ("alias-only",)},
        }

        states = _channel_observed_states(base, memberships)

        self.assertEqual(
            states["artist_direct"],
            {"direct-only": "observed", "alias-only": "abstained", "neither": "isolated"},
        )
        self.assertEqual(
            states["reviewed_alias_context"],
            {"direct-only": "isolated", "alias-only": "observed", "neither": "isolated"},
        )
