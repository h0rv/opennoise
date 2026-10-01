"""Refresh local discovery UI without rebuilding or rewriting data artifacts."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from opennoise.catalog.musicbrainz_candidate import require_local_candidate_destination
from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.deployment.community_preview import verified_receipt
from opennoise.deployment.discovery_product import (
    _binding,
    _replace_navigation,
    _require_html_targets,
    _require_paths,
)
from opennoise.serving.metadata.artist_links import verify_artist_link_projection
from opennoise.serving.metadata.artist_works import verify_projected_artist_work_examples

_STATIC = Path(__file__).resolve().parents[1] / "static"
_DISPLAY = {
    "index.html": "style-atlas.html",
    "style-atlas.css": "style-atlas.css",
    "style-atlas.js": "style-atlas.js",
    "communities/index.html": "community-preview.html",
    "communities/community-preview.css": "community-preview.css",
    "communities/community-preview.js": "community-preview.js",
}


def _clone_display_files(source: Path, output: Path, files: dict[str, Any]) -> None:
    for relative, binding in files.items():
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if relative in _DISPLAY:
            shutil.copyfile(_STATIC / _DISPLAY[relative], destination)
        else:
            os.link(source / relative, destination)
            if _binding(destination) != binding:
                raise ValueError("source artifact changed during display clone")


def _attach_examples(
    output: Path, source: Path | None, files: dict[str, Any]
) -> dict[str, Any] | None:
    if source is None:
        return None
    for original, relative in (
        ("credited-examples.json", "representative-music.json"),
        ("receipt.json", "provenance/representative-music-receipt.json"),
    ):
        destination = output / relative
        if destination.exists():
            raise ValueError("example artifacts collide with source product")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / original, destination)
        files[relative] = _binding(destination)
    verify_projected_artist_work_examples(
        output / "representative-music.json",
        output / "provenance/representative-music-receipt.json",
    )
    for relative, target in (
        ("index.html", "representative-music.json"),
        ("communities/index.html", "../representative-music.json"),
    ):
        path = output / relative
        html = path.read_text(encoding="utf-8")
        if html.count("<body>") != 1:
            raise ValueError("example display requires one plain document body")
        path.write_text(
            html.replace("<body>", f'<body data-artist-examples="{target}">'), encoding="utf-8"
        )
    return {
        "path": "representative-music.json",
        "receipt_path": "provenance/representative-music-receipt.json",
        "projection_sha256": files["representative-music.json"]["sha256"],
        "audio_used": False,
    }


def _attach_artist_links(
    output: Path, source: Path | None, files: dict[str, Any]
) -> dict[str, Any] | None:
    if source is None:
        return None
    for original, relative in (
        ("artist-links.json", "artist-links.json"),
        ("receipt.json", "provenance/artist-links-receipt.json"),
    ):
        destination = output / relative
        if destination.exists():
            raise ValueError("artist link artifacts collide with source product")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / original, destination)
        files[relative] = _binding(destination)
    verify_artist_link_projection(source / "artist-links.json", source / "receipt.json")
    for original, relative in (
        ("artist-links.json", "artist-links.json"),
        ("receipt.json", "provenance/artist-links-receipt.json"),
    ):
        if files[relative] != _binding(source / original):
            raise ValueError("artist link projection changed during display copy")
    for relative, target in (
        ("index.html", "artist-links.json"),
        ("communities/index.html", "../artist-links.json"),
    ):
        path = output / relative
        html = path.read_text(encoding="utf-8")
        if html.count("<body") != 1:
            raise ValueError("artist links require one document body")
        path.write_text(
            html.replace("<body", f'<body data-artist-links="{target}"', 1), encoding="utf-8"
        )
    return {
        "path": "artist-links.json",
        "receipt_path": "provenance/artist-links-receipt.json",
        "projection_sha256": files["artist-links.json"]["sha256"],
        "audio_used": False,
    }


def _verify_optional_examples(source: Path | None, artist_links: Path | None) -> None:
    if artist_links is not None:
        verify_artist_link_projection(
            artist_links / "artist-links.json", artist_links / "receipt.json"
        )
    if source is not None:
        verify_projected_artist_work_examples(
            source / "credited-examples.json", source / "receipt.json"
        )


def refresh_discovery_display(
    *,
    source: Path,
    output: Path,
    representative_music: Path | None = None,
    artist_links: Path | None = None,
) -> dict[str, Any]:
    """Hardlink verified data into a fresh local product; replace only six UI files."""
    require_local_candidate_destination(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing to replace a discovery product")
    prior = verified_receipt(source, "receipt.json")
    if (
        prior.get("revision") != "local-discovery-product-v1"
        or prior.get("scope") != "local_research_only"
        or prior.get("public_export_authorized") is not False
        or prior.get("serving_authorized") is not False
        or prior.get("native_genre_memberships_added") != 0
    ):
        raise ValueError("unsupported local discovery display boundary")
    _require_paths(source, prior)
    if not set(_DISPLAY).issubset(prior["files"]):
        raise ValueError("discovery product lacks required display assets")
    # No copy fallback: a cross-device refresh must fail before copying gigabytes.
    output.parent.mkdir(parents=True, exist_ok=True)
    if source.stat().st_dev != output.parent.stat().st_dev:
        raise ValueError("display refresh requires same-device hardlinks")
    _verify_optional_examples(representative_music, artist_links)
    output.mkdir()
    try:
        files = dict(prior["files"])
        _clone_display_files(source, output, files)
        for relative in ("index.html", "communities/index.html"):
            _replace_navigation(output / relative, relative)
        example_binding = _attach_examples(output, representative_music, files)
        link_binding = _attach_artist_links(output, artist_links, files)
        changes = {}
        for relative in _DISPLAY:
            files[relative] = _binding(output / relative)
            if files[relative] != prior["files"][relative]:
                changes[relative] = {"before": prior["files"][relative], "after": files[relative]}
        for relative in ("index.html", "communities/index.html"):
            _require_html_targets(output, relative, {*files, "receipt.json"})
        receipt = {
            **prior,
            "source_product_output_sha256": prior["output_sha256"],
            "source_product_builder_sha256": prior["builder_sha256"],
            "builder_sha256": sha256_file(Path(__file__))[0],
            "derivation_method": "verified_hardlink_data_with_fresh_display_assets",
            "display_changed_files": changes,
            "unchanged_source_artifact_count": len(prior["files"]) - len(changes),
            "files": files,
            "representative_music": example_binding,
            "artist_links": link_binding,
        }
        receipt.pop("output_sha256")
        receipt["output_sha256"] = sha256_json(receipt)
        (output / "receipt.json").write_bytes(canonical_json(receipt) + b"\n")
    except Exception:
        shutil.rmtree(output)
        raise
    return receipt
