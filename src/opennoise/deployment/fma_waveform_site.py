"""Closed, local waveform discovery site built only from the reviewed candidate."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from opennoise.deployment.fma_public_candidate import (
    REVIEWED_MANIFEST_SHA256,
    validate_candidate,
)

REVISION = "fma-permitted55-waveform-site-v1"
MAX_SITE_BYTES = 165_000_000
MAX_FILES = 256
EXPECTED_TRACKS = 55
SHA256_LENGTH = 64
MAX_RECEIPT_BYTES = 200_000
PAGE_PATH = Path(__file__).parents[1] / "static" / "fma-waveform-site.html"


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1_000_000):
            digest.update(block)
    return digest.hexdigest()


def _inventory(root: Path) -> dict[str, dict[str, Any]]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Site root must be a regular directory")
    result = {}
    total = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ValueError("Unsupported or symlinked site member")
        if path.is_file():
            name = path.relative_to(root).as_posix()
            if name == "site-receipt.json":
                continue
            size = path.stat().st_size
            total += size
            if total > MAX_SITE_BYTES or len(result) >= MAX_FILES:
                raise ValueError("Site inventory exceeds its bounded budget")
            result[name] = {"bytes": size, "sha256": _hash(path)}
    return result


def _validate_model(pack: Path, manifest: Path) -> dict[str, Any]:
    # The independent producer owns numerical/custody validation. No historical loader.
    from opennoise.ml.fma_waveform_pipeline import validate_waveform_pack  # noqa: PLC0415

    return validate_waveform_pack(pack, manifest)


def validate_waveform_site(directory: Path, pack_inventory_sha256: str) -> dict[str, Any]:
    """Recheck both original closed subtrees and the new interface receipt."""
    receipt_path = directory / "site-receipt.json"
    if receipt_path.is_symlink() or receipt_path.stat().st_size > MAX_RECEIPT_BYTES:
        raise ValueError("Invalid site receipt")
    receipt = json.loads(receipt_path.read_bytes())
    if (
        not isinstance(receipt, dict)
        or set(receipt)
        != {
            "revision",
            "candidate_manifest_sha256",
            "pack_inventory_sha256",
            "layout_sha256",
            "files",
            "public_deployment_authorized",
            "musical_quality_validated",
        }
        or receipt["revision"] != REVISION
        or receipt["candidate_manifest_sha256"] != REVIEWED_MANIFEST_SHA256
        or receipt["pack_inventory_sha256"] != pack_inventory_sha256
        or _hash(directory / "model" / "inventory.json") != pack_inventory_sha256
        or receipt["public_deployment_authorized"] is not False
        or receipt["musical_quality_validated"] is not False
        or receipt["files"] != _inventory(directory)
        or _hash(directory / "index.html") != _hash(PAGE_PATH)
        or receipt["layout_sha256"] != _hash(directory / "model" / "layout.json")
        or {p.name for p in directory.iterdir()}
        != {
            "candidate",
            "model",
            "index.html",
            "site-receipt.json",
        }
    ):
        raise ValueError("Waveform site receipt, scope, or inventory differs")
    manifest = validate_candidate(directory / "candidate", REVIEWED_MANIFEST_SHA256)
    layout = _validate_model(directory / "model", directory / "candidate" / "manifest.json")
    if (
        len(manifest["tracks"]) != EXPECTED_TRACKS
        or {r["track_id"] for r in layout["tracks"]} != {r["track_id"] for r in manifest["tracks"]}
        or layout["candidate_manifest_sha256"] != REVIEWED_MANIFEST_SHA256
    ):
        raise ValueError("Waveform and reviewed candidate rosters differ")
    return receipt


def build_waveform_site(
    candidate: Path, pack: Path, output: Path, pack_inventory_sha256: str
) -> dict[str, Any]:
    """Copy validated inputs without changing a byte of their metadata or audio."""
    if (
        len(pack_inventory_sha256) != SHA256_LENGTH
        or any(c not in "0123456789abcdef" for c in pack_inventory_sha256)
        or _hash(pack / "inventory.json") != pack_inventory_sha256
    ):
        raise ValueError("Model pack does not match the independently supplied inventory pin")
    validate_candidate(candidate, REVIEWED_MANIFEST_SHA256)
    _validate_model(pack, candidate / "manifest.json")
    if output.exists() or output.is_symlink() or any(p.is_symlink() for p in output.parents):
        raise ValueError("Waveform site output must be fresh and nonsymlinked")
    # Validate budgets before materializing, then validate snapshots again after copying.
    candidate_files, model_files = _inventory(candidate), _inventory(pack)
    if (
        sum(r["bytes"] for r in [*candidate_files.values(), *model_files.values()])
        + PAGE_PATH.stat().st_size
        > MAX_SITE_BYTES
        or len(candidate_files) + len(model_files) + 1 > MAX_FILES
    ):
        raise ValueError("Combined site exceeds its bounded budget")
    output.mkdir(parents=True)
    shutil.copytree(candidate, output / "candidate")
    shutil.copytree(pack, output / "model")
    shutil.copyfile(PAGE_PATH, output / "index.html")
    receipt = {
        "revision": REVISION,
        "candidate_manifest_sha256": REVIEWED_MANIFEST_SHA256,
        "pack_inventory_sha256": pack_inventory_sha256,
        "layout_sha256": _hash(output / "model" / "layout.json"),
        "public_deployment_authorized": False,
        "musical_quality_validated": False,
        "files": _inventory(output),
    }
    encoded = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
    if len(encoded) > MAX_RECEIPT_BYTES:
        raise ValueError("Site receipt exceeds its bounded budget")
    (output / "site-receipt.json").write_bytes(encoded)
    return validate_waveform_site(output, pack_inventory_sha256)
