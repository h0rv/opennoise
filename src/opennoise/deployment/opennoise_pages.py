"""Build a deterministic, backend-free OpenNoise Pages directory."""

from __future__ import annotations

import gzip
import json
import shutil
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal
from xml.etree import ElementTree as ET

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import Field

from opennoise.common import canonical_json, sha256_file, sha256_hex, write_atomic_bytes
from opennoise.models import FrozenModel
from opennoise.models.production import ProductionMapArtifact
from opennoise.serving.open.construction_graph_v2 import OpenConstructionGraphV2Artifact

if TYPE_CHECKING:
    from collections.abc import Mapping

_REVISION: Final = "opennoise-pages-static-v3"
_PACKAGE_ROOT: Final = Path(__file__).resolve().parents[1]
_TEMPLATE_ROOT: Final = _PACKAGE_ROOT / "templates" / "pages"
_STATIC_ROOT: Final = _PACKAGE_ROOT / "static" / "pages"


class OpenNoisePagesExportError(ValueError):
    """The requested static-release input is unavailable or not publishable."""


class OpenNoisePagesArtifactBinding(FrozenModel):
    """Exact identity of the production map behind the visible SVG."""

    revision: Literal["production-map-v1"] = "production-map-v1"
    byte_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(gt=0)
    logical_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mapped_node_count: int = Field(ge=1)
    similarity_edge_count: int = Field(ge=0)
    taxonomy_edge_count: int = Field(ge=0)


class OpenNoisePagesSearchBinding(FrozenModel):
    """Search-only vocabulary boundary; it makes no placement claim."""

    source_logical_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    searchable_name_count: int = Field(ge=1)
    direct_mapped_search_name_count: int = Field(ge=0)
    searchable_only_name_count: int = Field(ge=0)


class OpenNoisePagesAsset(FrozenModel):
    """One deterministic output-file byte budget entry."""

    path: str = Field(min_length=1)
    raw_bytes: int = Field(ge=0)
    gzip_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class OpenNoisePagesExportManifest(FrozenModel):
    """Receipt for a fully static Pages export."""

    revision: Literal["opennoise-pages-static-v3"] = _REVISION
    artifact: OpenNoisePagesArtifactBinding
    search: OpenNoisePagesSearchBinding
    explicit_backend_api_available: Literal[False] = False
    asset_budget: tuple[OpenNoisePagesAsset, ...]
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class OpenNoisePagesExportInputs:
    """Explicit source-neutral map and full-name search inputs."""

    production_map_path: Path
    open_construction_v2_path: Path
    output_directory: Path


def export_opennoise_pages(inputs: OpenNoisePagesExportInputs) -> OpenNoisePagesExportManifest:
    """Write a static 603-node map and distinct 6,291-name search index."""
    if inputs.output_directory.exists() and any(inputs.output_directory.iterdir()):
        raise OpenNoisePagesExportError("static Pages output directory must be empty")
    production, binding = _load_production_map(inputs.production_map_path)
    search_graph = _load_search_graph(inputs.open_construction_v2_path)
    output, assets, details = (
        inputs.output_directory,
        inputs.output_directory / "assets",
        inputs.output_directory / "genres",
    )
    output.mkdir(parents=True, exist_ok=True)
    assets.mkdir()
    details.mkdir()
    mapped = {node.genre_id: node for node in production.nodes}
    shutil.copyfile(_STATIC_ROOT / "opennoise.css", assets / "opennoise.css")
    shutil.copyfile(_STATIC_ROOT / "search.js", assets / "search.js")
    shutil.copyfile(_STATIC_ROOT / "map.js", assets / "map.js")
    search_entries = _search_entries(search_graph, mapped)
    _write_json(assets / "search-index.json", search_entries)
    _write_json(assets / "map-data.json", _map_payload(production))
    _write_template(
        output / "index.html",
        "index.html",
        mapped_node_count=len(mapped),
        searchable_name_count=search_graph.coverage.legacy_seed_node_count,
        svg=_map_svg(production, 0, ""),
    )
    _write_template(
        output / "search.html",
        "search.html",
        mapped_node_count=len(mapped),
        searchable_name_count=search_graph.coverage.legacy_seed_node_count,
    )
    for node in sorted(production.nodes, key=lambda item: item.genre_id):
        _write_template(
            details / f"{_page_id(node.genre_id)}.html",
            "detail.html",
            name=node.name,
            peers=_detail_peers(production, node.genre_id, mapped),
        )
    _write(output / "_headers", "/assets/*\n  Cache-Control: public, max-age=31536000, immutable\n")
    _write(output / "_redirects", "/ /index.html 200\n/search /search.html 200\n")
    search = OpenNoisePagesSearchBinding(
        source_logical_sha256=search_graph.output_sha256,
        searchable_name_count=search_graph.coverage.legacy_seed_node_count,
        direct_mapped_search_name_count=sum(item["status"] == "mapped" for item in search_entries),
        searchable_only_name_count=sum(
            item["status"] == "searchable_only" for item in search_entries
        ),
    )
    base = OpenNoisePagesExportManifest(
        artifact=binding, search=search, asset_budget=_asset_budget(output), output_sha256="0" * 64
    )
    manifest = base.model_copy(update={"output_sha256": _manifest_sha256(base)})
    _write_json(output / "opennoise-static-manifest.json", manifest.model_dump(mode="json"))
    return manifest


