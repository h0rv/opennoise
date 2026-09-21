"""Terminal positive-only Last.fm confirmation for a fixed peer candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from collections import Counter
from pathlib import Path
from typing import Final

_REVISION: Final = "conservative-peer-lastfm-positive-only-v1"
_ARCHIVE_SHA256: Final = "b2b78000279c00c49ad6c0e764203dfbe4deb18a8012c1f43b7fb64933741c4f"
_DATA_MEMBER: Final = "Lastfm-ArtistTags2007/ArtistTags.dat"
_SEPARATOR: Final = "<sep>"
_ROW_FIELDS: Final = 4
_CANDIDATE_BYTE_SHA256: Final = "b605e855681bab1c8b17a7e67dd66f128b00dd4acc6ba1bcde05a9629361c028"
_CANDIDATE_LOGICAL_SHA256: Final = (
    "05eae8b22a94fffddd30e25c29d4629257a611956d9b59a21440e862c80436d2"
)
_RECONCILIATION_SHA256: Final = "c87fe5b67c0974b30d5ae1d2a9f66b22b122126230cd2561837c94897514f022"
_EXPECTED_EDGE_COUNT: Final = 1_497
_EXPECTED_SCOPED_SEED_COUNT: Final = 495
_EXPECTED_CONNECTED_SEED_COUNT: Final = 414
_MINIMUM_SHARED_DIRECT_ARTISTS: Final = 1
_EXCLUDED_ARTIST_SEED_DEGREE: Final = 10


class EvaluationError(ValueError):
    """Raised when a pinned terminal-evaluation input is malformed."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise EvaluationError(f"{label} must be an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise EvaluationError(f"{label} must have string keys")
        result[key] = item
    return result


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise EvaluationError(f"{label} must be a string")
    return value


def _seed_names(path: Path) -> dict[str, str]:
    payload = _mapping(json.loads(path.read_text(encoding="utf-8")), "reconciliation")
    rows = payload.get("dispositions")
    if not isinstance(rows, list):
        raise EvaluationError("reconciliation requires dispositions")
    names: dict[str, str] = {}
    for row in rows:
        item = _mapping(row, "disposition")
        seed_id = _string(item.get("source_item_id"), "source_item_id")
        name = _string(item.get("seed_name"), "seed_name")
        names[seed_id] = name
    return names


def _candidate_requirements(
    path: Path, seed_names: dict[str, str]
) -> tuple[str, dict[str, tuple[str, str, str]]]:
    payload = _mapping(json.loads(path.read_text(encoding="utf-8")), "candidate")
    output_hash = _string(payload.get("output_sha256"), "candidate.output_sha256")
    rows = payload.get("edges")
    if not isinstance(rows, list):
        raise EvaluationError("candidate requires edges")
    requirements: dict[str, tuple[str, str, str]] = {}
    for row in rows:
        edge = _mapping(row, "edge")
        edge_id = _string(edge.get("edge_id"), "edge_id")
        source = _string(edge.get("source_genre_id"), "source_genre_id")
        target = _string(edge.get("target_genre_id"), "target_genre_id")
        evidence = _mapping(edge.get("evidence"), "edge.evidence")
        artist = _string(evidence.get("artist_id"), "edge.evidence.artist_id")
        mbid = artist.removeprefix("musicbrainz:artist:")
        if mbid == artist or source not in seed_names or target not in seed_names:
            raise EvaluationError("candidate edge lacks an exact artist or seed label bridge")
        if edge_id in requirements:
            raise EvaluationError("candidate has duplicate edge IDs")
        requirements[edge_id] = (mbid, seed_names[source], seed_names[target])
    return output_hash, requirements


