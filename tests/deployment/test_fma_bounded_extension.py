"""Protect bounded extensions against resealing, roster changes and custody failures."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from opennoise.common import canonical_json
from opennoise.deployment import fma_bounded_extension as extension

RECIPES = Path(__file__).resolve().parents[2] / "data/recipes"


def fixture() -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, str]
]:
    """Use retained metadata with an explicitly synthetic, never-authorized addition."""
    original = json.loads(
        (RECIPES / "fma-reconstruction-20261013/original-playback-manifest.json").read_bytes()
    )
    parent = json.loads((RECIPES / "fma-four-artists-20261013/playback-manifest.json").read_bytes())
    capture = json.loads((RECIPES / "fma-four-artists-20261013/capture.json").read_bytes())
    row = copy.deepcopy(capture["tracks"][0])
    row.update(track_id=900000, audio_path="900000.mp3")
    capture["tracks"] = [row]
    retained = parent["original_track_ids"][:8]
    proposal = {
        "tracks": [copy.deepcopy(row)],
        "protected_original_ids": retained[:7],
        "expanded_view_plan": {
            "retained_original_ids": retained,
            "retained_added_ids": parent["expanded_track_ids"],
            "new_ids": [900000],
            "track_ids": sorted(retained + parent["expanded_track_ids"] + [900000]),
            "audio_bytes_bound": 64_000_000,
        },
    }
    capture["proposal_sha256"] = "a" * 64
    hashes = {
        "original_manifest": parent["sources"]["original"]["manifest_sha256"],
        "parent_manifest": "b" * 64,
        "capture": "c" * 64,
        "proposal": "a" * 64,
    }
    return original, parent, capture, proposal, hashes


def approved_fixture() -> tuple[dict[str, Any], str]:
    """Create a synthetic recipe; callers explicitly patch approval only within tests."""
    inputs = fixture()
    core = extension._core(*inputs)  # noqa: SLF001 -- isolated derivation contract.
    recipe = {
        "revision": extension.RECIPE_REVISION,
        "source_bindings": inputs[-1],
        "manifest_core_sha256": extension._digest(core),  # noqa: SLF001 -- recipe binding test.
        "new_track_ids": [900000],
    }
    return {**core, "recipe": recipe}, extension._digest(recipe)  # noqa: SLF001


class BoundedExtensionTests(unittest.TestCase):
    def test_flat_inventory_preserves_all_prior_additions_and_paired_originals(self) -> None:
        result, digest = approved_fixture()
        with patch.object(extension, "APPROVED_RECIPES", frozenset({digest})):
            extension.validate_bounded_metadata(result)
        self.assertEqual(len(result["tracks"]), 53)
        self.assertEqual(len(result["expanded_track_ids"]), 45)
        self.assertNotIn("source_evidence", result)
        self.assertNotIn("parent_capture_sha256", result["sources"]["expanded"])
        self.assertLess(len(canonical_json(result)), 200_000)
        self.assertEqual(len(result["sources"]["original"]["tracks"]), 60)

    def test_arbitrary_generated_recipe_does_not_authorize_export(self) -> None:
        result, _ = approved_fixture()
        with self.assertRaisesRegex(ValueError, "not been approved"):
            extension.validate_bounded_metadata(result)

    def test_coherent_rehash_cannot_substitute_source_license_or_identity(self) -> None:
        for field in ("artist_id", "license_url", "audio_sha256", "duration_seconds"):
            with self.subTest(field=field):
                result, digest = approved_fixture()
                result["tracks"]["900000"][field] = "replacement"
                with patch.object(extension, "APPROVED_RECIPES", frozenset({digest})):
                    with self.assertRaisesRegex(ValueError, "reviewed source"):
                        extension.validate_bounded_metadata(result)
                    result["recipe"]["manifest_core_sha256"] = extension._digest(  # noqa: SLF001
                        {k: v for k, v in result.items() if k != "recipe"}
                    )
                    with self.assertRaisesRegex(ValueError, "not been approved"):
                        extension.validate_bounded_metadata(result)

    def test_selection_cannot_drop_old_additions_pairs_or_add_duplicates(self) -> None:
        for field in ("retained_added_ids", "retained_original_ids", "new_ids"):
            with self.subTest(field=field):
                inputs = fixture()
                plan = inputs[3]["expanded_view_plan"]
                if field == "new_ids":
                    plan[field] *= 2
                else:
                    plan[field].pop(0)
                with self.assertRaises(ValueError):
                    extension._core(*inputs)  # noqa: SLF001

    def test_changed_native_license_source_and_metadata_receipt_rejected(self) -> None:
        for field in ("source", "artist_id", "genre_ids"):
            with self.subTest(field=field):
                inputs = fixture()
                inputs[2]["tracks"][0][field] = (
                    {} if field == "source" else ([] if field == "genre_ids" else 1)
                )
                with self.assertRaisesRegex(ValueError, "native source"):
                    extension._core(*inputs)  # noqa: SLF001
        inputs = fixture()
        inputs[2]["source_receipt_sha256"] = "d" * 64
        with self.assertRaisesRegex(ValueError, "association"):
            extension._core(*inputs)  # noqa: SLF001

    def test_existing_byte_caps_are_enforced_before_output(self) -> None:
        inputs = fixture()
        inputs[2]["tracks"][0]["audio_bytes"] = 2_000_001
        with self.assertRaisesRegex(ValueError, "native source"):
            extension._core(*inputs)  # noqa: SLF001
        inputs = fixture()
        inputs[3]["expanded_view_plan"]["audio_bytes_bound"] = 1
        with self.assertRaisesRegex(ValueError, "budget"):
            extension._core(*inputs)  # noqa: SLF001

    def test_symlinks_and_oversized_inputs_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "real").write_bytes(b"source")
            (root / "link").symlink_to(root / "real")
            with self.assertRaisesRegex(ValueError, "symlink"):
                extension._read(root / "link")  # noqa: SLF001
            with self.assertRaisesRegex(ValueError, "oversized"):
                extension._read(root / "real", 2)  # noqa: SLF001

    def test_unapproved_build_stops_before_source_reads(self) -> None:
        result, _ = approved_fixture()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            recipe = root / "recipe.json"
            recipe.write_bytes(canonical_json(result["recipe"]))
            with (
                patch.object(extension, "_inputs", side_effect=AssertionError("must not read")),
                self.assertRaisesRegex(ValueError, "not been approved"),
            ):
                extension.build(root, root, root, root, recipe, root / "output")
            self.assertFalse((root / "output").exists())

    def test_thirteenth_addition_is_rejected_even_with_consistent_roster(self) -> None:
        inputs = fixture()
        plan = inputs[3]["expanded_view_plan"]
        plan["new_ids"] = list(range(900000, 900013))
        plan["track_ids"] = (
            plan["retained_original_ids"] + plan["retained_added_ids"] + plan["new_ids"]
        )
        with self.assertRaisesRegex(ValueError, "selection"):
            extension._core(*inputs)  # noqa: SLF001

    def test_build_decodes_exact_snapshot_and_leaves_no_output_on_failure(self) -> None:
        inputs = fixture()
        original, parent, capture, _, _ = inputs
        body = b"synthetic test-only bytes, not playable audio"
        digest = hashlib.sha256(body).hexdigest()
        for manifest in (original, parent):
            for row in manifest["tracks"].values():
                row.update(audio_bytes=len(body), audio_sha256=digest)
                row["decode"]["audio_sha256"] = digest
        for identity, row in original["tracks"].items():
            record_digest = extension._digest(row)  # noqa: SLF001 -- synthetic source inventory.
            parent["sources"]["original"]["tracks"][identity]["record_sha256"] = record_digest
        capture["tracks"][0].update(audio_bytes=len(body), audio_sha256=digest)
        core = extension._core(*inputs)  # noqa: SLF001
        recipe = {
            "revision": extension.RECIPE_REVISION,
            "source_bindings": inputs[-1],
            "manifest_core_sha256": extension._digest(core),  # noqa: SLF001 -- recipe identity.
            "new_track_ids": [900000],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            recipe_path = root / "recipe.json"
            recipe_path.write_bytes(canonical_json(recipe))
            for identity in set(original["tracks"]) | set(parent["tracks"]) | {"900000"}:
                (root / f"{identity}.mp3").write_bytes(body)
            output = root / "output"
            with (
                patch.object(extension, "APPROVED_RECIPES", frozenset({extension._digest(recipe)})),  # noqa: SLF001
                patch.object(extension, "_inputs", return_value=inputs),
                patch.object(extension.fma_playback, "decode_duration", return_value=0),
                self.assertRaisesRegex(ValueError, "full decode"),
            ):
                extension.build(root, root, root, root, recipe_path, output)
            self.assertFalse(output.exists())

            def decode(snapshot: Path) -> float:
                self.assertNotEqual(snapshot.parent, root)
                self.assertEqual(snapshot.read_bytes(), body)
                return float(capture["tracks"][0]["duration_seconds"])

            with (
                patch.object(extension, "APPROVED_RECIPES", frozenset({extension._digest(recipe)})),  # noqa: SLF001
                patch.object(extension, "_inputs", return_value=inputs),
                patch.object(extension.fma_playback, "decode_duration", side_effect=decode),
            ):
                result = extension.build(root, root, root, root, recipe_path, output)
                self.assertEqual(len(result["tracks"]), 53)
                (output / "900000.mp3").write_bytes(b"substitution")
                with self.assertRaisesRegex(ValueError, "audio bytes"):
                    extension.fma_playback.validate_playback_export(output)

    def test_freeze_writes_source_bound_review_candidate_without_approving_it(self) -> None:
        inputs = fixture()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            recipe_path = root / "recipe.json"
            with patch.object(extension, "_inputs", return_value=inputs):
                recipe = extension.freeze(root, root, root, root, recipe_path)
            self.assertEqual(recipe["source_bindings"], inputs[-1])
            self.assertEqual(recipe["limits"]["new_clips"], 12)
            self.assertEqual(json.loads(recipe_path.read_bytes()), recipe)
            with self.assertRaisesRegex(ValueError, "not been approved"):
                extension.build(root, root, root, root, recipe_path, root / "output")

    def test_checked_in_recipe_is_exactly_approved_but_cannot_authorize_other_records(self) -> None:
        recipe = json.loads(
            (RECIPES / "fma-twelve-expansion-20261015/extension-recipe.json").read_bytes()
        )
        digest = hashlib.sha256(canonical_json(recipe)).hexdigest()
        self.assertIn(digest, extension.APPROVED_RECIPES)
        self.assertEqual(len(recipe["new_track_ids"]), 12)
        with self.assertRaisesRegex(ValueError, "reviewed source records"):
            extension.validate_bounded_metadata(
                {
                    "revision": extension.REVISION,
                    "source_bindings": recipe["source_bindings"],
                    "tracks": {},
                    "recipe": recipe,
                }
            )