def _load_production_map(path: Path) -> tuple[ProductionMapArtifact, OpenNoisePagesArtifactBinding]:
    try:
        artifact = ProductionMapArtifact.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise OpenNoisePagesExportError("invalid sealed production map artifact") from error
    if not artifact.export_allowed:
        raise OpenNoisePagesExportError("production map artifact is not export allowed")
    byte_sha256, byte_count = sha256_file(path)
    return artifact, OpenNoisePagesArtifactBinding(
        byte_sha256=byte_sha256,
        byte_count=byte_count,
        logical_sha256=artifact.output_sha256,
        mapped_node_count=len(artifact.nodes),
        similarity_edge_count=sum(edge.kind == "similarity" for edge in artifact.edges),
        taxonomy_edge_count=sum(edge.kind == "taxonomy" for edge in artifact.edges),
    )


def _load_search_graph(path: Path) -> OpenConstructionGraphV2Artifact:
    try:
        artifact = OpenConstructionGraphV2Artifact.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise OpenNoisePagesExportError("invalid full-vocabulary search artifact") from error
    audit = artifact.input_audit
    if any(
        (
            audit.historical_coordinates_read,
            audit.historical_memberships_read,
            audit.historical_neighbors_read,
            audit.artist_membership_evidence_read,
            audit.aggregate_listening_data_read,
            audit.audio_or_music_files_read,
        )
    ):
        raise OpenNoisePagesExportError("search artifact violates source-neutral input boundary")
    return artifact


def _search_entries(
    artifact: OpenConstructionGraphV2Artifact, mapped: Mapping[str, object]
) -> list[dict[str, str]]:
    direct_catalog_by_seed = {
        edge.source_node_id: edge.target_node_id.removeprefix("catalog:")
        for edge in artifact.edges
        if edge.kind == "canonical_catalog_identity"
        and edge.source_node_id.startswith("legacy:")
        and edge.target_node_id.startswith("catalog:")
    }
    entries = [
        {
            "id": node.node_id,
            "name": node.name,
            "status": "mapped"
            if direct_catalog_by_seed.get(node.node_id) in mapped
            else "searchable_only",
            **(
                {"href": f"genres/{_page_id(direct_catalog_by_seed[node.node_id])}.html"}
                if direct_catalog_by_seed.get(node.node_id) in mapped
                else {}
            ),
        }
        for node in artifact.nodes
        if node.node_kind == "legacy_name_seed"
    ]
    if len(entries) != artifact.coverage.legacy_seed_node_count:
        raise OpenNoisePagesExportError("full-vocabulary search count does not match receipt")
    return sorted(entries, key=lambda item: (item["name"].casefold(), item["id"]))