def _validate_candidate(
    candidate: Path, reconciliation: Path
) -> tuple[str, dict[str, tuple[str, str, str]]]:
    """Reject an altered or structurally incomplete candidate before opening history."""
    if _sha256(candidate) != _CANDIDATE_BYTE_SHA256:
        raise EvaluationError("candidate byte hash does not match the immutable receipt")
    if _sha256(reconciliation) != _RECONCILIATION_SHA256:
        raise EvaluationError("reconciliation byte hash does not match the immutable receipt")
    payload = _mapping(json.loads(candidate.read_text(encoding="utf-8")), "candidate")
    declared_logical_hash = _string(payload.get("output_sha256"), "candidate.output_sha256")
    hash_payload = dict(payload)
    del hash_payload["output_sha256"]
    replayed_logical_hash = hashlib.sha256(
        json.dumps(hash_payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    if (
        declared_logical_hash != _CANDIDATE_LOGICAL_SHA256
        or replayed_logical_hash != declared_logical_hash
    ):
        raise EvaluationError("candidate logical hash does not replay")
    rule = _mapping(payload.get("rule"), "candidate.rule")
    counts = _mapping(payload.get("counts"), "candidate.counts")
    if (
        rule.get("minimum_shared_direct_artists") != _MINIMUM_SHARED_DIRECT_ARTISTS
        or rule.get("sole_shared_artist_seed_degree_must_be_below") != _EXCLUDED_ARTIST_SEED_DEGREE
        or counts.get("edge_count") != _EXPECTED_EDGE_COUNT
        or counts.get("scoped_unplaced_seed_count") != _EXPECTED_SCOPED_SEED_COUNT
        or counts.get("connected_scoped_unplaced_seed_count") != _EXPECTED_CONNECTED_SEED_COUNT
    ):
        raise EvaluationError("candidate rule or fixed count receipt does not match")
    seed_names = _seed_names(reconciliation)
    output_hash, requirements = _candidate_requirements(candidate, seed_names)
    if len(requirements) != _EXPECTED_EDGE_COUNT:
        raise EvaluationError("candidate edge IDs are not unique or complete")
    return output_hash, requirements


def evaluate(  # noqa: C901 - terminal streaming parse keeps positive-only accounting together.
    *, archive: Path, candidate: Path, reconciliation: Path
) -> dict[str, object]:
    """Confirm only observed positive witness tags; missing rows remain abstentions."""
    candidate_output_hash, requirements = _validate_candidate(candidate, reconciliation)
    archive_hash = _sha256(archive)
    if archive_hash != _ARCHIVE_SHA256:
        raise EvaluationError("archive does not match the pinned Last.fm source hash")
    needed_pairs = {
        (mbid, tag) for mbid, source, target in requirements.values() for tag in (source, target)
    }
    observed: set[tuple[str, str]] = set()
    parse = Counter[str]()
    with tarfile.open(archive, mode="r:gz") as source:
        member = source.getmember(_DATA_MEMBER)
        stream = source.extractfile(member)
        if stream is None:
            raise EvaluationError("archive data member is unavailable")
        for raw in stream:
            parse["total_rows"] += 1
            try:
                fields = raw.rstrip(b"\r\n").decode("utf-8").split(_SEPARATOR)
            except UnicodeDecodeError:
                parse["invalid_utf8_rows"] += 1
                continue
            if len(fields) != _ROW_FIELDS:
                parse["malformed_rows"] += 1
                continue
            mbid, _artist_name, tag, raw_count = fields
            try:
                positive = int(raw_count) > 0
            except ValueError:
                parse["invalid_count_rows"] += 1
                continue
            if positive and (mbid, tag) in needed_pairs:
                observed.add((mbid, tag))
    confirmed = 0
    artist_observed = 0
    one_tag_only = 0
    for mbid, source_tag, target_tag in requirements.values():
        source_seen = (mbid, source_tag) in observed
        target_seen = (mbid, target_tag) in observed
        if source_seen or target_seen:
            artist_observed += 1
        if source_seen and target_seen:
            confirmed += 1
        elif source_seen or target_seen:
            one_tag_only += 1
    total = len(requirements)
    scoreable = confirmed + one_tag_only
    report: dict[str, object] = {
        "revision": _REVISION,
        "evaluation_scope": "terminal_local_positive_only_exact_mbid_and_literal_seed_name",
        "inputs": {
            "archive_sha256": archive_hash,
            "candidate_byte_sha256": _sha256(candidate),
            "candidate_output_sha256": candidate_output_hash,
            "reconciliation_byte_sha256": _sha256(reconciliation),
        },
        "counts": {
            "candidate_edge_count": total,
            "candidate_edges_with_any_observed_witness_tag": artist_observed,
            "positive_exact_witness_tag_pair_overlap_count": confirmed,
            "one_tag_only_abstention_count": one_tag_only,
            "no_observed_witness_tag_abstention_count": total - scoreable,
        },
        "positive_only_overlap": {
            "global_candidate_coverage_lower_bound": confirmed / total if total else 0.0,
            "denominator_note": "missing archive tags are abstentions, never negatives",
            "co_observation_diagnostic": (confirmed / scoreable if scoreable else None),
            "co_observation_assumption": (
                "Treats one-tag-only rows as not jointly observed; it is not recall or precision."
            ),
        },
        "historical_used_for_construction_or_tuning": False,
        "precision_or_negative_metrics_computed": False,
        "release_claims_computed": False,
        "public_or_static_data_mutated": False,
    }
    report["output_sha256"] = hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return report


def main() -> int:
    """Write the terminal receipt without altering construction inputs."""
    parser = argparse.ArgumentParser(prog="evaluate-conservative-peer-lastfm-positive-only")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        raise FileExistsError(f"refusing to overwrite evaluation: {arguments.output}")
    report = evaluate(
        archive=arguments.archive,
        candidate=arguments.candidate,
        reconciliation=arguments.reconciliation,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
