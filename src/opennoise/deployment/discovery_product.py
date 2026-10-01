"""Compose verified local explorers without changing source or model artifacts."""

from __future__ import annotations

import errno
import json
import os
import shutil
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, override
from urllib.parse import unquote, urlsplit

from opennoise.catalog.musicbrainz_candidate import require_local_candidate_destination
from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.deployment.community_preview import verified_receipt

_RECEIPT = "receipt.json"
_SHA256_LENGTH = 64
_NAVIGATION_FILES = ("index.html", "communities/index.html", "communities/source-explorer.html")


def _binding(path: Path) -> dict[str, Any]:
    return {"sha256": sha256_file(path)[0], "bytes": path.stat().st_size}


def _require_local_parent(receipt: dict[str, Any], revision: str) -> None:
    if (
        receipt.get("revision") != revision
        or receipt.get("scope") != "local_research_only"
        or receipt.get("public_export_authorized") is not False
        or receipt.get("serving_authorized") is not False
        or receipt.get("native_genre_memberships_added") != 0
        or isinstance(receipt.get("native_genre_memberships_added"), bool)
    ):
        raise ValueError("unsupported local discovery parent boundary")
    for key in ("features_sha256", "feature_receipt_sha256", "source_preview_output_sha256"):
        value = receipt.get(key)
        if (
            not isinstance(value, str)
            or len(value) != _SHA256_LENGTH
            or set(value) - set("0123456789abcdef")
        ):
            raise ValueError("missing exact parent lineage digest")


def _require_paths(source: Path, receipt: dict[str, Any]) -> None:
    for relative in receipt["files"]:
        path = Path(relative)
        if path.as_posix() != relative or any(part in {".", ".."} for part in path.parts):
            raise ValueError("noncanonical parent artifact path")
        if any(parent.is_symlink() for parent in (source / path).parents if parent != source):
            raise ValueError("symlinked parent artifact directory")


