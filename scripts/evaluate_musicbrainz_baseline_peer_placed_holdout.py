"""Hold out placed atlas coordinates using the frozen minimum-two direct-peer graph."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import ijson

from opennoise.serving.local.conservative_peer_holdout import Point, adjacency, evaluate_holdout

_EXPECTED_SEED_COUNT = 6_291
_EXPECTED_PLACED_SEED_COUNT = 2_945
_EXPECTED_UNPLACED_SEED_COUNT = 3_346
_EXPECTED_BASELINE_PLACED_EDGE_COUNT = 28_508
_MINIMUM_BASELINE_SHARED_ARTISTS = 2
_PINNED_INPUT_SHA256 = "ddc5d06c26ca79efa2fe038eea758200bff1528d21db5f2d8927b8aed55f24de"
_PINNED_SETTINGS_SHA256 = "88a708cd5d0745c87a6c4f164fe8c0d306345ffaa59b87a87aa1b929255eef0f"
_PINNED_LAYOUT_BYTE_SHA256 = "e7723b42657451a341e92a9aefa1ced499067e673366b468fd38f84fc86f5972"
_PINNED_CANDIDATE_BYTE_SHA256 = "1991cac3a084d2f02bd56c090fef7cadca263d6953a9aaaaee13425b1813bb39"


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise TypeError(f"{label} must be an object with string keys")
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _string(row: dict[str, object], key: str) -> str:
    if not isinstance(value := row.get(key), str):
        raise TypeError(f"row requires string {key}")
    return value


def _number(row: dict[str, object], key: str) -> float:
    value = row.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"row requires numeric {key}")
    return float(value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_no_replace(path: Path, content: bytes) -> None:
    """Atomically create a local report without replacing a concurrent writer."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)


def _read_layout(path: Path) -> tuple[dict[str, Point], frozenset[str]]:
    payload = _mapping(json.loads(path.read_bytes()), "layout")
    coordinates, unplaced = payload.get("coordinates"), payload.get("unplaced")
    if not isinstance(coordinates, list) or not isinstance(unplaced, list):
        raise TypeError("layout requires coordinates and unplaced")
    anchors: dict[str, Point] = {}
    for value in coordinates:
        row = _mapping(value, "coordinate")
        seed_id = _string(row, "seed_id")
        if seed_id in anchors:
            raise ValueError("layout has duplicate placed seed IDs")
        anchors[seed_id] = Point(_number(row, "x"), _number(row, "y"))
    unplaced_values = tuple(_string(_mapping(value, "unplaced"), "seed_id") for value in unplaced)
    unplaced_ids = frozenset(unplaced_values)
    if len(unplaced_values) != len(unplaced_ids):
        raise ValueError("layout has duplicate unplaced seed IDs")
    if set(anchors) & unplaced_ids:
        raise ValueError("layout IDs cannot be both placed and unplaced")
    if (
        len(anchors) != _EXPECTED_PLACED_SEED_COUNT
        or len(unplaced_ids) != _EXPECTED_UNPLACED_SEED_COUNT
        or len(anchors) + len(unplaced_ids) != _EXPECTED_SEED_COUNT
    ):
        raise ValueError("layout does not have the fixed placed and unplaced counts")
    return anchors, unplaced_ids


def _stream_conservative_baseline_edges(
    path: Path, anchors: dict[str, Point]
) -> tuple[tuple[str, str], ...]:
    """Retain placed pairs satisfying the same conservative predicate.

    The frozen baseline has a predeclared minimum of two shared direct artists;
    it therefore satisfies the predicate without admitting any singleton edge
    whose sole artist would require the degree-below-ten branch.
    """
    pairs: list[tuple[str, str]] = []
    with path.open("rb") as stream:
        for value in ijson.items(stream, "candidates.item"):
            row = _mapping(value, "candidate")
            shared = row.get("shared_direct_artist_count")
            if (
                not isinstance(shared, int)
                or isinstance(shared, bool)
                or shared < _MINIMUM_BASELINE_SHARED_ARTISTS
            ):
                continue
            left, right = _string(row, "source_genre_id"), _string(row, "target_genre_id")
            if left in anchors and right in anchors:
                pairs.append((left, right))
    return tuple(pairs)


