"""Tests for the local-only review-input CLI path boundary."""

from __future__ import annotations

import argparse
import unittest
from pathlib import Path

from scripts.write_musicbrainz_direct_static_policy_review_input import local_cache_output


class WriteMusicBrainzDirectStaticPolicyReviewInputTests(unittest.TestCase):
    """Keep review files out of public and release directories."""

    def test_accepts_a_repository_cache_path(self) -> None:
        self.assertEqual(
            local_cache_output(".cache/musicbrainz-direct-static-policy-review-input-test.json"),
            Path(".cache/musicbrainz-direct-static-policy-review-input-test.json"),
        )

    def test_rejects_a_dist_path(self) -> None:
        with self.assertRaisesRegex(argparse.ArgumentTypeError, "repository .cache"):
            local_cache_output("dist/musicbrainz-direct-static-policy-review-input.json")