def _copy_artifact(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
        shutil.copyfile(source, destination)


def _navigation(relative: str) -> str:
    prefix = "" if relative == "index.html" else "../"
    links = (
        (prefix + "index.html", "Named styles"),
        (prefix + "communities/index.html", "Inferred communities"),
        (prefix + "communities/source-explorer.html", "Source genres"),
    )
    return (
        '<nav id="discovery-navigation" aria-label="Discovery explorers">'
        + " · ".join(f'<a href="{target}">{label}</a>' for target, label in links)
        + "</nav>"
    )


def _replace_navigation(path: Path, relative: str) -> None:
    html = path.read_text(encoding="utf-8")
    if html.count("</header>") != 1 or html.count("</head>") != 1:
        raise ValueError("explorer requires one navigation header and document head")
    desktop_height = 136 if relative == "index.html" else 156
    styles = (
        '<style id="discovery-navigation-style">'
        "#discovery-navigation{display:flex;gap:12px;align-items:center;"
        "height:38px;padding:0 18px;font-size:11px;overflow-x:auto;white-space:nowrap;"
        "border-bottom:1px solid #dfe5da;background:#fafbf7}"
        "#discovery-navigation a{color:#357d70;text-decoration:none}"
        f".workspace{{height:calc(100dvh - {desktop_height}px)}}"
        "@media(max-width:850px){.masthead~.workspace{height:calc(100dvh - 144px)}}"
        "@media(max-width:720px){.header~.workspace{height:auto}}"
        "@media(max-width:620px){.masthead~.workspace{height:auto}"
        "#discovery-navigation{gap:9px;font-size:10px;padding:0 12px}}"
        "</style>"
    )
    html = html.replace("</head>", styles + '<link rel="icon" href="data:,"></head>')
    html = html.replace("</header>", "</header>" + _navigation(relative))
    if relative.startswith("communities/"):
        for name in ("community-preview-receipt.json", "preview-receipt.json"):
            html = html.replace(f'href="{name}"', 'href="../receipt.json"')
    temporary = path.with_suffix(".navigation.tmp")
    temporary.write_text(html, encoding="utf-8")
    temporary.replace(path)


class _LocalReferences(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if not tag:
            return
        for key, value in attrs:
            if key in {"href", "src"} and value is not None:
                self.references.append(value)


def _require_html_targets(output: Path, relative: str, declared: set[str]) -> None:
    parser = _LocalReferences()
    parser.feed((output / relative).read_text(encoding="utf-8"))
    for reference in parser.references:
        url = urlsplit(reference)
        if url.scheme or url.netloc or not url.path:
            continue
        target = (output / relative).parent / unquote(url.path)
        if target.is_dir():
            target /= "index.html"
        resolved = target.resolve()
        if not resolved.is_relative_to(output.resolve()):
            raise ValueError("HTML reference escapes local product")
        if resolved.relative_to(output.resolve()).as_posix() not in declared:
            raise ValueError(f"HTML reference has no bound product target: {reference}")


def _require_parent_pair(
    atlas: Path,
    atlas_receipt: dict[str, Any],
    communities: Path,
    community_receipt: dict[str, Any],
) -> dict[str, Any]:
    _require_local_parent(atlas_receipt, "named-source-style-atlas-v1")
    _require_local_parent(community_receipt, "emergent-community-local-preview-v1")
    for key in ("features_sha256", "feature_receipt_sha256", "source_preview_output_sha256"):
        if atlas_receipt[key] != community_receipt[key]:
            raise ValueError(f"discovery parent lineage differs: {key}")
    if atlas_receipt.get("source_licenses") != community_receipt.get("source_licenses"):
        raise ValueError("discovery parent licenses differ")
    enrichment = community_receipt.get("enrichment_prediction_output_sha256")
    if enrichment is not None and enrichment != atlas_receipt.get("prediction_output_sha256"):
        raise ValueError("discovery parent enrichment prediction identities differ")
    _require_paths(atlas, atlas_receipt)
    _require_paths(communities, community_receipt)
    if any(
        name == "receipt.json" or Path(name).parts[0] in {"communities", "provenance"}
        for name in atlas_receipt["files"]
    ):
        raise ValueError("atlas artifact collides with product destinations")
    originals = {
        **atlas_receipt["files"],
        **{f"communities/{name}": value for name, value in community_receipt["files"].items()},
    }
    if not set(_NAVIGATION_FILES).issubset(originals):
        raise ValueError("discovery parents lack required explorer HTML")
    return originals


def _parent_binding(
    source: Path, name: str, output: Path, kind: str, receipt: dict[str, Any]
) -> dict[str, Any]:
    relative = f"provenance/{kind}-receipt.json"
    _copy_artifact(source / name, output / relative)
    original = json.loads((output / relative).read_bytes())
    if original != receipt:
        raise ValueError("parent receipt changed during product copy")
    return {
        "receipt_path": relative,
        "receipt_sha256": sha256_file(output / relative)[0],
        "output_sha256": receipt["output_sha256"],
        "model_output_sha256": receipt.get("model_output_sha256"),
        "model_sha256": receipt.get("model_sha256"),
        "prediction_output_sha256": receipt.get("prediction_output_sha256"),
        "enrichment_prediction_output_sha256": receipt.get("enrichment_prediction_output_sha256"),
        "coverage": receipt["coverage"],
        "derived_output_obligations": receipt["derived_output_obligations"],
    }


def _navigation_changes(files: dict[str, Any], originals: dict[str, Any]) -> dict[str, Any]:
    changes = {}
    for relative, original in originals.items():
        if files[relative] != original:
            if relative not in _NAVIGATION_FILES:
                raise ValueError("non-navigation source artifact changed during composition")
            changes[relative] = {"before": original, "after": files[relative]}
    return changes


def build_discovery_product(*, atlas: Path, communities: Path, output: Path) -> dict[str, Any]:
    """Build one fresh cache-only product with exact lineage and navigation-only edits."""
    require_local_candidate_destination(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing to replace a local discovery product")
    atlas_receipt = verified_receipt(atlas, "receipt.json")
    community_receipt = verified_receipt(communities, "community-preview-receipt.json")
    originals = _require_parent_pair(atlas, atlas_receipt, communities, community_receipt)
    output.mkdir(parents=True)
    for source, receipt, prefix in (
        (atlas, atlas_receipt, ""),
        (communities, community_receipt, "communities/"),
    ):
        for relative in receipt["files"]:
            _copy_artifact(source / relative, output / (prefix + relative))
    parent_bindings = {}
    for kind, source, name, receipt in (
        ("atlas", atlas, "receipt.json", atlas_receipt),
        ("communities", communities, "community-preview-receipt.json", community_receipt),
    ):
        parent_bindings[kind] = _parent_binding(source, name, output, kind, receipt)
    for relative in _NAVIGATION_FILES:
        _replace_navigation(output / relative, relative)
    files = {
        path.relative_to(output).as_posix(): _binding(path)
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }
    changes = _navigation_changes(files, originals)
    for relative in _NAVIGATION_FILES:
        _require_html_targets(output, relative, {*files, _RECEIPT})
    receipt = {
        "revision": "local-discovery-product-v1",
        "scope": "local_research_only",
        "public_export_authorized": False,
        "serving_authorized": False,
        "native_genre_memberships_added": 0,
        "features_sha256": atlas_receipt["features_sha256"],
        "feature_receipt_sha256": atlas_receipt["feature_receipt_sha256"],
        "source_preview_output_sha256": atlas_receipt["source_preview_output_sha256"],
        "source_licenses": atlas_receipt["source_licenses"],
        "derived_output_obligations": (
            "Preserve both parent obligations; local research; no public export"
        ),
        "parents": parent_bindings,
        "builder_sha256": sha256_file(Path(__file__))[0],
        "derivation_method": (
            "verified_hardlink_or_cross_device_copy_with_atomic_navigation_replacement"
        ),
        "navigation_changed_files": changes,
        "unchanged_parent_artifact_count": len(originals) - len(changes),
        "files": files,
    }
    receipt["output_sha256"] = sha256_json(receipt)
    (output / _RECEIPT).write_bytes(canonical_json(receipt) + b"\n")
    return receipt
