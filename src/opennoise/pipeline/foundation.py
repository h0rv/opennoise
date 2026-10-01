"""Inspect the versioned inputs and stages behind local research builds."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Final, cast

MANIFEST_VERSION: Final = 1

# Paths are deliberately declared at artifact boundaries, rather than claiming
# that every ignored research cache is a portable or complete release input.
FOUNDATION: Final[dict[str, object]] = {
    "version": MANIFEST_VERSION,
    "scope": "reproducibility inventory; not a full-site build recipe",
    "inputs": [
        {
            "id": "canonical-database",
            "path": "data/public.sqlite",
            "required": True,
            "license": "project-controlled public release input",
        },
        {
            "id": "canonical-layout",
            "path": ".cache/semantic-map-layout-v3/artifact.json",
            "required": True,
            "license": "derived project artifact",
        },
        {
            "id": "historical-reference",
            "path": (
                "data/vault/raw/sha256/"
                "1ac0c659a9764536675b2fbc9b52186dd745a537a953855e97090878e74fe180"
            ),
            "required": False,
            "license": "historical evaluation reference; not model or serving input",
        },
        {
            "id": "musicbrainz-source-catalog",
            "path": ".cache/musicbrainz-candidate-catalog-final/receipt.json",
            "required": False,
            "license": (
                "mixed research catalog: core metadata CC0-1.0; "
                "supplementary genre/tag associations CC-BY-NC-SA-3.0"
            ),
        },
        {
            "id": "musicbrainz-tags",
            "path": ".cache/musicbrainz-bulk-artist-tags-20260930-v2/receipt.json",
            "required": False,
            "license": (
                "MusicBrainz tags/genre associations CC-BY-NC-SA-3.0; "
                "optional noncommercial research"
            ),
        },
        {
            "id": "microgenre-features",
            "path": ".cache/microgenre-features-primary-v4/receipt.json",
            "required": False,
            "license": "derived from declared input packs; receipt binds local research artifact",
        },
        {
            "id": "atlas-data",
            "path": ".cache/named-style-atlas-bulk-20260930-final/data.json",
            "required": False,
            "license": "optional noncommercial source-tag research atlas",
        },
        {
            "id": "acoustic-pilot-source",
            "path": (
                ".cache/acousticbrainz-benchmark-metadata-20260930-v1-offline-projection-v2/"
                "receipt.json"
            ),
            "required": False,
            "license": "numeric acoustic metadata CC0; raw MusicBrainz tags excluded from models",
        },
        {
            "id": "expanded-acoustic-source",
            "path": ".cache/acoustic-expanded-metadata-20261001-v1/receipt.json",
            "required": False,
            "license": "AcousticBrainz CC0 numeric metadata and capture provenance",
        },
        {
            "id": "acoustic-demo",
            "path": "data/examples/acoustic-descriptors/acoustic-descriptors.json",
            "required": True,
            "license": "CC0-1.0; numeric projected metadata with source attribution",
        },
        {
            "id": "acoustic-demo-receipt",
            "path": "data/examples/acoustic-descriptors/receipt.json",
            "required": True,
            "license": "CC0-1.0 provenance receipt with source hashes",
        },
        {
            "id": "credited-music-demo",
            "path": "data/examples/representative-music/credited-examples.json",
            "required": True,
            "license": "MusicBrainz core metadata CC0 1.0",
        },
        {
            "id": "credited-music-demo-receipt",
            "path": "data/examples/representative-music/receipt.json",
            "required": True,
            "license": "MusicBrainz CC0 projection hash and source capture attribution",
        },
        {
            "id": "cultural-context-example",
            "path": "data/examples/cultural-context/receipt.json",
            "required": True,
            "license": "Wikidata CC0 raw responses and sanitized portable projections",
        },
        {
            "id": "outbound-link-example",
            "path": "data/examples/artist-links/receipt.json",
            "required": True,
            "license": "MusicBrainz CC0 artist URL relationships; no destination content",
        },
    ],
    "stages": [
        {
            "id": "checkout",
            "needs": [],
            "command": "poe sync && poe check",
            "purpose": "install dependencies and validate the checkout",
        },
        {
            "id": "portable-examples",
            "needs": [
                "acoustic-demo",
                "acoustic-demo-receipt",
                "credited-music-demo",
                "credited-music-demo-receipt",
            ],
            "command": (
                ".venv/bin/python scripts/demo_acoustic_descriptors.py && "
                ".venv/bin/python scripts/rerank_projected_artist_work_examples.py "
                "data/examples/representative-music/credited-examples.json "
                "--receipt data/examples/representative-music/receipt.json "
                "--output .cache/foundation-demo/representative-music.json"
            ),
            "purpose": (
                "replay numeric descriptors and exact artist-credited work "
                "examples from checked-in CC0 projections"
            ),
        },
        {
            "id": "canonical-static-release",
            "needs": ["canonical-database", "canonical-layout"],
            "command": "poe build",
            "purpose": "build and certify the canonical static export",
        },
        {
            "id": "portable-cultural-context",
            "needs": ["cultural-context-example"],
            "command": (
                ".venv/bin/python scripts/probe_open_cultural_sources.py "
                "--verify-pack --pack-output data/examples/cultural-context"
            ),
            "purpose": "replay independent direct Wikidata claims and property-specific overlaps",
        },
        {
            "id": "portable-listening-links",
            "needs": ["outbound-link-example"],
            "command": (
                ".venv/bin/python scripts/verify_artist_outbound_links.py "
                "data/examples/artist-links"
            ),
            "purpose": "verify source-declared outbound destinations without requesting media",
        },
        {
            "id": "historical-parity-evaluation",
            "needs": ["historical-reference", "atlas-data"],
            "command": (
                "poe bootstrap && .venv/bin/python scripts/evaluate_reference_benchmark.py "
                "--reference data/vault/raw/sha256/"
                "1ac0c659a9764536675b2fbc9b52186dd745a537a953855e97090878e74fe180 "
                "--atlas .cache/named-style-atlas-bulk-20260930-final "
                "--output .cache/parity-report.json"
            ),
            "purpose": "evaluate a dated reference against a separately built preview",
        },
        {
            "id": "acoustic-representation-research",
            "needs": ["acoustic-pilot-source", "expanded-acoustic-source"],
            "command": (
                ".venv/bin/python scripts/build_acoustic_representation_pilot.py "
                "--source "
                ".cache/acousticbrainz-benchmark-metadata-20260930-v1-offline-projection-v2 "
                "--expanded .cache/acoustic-expanded-metadata-20261001-v1 "
                "--output .cache/acoustic-foundation-replay"
            ),
            "purpose": (
                "verify raw capture lineage and build separate sonic/cultural research neighbors"
            ),
        },
        {
            "id": "open-source-explorer",
            "needs": ["musicbrainz-source-catalog"],
            "command": (
                "See docs/checkpoints/SOURCE_MODEL_UI_BATCH_20260930.md "
                "(build_local_musicbrainz_candidate_catalog.py → "
                "enrich_local_musicbrainz_genre_labels.py → "
                "build_direct_custody_neighborhoods.py → "
                "build_local_direct_custody_preview.py)"
            ),
            "purpose": (
                "rebuild an exploratory source-only atlas; output destinations "
                "must be chosen by the operator"
            ),
        },
        {
            "id": "enriched-community-research",
            "needs": ["musicbrainz-tags", "microgenre-features"],
            "command": "See docs/checkpoints/EMERGENT_COMMUNITY_EVALUATION_CONTRACT_20260930.md",
            "purpose": "optional source enrichment and evaluation; tag pack is noncommercial",
        },
    ],
}


def _hash(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_path(root: Path, relative: str) -> Path:
    """Resolve a declared relative input without allowing symlink escapes."""
    candidate = root / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError(f"manifest input must stay relative to root: {relative}")
    current = root
    for part in Path(relative).parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"manifest input traverses symlink: {relative}")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"manifest input escapes root: {relative}")
    return candidate


def inspect(root: Path, manifest: dict[str, object] | None = None) -> dict[str, object]:
    """Return stable input statuses and per-stage hashes for *root*."""
    source = FOUNDATION if manifest is None else manifest
    validate_manifest(source)
    entries = source["inputs"]
    assert isinstance(entries, list)  # noqa: S101 - validated schema narrows this shape.
    statuses: dict[str, dict[str, object]] = {}
    for item in entries:
        path = _safe_path(root, item["path"])
        exists = path.is_file() and not path.is_symlink()
        digest = _hash(path) if exists and path.is_file() else None
        statuses[item["id"]] = {
            "path": item["path"],
            "exists": exists,
            "sha256": digest,
            "hash_scope": "file bytes" if digest else None,
            "required": item["required"],
            "license": item["license"],
        }
    stages = source["stages"]
    assert isinstance(stages, list)  # noqa: S101 - validated schema narrows this shape.
    reports = []
    for stage in stages:
        needs = stage["needs"]
        missing = [name for name in needs if not statuses[name]["exists"]]
        basis = {
            "manifest_version": MANIFEST_VERSION,
            "stage": stage,
            "inputs": {name: statuses[name] for name in needs},
        }
        fingerprint = hashlib.sha256(json.dumps(basis, sort_keys=True).encode()).hexdigest()
        reports.append(
            {**stage, "missing_inputs": missing, "ready": not missing, "stage_sha256": fingerprint}
        )
    return {
        "manifest_version": source["version"],
        "root": str(root),
        "inputs": list(statuses.values()),
        "stages": reports,
    }


def render_plan(root: Path, manifest: dict[str, object] | None = None) -> str:
    """Render a compact human-readable plan."""
    source = FOUNDATION if manifest is None else manifest
    report = inspect(root, source)
    lines = [f"Foundation manifest v{source['version']} — {source['scope']}", "Inputs:"]
    for item in cast("list[dict[str, object]]", report["inputs"]):
        status = "present" if item["exists"] else "MISSING"
        lines.append(f"  {status:7} {item['path']} — {item['license']}")
    lines.append("Stages:")
    for stage in cast("list[dict[str, object]]", report["stages"]):
        missing_inputs = cast("list[str]", stage["missing_inputs"])
        missing = f"; missing {', '.join(missing_inputs)}" if missing_inputs else ""
        lines.extend(
            [
                f"  {'ready' if stage['ready'] else 'blocked':7} {stage['id']}{missing}",
                f"    {stage['command']}",
                f"    sha256 {stage['stage_sha256']}",
            ]
        )
    return "\n".join(lines)


def validate_manifest(manifest: dict[str, object] | None = None) -> None:  # noqa: C901, PLR0912
    """Reject unsupported or malformed manifest schemas."""
    source = FOUNDATION if manifest is None else manifest
    if not isinstance(source, dict):
        raise TypeError("manifest must be an object")
    if set(source) != {"version", "scope", "inputs", "stages"}:
        raise ValueError("manifest has unknown or missing top-level fields")
    if not isinstance(source["scope"], str):
        raise TypeError("manifest scope must be a string")
    if isinstance(source["version"], bool) or source["version"] != MANIFEST_VERSION:
        raise ValueError(f"unsupported manifest version: {source['version']}")
    if not isinstance(source["inputs"], list) or not isinstance(source["stages"], list):
        raise TypeError("manifest inputs and stages must be lists")
    input_ids: set[str] = set()
    for item in source["inputs"]:
        if not isinstance(item, dict) or set(item) != {"id", "path", "required", "license"}:
            raise ValueError("malformed input declaration")
        if (
            not isinstance(item["id"], str)
            or not item["id"]
            or not isinstance(item["required"], bool)
            or not isinstance(item["license"], str)
        ):
            raise TypeError("input id, required flag, or license has the wrong type")
        if item["id"] in input_ids:
            raise ValueError(f"duplicate input id: {item['id']}")
        input_ids.add(item["id"])
        if (
            not isinstance(item["path"], str)
            or not item["path"]
            or Path(item["path"]).is_absolute()
            or ".." in Path(item["path"]).parts
        ):
            raise ValueError(f"unsafe input path: {item['path']}")
    stage_ids: set[str] = set()
    for stage in source["stages"]:
        if not isinstance(stage, dict) or set(stage) != {"id", "needs", "command", "purpose"}:
            raise ValueError("malformed stage declaration")
        if not all(isinstance(stage[field], str) for field in ("id", "command", "purpose")):
            raise ValueError("stage id, command, and purpose must be strings")
        if stage["id"] in stage_ids:
            raise ValueError(f"duplicate stage id: {stage['id']}")
        stage_ids.add(stage["id"])
        if not isinstance(stage["needs"], list) or any(
            not isinstance(name, str) or name not in input_ids for name in stage["needs"]
        ):
            raise ValueError(f"stage {stage['id']} refers to unknown inputs")
