"""Optional CC0 source-taxonomy explorer, separate from the default artist export."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from opennoise.analysis.taxonomy_neighborhoods import build_taxonomy_neighborhoods
from opennoise.common import canonical_json, sha256_file
from opennoise.ingest.wikidata.open_genre_taxonomy import verify_pack
from opennoise.pipeline.portable_foundation import (
    _path,
    build_portable_foundation,
    validate_portable_foundation,
)

if TYPE_CHECKING:
    from pathlib import Path

REVISION = "open-foundation-taxonomy-v1"
PACK = "data/examples/open-genre-taxonomy"
PROTOCOL = "config/open_taxonomy_neighborhood_protocol_v1.json"
ASSETS = ("portable-taxonomy.html", "portable-taxonomy.mjs", "portable-taxonomy.css")
IMPLEMENTATIONS = (
    "src/opennoise/analysis/taxonomy_neighborhoods.py",
    "src/opennoise/ingest/wikidata/open_genre_taxonomy.py",
    "src/opennoise/common/hashing.py",
    "src/opennoise/pipeline/portable_taxonomy.py",
)


def _hashes(root: Path, paths: list[str] | tuple[str, ...]) -> dict[str, str]:
    return {relative: sha256_file(_path(root, relative))[0] for relative in paths}


def _source_hashes(root: Path) -> dict[str, str]:
    return _hashes(
        root,
        [
            str(path.relative_to(root))
            for path in sorted((root / PACK).rglob("*"))
            if path.is_file() and path.name != "README.md"
        ]
        + [PROTOCOL],
    )


def taxonomy_projection(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Replay bounded native claims before graph construction; labels never affect distance."""
    pack = root / PACK
    source = verify_pack(pack)
    graph = build_taxonomy_neighborhoods(
        source,
        projection_path=_path(pack, "projection.json"),
        source_receipt_path=_path(pack, "receipt.json"),
        protocol_path=_path(root, PROTOCOL),
    )
    coordinates = {row["genre_id"]: row for row in graph["layout"]["coordinates"]}
    abstentions = {row["genre_id"]: row for row in graph["layout"]["abstentions"]}
    entities = []
    for row in source["entities"]:
        qid = row["qid"]
        position = coordinates.get(qid)
        entities.append(
            {
                "genre_id": qid,
                "name": row["english_label"] or qid,
                "english_label_missing": row["english_label"] is None,
                "position": position,
                "component_id": (position or abstentions[qid])["component_id"],
                "position_status": "source_graph_projection"
                if position
                else abstentions[qid]["reason"],
                "neighbors": graph["neighbors"][qid],
            }
        )
    return {
        "revision": REVISION,
        "license": "CC0-1.0",
        "scope": {
            "selected_taxonomy_entities": len(entities),
            "selection_possibly_truncated": source["selection_possibly_truncated"],
            "full_foundation_complete": False,
            "historical_inputs_used": False,
            "spotify_private_inputs_used": False,
            "artist_membership_inference": False,
            "independent_musical_validation": False,
            "across_component_semantics": False,
        },
        "counts": {
            "genres": len(entities),
            "selected_p279_edges": len(graph["selected_p279_undirected_edges"]),
            "positioned": len(coordinates),
            "unpositioned": len(abstentions),
            "components": len(graph["layout"]["components"]),
            "isolated": sum(row["reason"] == "isolated" for row in abstentions.values()),
        },
        "genres": entities,
        "claims": source["claims"],
        "source_captures": source["source_captures"],
        "components": graph["layout"]["components"],
    }, graph


def build_portable_taxonomy(root: Path, output: Path) -> dict[str, Any]:
    """Create a new optional taxonomy export with an unchanged nested artist explorer."""
    if output.exists() or output.is_symlink():
        raise FileExistsError("taxonomy output must be a new directory")
    data, graph = taxonomy_projection(root)
    output.mkdir(parents=True)
    build_portable_foundation(root, output / "artists")
    for name, value in (
        ("data.json", data),
        ("graph.json", graph),
        ("layout.json", graph["layout"]),
    ):
        (output / name).write_bytes(canonical_json(value) + b"\n")
    assets = root / "src/opennoise/static"
    for asset in ASSETS:
        target = "index.html" if asset.endswith(".html") else asset
        (output / target).write_bytes(_path(assets, asset).read_bytes())
    receipt = {
        "revision": REVISION,
        "license": data["license"],
        "scope": data["scope"],
        "counts": data["counts"],
        "source_files_sha256": _source_hashes(root),
        "implementation_files_sha256": _hashes(root, IMPLEMENTATIONS),
        "asset_files_sha256": _hashes(assets, ASSETS),
        "files_sha256": _hashes(
            output, sorted(path.name for path in output.iterdir() if path.is_file())
        ),
        "artist_receipt_sha256": sha256_file(output / "artists/receipt.json")[0],
        "legacy_sealed_release": False,
        "full_foundation_acceptance": "incomplete",
    }
    (output / "receipt.json").write_bytes(canonical_json(receipt) + b"\n")
    validate_portable_taxonomy(root, output)
    return receipt


def validate_portable_taxonomy(root: Path, output: Path) -> dict[str, Any]:
    """Verify every artifact and rederive graph metrics and positions from native responses."""
    receipt = json.loads(_path(output, "receipt.json").read_bytes())
    assets = root / "src/opennoise/static"
    if (
        receipt["revision"] != REVISION
        or receipt["license"] != "CC0-1.0"
        or receipt["legacy_sealed_release"] is not False
        or receipt["full_foundation_acceptance"] != "incomplete"
        or receipt["source_files_sha256"] != _source_hashes(root)
        or receipt["implementation_files_sha256"] != _hashes(root, IMPLEMENTATIONS)
        or receipt["asset_files_sha256"] != _hashes(assets, ASSETS)
    ):
        raise ValueError("taxonomy receipt scope, source or implementation differs")
    actual = {path.name for path in output.iterdir() if path.name != "receipt.json"}
    if actual != {*receipt["files_sha256"], "artists"}:
        raise ValueError("taxonomy output member set differs")
    if receipt["files_sha256"] != _hashes(output, sorted(receipt["files_sha256"])):
        raise ValueError("taxonomy output byte hash differs")
    for asset in ASSETS:
        target = "index.html" if asset.endswith(".html") else asset
        if _path(output, target).read_bytes() != _path(assets, asset).read_bytes():
            raise ValueError("taxonomy static asset differs")
    data, graph = taxonomy_projection(root)
    expected = {"data.json": data, "graph.json": graph, "layout.json": graph["layout"]}
    if any(
        json.loads(_path(output, name).read_bytes()) != value for name, value in expected.items()
    ):
        raise ValueError("taxonomy source graph does not replay")
    if receipt["scope"] != data["scope"] or receipt["counts"] != data["counts"]:
        raise ValueError("taxonomy cohort scope differs")
    validate_portable_foundation(root, output / "artists")
    if receipt["artist_receipt_sha256"] != sha256_file(output / "artists/receipt.json")[0]:
        raise ValueError("taxonomy artist receipt differs")
    return receipt
