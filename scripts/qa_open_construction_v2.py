"""Certify the served Open construction graph v2 contract against a live app."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from opennoise.serving.open.construction_graph_v2 import (
    OpenConstructionGraphV2Artifact,
    verify_open_construction_graph_v2,
)
from opennoise.serving.open.construction_store_v2 import (
    OpenConstructionV2MapResponse,
    OpenConstructionV2NeighborResponse,
    OpenConstructionV2SearchResponse,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT = ROOT / "data/model/open-construction-graph-v2.json"
DEFAULT_REPORT = ROOT / ".cache/open-v2-runtime-qa/report.json"
HTTP_OK = 200
MAX_NEIGHBOR_NODES = 25


def fetch(base_url: str, path: str, **params: str | float) -> tuple[int, str]:
    """Fetch one local QA endpoint and return its status and UTF-8 body."""
    query = urlencode(params)
    url = f"{base_url.rstrip('/')}{path}" + (f"?{query}" if query else "")
    with urlopen(url, timeout=10) as response:  # noqa: S310 - caller supplies local QA URL.
        status = int(response.status)
        body = str(response.read().decode("utf-8"))
        return status, body


def main() -> None:
    """Validate artifact integrity, bounded endpoints, and the no-script page."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:3001")
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    raw = args.artifact.read_bytes()
    artifact = OpenConstructionGraphV2Artifact.model_validate_json(raw)
    verify_open_construction_graph_v2(artifact)
    nodes = artifact.nodes
    edges = artifact.edges
    layout_by_id = {item.node_id: item for item in artifact.layout}
    edge_endpoints = {
        endpoint for edge in edges for endpoint in (edge.source_node_id, edge.target_node_id)
    }
    isolated = next(node for node in nodes if node.node_id not in edge_endpoints)
    isolated_layout = layout_by_id[isolated.node_id]
    x = isolated_layout.landscape_x
    y = isolated_layout.landscape_y
    status, overview_text = fetch(args.base_url, "/api/open-construction-map/v2", level=0)
    overview = OpenConstructionV2MapResponse.model_validate_json(overview_text)
    status_view, viewport_text = fetch(
        args.base_url,
        "/api/open-construction-map/v2",
        level=2,
        min_x=x - 1,
        min_y=y - 1,
        max_x=x + 1,
        max_y=y + 1,
    )
    viewport = OpenConstructionV2MapResponse.model_validate_json(viewport_text)
    status_search, search_text = fetch(
        args.base_url, "/api/open-construction-map/v2/search", q=isolated.name
    )
    search = OpenConstructionV2SearchResponse.model_validate_json(search_text)
    status_neighbors, neighbors_text = fetch(
        args.base_url, f"/api/open-construction-map/v2/neighbors/{isolated.node_id}"
    )
    neighbors = OpenConstructionV2NeighborResponse.model_validate_json(neighbors_text)
    status_page, page = fetch(args.base_url, "/", view="open")
    checks = {
        "artifact_sha256": hashlib.sha256(raw).hexdigest(),
        "artifact_nodes": len(nodes),
        "artifact_edges": len(edges),
        "overview_bounded": status == HTTP_OK and len(overview.nodes) <= overview.node_budget,
        "viewport_reaches_isolate": status_view == HTTP_OK
        and any(node.node_id == isolated.node_id for node in viewport.nodes),
        "search_all_names": status_search == HTTP_OK
        and any(hit.node_id == isolated.node_id for hit in search.hits),
        "neighbor_contract": status_neighbors == HTTP_OK
        and neighbors.node_id == isolated.node_id
        and len(neighbors.nodes) <= MAX_NEIGHBOR_NODES,
        "default_open_v2": status_page == HTTP_OK
        and 'data-map-view="open"' in page
        and 'data-open-graph-version="v2"' in page
        and 'id="map-view-switch"' not in page,
        "no_js_fallback": '<section id="open-fallback"' in page
        and "/api/open-construction-map/v2?level=0" in page
        and 'id="open-detail"' not in page,
    }
    if not all(checks.values()):
        failed = ", ".join(name for name, passed in checks.items() if not passed)
        raise SystemExit(f"Open v2 QA failed: {failed}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "base_url": args.base_url,
                "isolated_node": isolated.node_id,
                "isolated_name": isolated.name,
                "checks": checks,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    sys.stdout.write(json.dumps(checks, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
