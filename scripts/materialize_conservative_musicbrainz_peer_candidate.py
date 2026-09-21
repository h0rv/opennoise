"""Materialize the fixed local conservative MusicBrainz peer-edge candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import ijson

_REVISION: Final = "conservative-musicbrainz-peer-candidate-v1"
_BASELINE_LOGICAL_SHA256: Final = "15ce7a9a2b40caf64fa1f4050457d4a36635db132a92f9c70a5edce45d68b1cd"
_BASELINE_SETTINGS_SHA256: Final = (
    "88a708cd5d0745c87a6c4f164fe8c0d306345ffaa59b87a87aa1b929255eef0f"
)
_PUBLIC_INPUT_SHA256: Final = "3c2c8b23e00c0201f1505be6851bc392258665cb11fc353949c1a332ebc9dd1c"
_SENSITIVITY_REPORT_SHA256: Final = (
    "8391ebccb7f37f7dd9d784bb8045f9ca066a649d054f0a3a3dd4a68c83808d54"
)
_LAYOUT_LOGICAL_SHA256: Final = "853353cfdc4d9ad1ea2a6faaaf58eff372b760133f70d3512e8d6de185838f76"
_MAX_SHARED_ARTIST_SEED_DEGREE: Final = 9
_EXPECTED_EDGE_COUNT: Final = 1_497
_EXPECTED_SCOPED_SEED_COUNT: Final = 495
_EXPECTED_CONNECTED_SEED_COUNT: Final = 414


class MaterializationError(ValueError):
    """Raised when a fixed candidate input or replay invariant is not satisfied."""


@dataclass(frozen=True, slots=True)
class DirectMembership:
    """One direct evidence reference grouped at the artist--seed boundary."""

    artist_id: str
    genre_id: str
    evidence_ref: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _required_string(row: object, key: str) -> str:
    if not isinstance(row, dict) or not isinstance(value := row.get(key), str):
        raise MaterializationError(f"row requires string {key}")
    return value


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise MaterializationError(f"{label} must be an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise MaterializationError(f"{label} must have string keys")
        result[key] = item
    return result


def _unplaced_seed_ids(path: Path) -> tuple[frozenset[str], str]:
    """Read only the local layout's unplaced seed IDs."""
    payload = _mapping(json.loads(path.read_text(encoding="utf-8")), "layout")
    if not isinstance(rows := payload.get("unplaced"), list):
        raise MaterializationError("layout requires an unplaced list")
    return frozenset(_required_string(row, "seed_id") for row in rows), _required_string(
        payload, "output_sha256"
    )


def _validate_pinned_receipt(
    sensitivity_report: Path, baseline_candidate: Path, layout: Path, layout_output_sha256: str
) -> tuple[str, str]:
    """Bind all local construction inputs to the fixed sensitivity receipt."""
    if _sha256(sensitivity_report) != _SENSITIVITY_REPORT_SHA256:
        raise MaterializationError("sensitivity receipt byte hash is not pinned")
    report = _mapping(json.loads(sensitivity_report.read_text(encoding="utf-8")), "receipt")
    inputs = _mapping(report.get("inputs"), "receipt.inputs")
    baseline = _mapping(inputs.get("baseline_candidate"), "receipt.baseline")
    layout_receipt = _mapping(inputs.get("layout"), "receipt.layout")
    if (
        baseline.get("logical_output_sha256") != _BASELINE_LOGICAL_SHA256
        or baseline.get("settings_sha256") != _BASELINE_SETTINGS_SHA256
        or layout_receipt.get("logical_output_sha256") != _LAYOUT_LOGICAL_SHA256
        or layout_output_sha256 != _LAYOUT_LOGICAL_SHA256
    ):
        raise MaterializationError("pinned baseline settings or layout identity does not match")
    baseline_hash = _sha256(baseline_candidate)
    layout_hash = _sha256(layout)
    if (
        baseline.get("byte_sha256") != baseline_hash
        or layout_receipt.get("byte_sha256") != layout_hash
    ):
        raise MaterializationError("pinned receipt does not match local baseline or layout bytes")
    return baseline_hash, layout_hash


def _read_scoped_seeds(path: Path, unplaced: frozenset[str]) -> frozenset[str]:
    """Stream only threshold-one abstentions to define the already-fixed scope."""
    scoped: set[str] = set()
    with path.open("rb") as stream:
        for row in ijson.items(stream, "abstentions.item"):
            if not isinstance(row, dict) or row.get("reason") != "insufficient_direct_overlap":
                continue
            for key in ("source_genre_id", "target_genre_id"):
                value = row.get(key)
                if isinstance(value, str) and value in unplaced:
                    scoped.add(value)
    if len(scoped) != _EXPECTED_SCOPED_SEED_COUNT:
        raise MaterializationError("baseline candidate has an unexpected scoped abstention count")
    return frozenset(scoped)


def _target_artists(path: Path, scoped: frozenset[str]) -> frozenset[str]:
    """Stream direct rows once to retain only artists that touch the fixed scope."""
    artists: set[str] = set()
    with path.open("rb") as stream:
        for row in ijson.items(stream, "direct_memberships.item"):
            if not isinstance(row, dict) or row.get("genre_id") not in scoped:
                continue
            artists.add(_required_string(row, "artist_id"))
    return frozenset(artists)


