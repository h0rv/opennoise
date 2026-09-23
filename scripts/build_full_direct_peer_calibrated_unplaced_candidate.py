"""Calibrate a sparse direct-artist rule, then project its frozen unplaced frontier locally."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

import ijson

from opennoise.serving.local.conservative_peer_holdout import (
    Point,
    adjacency,
    evaluate_holdout,
    project_unplaced,
    singleton_degree_bounded_edges,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_PUBLIC_INPUT_SHA = "3c2c8b23e00c0201f1505be6851bc392258665cb11fc353949c1a332ebc9dd1c"
_LAYOUT_SHA = "e7723b42657451a341e92a9aefa1ced499067e673366b468fd38f84fc86f5972"
_FRONTIER_SHA = "b605e855681bab1c8b17a7e67dd66f128b00dd4acc6ba1bcde05a9629361c028"
_PROJECT_CACHE_ROOT = Path(__file__).resolve().parents[1] / ".cache"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1_048_576), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def _direct_memberships(path: Path) -> Iterator[tuple[str, str]]:
    """Stream only exact artist--genre identities from the large pinned input."""
    with path.open("rb") as stream:
        for row in ijson.items(stream, "direct_memberships.item"):
            if not isinstance(row, dict):
                raise TypeError("direct membership row must be an object")
            artist_id, genre_id = row.get("artist_id"), row.get("genre_id")
            if not isinstance(artist_id, str) or not isinstance(genre_id, str):
                raise TypeError("direct membership row requires string artist and genre IDs")
            yield artist_id, genre_id


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("percentile requires values")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def _calibration_diagnostics(
    *, anchors: dict[str, Point], edges: tuple[tuple[str, str], ...]
) -> dict[str, object]:
    """Expose target-excluded error tails and one-versus-many peer strata."""
    peer_adjacency = adjacency(edges)
    rows: dict[str, list[tuple[float, float]]] = defaultdict(list)
    all_rows: list[tuple[float, float]] = []
    for seed_id, target in anchors.items():
        peers = tuple(anchors[item] for item in peer_adjacency.get(seed_id, ()) if item in anchors)
        if not peers:
            continue
        prediction = Point(
            sum(item.x for item in peers) / len(peers), sum(item.y for item in peers) / len(peers)
        )
        remaining = tuple(item for other, item in anchors.items() if other != seed_id)
        baseline = Point(
            sum(item.x for item in remaining) / len(remaining),
            sum(item.y for item in remaining) / len(remaining),
        )
        values = (
            math.hypot(prediction.x - target.x, prediction.y - target.y),
            math.hypot(baseline.x - target.x, baseline.y - target.y),
        )
        all_rows.append(values)
        rows["one" if len(peers) == 1 else "two_or_more"].append(values)

    def summarize(values: list[tuple[float, float]]) -> dict[str, object]:
        errors = [item[0] for item in values]
        return {
            "target_count": len(values),
            "median_peer_error": _percentile(errors, 0.5),
            "p90_peer_error": _percentile(errors, 0.9),
            "fraction_improved_vs_global_centroid": sum(left < right for left, right in values)
            / len(values),
        }

    overall = summarize(all_rows)
    overall["by_placed_peer_anchor_count"] = {
        key: summarize(value) for key, value in sorted(rows.items())
    }
    return overall


def build(*, public_input: Path, layout: Path, frontier: Path) -> dict[str, object]:
    """Return a create-only, non-serving candidate after target-excluded calibration."""
    if (_sha(public_input), _sha(layout), _sha(frontier)) != (
        _PUBLIC_INPUT_SHA,
        _LAYOUT_SHA,
        _FRONTIER_SHA,
    ):
        raise ValueError("direct source, layout, or frontier bytes are not pinned")
    calibration_edges = singleton_degree_bounded_edges(_direct_memberships(public_input))
    atlas = json.loads(layout.read_bytes())
    anchors = {
        row["seed_id"]: Point(float(row["x"]), float(row["y"])) for row in atlas["coordinates"]
    }
    unplaced = frozenset(row["seed_id"] for row in atlas["unplaced"])
    placed_edges = tuple(
        edge for edge in calibration_edges if edge[0] in anchors and edge[1] in anchors
    )
    holdout = evaluate_holdout(anchors=anchors, peer_adjacency=adjacency(placed_edges))
    diagnostics = _calibration_diagnostics(anchors=anchors, edges=placed_edges)
    if holdout.mean_error_improvement <= 0:
        raise ValueError("full-source singleton calibration does not beat target-excluded baseline")
    frozen = json.loads(frontier.read_bytes())
    frontier_rows = tuple(frozen["edges"])
    frontier_edges = tuple(
        (row["source_genre_id"], row["target_genre_id"]) for row in frontier_rows
    )
    proposals = project_unplaced(
        unplaced_ids=unplaced, anchors=anchors, peer_adjacency=adjacency(frontier_edges)
    )
    evidence_by_seed: dict[str, set[str]] = defaultdict(set)
    for row in frontier_rows:
        for seed_id, key in (
            (row["source_genre_id"], "source_direct_evidence_refs"),
            (row["target_genre_id"], "target_direct_evidence_refs"),
        ):
            if seed_id in unplaced:
                evidence_by_seed[seed_id].update(row["evidence"][key])
    support_distribution = Counter(item.placed_peer_count for item in proposals)
    result: dict[str, object] = {
        "revision": "full-direct-peer-calibrated-unplaced-candidate-v1",
        "scope": "local_only_open_direct_musicbrainz_geometry_candidate",
        "historical_inputs_used": False,
        "serving_allowed": False,
        "export_allowed": False,
        "layout_mutated": False,
        "factual_membership_or_placement_claim": False,
        "rule": (
            "overlap-one eligible witness; artist seed degree below ten before pair enumeration"
        ),
        "calibration": {
            "source": "full pinned direct MusicBrainz memberships",
            "target_coordinate_excluded_from_prediction": True,
            "edge_count": len(calibration_edges),
            "placed_edge_count": len(placed_edges),
            "evaluable_target_count": holdout.evaluable_target_count,
            "mean_peer_error": holdout.mean_peer_error,
            "mean_leave_one_out_centroid_error": holdout.mean_global_baseline_error,
            "mean_error_improvement": holdout.mean_error_improvement,
            **diagnostics,
        },
        "frontier_support": {
            "edge_count": len(frontier_edges),
            "proposal_count": len(proposals),
            "abstained_unplaced_seed_count": len(unplaced) - len(proposals),
            "placed_peer_count_distribution": dict(sorted(support_distribution.items())),
        },
        "proposals": [
            {
                "seed_id": item.seed_id,
                "x": item.point.x,
                "y": item.point.y,
                "placed_peer_count": item.placed_peer_count,
                "status": "local_candidate_only",
                "peer_evidence_refs": sorted(evidence_by_seed[item.seed_id]),
            }
            for item in proposals
        ],
    }
    result["output_sha256"] = hashlib.sha256(_canonical(result)).hexdigest()
    return result


def main() -> int:
    """Write one pinned, local-only candidate without replacing an existing result."""
    parser = argparse.ArgumentParser(prog="build-full-direct-peer-calibrated-unplaced-candidate")
    parser.add_argument("--public-input", type=Path, required=True)
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--frontier", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cache_root = _PROJECT_CACHE_ROOT.resolve()
    if not args.output.resolve(strict=False).is_relative_to(cache_root):
        raise ValueError("output must be below the project .cache root")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not args.output.resolve(strict=False).is_relative_to(cache_root):
        raise ValueError("output parent resolves outside the project .cache root")
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError(f"refusing to overwrite candidate: {args.output}")
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(
            _canonical(
                build(public_input=args.public_input, layout=args.layout, frontier=args.frontier)
            )
        )
        stream.write(b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