def _pinned_candidate_header(path: Path) -> tuple[str, str]:
    """Read the two identity fields before streaming the large candidate body."""
    input_sha256: str | None = None
    settings_sha256: str | None = None
    with path.open("rb") as stream:
        for prefix, event, value in ijson.parse(stream):
            if event != "string":
                continue
            if prefix == "input_sha256":
                input_sha256 = str(value)
            elif prefix == "settings_sha256":
                settings_sha256 = str(value)
            if input_sha256 is not None and settings_sha256 is not None:
                return input_sha256, settings_sha256
    raise ValueError("baseline candidate lacks pinned identity fields")


def build_report(*, layout: Path, baseline_candidate: Path) -> dict[str, object]:
    """Evaluate a pinned, fixed direct-peer source without changing either candidate."""
    layout_hash = _sha256(layout)
    candidate_hash = _sha256(baseline_candidate)
    if layout_hash != _PINNED_LAYOUT_BYTE_SHA256:
        raise ValueError("layout bytes do not match the pinned v3 atlas")
    if candidate_hash != _PINNED_CANDIDATE_BYTE_SHA256:
        raise ValueError("baseline candidate bytes do not match the pinned candidate")
    anchors, unplaced = _read_layout(layout)
    input_sha256, settings_sha256 = _pinned_candidate_header(baseline_candidate)
    if input_sha256 != _PINNED_INPUT_SHA256 or settings_sha256 != _PINNED_SETTINGS_SHA256:
        raise ValueError("baseline candidate is not the pinned direct-membership replay")
    edges = _stream_conservative_baseline_edges(baseline_candidate, anchors)
    if len(edges) != _EXPECTED_BASELINE_PLACED_EDGE_COUNT:
        raise ValueError("baseline does not have the fixed placed-to-placed edge count")
    summary = evaluate_holdout(anchors=anchors, peer_adjacency=adjacency(edges))
    report: dict[str, object] = {
        "revision": "musicbrainz-baseline-direct-peer-placed-holdout-v1",
        "scope": "local_only_open_data_geometry_diagnostic",
        "historical_inputs_used": False,
        "layout_mutated": False,
        "similarity_claim": "none; frozen shared direct-artist evidence only",
        "inputs": {
            "layout_byte_sha256": layout_hash,
            "baseline_candidate_byte_sha256": candidate_hash,
        },
        "coverage": {
            "placed_seed_count": len(anchors),
            "unplaced_seed_count": len(unplaced),
            "retained_placed_to_placed_edge_count": len(edges),
        },
        "holdout": {
            "target_coordinate_excluded_from_prediction": True,
            "evaluable_placed_target_count": summary.evaluable_target_count,
            "mean_peer_error": summary.mean_peer_error,
            "mean_leave_one_out_global_centroid_error": summary.mean_global_baseline_error,
            "mean_error_improvement": summary.mean_error_improvement,
            "median_peer_error": summary.median_peer_error,
            "median_leave_one_out_global_centroid_error": summary.median_global_baseline_error,
            "peer_beats_baseline_count": summary.peer_beats_baseline_count,
        },
    }
    report["output_sha256"] = hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return report


def main() -> int:
    """Write one no-overwrite local geometry report."""
    parser = argparse.ArgumentParser(prog="evaluate-musicbrainz-baseline-peer-placed-holdout")
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--baseline-candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    _write_no_replace(
        arguments.output,
        (
            json.dumps(
                build_report(
                    layout=arguments.layout, baseline_candidate=arguments.baseline_candidate
                ),
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
