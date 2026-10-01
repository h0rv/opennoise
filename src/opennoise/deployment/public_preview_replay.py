"""Bounded replay of the currently served OpenNoise static presentation."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Final, TypedDict, cast
from urllib.parse import urljoin, urlparse

import httpx

from opennoise.common import canonical_json, sha256_hex
from opennoise.deployment import semantic_pages

_REVISION: Final = "opennoise-semantic-pages-v1"
_EXPECTED_ASSETS: Final = {
    "app_css",
    "map_atlas_module",
    "map_renderer_module",
    "semantic_atlas",
    "static_discovery",
}
_CONTROL_PATHS: Final = {"_headers", "_redirects"}
_RESERVED_OUTPUT_PATHS: Final = {
    "opennoise-static-manifest.json",
    "public-preview-replay-receipt.json",
}
_HASH_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_MAX_MANIFEST_BYTES: Final = 1_000_000
_MAX_ASSET_BYTES: Final = 8_000_000
_MAX_TOTAL_BYTES: Final = 12_000_000
_MAX_GZIP_BYTES: Final = 8_000_000


class PublicPreviewReplayError(ValueError):
    """The public manifest or a fetched public asset failed validation."""


class _BudgetEntry(TypedDict):
    path: str
    raw_bytes: int
    gzip_bytes: int
    sha256: str


class _ValidatedManifest(TypedDict):
    origin: str
    budget: dict[str, _BudgetEntry]
    fetch_paths: list[str]


def replay_public_static_preview(  # noqa: C901, PLR0915
    manifest_url: str,
    output_dir: Path,
    *,
    client: httpx.Client | None = None,
) -> dict[str, object]:
    """Fetch and atomically store the bounded public static export and receipt."""
    parsed_manifest_url = urlparse(manifest_url)
    if parsed_manifest_url.scheme != "https" or not parsed_manifest_url.netloc:
        raise PublicPreviewReplayError("manifest URL must use HTTPS")
    output_dir = _validated_output_path(output_dir)
    if output_dir.exists() or output_dir.is_symlink():
        raise PublicPreviewReplayError(f"output already exists: {output_dir}")
    owns_client = client is None
    active_client = client or httpx.Client(follow_redirects=False, timeout=30.0)
    try:
        manifest_bytes = _fetch_bounded(
            active_client, manifest_url, "manifest", _MAX_MANIFEST_BYTES
        )
        try:
            manifest = json.loads(manifest_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PublicPreviewReplayError("manifest is not valid JSON") from exc
        validated = _validate_manifest(manifest)
        validated["origin"] = f"{parsed_manifest_url.scheme}://{parsed_manifest_url.netloc}"

        manifest_byte_sha = sha256_hex(manifest_bytes)
        if output_dir.exists() or output_dir.is_symlink():
            raise PublicPreviewReplayError(f"output already exists: {output_dir}")
        stage = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.stage-", dir=output_dir.parent))
        try:
            fetched: list[dict[str, object]] = []
            total = 0
            for raw_path in validated["fetch_paths"]:
                path = str(raw_path)
                entry = validated["budget"][path]
                url = (
                    f"{validated['origin']}/"
                    if path == "index.html"
                    else urljoin(f"{validated['origin']}/", path)
                )
                payload = _fetch_bounded(active_client, url, path, _MAX_ASSET_BYTES)
                total += len(payload)
                if len(payload) > _MAX_ASSET_BYTES or total > _MAX_TOTAL_BYTES:
                    _raise_size_limit()
                if len(payload) != entry["raw_bytes"]:
                    _raise_byte_count(path)
                digest = sha256_hex(payload)
                if digest != entry["sha256"]:
                    _raise_hash_mismatch(path)
                destination = stage.joinpath(*Path(path).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(payload)
                fetched.append({"path": path, "byte_count": len(payload), "sha256": digest})

            (stage / "opennoise-static-manifest.json").write_bytes(manifest_bytes)
            receipt: dict[str, object] = {
                "revision": "opennoise-public-static-replay-v1",
                "manifest_url": manifest_url,
                "manifest_output_sha256": manifest["output_sha256"],
                "manifest_byte_sha256": manifest_byte_sha,
                "manifest_revision": manifest["revision"],
                "explicit_backend_api_available": False,
                "delivery_mode": "static-only",
                "fetched_assets": fetched,
                "excluded_hosting_controls": sorted(_CONTROL_PATHS),
                "observation_scope": (
                    "Observed public static presentation bytes only. This receipt does not "
                    "certify source database lineage, model training, or build provenance."
                ),
            }
            receipt["receipt_logical_sha256"] = sha256_hex(canonical_json(receipt))
            (stage / "public-preview-replay-receipt.json").write_bytes(
                canonical_json(receipt) + b"\n"
            )
            try:
                stage.rename(output_dir)
            except FileExistsError as exc:
                raise PublicPreviewReplayError(f"output already exists: {output_dir}") from exc
            return receipt  # noqa: TRY300
        except BaseException:
            shutil.rmtree(stage, ignore_errors=True)
            raise
    finally:
        if owns_client:
            active_client.close()


def build_local_ui_preview(replay_dir: Path, output_dir: Path) -> dict[str, object]:
    """Bind the current UI to verified public JSON without certifying a release."""
    output_dir = _validated_output_path(output_dir)
    if output_dir.exists() or output_dir.is_symlink():
        raise PublicPreviewReplayError(f"output already exists: {output_dir}")
    manifest_bytes = (replay_dir / "opennoise-static-manifest.json").read_bytes()
    if len(manifest_bytes) > _MAX_MANIFEST_BYTES:
        raise PublicPreviewReplayError("saved manifest exceeds the bounded size")
    manifest = json.loads(manifest_bytes)
    validated = _validate_manifest(manifest)
    replay_receipt = json.loads((replay_dir / "public-preview-replay-receipt.json").read_bytes())
    _verify_saved_receipt(replay_receipt, manifest_bytes, manifest["output_sha256"])
    for path in validated["fetch_paths"]:
        asset = replay_dir / path
        expected = validated["budget"][path]
        if asset.is_symlink() or asset.stat().st_size != expected["raw_bytes"]:
            raise PublicPreviewReplayError(f"saved asset byte count mismatch for {path}")
        if sha256_hex(asset.read_bytes()) != expected["sha256"]:
            raise PublicPreviewReplayError(f"saved asset SHA-256 mismatch for {path}")
    stage = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.stage-", dir=output_dir.parent))
    try:
        assets = stage / "assets"
        assets.mkdir()
        source_paths = manifest["assets"]
        atlas_path = Path(source_paths["semantic_atlas"]["path"])
        atlas = assets / atlas_path.name
        shutil.copyfile(replay_dir / atlas_path, atlas)
        discovery_path = Path(source_paths["static_discovery"]["path"])
        paths = semantic_pages._export_fingerprinted_assets(  # noqa: SLF001
            assets, atlas, (replay_dir / discovery_path).read_bytes()
        )
        html = semantic_pages._html(paths).replace(  # noqa: SLF001
            "<title>OpenNoise</title>", "<title>OpenNoise · local UI preview</title>"
        )
        (stage / "index.html").write_text(html, encoding="utf-8")
        receipt: dict[str, object] = {
            "revision": "opennoise-local-ui-preview-v1",
            "scope": "local_modified_presentation_only",
            "public_export_authorized": False,
            "sealed_source_certification": False,
            "source_replay_receipt_sha256": replay_receipt["receipt_logical_sha256"],
            "source_manifest_sha256": manifest["output_sha256"],
            "semantic_atlas_sha256": source_paths["semantic_atlas"]["sha256"],
            "static_discovery_sha256": source_paths["static_discovery"]["sha256"],
            "files": semantic_pages._asset_budget(stage),  # noqa: SLF001
        }
        receipt["output_sha256"] = sha256_hex(canonical_json(receipt))
        (stage / "local-ui-preview-receipt.json").write_bytes(canonical_json(receipt) + b"\n")
        stage.rename(output_dir)
        return receipt  # noqa: TRY300
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def _verify_saved_receipt(receipt: object, manifest_bytes: bytes, manifest_sha256: str) -> None:
    if not isinstance(receipt, dict):
        raise PublicPreviewReplayError("saved replay receipt must be an object")
    unsigned = dict(receipt)
    digest = unsigned.pop("receipt_logical_sha256", None)
    if (
        digest != sha256_hex(canonical_json(unsigned))
        or receipt.get("revision") != "opennoise-public-static-replay-v1"
        or receipt.get("manifest_byte_sha256") != sha256_hex(manifest_bytes)
        or receipt.get("manifest_output_sha256") != manifest_sha256
    ):
        raise PublicPreviewReplayError("saved replay receipt or manifest binding mismatch")


def _validate_manifest(manifest: object) -> _ValidatedManifest:  # noqa: C901, PLR0912, PLR0915
    if not isinstance(manifest, dict):
        raise PublicPreviewReplayError("manifest must be a JSON object")
    if manifest.get("revision") != _REVISION:
        raise PublicPreviewReplayError("unsupported static manifest revision")
    if manifest.get("explicit_backend_api_available") is not False:
        raise PublicPreviewReplayError("manifest does not declare static-only delivery")
    output_sha = manifest.get("output_sha256")
    if not isinstance(output_sha, str) or not _HASH_RE.fullmatch(output_sha):
        raise PublicPreviewReplayError("manifest output_sha256 is malformed")
    unsigned = dict(manifest)
    del unsigned["output_sha256"]
    if sha256_hex(canonical_json(unsigned)) != output_sha:
        raise PublicPreviewReplayError("manifest canonical logical hash mismatch")

    assets = manifest.get("assets")
    budget_rows = manifest.get("asset_budget")
    if not isinstance(assets, dict) or set(assets) != _EXPECTED_ASSETS:
        raise PublicPreviewReplayError("manifest assets do not match the expected asset set")
    if not isinstance(budget_rows, list):
        raise PublicPreviewReplayError("manifest asset_budget must be a list")
    budget: dict[str, _BudgetEntry] = {}
    for row in budget_rows:
        if not isinstance(row, dict) or set(row) != {"path", "raw_bytes", "gzip_bytes", "sha256"}:
            raise PublicPreviewReplayError("malformed asset_budget row")
        path = row["path"]
        if not isinstance(path, str) or not _safe_relative_path(path):
            raise PublicPreviewReplayError("asset_budget contains an unsafe relative path")
        if path in budget:
            raise PublicPreviewReplayError("asset_budget contains duplicate paths")
        raw_bytes, gzip_bytes, digest = row["raw_bytes"], row["gzip_bytes"], row["sha256"]
        if type(raw_bytes) is not int or not 0 < raw_bytes <= _MAX_ASSET_BYTES:
            raise PublicPreviewReplayError(f"invalid raw byte count for {path}")
        if type(gzip_bytes) is not int or not 0 < gzip_bytes <= _MAX_GZIP_BYTES:
            raise PublicPreviewReplayError(f"invalid gzip byte count for {path}")
        if not isinstance(digest, str) or not _HASH_RE.fullmatch(digest):
            raise PublicPreviewReplayError(f"invalid SHA-256 for {path}")
        budget[path] = cast("_BudgetEntry", row)
    expected_paths = {"index.html", *_CONTROL_PATHS}
    fetch_paths = ["index.html"]
    for key in sorted(assets):
        asset = assets[key]
        if not isinstance(asset, dict) or set(asset) != {"path", "sha256"}:
            raise PublicPreviewReplayError(f"malformed manifest asset {key}")
        path, digest = asset["path"], asset["sha256"]
        if not isinstance(path, str) or not _safe_relative_path(path):
            raise PublicPreviewReplayError(f"unsafe path for manifest asset {key}")
        if path in expected_paths:
            raise PublicPreviewReplayError("manifest asset paths must be unique")
        if not isinstance(digest, str) or not _HASH_RE.fullmatch(digest):
            raise PublicPreviewReplayError(f"malformed SHA-256 for manifest asset {key}")
        expected_paths.add(path)
        fetch_paths.append(path)
        row = budget.get(path)
        if row is None or row["sha256"] != digest:
            raise PublicPreviewReplayError(f"asset_budget does not match manifest asset {key}")
    if set(budget) != expected_paths:
        raise PublicPreviewReplayError("asset_budget paths do not exactly match expected paths")
    for path in _CONTROL_PATHS:
        if path not in budget:
            raise PublicPreviewReplayError(f"asset_budget is missing hosting control {path}")
    for path in fetch_paths:
        if path not in budget:
            raise PublicPreviewReplayError(f"asset_budget is missing fetched asset {path}")
    budget_total = sum(int(row["raw_bytes"]) for row in budget.values())
    if budget_total > _MAX_TOTAL_BYTES:
        raise PublicPreviewReplayError("manifest asset_budget exceeds total size limit")
    return {"origin": "", "budget": budget, "fetch_paths": fetch_paths}


def _safe_relative_path(path: str) -> bool:
    if (
        not path
        or path.startswith(("/", "\\"))
        or "\\" in path
        or any(marker in path for marker in (":", "?", "#", "%"))
    ):
        return False
    parts = path.split("/")
    return parts[0] not in _RESERVED_OUTPUT_PATHS and all(
        part not in {"", ".", ".."} for part in parts
    )


def _require_success(response: httpx.Response, label: str) -> None:
    if response.status_code != _OK_STATUS:
        raise PublicPreviewReplayError(f"HTTP {response.status_code} while fetching {label}")


def _fetch_bounded(client: httpx.Client, url: str, label: str, limit: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    try:
        with client.stream("GET", url) as response:
            _require_success(response, label)
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > limit:
                    raise PublicPreviewReplayError(f"{label} exceeds the bounded size")
                chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise PublicPreviewReplayError(f"HTTP error while fetching {label}: {exc}") from exc
    return b"".join(chunks)


_OK_STATUS: Final = 200


def _raise_size_limit() -> None:
    raise PublicPreviewReplayError("public assets exceed bounded size limits")


def _raise_byte_count(path: str) -> None:
    raise PublicPreviewReplayError(f"byte count mismatch for {path}")


def _raise_hash_mismatch(path: str) -> None:
    raise PublicPreviewReplayError(f"SHA-256 mismatch for {path}")


def _validated_output_path(output_dir: Path) -> Path:
    cwd = Path.cwd().resolve()
    cache_root = cwd / ".cache"
    if cache_root.is_symlink():
        raise PublicPreviewReplayError(".cache output root must not be a symlink")
    cache_root.mkdir(parents=True, exist_ok=True)
    raw_output = output_dir if output_dir.is_absolute() else cwd / output_dir
    normalized = Path(os.path.normpath(raw_output))
    try:
        relative = normalized.relative_to(cache_root)
    except ValueError as exc:
        raise PublicPreviewReplayError(
            "output must be contained in the local .cache directory"
        ) from exc
    if not relative.parts:
        raise PublicPreviewReplayError("output must name a new directory under .cache")
    cursor = cache_root
    for part in relative.parts[:-1]:
        cursor = cursor / part
        if cursor.is_symlink():
            raise PublicPreviewReplayError("output path must not traverse a symlink")
    if normalized.is_symlink():
        raise PublicPreviewReplayError("output path must not be a symlink")
    normalized.parent.mkdir(parents=True, exist_ok=True)
    return normalized
