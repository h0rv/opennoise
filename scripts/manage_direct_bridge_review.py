"""Build and append sealed direct-bridge review ledgers without publication."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.checkpoints.direct_bridge_audit import (
    DirectBridgeAuditReport,
    DirectBridgeReviewArtifact,
    DirectBridgeReviewDecision,
    audit_direct_bridges,
    build_direct_bridge_review_artifact,
    direct_bridge_audit_sha256,
    parse_direct_bridge_audit_report,
    verify_direct_bridge_review_artifact,
)
from opennoise.common import write_atomic_bytes


def _write(path: Path, artifact: DirectBridgeReviewArtifact) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic_bytes(path, (artifact.model_dump_json(indent=2) + "\n").encode())


def _verified_audit(arguments: argparse.Namespace) -> DirectBridgeAuditReport:
    supplied = parse_direct_bridge_audit_report(
        json.loads(arguments.audit.read_text(encoding="utf-8"))
    )
    recomputed = parse_direct_bridge_audit_report(
        audit_direct_bridges(arguments.graph, arguments.discovery, arguments.database)
    )
    if direct_bridge_audit_sha256(supplied) != direct_bridge_audit_sha256(recomputed):
        raise ValueError("audit JSON does not match the verified audit inputs")
    return supplied


def _decisions(path: Path) -> tuple[DirectBridgeReviewDecision, ...]:
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("review_decisions")
    if not isinstance(raw, list):
        raise TypeError("decision file must be a JSON array or contain a review_decisions array")
    return tuple(DirectBridgeReviewDecision.model_validate(item) for item in raw)


def _emit(artifact: DirectBridgeReviewArtifact) -> None:
    sys.stdout.write(
        json.dumps(
            {
                "output_sha256": artifact.output_sha256,
                "coverage": artifact.coverage.model_dump(mode="json"),
                "static_bridge_published": artifact.static_bridge_published,
            },
            sort_keys=True,
        )
        + "\n"
    )


def _queue(arguments: argparse.Namespace) -> int:
    artifact = build_direct_bridge_review_artifact(_verified_audit(arguments), ())
    verify_direct_bridge_review_artifact(artifact)
    _write(arguments.output, artifact)
    _emit(artifact)
    return 0


def _apply(arguments: argparse.Namespace) -> int:
    audit = _verified_audit(arguments)
    predecessor = DirectBridgeReviewArtifact.model_validate_json(arguments.predecessor.read_bytes())
    verify_direct_bridge_review_artifact(predecessor)
    if predecessor.source_audit_sha256 != direct_bridge_audit_sha256(audit):
        raise ValueError("predecessor references a different verified audit")
    artifact = build_direct_bridge_review_artifact(
        audit,
        predecessor.review_decisions + _decisions(arguments.decisions),
        predecessor.policy,
        predecessor,
    )
    verify_direct_bridge_review_artifact(artifact)
    _write(arguments.output, artifact)
    _emit(artifact)
    return 0


def _add_audit_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument(
        "--graph", type=Path, default=Path("data/model/open-construction-graph-v2.json")
    )
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=Path("data/public.sqlite"))


def build_parser() -> argparse.ArgumentParser:
    """Expose queue and append-only decision operations without publication commands."""
    parser = argparse.ArgumentParser(prog="manage-direct-bridge-review")
    commands = parser.add_subparsers(dest="command", required=True)
    queue = commands.add_parser("queue")
    _add_audit_arguments(queue)
    queue.add_argument("--output", type=Path, required=True)
    apply = commands.add_parser("apply")
    _add_audit_arguments(apply)
    apply.add_argument("--predecessor", type=Path, required=True)
    apply.add_argument("--decisions", type=Path, required=True)
    apply.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    """Run a review-only direct-bridge queue or append operation."""
    arguments = build_parser().parse_args()
    match arguments.command:
        case "queue":
            return _queue(arguments)
        case "apply":
            return _apply(arguments)
        case unexpected:
            raise ValueError(f"unsupported command {unexpected!r}")


if __name__ == "__main__":
    raise SystemExit(main())
