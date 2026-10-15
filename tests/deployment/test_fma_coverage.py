"""Guard the fixed optional collection without authorizing arbitrary recipe snapshots."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from opennoise.common import canonical_json, sha256_file
from opennoise.deployment import fma_bounded_extension as bounded
from opennoise.deployment import fma_coverage as coverage
from opennoise.deployment import fma_listening_home as home
from tests.deployment.test_fma_bounded_extension import fixture as prior_fixture


def inputs() -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, str]
]:
    """Synthetic addition over retained metadata; it is never an approved recipe."""
    original, parent, capture, proposal, hashes = prior_fixture()
    proposal["third_view_plan"] = {
        "key": "coverage",
        "new_ids": [900000],
        "track_ids": [900000],
        "original_and_expanded_unchanged": True,
        "disjoint_from_prior_collections": True,
        "audio_bytes_bound": 2_000_000,
    }
    return original, parent, capture, proposal, hashes


def site(
    root: Path, original_count: int = 2, added_count: int = 1, coverage_count: int = 1
) -> None:
    """Create metadata-only synthetic home fixtures; playback validation is separately tested."""
    originals = list(range(1, original_count + 1))
    added = list(range(original_count + 1, original_count + added_count + 1))
    new = list(
        range(original_count + added_count + 1, original_count + added_count + coverage_count + 1)
    )
    domains = {"original": originals, "expanded": [originals[-1], *added], "coverage": new}
    manifests: dict[str, dict[str, Any]] = {}
    source_inventory: dict[str, dict[str, Any]] = {}
    for key, ids in domains.items():
        (root / key / "audio").mkdir(parents=True)
        (root / key / "explorer").mkdir()
        tracks = {str(i): {"track_id": i, "artist_id": i} for i in ids}
        for identity, row in tracks.items():
            source_inventory[identity] = {
                "record_sha256": bounded._digest(row),  # noqa: SLF001
                "artist_id": row["artist_id"],
                "genre_ids": [1],
            }
        manifests[key] = {
            "revision": home.REVISION,
            "source_pack_sha256": "b" * 64,
            "tracks": tracks,
        }
    manifests["expanded"].update(
        revision=home.BOUNDED_EXTENSION_REVISION,
        sources={
            "original": {
                "capture_sha256": "b" * 64,
                "metadata_source_receipt_sha256": "a" * 64,
                "tracks": {str(i): source_inventory[str(i)] for i in originals},
            },
            "expanded": {"tracks": {str(i): source_inventory[str(i)] for i in added}},
        },
    )
    manifests["coverage"].update(
        revision=home.COVERAGE_REVISION,
        metadata_source_receipt_sha256="a" * 64,
        prior_track_ids=sorted(originals + added),
        native_inventory={str(i): source_inventory[str(i)] for i in new},
    )
    for key, identities in domains.items():
        if key == "expanded":
            manifests[key]["sources"]["original"]["manifest_sha256"] = sha256_file(
                root / "original/audio/manifest.json"
            )[0]
        if key == "coverage":
            manifests[key]["source_bindings"] = {
                "original_manifest": sha256_file(root / "original/audio/manifest.json")[0],
                "parent_manifest": sha256_file(root / "expanded/audio/manifest.json")[0],
            }
        (root / key / "audio/manifest.json").write_bytes(canonical_json(manifests[key]))
        catalog = {
            "collection": {"label": key},
            "source_receipt_sha256": "a" * 64,
            "genres": [{"genre_id": 1, "title": "Synthetic tag"}],
            "playback": {
                "manifest_sha256": sha256_file(root / key / "audio/manifest.json")[0],
                "tracks": [{"track_id": i, "artist_id": i, "genre_ids": [1]} for i in identities],
            },
        }
        (root / key / "explorer/catalog.json").write_bytes(canonical_json(catalog))


def mocked_playback(path: Path) -> dict[str, Any]:
    """Read synthetic manifests while isolating home source association checks."""
    return json.loads((path / "manifest.json").read_bytes())


class CoverageTests(unittest.TestCase):
    def test_new_collection_contains_only_disjoint_delta_and_parent_bindings(self) -> None:
        core = coverage._core(*inputs())  # noqa: SLF001
        self.assertEqual(set(core["tracks"]), {"900000"})
        self.assertEqual(len(core["prior_track_ids"]), 104)
        self.assertNotIn("source_evidence", core)
        self.assertEqual(set(core["native_inventory"]), {"900000"})

    def test_unapproved_and_resealed_recipes_rejected(self) -> None:
        core = coverage._core(*inputs())  # noqa: SLF001
        recipe: dict[str, Any] = {
            "revision": coverage.RECIPE_REVISION,
            "source_bindings": core["source_bindings"],
            "manifest_core_sha256": bounded._digest(core),  # noqa: SLF001 -- exact recipe binding.
        }
        manifest: dict[str, Any] = {**core, "recipe": recipe}
        with self.assertRaisesRegex(ValueError, "not been approved"):
            coverage.validate_coverage_metadata(manifest)
        with patch.object(coverage, "APPROVED_RECIPES", frozenset({bounded._digest(recipe)})):  # noqa: SLF001
            coverage.validate_coverage_metadata(manifest)
            manifest["tracks"]["900000"]["license_url"] = "replacement"
            with self.assertRaisesRegex(ValueError, "reviewed source"):
                coverage.validate_coverage_metadata(manifest)
            recipe["manifest_core_sha256"] = bounded._digest(  # noqa: SLF001 -- adversarial resealing.
                {k: v for k, v in manifest.items() if k != "recipe"}
            )
            with self.assertRaisesRegex(ValueError, "not been approved"):
                coverage.validate_coverage_metadata(manifest)

    def test_disjoint_identity_scope_source_license_and_caps(self) -> None:
        for change in (
            "overlap",
            "thirteenth",
            "metadata",
            "artist",
            "license",
            "oversize",
            "root129",
        ):
            with self.subTest(change=change):
                values = inputs()
                row = values[2]["tracks"][0]
                if change == "overlap":
                    values[0]["tracks"]["900000"] = {}
                elif change == "thirteenth":
                    values[3]["third_view_plan"]["new_ids"] = list(range(900000, 900013))
                elif change == "metadata":
                    values[2]["source_receipt_sha256"] = "changed"
                elif change == "artist":
                    row["artist_id"] += 1
                elif change == "license":
                    row["source"]["license_url"] = "unlicensed"
                elif change == "oversize":
                    row["audio_bytes"] = 2_000_001
                else:
                    values[1]["tracks"].update({str(i): {} for i in range(800000, 800025)})
                with self.assertRaises(ValueError):
                    coverage._core(*values)  # noqa: SLF001

    def test_fixed_third_collection_rejects_fourth_missing_prior_and_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "original").mkdir()
            with self.assertRaisesRegex(ValueError, "missing"):
                home.collection_keys(root)
            (root / "expanded").mkdir()
            self.assertEqual(home.collection_keys(root), ("original", "expanded"))
            (root / "coverage").mkdir()
            self.assertEqual(home.collection_keys(root), ("original", "expanded", "coverage"))
            (root / "fourth").mkdir()
            with self.assertRaisesRegex(ValueError, "unknown"):
                home.collection_keys(root)
            (root / "fourth").rmdir()
            (root / "link").symlink_to(root / "coverage")
            with self.assertRaisesRegex(ValueError, "symlinked"):
                home.collection_keys(root)

    def test_home_binds_unchanged_parents_and_every_coverage_native_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            site(root)
            with patch.object(home, "validate_playback_export", side_effect=mocked_playback):
                result = home.build_listening_home(root)
            self.assertEqual(result["distinct_clips"], 4)
            self.assertEqual(result["shared_clips"], 1)
            self.assertEqual(
                [row["key"] for row in result["collections"]], ["original", "expanded", "coverage"]
            )
            self.assertIn("coverage/explorer/index.html#listen", (root / "index.html").read_text())

    def test_home_rejects_source_parent_inventory_changes_and_root129(self) -> None:
        for change in ("source", "parent", "prior", "duplicate", "root129", "artist", "genre"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                site(root, 64, 63, 2) if change == "root129" else site(root)
                path = root / "coverage/audio/manifest.json"
                manifest = json.loads(path.read_bytes())
                if change == "source":
                    manifest["metadata_source_receipt_sha256"] = "changed"
                elif change == "parent":
                    manifest["source_bindings"]["parent_manifest"] = "changed"
                elif change == "prior":
                    manifest["prior_track_ids"].pop()
                elif change == "duplicate":
                    manifest["tracks"]["1"] = manifest["tracks"].pop("4")
                path.write_bytes(canonical_json(manifest))
                if change in {"artist", "genre"}:
                    catalog_path = root / "coverage/explorer/catalog.json"
                    catalog = json.loads(catalog_path.read_bytes())
                    catalog["playback"]["manifest_sha256"] = sha256_file(path)[0]
                    field = "artist_id" if change == "artist" else "genre_ids"
                    catalog["playback"]["tracks"][0][field] = 999 if change == "artist" else [2]
                    catalog_path.write_bytes(canonical_json(catalog))
                with (
                    patch.object(home, "validate_playback_export", side_effect=mocked_playback),
                    self.assertRaises(ValueError),
                ):
                    home.build_listening_home(root)