def _target_memberships(
    path: Path, target_artists: frozenset[str]
) -> dict[str, dict[str, tuple[str, ...]]]:
    """Stream direct rows again and retain evidence only for scoped-touching artists."""
    memberships: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    with path.open("rb") as stream:
        for row in ijson.items(stream, "direct_memberships.item"):
            if not isinstance(row, dict):
                continue
            artist_id = row.get("artist_id")
            if not isinstance(artist_id, str) or artist_id not in target_artists:
                continue
            membership = DirectMembership(
                artist_id=artist_id,
                genre_id=_required_string(row, "genre_id"),
                evidence_ref=_required_string(row, "evidence_ref"),
            )
            memberships[membership.artist_id][membership.genre_id].add(membership.evidence_ref)
    return {
        artist_id: {
            genre_id: tuple(sorted(evidence_refs))
            for genre_id, evidence_refs in sorted(genres.items())
        }
        for artist_id, genres in sorted(memberships.items())
    }


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def materialize(
    *, baseline_candidate: Path, public_input: Path, layout: Path, sensitivity_report: Path
) -> dict[str, object]:
    """Build the fixed degree-bounded edges without using historical data."""
    unplaced, layout_output_sha256 = _unplaced_seed_ids(layout)
    baseline_hash, layout_hash = _validate_pinned_receipt(
        sensitivity_report, baseline_candidate, layout, layout_output_sha256
    )
    public_input_hash = _sha256(public_input)
    if public_input_hash != _PUBLIC_INPUT_SHA256:
        raise MaterializationError("direct-membership input does not match the pinned source hash")
    scoped = _read_scoped_seeds(baseline_candidate, unplaced)
    target_artists = _target_artists(public_input, scoped)
    memberships = _target_memberships(public_input, target_artists)
    edge_artists: dict[tuple[str, str], list[tuple[str, int, tuple[str, ...], tuple[str, ...]]]] = (
        defaultdict(list)
    )
    for artist_id, genres in memberships.items():
        artist_degree = len(genres)
        ordered_genres = tuple(genres)
        for offset, source_genre_id in enumerate(ordered_genres):
            for target_genre_id in ordered_genres[offset + 1 :]:
                if source_genre_id not in scoped and target_genre_id not in scoped:
                    continue
                edge_artists[(source_genre_id, target_genre_id)].append(
                    (
                        artist_id,
                        artist_degree,
                        genres[source_genre_id],
                        genres[target_genre_id],
                    )
                )
    edges: list[dict[str, object]] = []
    for (source_genre_id, target_genre_id), witnesses in sorted(edge_artists.items()):
        if len(witnesses) != 1 or witnesses[0][1] > _MAX_SHARED_ARTIST_SEED_DEGREE:
            continue
        artist_id, artist_degree, source_refs, target_refs = witnesses[0]
        evidence = {
            "artist_id": artist_id,
            "artist_seed_degree": artist_degree,
            "source_direct_evidence_refs": list(source_refs),
            "target_direct_evidence_refs": list(target_refs),
        }
        edge_key = {"source_genre_id": source_genre_id, "target_genre_id": target_genre_id}
        edges.append(
            {
                "edge_id": hashlib.sha256(_canonical_json(edge_key)).hexdigest(),
                **edge_key,
                "shared_direct_artist_count": 1,
                "evidence": evidence,
            }
        )
    connected_scoped = {
        seed
        for edge in edges
        for seed in (edge["source_genre_id"], edge["target_genre_id"])
        if seed in scoped
    }
    if (
        len(edges) != _EXPECTED_EDGE_COUNT
        or len(connected_scoped) != _EXPECTED_CONNECTED_SEED_COUNT
    ):
        raise MaterializationError(
            "conservative edge replay does not match the fixed checkpoint counts"
        )
    report: dict[str, object] = {
        "revision": _REVISION,
        "construction_scope": "local_only_open_direct_musicbrainz_evidence",
        "historical_inputs_used": False,
        "public_or_static_data_mutated": False,
        "baseline": {
            "path": str(baseline_candidate),
            "byte_sha256": baseline_hash,
            "logical_output_sha256": _BASELINE_LOGICAL_SHA256,
            "settings_sha256": _BASELINE_SETTINGS_SHA256,
        },
        "public_input": {"path": str(public_input), "byte_sha256": public_input_hash},
        "layout": {
            "path": str(layout),
            "byte_sha256": layout_hash,
            "logical_output_sha256": layout_output_sha256,
        },
        "sensitivity_report": {
            "path": str(sensitivity_report),
            "byte_sha256": _SENSITIVITY_REPORT_SHA256,
        },
        "rule": {
            "minimum_shared_direct_artists": 1,
            "sole_shared_artist_seed_degree_must_be_below": 10,
        },
        "counts": {
            "scoped_unplaced_seed_count": len(scoped),
            "connected_scoped_unplaced_seed_count": len(connected_scoped),
            "edge_count": len(edges),
        },
        "edges": edges,
    }
    report["output_sha256"] = hashlib.sha256(_canonical_json(report)).hexdigest()
    return report


def main() -> int:
    """Write a no-overwrite, hash-bound local candidate artifact."""
    parser = argparse.ArgumentParser(prog="materialize-conservative-musicbrainz-peer-candidate")
    parser.add_argument("--baseline-candidate", type=Path, required=True)
    parser.add_argument("--public-input", type=Path, required=True)
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--sensitivity-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        raise FileExistsError(f"refusing to overwrite candidate: {arguments.output}")
    report = materialize(
        baseline_candidate=arguments.baseline_candidate,
        public_input=arguments.public_input,
        layout=arguments.layout,
        sensitivity_report=arguments.sensitivity_report,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_bytes(_canonical_json(report) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
