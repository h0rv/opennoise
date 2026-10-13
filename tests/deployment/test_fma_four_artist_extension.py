"""Protect the exact four-artist cohort and its paired-example retention."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from opennoise.deployment import fma_four_artist_extension as extension

RECIPE = Path(__file__).resolve().parents[2] / "data/recipes/fma-four-artists-20261013"


def manifest() -> dict[str, Any]:
    """Read the compact reviewed export without any audio or network access."""
    return json.loads((RECIPE / "playback-manifest.json").read_bytes())


class FourArtistExtensionTests(unittest.TestCase):
    def test_exact_cohort_and_paired_originals_preserve_bounds(self) -> None:
        value = manifest()
        extension.validate_four_artist_metadata(value)
        proposal = json.loads((RECIPE / "proposal.json").read_bytes())
        self.assertEqual(len(value["tracks"]), 64)
        self.assertEqual(len(value["expanded_track_ids"]), 44)
        self.assertEqual(value["audio_bytes"], 58_665_802)
        self.assertTrue(
            set(proposal["expanded_view_plan"]["required_original_ids_for_paired_examples"])
            <= set(value["original_track_ids"])
        )

    def test_source_substitution_cannot_be_made_valid_by_coherent_rehash(self) -> None:
        for field in ("license_url", "artist_id", "audio_sha256", "duration_seconds"):
            with self.subTest(field=field):
                value = manifest()
                value["tracks"]["32633"][field] = "substituted"
                with self.assertRaisesRegex(ValueError, "reviewed source"):
                    extension.validate_four_artist_metadata(value)

    def test_dropping_a_paired_original_and_adjusting_total_is_rejected(self) -> None:
        value = manifest()
        removed = value["tracks"].pop("141591")
        value["audio_bytes"] -= removed["audio_bytes"]
        value["original_track_ids"].remove(141591)
        with self.assertRaisesRegex(ValueError, "reviewed source"):
            extension.validate_four_artist_metadata(value)

    def test_unapproved_input_receipts_are_rejected_before_derivation(self) -> None:
        with self.assertRaisesRegex(ValueError, "approved source"):
            extension._derive({}, {}, {}, {})  # noqa: SLF001 -- explicit source-boundary rejection.
