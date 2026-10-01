"""Checks the bounded, byte-verified public static replay boundary."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import cast, override

import httpx

from opennoise.common import canonical_json, sha256_hex
from opennoise.deployment.public_preview_replay import (
    PublicPreviewReplayError,
    build_local_ui_preview,
    replay_public_static_preview,
)


class PublicPreviewReplayTest(unittest.TestCase):
    @override
    def setUp(self) -> None:
        (Path.cwd() / ".cache").mkdir(exist_ok=True)
        self.payloads = {
            "index.html": b"<!doctype html><title>Public OpenNoise</title>",
            "assets/app.css": b"body{color:#123}",
            "assets/atlas.mjs": b"export const atlas = {};",
            "assets/renderer.js": b"export function draw() {}",
            "assets/semantic.json": b'{"nodes":[]}',
            "assets/discovery.json": b'{"artists":[]}',
        }
        self.asset_names = {
            "app_css": "assets/app.css",
            "map_atlas_module": "assets/atlas.mjs",
            "map_renderer_module": "assets/renderer.js",
            "semantic_atlas": "assets/semantic.json",
            "static_discovery": "assets/discovery.json",
        }
        budget = []
        for path in [*self.payloads, "_headers", "_redirects"]:
            payload = self.payloads.get(path, b"unserved hosting policy")
            budget.append(
                {
                    "path": path,
                    "raw_bytes": len(payload),
                    "gzip_bytes": max(1, len(payload) // 2),
                    "sha256": sha256_hex(payload),
                }
            )
        assets = {
            key: {"path": path, "sha256": sha256_hex(self.payloads[path])}
            for key, path in self.asset_names.items()
        }
        self.manifest: dict[str, object] = {
            "revision": "opennoise-semantic-pages-v1",
            "explicit_backend_api_available": False,
            "assets": assets,
            "asset_budget": budget,
        }
        self.manifest["output_sha256"] = sha256_hex(canonical_json(self.manifest))
        self.manifest_bytes = canonical_json(self.manifest)

    def _client(self, requested: list[str]) -> httpx.Client:
        def handler(request: httpx.Request) -> httpx.Response:
            requested.append(str(request.url))
            if request.url.path == "/opennoise-static-manifest.json":
                return httpx.Response(200, content=self.manifest_bytes)
            if request.url.path == "/":
                return httpx.Response(200, content=self.payloads["index.html"])
            path = request.url.path.lstrip("/")
            if path in self.payloads:
                return httpx.Response(200, content=self.payloads[path])
            return httpx.Response(404)

        return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)

    def test_replays_only_public_presentation_and_records_excluded_controls(self) -> None:
        requested: list[str] = []
        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".cache") as temporary:
            output = Path(temporary) / "replay"
            with self._client(requested) as client:
                receipt = replay_public_static_preview(
                    "https://opennoise.horv.co/opennoise-static-manifest.json",
                    output,
                    client=client,
                )
            expected_urls = {
                "https://opennoise.horv.co/",
                *(
                    f"https://opennoise.horv.co/{path}"
                    for path in self.payloads
                    if path != "index.html"
                ),
                "https://opennoise.horv.co/opennoise-static-manifest.json",
            }
            self.assertEqual(expected_urls, set(requested))
            self.assertFalse(any(url.endswith(("/_headers", "/_redirects")) for url in requested))
            for path, payload in self.payloads.items():
                self.assertEqual(payload, output.joinpath(*Path(path).parts).read_bytes())
            self.assertEqual(["_headers", "_redirects"], receipt["excluded_hosting_controls"])
            self.assertFalse(receipt["explicit_backend_api_available"])
            self.assertTrue((output / "public-preview-replay-receipt.json").is_file())
            self.assertTrue((output / "opennoise-static-manifest.json").is_file())
            self.assertEqual(
                self.manifest_bytes,
                (output / "opennoise-static-manifest.json").read_bytes(),
            )

    def test_rejects_noncanonical_manifest_hash_before_fetching_assets(self) -> None:
        requested: list[str] = []
        self.manifest["revision"] = "tampered"
        self.manifest_bytes = json.dumps(self.manifest).encode()
        with (
            tempfile.TemporaryDirectory(dir=Path.cwd() / ".cache") as temporary,
            self._client(requested) as client,
        ):
            output = Path(temporary) / "replay"
            with self.assertRaises(PublicPreviewReplayError):
                replay_public_static_preview(
                    "https://opennoise.horv.co/opennoise-static-manifest.json",
                    output,
                    client=client,
                )
            self.assertFalse(output.exists())
            self.assertEqual(1, len(requested))

    def test_rejects_asset_bytes_that_do_not_match_manifest(self) -> None:
        requested: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested.append(request.url.path)
            if request.url.path == "/opennoise-static-manifest.json":
                return httpx.Response(200, content=self.manifest_bytes)
            if request.url.path == "/":
                return httpx.Response(200, content=b"wrong index")
            return httpx.Response(200, content=b"unused")

        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".cache") as temporary:
            output = Path(temporary) / "replay"
            with (
                httpx.Client(transport=httpx.MockTransport(handler)) as client,
                self.assertRaisesRegex(PublicPreviewReplayError, "byte count mismatch"),
            ):
                replay_public_static_preview(
                    "https://opennoise.horv.co/opennoise-static-manifest.json",
                    output,
                    client=client,
                )
            self.assertFalse(output.exists())

    def test_rejects_unsafe_manifest_asset_path(self) -> None:
        requested: list[str] = []
        manifest_assets = cast("dict[str, dict[str, str]]", self.manifest["assets"])
        manifest_assets["app_css"]["path"] = "assets/%2e%2e/private.css"
        unsigned = dict(self.manifest)
        del unsigned["output_sha256"]
        self.manifest["output_sha256"] = sha256_hex(canonical_json(unsigned))
        self.manifest_bytes = canonical_json(self.manifest)
        with (
            tempfile.TemporaryDirectory(dir=Path.cwd() / ".cache") as temporary,
            self._client(requested) as client,
        ):
            output = Path(temporary) / "replay"
            with self.assertRaisesRegex(PublicPreviewReplayError, "unsafe path"):
                replay_public_static_preview(
                    "https://opennoise.horv.co/opennoise-static-manifest.json",
                    output,
                    client=client,
                )
            self.assertFalse(output.exists())
            self.assertEqual(1, len(requested))

    def test_rejects_assets_colliding_with_generated_receipt_files(self) -> None:
        original = json.loads(self.manifest_bytes)
        for path in (
            "opennoise-static-manifest.json",
            "public-preview-replay-receipt.json",
            "public-preview-replay-receipt.json/asset.css",
        ):
            with self.subTest(path=path):
                self.manifest = json.loads(json.dumps(original))
                assets = cast("dict[str, dict[str, str]]", self.manifest["assets"])
                assets["app_css"]["path"] = path
                rows = cast("list[dict[str, object]]", self.manifest["asset_budget"])
                for row in rows:
                    if row["path"] == "assets/app.css":
                        row["path"] = path
                unsigned = dict(self.manifest)
                del unsigned["output_sha256"]
                self.manifest["output_sha256"] = sha256_hex(canonical_json(unsigned))
                self.manifest_bytes = canonical_json(self.manifest)
                requested: list[str] = []
                with (
                    tempfile.TemporaryDirectory(dir=Path.cwd() / ".cache") as temporary,
                    self._client(requested) as client,
                ):
                    output = Path(temporary) / "replay"
                    with self.assertRaisesRegex(PublicPreviewReplayError, "unsafe"):
                        replay_public_static_preview(
                            "https://opennoise.horv.co/opennoise-static-manifest.json",
                            output,
                            client=client,
                        )
                    self.assertFalse(output.exists())
                    self.assertEqual(1, len(requested))

    def test_stops_streaming_oversized_response_before_output(self) -> None:
        requested: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested.append(request.url.path)
            if request.url.path == "/opennoise-static-manifest.json":
                return httpx.Response(200, content=self.manifest_bytes)
            return httpx.Response(200, content=b"x" * (8_000_001))

        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".cache") as temporary:
            output = Path(temporary) / "replay"
            with (
                httpx.Client(transport=httpx.MockTransport(handler)) as client,
                self.assertRaisesRegex(PublicPreviewReplayError, "bounded size"),
            ):
                replay_public_static_preview(
                    "https://opennoise.horv.co/opennoise-static-manifest.json",
                    output,
                    client=client,
                )
            self.assertFalse(output.exists())
            self.assertEqual(["/opennoise-static-manifest.json", "/"], requested)

    def test_current_ui_preview_retains_exact_data_and_rejects_changed_replay(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".cache") as temporary:
            root = Path(temporary)
            replay = root / "public"
            with self._client([]) as client:
                replay_public_static_preview(
                    "https://opennoise.horv.co/opennoise-static-manifest.json",
                    replay,
                    client=client,
                )
            output = root / "ui"
            receipt = build_local_ui_preview(replay, output)
            self.assertFalse(receipt["public_export_authorized"])
            self.assertFalse(receipt["sealed_source_certification"])
            self.assertIn("local UI preview", (output / "index.html").read_text())
            for key in ("semantic_atlas", "static_discovery"):
                payload = self.payloads[self.asset_names[key]]
                self.assertEqual(sha256_hex(payload), receipt[f"{key}_sha256"])
                self.assertTrue(
                    any(path.read_bytes() == payload for path in (output / "assets").iterdir())
                )
            (replay / self.asset_names["semantic_atlas"]).write_bytes(b"changed")
            with self.assertRaisesRegex(PublicPreviewReplayError, "saved asset"):
                build_local_ui_preview(replay, root / "changed-ui")
            self.assertFalse((root / "changed-ui").exists())

    def test_output_must_stay_inside_cache_without_symlink_components(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".cache") as temporary:
            outside_cache = Path.cwd() / "dist" / "public-replay-test"
            with self.assertRaisesRegex(PublicPreviewReplayError, "contained in the local .cache"):
                replay_public_static_preview(
                    "https://opennoise.horv.co/opennoise-static-manifest.json",
                    outside_cache,
                )
            link = Path.cwd() / ".cache" / "public-preview-replay-link"
            link.symlink_to(Path(temporary), target_is_directory=True)
            try:
                with self.assertRaisesRegex(PublicPreviewReplayError, "symlink"):
                    replay_public_static_preview(
                        "https://opennoise.horv.co/opennoise-static-manifest.json",
                        link / "replay",
                    )
            finally:
                link.unlink()


if __name__ == "__main__":
    unittest.main()
