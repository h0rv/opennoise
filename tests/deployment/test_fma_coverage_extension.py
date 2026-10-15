"""Separate reviewed coverage extension limits from the unchanged twelve-clip protocol."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from opennoise.common import canonical_json, sha256_file
from opennoise.deployment import fma_bounded_extension as bounded
from opennoise.deployment import fma_coverage as old
from opennoise.deployment import fma_coverage_extension as extension
from opennoise.deployment import fma_listening_home as home
from tests.deployment.test_fma_coverage import inputs, mocked_playback, site


def fixture() -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, str], dict[str, Any]
]:
    """Synthetic twelve retained rows plus five new rows, with repeated source artists."""
    original, parent, capture, proposal, hashes = inputs()
    template = capture["tracks"][0]

    def rows(start: int, count: int) -> list[dict[str, Any]]:
        result = []
        for identity in range(start, start + count):
            row = copy.deepcopy(template)
            row.update(track_id=identity, audio_path=f"{identity}.mp3")
            result.append(row)
        return result

    capture["tracks"] = rows(900000, 12)
    proposal["tracks"] = copy.deepcopy(capture["tracks"])
    proposal["third_view_plan"].update(
        new_ids=list(range(900000, 900012)),
        track_ids=list(range(900000, 900012)),
        audio_bytes_bound=64_000_000,
    )
    previous = old._core(original, parent, capture, proposal, hashes)  # noqa: SLF001
    capture = copy.deepcopy(capture)
    capture["tracks"] = rows(910000, 5)
    proposal = {
        "tracks": copy.deepcopy(capture["tracks"]),
        "coverage_view_plan": {
            "key": "coverage",
            "new_ids": list(range(910000, 910005)),
            "retained_ids": list(range(900000, 900012)),
            "track_ids": list(range(900000, 900012)) + list(range(910000, 910005)),
            "audio_bytes_bound": 64_000_000,
            "new_audio_bytes_bound": 10_000_000,
        },
    }
    hashes = {**hashes, "coverage_manifest": "d" * 64}
    return original, parent, capture, proposal, hashes, previous


class CoverageExtensionTests(unittest.TestCase):
    def test_preserves_twelve_exact_rows_and_allows_repeated_artists(self) -> None:
        values = fixture()
        result = extension._core(*values)  # noqa: SLF001
        self.assertEqual(len(result["tracks"]), 17)
        for key, row in values[-1]["tracks"].items():
            self.assertEqual(result["tracks"][key], row)
            self.assertEqual(result["native_inventory"][key], values[-1]["native_inventory"][key])
        self.assertEqual(len({row["artist_id"] for row in result["tracks"].values()}), 1)
        self.assertEqual(home.coverage_limits(old.REVISION), (12, 128))
        self.assertEqual(home.coverage_limits(extension.REVISION), (17, 133))
        with self.assertRaises(ValueError):
            home.coverage_limits("unknown")

    def test_source_preservation_license_and_bounds(self) -> None:
        for change in ("missing", "sixth", "parent", "source", "license", "alias", "root134"):
            with self.subTest(change=change):
                values = fixture()
                plan = values[3]["coverage_view_plan"]
                if change == "missing":
                    plan["retained_ids"].pop()
                elif change == "sixth":
                    plan["new_ids"].append(910005)
                elif change == "parent":
                    values[4]["parent_manifest"] = "changed"
                elif change == "source":
                    values[2]["source_receipt_sha256"] = "changed"
                elif change == "license":
                    values[2]["tracks"][0]["source"]["license_url"] = "unlicensed"
                elif change == "alias":
                    values[1]["tracks"]["910000"] = {}
                else:
                    values[1]["tracks"].update({str(i): {} for i in range(800000, 800013)})
                with self.assertRaises(ValueError):
                    extension._core(*values)  # noqa: SLF001

    def test_generated_and_resealed_recipes_are_not_approval(self) -> None:
        core = extension._core(*fixture())  # noqa: SLF001
        recipe = {
            "revision": extension.RECIPE_REVISION,
            "source_bindings": core["source_bindings"],
            "manifest_core_sha256": bounded._digest(core),  # noqa: SLF001
        }
        manifest: dict[str, Any] = {**core, "recipe": recipe}
        with self.assertRaisesRegex(ValueError, "not been approved"):
            extension.validate_coverage_metadata(manifest)
        with patch.object(extension, "APPROVED_RECIPES", frozenset({bounded._digest(recipe)})):  # noqa: SLF001
            extension.validate_coverage_metadata(manifest)
            manifest["tracks"]["900000"]["audio_sha256"] = "changed"
            with self.assertRaisesRegex(ValueError, "reviewed source"):
                extension.validate_coverage_metadata(manifest)
            recipe["manifest_core_sha256"] = bounded._digest(core)  # noqa: SLF001
            with self.assertRaisesRegex(ValueError, "not been approved"):
                extension.validate_coverage_metadata(manifest)

    def test_root_133_requires_v2_and_134_remains_rejected(self) -> None:
        for revision, prior_added, accepted in (
            (old.REVISION, 52, False),
            (extension.REVISION, 52, True),
            (extension.REVISION, 53, False),
        ):
            with (
                self.subTest(revision=revision, prior_added=prior_added),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                site(root, 64, prior_added, 17)
                path = root / "coverage/audio/manifest.json"
                manifest = json.loads(path.read_bytes())
                manifest["revision"] = revision
                path.write_bytes(canonical_json(manifest))
                catalog_path = root / "coverage/explorer/catalog.json"
                catalog = json.loads(catalog_path.read_bytes())
                catalog["playback"]["manifest_sha256"] = sha256_file(path)[0]
                catalog_path.write_bytes(canonical_json(catalog))
                with patch.object(home, "validate_playback_export", side_effect=mocked_playback):
                    if accepted:
                        result = home.build_listening_home(root)
                        self.assertEqual(result["distinct_clips"], 133)
                    else:
                        with self.assertRaises(ValueError):
                            home.build_listening_home(root)
