"""Evaluate a fixed local MusicBrainz peer candidate against open atlas anchors."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from opennoise.serving.local.conservative_peer_holdout import (
    Point,
    adjacency,
    evaluate_holdout,
    project_unplaced,
)

_EXPECTED_SEED_COUNT = 6_291
_EXPECTED_PLACED_SEED_COUNT = 2_945
_EXPECTED_UNPLACED_SEED_COUNT = 3_346
_EXPECTED_CANDIDATE_EDGE_COUNT = 1_497
_EXPECTED_CANDIDATE_PLACED_ENDPOINT_COUNT = 509
_EXPECTED_CANDIDATE_UNPLACED_ENDPOINT_COUNT = 414
_PINNED_LAYOUT_BYTE_SHA256 = "e7723b42657451a341e92a9aefa1ced499067e673366b468fd38f84fc86f5972"
_PINNED_CANDIDATE_BYTE_SHA256 = "b605e855681bab1c8b17a7e67dd66f128b00dd4acc6ba1bcde05a9629361c028"


def _required_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise TypeError(f"{label} must be an object with string keys")
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _required_string(row: dict[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str):
        raise TypeError(f"row requires string {key}")
    return value


def _required_float(row: dict[str, object], key: str) -> float:
    value = row.get(key)
    if not isinstance(value, (float, int)) or isinstance(value, bool):
        raise TypeError(f"row requires numeric {key}")
    return float(value)


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_no_replace(path: Path, content: bytes) -> None:
    """Atomically create a local report without replacing a concurrent writer."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)


def _read_layout(path: Path) -> tuple[dict[str, Point], frozenset[str], str]:
    payload = _required_mapping(json.loads(path.read_bytes()), "layout")
    coordinates = payload.get("coordinates")
    unplaced = payload.get("unplaced")
    output_sha256 = payload.get("output_sha256")
    if (
        not isinstance(coordinates, list)
        or not isinstance(unplaced, list)
        or not isinstance(output_sha256, str)
    ):
        raise TypeError("layout requires coordinates, unplaced, and output_sha256")
    anchors: dict[str, Point] = {}
    for value in coordinates:
        row = _required_mapping(value, "coordinate")
        seed_id = _required_string(row, "seed_id")
        if seed_id in anchors:
            raise ValueError("layout has duplicate placed seed IDs")
        anchors[seed_id] = Point(x=_required_float(row, "x"), y=_required_float(row, "y"))
    unplaced_values = tuple(
        _required_string(_required_mapping(value, "unplaced"), "seed_id") for value in unplaced
    )
    unplaced_ids = frozenset(unplaced_values)
    if len(unplaced_values) != len(unplaced_ids):
        raise ValueError("layout has duplicate unplaced seed IDs")
    if set(anchors) & unplaced_ids:
        raise ValueError("layout IDs cannot be both placed and unplaced")
    if (
        len(anchors) != _EXPECTED_PLACED_SEED_COUNT
        or len(unplaced_ids) != _EXPECTED_UNPLACED_SEED_COUNT
    ):
        raise ValueError("layout does not have the fixed placed and unplaced counts")
    return anchors, unplaced_ids, output_sha256


def _read_edges(path: Path) -> tuple[tuple[str, str], ...]:
    payload = _required_mapping(json.loads(path.read_bytes()), "candidate")
    if payload.get("historical_inputs_used") is not False:
        raise ValueError("candidate must declare no historical inputs")
    edges = payload.get("edges")
    if not isinstance(edges, list):
        raise TypeError("candidate requires edges")
    result = tuple(
        (
            _required_string(_required_mapping(value, "edge"), "source_genre_id"),
            _required_string(_required_mapping(value, "edge"), "target_genre_id"),
        )
        for value in edges
    )
    if len(result) != _EXPECTED_CANDIDATE_EDGE_COUNT:
        raise ValueError("candidate does not have the fixed conservative edge count")
    return result


