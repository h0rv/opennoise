"""Audit whether a fixed conservative peer artifact can be terminally evaluated."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Final

_REVISION: Final = "conservative-peer-historical-readiness-v1"
_ARCHIVE_SHA256: Final = "b2b78000279c00c49ad6c0e764203dfbe4deb18a8012c1f43b7fb64933741c4f"
_BASELINE_LOGICAL_SHA256: Final = "15ce7a9a2b40caf64fa1f4050457d4a36635db132a92f9c70a5edce45d68b1cd"
_CONSERVATIVE_ARTIST_SEED_DEGREE_LIMIT: Final = 10


class ReadinessError(ValueError):
    """Raised when a supplied fixed-source receipt cannot be verified."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _required_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ReadinessError(f"{label} must be an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ReadinessError(f"{label} must use string keys")
        result[key] = item
    return result


def _required_string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ReadinessError(f"{label} must be a string")
    return value


def audit(
    *,
    archive: Path,
    sensitivity_report: Path,
    conservative_candidate: Path,
) -> dict[str, object]:
    """Return a non-evaluation receipt when the fixed edge artifact is absent."""
    archive_hash = _sha256(archive)
    if archive_hash != _ARCHIVE_SHA256:
        raise ReadinessError("historical archive does not match its pinned source hash")
    report_hash = _sha256(sensitivity_report)
    report = _required_mapping(json.loads(sensitivity_report.read_text(encoding="utf-8")), "report")
    replay = _required_mapping(report.get("replay"), "report.replay")
    baseline_hash = _required_string(
        replay.get("baseline_logical_output_sha256"), "report.replay.baseline_logical_output_sha256"
    )
    if baseline_hash != _BASELINE_LOGICAL_SHA256:
        raise ReadinessError("sensitivity report does not bind the fixed baseline candidate")
    conservative_value = report.get("conservative_variant")
    conservative = conservative_value if isinstance(conservative_value, dict) else None
    conservative_rule_is_bound = (
        conservative is not None
        and conservative.get("sole_shared_artist_seed_degree_must_be_below")
        == _CONSERVATIVE_ARTIST_SEED_DEGREE_LIMIT
    )

    candidate_exists = conservative_candidate.is_file()
    result: dict[str, object] = {
        "revision": _REVISION,
        "inputs": {
            "historical_archive_sha256": archive_hash,
            "sensitivity_report_sha256": report_hash,
            "baseline_peer_logical_output_sha256": baseline_hash,
            "conservative_rule": "sole_shared_artist_seed_degree_below_10",
            "conservative_rule_is_bound_in_report": conservative_rule_is_bound,
            "reported_conservative_edge_count": (
                conservative.get("added_edge_count") if conservative is not None else None
            ),
        },
        "historical_use": "terminal_positive_only_evaluation_if_and_only_if_fixed_artifact_exists",
        "historical_used_for_tuning": False,
        "precision_or_negative_metrics_computed": False,
        "release_claims_computed": False,
        "public_or_static_data_mutated": False,
    }
    if not candidate_exists or not conservative_rule_is_bound:
        result["status"] = "abstained_fixed_conservative_candidate_artifact_unavailable"
        result["candidate"] = {
            "path": str(conservative_candidate),
            "exists": False,
            "edge_hash": None,
        }
        result["positive_only_metrics"] = {
            "overlap": None,
            "recall": None,
            "abstention_reason": (
                "fixed_conservative_edge_artifact_not_materialized; "
                "sensitivity_report_does_not_bind_conservative_rule"
                if not conservative_rule_is_bound
                else "fixed_conservative_edge_artifact_not_materialized"
            ),
        }
        return result
    result["status"] = "ready_for_separate_terminal_evaluation"
    result["candidate"] = {
        "path": str(conservative_candidate),
        "exists": True,
        "edge_hash": _sha256(conservative_candidate),
    }
    result["positive_only_metrics"] = {
        "overlap": None,
        "recall": None,
        "abstention_reason": "this readiness audit deliberately does_not_evaluate_or_select_edges",
    }
    return result


def main() -> int:
    """Write a compact, no-overwrite readiness receipt."""
    parser = argparse.ArgumentParser(prog="audit-conservative-peer-historical-readiness")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sensitivity-report", type=Path, required=True)
    parser.add_argument("--conservative-candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        raise FileExistsError(f"refusing to overwrite report: {arguments.output}")
    report = audit(
        archive=arguments.archive,
        sensitivity_report=arguments.sensitivity_report,
        conservative_candidate=arguments.conservative_candidate,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    sys.stdout.write(json.dumps(report, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
