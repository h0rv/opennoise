"""Promote only the audited public catalog data; code assets follow reviewed commits."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from opennoise.pipeline import artist_network
from opennoise.pipeline import public_catalog_candidate as candidate

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
        k: v
        for k, v in manifest["payload"].items()
        if k.endswith(".json") and k != "receipt.json" and not k.startswith("artist-network/")
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
    network_payload = {
        k: v for k, v in manifest["payload"].items() if k.startswith("artist-network/")
    }
    if network_payload or "artist_network" in manifest:
        artist_network.authorize(
            Path(__file__).resolve().parents[3],
            manifest.get("artist_network", {}),
            manifest["payload"],
        )


def release_marker(
    manifest: dict[str, Any], approval: dict[str, Any], commit: str
) -> dict[str, Any]:
    """Bind the production build to its commit and every source-generated served file."""
    authorize(manifest, approval)
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("Release requires a complete Git commit SHA")
    marker = {
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
    if "artist_network" in manifest:
        marker["artist_network"] = manifest["artist_network"]
        marker["artist_network_promotion_sha256"] = artist_network.PROMOTION_SHA256
        marker["publication_scope"] += "+native-public-cc0-artist-network-v1"
    return marker