def build_report(*, layout: Path, candidate: Path) -> dict[str, object]:
    """Build a local-only report and proposed coordinates without publishing them."""
    if _sha256(layout) != _PINNED_LAYOUT_BYTE_SHA256:
        raise ValueError("layout bytes do not match the pinned v3 atlas")
    if _sha256(candidate) != _PINNED_CANDIDATE_BYTE_SHA256:
        raise ValueError("candidate bytes do not match the fixed conservative candidate")
    anchors, unplaced_ids, layout_output_sha256 = _read_layout(layout)
    if len(anchors) + len(unplaced_ids) != _EXPECTED_SEED_COUNT:
        raise ValueError("the experiment must preserve the 6,291-ID layout universe")
    edges = _read_edges(candidate)
    endpoint_ids = frozenset(seed_id for edge in edges for seed_id in edge)
    if (
        len(endpoint_ids & set(anchors)) != _EXPECTED_CANDIDATE_PLACED_ENDPOINT_COUNT
        or len(endpoint_ids & unplaced_ids) != _EXPECTED_CANDIDATE_UNPLACED_ENDPOINT_COUNT
        or len(endpoint_ids)
        != _EXPECTED_CANDIDATE_PLACED_ENDPOINT_COUNT + _EXPECTED_CANDIDATE_UNPLACED_ENDPOINT_COUNT
    ):
        raise ValueError("candidate endpoint counts do not match the fixed conservative frontier")
    peer_adjacency = adjacency(edges)
    projections = project_unplaced(
        unplaced_ids=unplaced_ids, anchors=anchors, peer_adjacency=peer_adjacency
    )
    try:
        holdout = evaluate_holdout(anchors=anchors, peer_adjacency=peer_adjacency)
    except ValueError as error:
        holdout_report: dict[str, object] = {
            "available": False,
            "target_coordinate_excluded_from_prediction": True,
            "reason": str(error),
        }
        supported = False
    else:
        holdout_report = {
            "available": True,
            "target_coordinate_excluded_from_prediction": True,
            "evaluable_placed_target_count": holdout.evaluable_target_count,
            "mean_peer_error": holdout.mean_peer_error,
            "mean_leave_one_out_global_centroid_error": holdout.mean_global_baseline_error,
            "mean_error_improvement": holdout.mean_error_improvement,
            "median_peer_error": holdout.median_peer_error,
            "median_leave_one_out_global_centroid_error": holdout.median_global_baseline_error,
            "peer_beats_baseline_count": holdout.peer_beats_baseline_count,
        }
        supported = holdout.mean_error_improvement > 0.0
    proposal_rows = (
        [
            {
                "seed_id": proposal.seed_id,
                "x": proposal.point.x,
                "y": proposal.point.y,
                "placed_peer_count": proposal.placed_peer_count,
            }
            for proposal in projections
        ]
        if supported
        else []
    )
    report: dict[str, object] = {
        "revision": "conservative-musicbrainz-peer-layout-holdout-v1",
        "scope": "local_only_open_data_geometry_diagnostic",
        "historical_inputs_used": False,
        "layout_mutated": False,
        "similarity_claim": "none; shared direct-artist evidence only",
        "inputs": {
            "layout": {
                "path": str(layout),
                "byte_sha256": _sha256(layout),
                "logical_output_sha256": layout_output_sha256,
            },
            "candidate": {"path": str(candidate), "byte_sha256": _sha256(candidate)},
        },
        "universe": {
            "total_seed_count": _EXPECTED_SEED_COUNT,
            "placed_seed_count": len(anchors),
            "unplaced_seed_count": len(unplaced_ids),
        },
        "holdout": holdout_report,
        "unplaced_projection": {
            "directly_reachable_unplaced_seed_count": len(projections),
            "proposal_supported_by_mean_baseline_comparison": supported,
            "proposal_count": len(proposal_rows),
            "abstained_unplaced_seed_count": len(unplaced_ids) - len(proposal_rows),
            "proposals": proposal_rows,
        },
    }
    report["output_sha256"] = hashlib.sha256(_canonical_json(report)).hexdigest()
    return report


def main() -> int:
    """Write one fresh report; this command never overwrites an experiment."""
    parser = argparse.ArgumentParser(prog="evaluate-conservative-musicbrainz-peer-layout-holdout")
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    _write_no_replace(
        arguments.output,
        _canonical_json(build_report(layout=arguments.layout, candidate=arguments.candidate))
        + b"\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
