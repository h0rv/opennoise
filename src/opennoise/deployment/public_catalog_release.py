"""Promote only the audited public catalog data; code assets follow reviewed commits."""

from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING, Any

from opennoise.pipeline import public_catalog_candidate as candidate

if TYPE_CHECKING:
    from pathlib import Path

PROMOTION = "config/releases/retained-public-catalog-promotion-v1.json"
PROMOTION_SHA256 = "d9d68d05330c01b9056dd3accae4aab331ad4a38039fbbf0c8162d0c51aafcf8"


def digest(value: object) -> str:
    """Hash canonical release metadata independently of filesystem iteration order."""
    return hashlib.sha256(
        (
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
    ).hexdigest()


def promotion(root: Path) -> dict[str, Any]:
    """Require the tracked, fixed approval for this exact public data scope."""
    path = root / PROMOTION
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != PROMOTION_SHA256:
        raise ValueError("Public catalog promotion receipt differs")
    return json.loads(path.read_bytes())


def authorize(manifest: dict[str, Any], approval: dict[str, Any]) -> None:
    """Keep data facts frozen while tested code assets can advance on main merges."""
    data = {
        k: v for k, v in manifest["payload"].items() if k.endswith(".json") and k != "receipt.json"
    }
    if (
        manifest["revision"] != candidate.REVISION
        or manifest["input_contract_sha256"] != approval["input_contract_sha256"]
        or manifest["counts"] != approval["counts"]
        or manifest["private_artifacts_consumed"] is not False
        or manifest["legacy_release_reconstructed"] is not False
        or manifest["acquisitions"] != 0
        or len(data) != approval["data_files"]
        or digest(data) != approval["data_inventory_sha256"]
    ):
        raise ValueError("Candidate differs from the audited public catalog scope")


def release_marker(
    manifest: dict[str, Any], approval: dict[str, Any], commit: str
) -> dict[str, Any]:
    """Bind the production build to its commit and every source-generated served file."""
    authorize(manifest, approval)
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("Release requires a complete Git commit SHA")
    return {
        "revision": "opennoise-retained-public-catalog-release-v1",
        "build_commit": commit,
        "promotion_sha256": PROMOTION_SHA256,
        "input_contract_sha256": approval["input_contract_sha256"],
        "data_inventory_sha256": approval["data_inventory_sha256"],
        "publication_authorized": True,
        "publication_scope": approval["publication_scope"],
        "counts": approval["counts"],
        "files": manifest["payload"],
        "private_artifacts": False,
        "audio_playback": False,
        "musical_relevance_validated": False,
    }
