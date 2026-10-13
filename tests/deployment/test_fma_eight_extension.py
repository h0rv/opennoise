"""Reject coherent source/selection substitutions in the closed eight-clip extension."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from typing import Any

from opennoise.deployment import fma_eight_extension as extension

RECIPE = Path(__file__).resolve().parents[2] / "data/recipes/fma-eight-expansion-20261013"


def manifest() -> dict[str, Any]:
    """Read the exact reviewed source receipts without audio or network access."""
    parent = json.loads((RECIPE / "parent-playback-manifest.json").read_bytes())
    capture = json.loads((RECIPE / "eight-capture.json").read_bytes())
    return extension._manifest(parent, capture)  # noqa: SLF001 -- immutable receipt fixture.


class EightExtensionTests(unittest.TestCase):
    def test_exact_extension_preserves_all_added_clips_and_existing_limits(self) -> None:
        result = manifest()
        extension.validate_extension_metadata(result)
        self.assertEqual(len(result["tracks"]), 64)
        self.assertEqual(len(result["expanded_track_ids"]), 40)
        self.assertEqual(len(result["original_track_ids"]), 24)
        self.assertLess(result["audio_bytes"], 64_000_000)
        self.assertFalse(result["public_deployment_authorized"])

    def test_source_substitution_rejected_even_if_playback_rows_are_rebuilt(self) -> None:
        for field in ("license_url", "artist_id", "audio_sha256", "duration_seconds"):
            with self.subTest(field=field):
                result = manifest()
                parent = result["source_evidence"]["parent"]
                capture = copy.deepcopy(result["source_evidence"]["capture"])
                row = capture["tracks"][0]
                if field == "license_url":
                    row["source"][field] = "http://creativecommons.org/licenses/by/3.0/"
                else:
                    row[field] = 1
                with self.assertRaisesRegex(ValueError, "receipt differs"):
                    extension._manifest(parent, capture)  # noqa: SLF001

    def test_omitted_clip_and_coherent_total_change_rejected(self) -> None:
        result = manifest()
        key = str(result["expanded_track_ids"][0])
        removed = result["tracks"].pop(key)
        result["audio_bytes"] -= removed["audio_bytes"]
        with self.assertRaisesRegex(ValueError, "playback record differs"):
            extension.validate_extension_metadata(result)

    def test_parent_source_substitution_rejected(self) -> None:
        result = manifest()
        result["source_evidence"]["parent"]["tracks"]["128457"]["artist_name"] = "substituted"
        with self.assertRaisesRegex(ValueError, "receipt differs"):
            extension.validate_extension_metadata(result)