def _map_svg(artifact: ProductionMapArtifact, level: int, base_prefix: str) -> str:
    """Generate only SVG data; templates own every HTML page shell."""
    lod = artifact.lods[level]
    visible = set(lod.visible_node_ids)
    labels = {item.genre_id for item in lod.desktop_labels if item.shown}
    svg = ET.Element(
        "svg",
        {
            "id": "plot",
            "role": "img",
            "aria-label": "Mapped genres",
            "viewBox": "-.04 -.04 1.08 1.08",
            "preserveAspectRatio": "xMidYMid meet",
        },
    )
    for node in sorted(
        (item for item in artifact.nodes if item.genre_id in visible),
        key=lambda item: item.genre_id,
    ):
        anchor = ET.SubElement(
            svg,
            "a",
            {
                "class": "point",
                "href": f"{base_prefix}genres/{_page_id(node.genre_id)}.html",
                "aria-label": f"{node.name}, mapped genre",
            },
        )
        ET.SubElement(anchor, "circle", {"cx": str(node.x), "cy": str(node.y), "r": ".004"})
        if node.genre_id in labels:
            label = ET.SubElement(
                anchor,
                "text",
                {"x": str(node.x + 0.006), "y": str(node.y + 0.003), "font-size": ".012"},
            )
            label.text = node.name
    return ET.tostring(svg, encoding="unicode")


def _map_payload(artifact: ProductionMapArtifact) -> dict[str, object]:
    """Expose only receipt-bound semantic geometry to the renderer."""
    nodes = [
        {"id": node.genre_id, "name": node.name, "x": node.x, "y": node.y}
        for node in sorted(artifact.nodes, key=lambda node: node.genre_id)
    ]
    lod = {
        str(level): [label.genre_id for label in item.desktop_labels if label.shown]
        for level, item in enumerate(artifact.lods)
    }
    return {
        "revision": "opennoise-map-v1",
        "world": {"min_x": 0, "min_y": 0, "max_x": 1, "max_y": 1},
        "nodes": nodes,
        "lod": lod,
        "peers": [
            {"source": edge.source_genre_id, "target": edge.target_genre_id, "weight": edge.weight}
            for edge in artifact.edges
            if edge.kind == "similarity"
        ],
    }


def _detail_peers(
    artifact: ProductionMapArtifact, genre_id: str, mapped: Mapping[str, object]
) -> tuple[dict[str, str], ...]:
    names = {node.genre_id: node.name for node in artifact.nodes}
    peers = sorted(
        (
            edge.target_genre_id if edge.source_genre_id == genre_id else edge.source_genre_id,
            edge.weight,
        )
        for edge in artifact.edges
        if edge.kind == "similarity" and genre_id in {edge.source_genre_id, edge.target_genre_id}
    )
    return tuple(
        {"name": names[peer_id], "href": f"{_page_id(peer_id)}.html"}
        for peer_id, _ in sorted(peers, key=lambda item: (-item[1], names[item[0]].casefold()))[:12]
        if peer_id in mapped
    )


def _write_template(path: Path, template_name: str, **context: object) -> None:
    environment = Environment(
        loader=FileSystemLoader(_TEMPLATE_ROOT), autoescape=select_autoescape(("html",))
    )
    _write(path, environment.get_template(template_name).render(**context))


def _asset_budget(directory: Path) -> tuple[OpenNoisePagesAsset, ...]:
    return tuple(
        OpenNoisePagesAsset(
            path=str(path.relative_to(directory)),
            raw_bytes=len(data),
            gzip_bytes=len(gzip.compress(data, mtime=0)),
            sha256=sha256(data).hexdigest(),
        )
        for path in sorted(item for item in directory.rglob("*") if item.is_file())
        for data in (path.read_bytes(),)
    )


def _manifest_sha256(manifest: OpenNoisePagesExportManifest) -> str:
    return sha256_hex(canonical_json(manifest.model_dump(mode="json", exclude={"output_sha256"})))


def _page_id(value: str | None) -> str:
    if value is None:
        raise OpenNoisePagesExportError("mapped genre lacks a stable identifier")
    return sha256(value.encode()).hexdigest()[:20]


def _write(path: Path, value: str) -> None:
    write_atomic_bytes(path, value.encode())


def _write_json(path: Path, value: object) -> None:
    write_atomic_bytes(
        path,
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
        + b"\n",
    )
