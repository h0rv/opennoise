"""Production promotion and post-upload verification fail closed on scope or byte changes."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from email.message import Message
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.error import HTTPError

from opennoise.deployment.public_catalog_release import authorize, digest, promotion, release_marker
from opennoise.pipeline.public_catalog_candidate import REVISION
from scripts import verify_public_catalog_live as live

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "a" * 40


def fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    """Use one hand-checkable public data file and separate implementation assets."""
    data = {"profile.json": {"bytes": 3, "sha256": "profile"}}
    approval = {
        "input_contract_sha256": "inputs",
        "counts": {"catalog_artists": 2},
        "data_files": 1,
        "data_inventory_sha256": digest(data),
        "publication_scope": "public-only",
    }
    manifest = {
        "revision": REVISION,
        "input_contract_sha256": "inputs",
        "counts": {"catalog_artists": 2},
        "payload": {**data, "receipt.json": {}, "index.html": {}},
        "private_artifacts_consumed": False,
        "legacy_release_reconstructed": False,
        "acquisitions": 0,
    }
    return manifest, approval


class PublicCatalogPromotionTests(unittest.TestCase):
    def test_fixed_receipt_and_marker_bind_scope_and_every_asset(self) -> None:
        self.assertEqual(promotion(ROOT)["project"], "opennoise")
        manifest, approval = fixture()
        marker = release_marker(manifest, approval, COMMIT)
        self.assertTrue(marker["publication_authorized"])
        self.assertEqual(marker["files"], manifest["payload"])
        self.assertEqual(marker["build_commit"], COMMIT)
        self.assertFalse(marker["private_artifacts"])
        self.assertFalse(marker["audio_playback"])
        with self.assertRaisesRegex(ValueError, "complete Git"):
            release_marker(manifest, approval, "a0dcad")

    def test_data_scope_changes_are_rejected_but_code_assets_can_advance(self) -> None:
        manifest, approval = fixture()
        manifest["payload"]["index.html"] = {"new": "reviewed implementation"}
        manifest["payload"]["receipt.json"] = {"new": "implementation-bound receipt"}
        authorize(manifest, approval)
        for key, value in (
            ("revision", "other"),
            ("input_contract_sha256", "other"),
            ("counts", {"catalog_artists": 3}),
            ("private_artifacts_consumed", True),
            ("legacy_release_reconstructed", True),
            ("acquisitions", 1),
            ("payload", {"profile.json": {"sha256": "changed"}}),
        ):
            with self.subTest(key=key):
                changed = copy.deepcopy(manifest)
                changed[key] = value
                with self.assertRaisesRegex(ValueError, "audited public"):
                    authorize(changed, approval)


class LiveReleaseTests(unittest.TestCase):
    def test_old_commit_propagation_then_expected_commit(self) -> None:
        with (
            patch.object(
                live,
                "fetch",
                side_effect=[
                    b'{"build_commit":"old"}',
                    json.dumps({"build_commit": COMMIT}).encode(),
                ],
            ) as fetch,
            patch.object(live.time, "sleep") as sleep,
        ):
            self.assertEqual(
                live.wait_for_marker("https://example.test", COMMIT)["build_commit"], COMMIT
            )
        self.assertEqual(fetch.call_count, 2)
        sleep.assert_called_once_with(5)

    def test_access_denial_stops_without_retry(self) -> None:
        denied = HTTPError("https://example.test", 403, "Forbidden", Message(), None)
        with (
            patch.object(live, "fetch", side_effect=denied) as fetch,
            patch.object(live.time, "sleep") as sleep,
            self.assertRaises(HTTPError),
        ):
            live.wait_for_marker("https://example.test", COMMIT)
        fetch.assert_called_once()
        sleep.assert_not_called()

    def test_live_bytes_must_match_certified_build(self) -> None:
        approval = promotion(ROOT)
        raw = b"verified served bytes"
        marker = {
            **approval,
            "build_commit": COMMIT,
            "publication_authorized": True,
            "files": {
                name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                for name in ("index.html", "profile.json", "pipeline.json", "app.mjs")
            },
        }
        with (
            patch.object(sys, "argv", ["verify", "--commit", COMMIT]),
            patch.object(live, "promotion", return_value=approval),
            patch.object(live, "read", return_value=marker),
            patch.object(live, "wait_for_marker", return_value=marker),
            patch.object(live, "fetch", return_value=raw),
            patch("builtins.print"),
        ):
            live.main()
            with (
                patch.object(live, "fetch", return_value=b"forged"),
                self.assertRaisesRegex(ValueError, "served bytes"),
            ):
                live.main()
            changed = {**marker, "counts": {"catalog_artists": 999}}
            with (
                patch.object(live, "wait_for_marker", return_value=changed),
                self.assertRaisesRegex(ValueError, "public scope"),
            ):
                live.main()

    def test_non_core_assets_and_inventory_bounds_are_verified(self) -> None:
        raw = b"module bytes"
        files = {"app.mjs": {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}}
        with (
            patch.object(live, "fetch", return_value=b"stale module"),
            self.assertRaisesRegex(ValueError, "served bytes.*app.mjs"),
        ):
            live.verify_files("https://example.test", files)
        for invalid in (
            {"app.mjs": {"bytes": live.MAX_BYTES + 1}},
            {"../app.mjs": files["app.mjs"]},
            {str(i): files["app.mjs"] for i in range(live.MAX_FILES + 1)},
        ):
            with (
                patch.object(live, "fetch") as fetch,
                self.assertRaisesRegex(ValueError, "inventory"),
            ):
                live.verify_files("https://example.test", invalid)
            fetch.assert_not_called()

    def test_asset_denial_never_schedules_a_second_batch(self) -> None:
        files = {f"{i:03}.json": {"bytes": 1, "sha256": "unused"} for i in range(16)}
        denied = HTTPError("https://example.test", 403, "Forbidden", Message(), None)
        with patch.object(live, "fetch", side_effect=denied) as fetch, self.assertRaises(HTTPError):
            live.verify_files("https://example.test", files)
        self.assertLessEqual(fetch.call_count, 8)
