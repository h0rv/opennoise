"""Versioned artist-recording/source-tag discovery over unchanged reviewed inputs."""

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
from opennoise.deployment.fma_waveform_site import MAX_FILES, MAX_RECEIPT_BYTES, MAX_SITE_BYTES
from opennoise.ml.fma_waveform_pipeline import validate_waveform_pack

REVISION = "fma-permitted55-profile-site-v1"
PAGE_PATH = Path(__file__).parents[1] / "static" / "fma-profile-site.html"
SHA_LENGTH = 64


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1_000_000):
            digest.update(block)
    return digest.hexdigest()


def _inventory(root: Path, *, site: bool = False) -> dict[str, Any]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Input must be a nonsymlinked directory")
    files, size, count = {}, 0, 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError("Unsupported discovery site member")
        if path.is_file():
            name = path.relative_to(root).as_posix()
            count += 1
            size += path.stat().st_size
            if count > MAX_FILES or size > MAX_SITE_BYTES:
                raise ValueError("Closed discovery site exceeds unchanged budget")
            if not (site and name == "site-receipt.json"):
                files[name] = {"bytes": path.stat().st_size, "sha256": _hash(path)}
    return files


def _pin(directory: Path, expected: str) -> None:
    if (
        len(expected) != SHA_LENGTH
        or any(c not in "0123456789abcdef" for c in expected)
        or (directory / "inventory.json").is_symlink()
        or _hash(directory / "inventory.json") != expected
    ):
        raise ValueError("Pack differs from independently supplied inventory pin")


def _discovery(pack: Path, manifest: Path, model: Path, pin: str) -> dict[str, Any]:
    from opennoise.ml.fma_recording_profiles import validate_discovery_pack  # noqa: PLC0415

    return validate_discovery_pack(pack, manifest, model, pin)


def _inputs(
    candidate: Path, model: Path, discovery: Path, model_pin: str, discovery_pin: str
) -> None:
    _pin(model, model_pin)
    _pin(discovery, discovery_pin)
    validate_candidate(candidate, REVIEWED_MANIFEST_SHA256)
    validate_waveform_pack(model, candidate / "manifest.json")
    _discovery(discovery, candidate / "manifest.json", model, discovery_pin)


def validate_profile_site(directory: Path, model_pin: str, discovery_pin: str) -> dict[str, Any]:
    """Verify closed nested inputs, exact page, and both external artifact pins."""
    path = directory / "site-receipt.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_RECEIPT_BYTES:
        raise ValueError("Invalid profile site receipt")
    receipt = json.loads(path.read_bytes())
    if (
        not isinstance(receipt, dict)
        or set(receipt)
        != {
            "revision",
            "candidate_manifest_sha256",
            "model_inventory_sha256",
            "discovery_inventory_sha256",
            "files",
            "public_deployment_authorized",
            "musical_quality_validated",
        }
        or receipt["revision"] != REVISION
        or receipt["candidate_manifest_sha256"] != REVIEWED_MANIFEST_SHA256
        or receipt["model_inventory_sha256"] != model_pin
        or receipt["discovery_inventory_sha256"] != discovery_pin
        or receipt["public_deployment_authorized"] is not False
        or receipt["musical_quality_validated"] is not False
        or receipt["files"] != _inventory(directory, site=True)
        or _hash(directory / "index.html") != _hash(PAGE_PATH)
        or {p.name for p in directory.iterdir()}
        != {"candidate", "model", "discovery", "index.html", "site-receipt.json"}
    ):
        raise ValueError("Profile site inventory, page or scope differs")
    _inputs(
        directory / "candidate",
        directory / "model",
        directory / "discovery",
        model_pin,
        discovery_pin,
    )
    return receipt


def build_profile_site(  # noqa: PLR0913, PLR0917 -- three explicit separately bound inputs.
    candidate: Path,
    model: Path,
    discovery: Path,
    output: Path,
    model_pin: str,
    discovery_pin: str,
) -> dict[str, Any]:
    """Create a separate site without changing any prior site, model or recording."""
    _inputs(candidate, model, discovery, model_pin, discovery_pin)
    inventories = [_inventory(p) for p in (candidate, model, discovery)]
    if (
        sum(len(i) for i in inventories) + 2 > MAX_FILES
        or sum(r["bytes"] for i in inventories for r in i.values())
        + PAGE_PATH.stat().st_size
        + MAX_RECEIPT_BYTES
        > MAX_SITE_BYTES
    ):
        raise ValueError("New site exceeds unchanged combined export budget")
    if output.exists() or output.is_symlink() or any(p.is_symlink() for p in output.parents):
        raise ValueError("Profile site output must be fresh and nonsymlinked")
    output.mkdir(parents=True)
    for name, source in (("candidate", candidate), ("model", model), ("discovery", discovery)):
        shutil.copytree(source, output / name)
    shutil.copyfile(PAGE_PATH, output / "index.html")
    receipt = {
        "revision": REVISION,
        "candidate_manifest_sha256": REVIEWED_MANIFEST_SHA256,
        "model_inventory_sha256": model_pin,
        "discovery_inventory_sha256": discovery_pin,
        "files": _inventory(output, site=True),
        "public_deployment_authorized": False,
        "musical_quality_validated": False,
    }
    body = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
    if len(body) > MAX_RECEIPT_BYTES:
        raise ValueError("Profile site receipt exceeds metadata budget")
    (output / "site-receipt.json").write_bytes(body)
    return validate_profile_site(output, model_pin, discovery_pin)
