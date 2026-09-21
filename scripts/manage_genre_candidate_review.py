"""Create and review queues from a sealed open-label-graph candidate artifact."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.common import write_atomic_bytes
from opennoise.taxonomy.candidates.open_label_graph import (
    genre_candidate_review_from_open_label_graph,
    require_original_open_label_graph_queue,
)
from opennoise.taxonomy.candidates.workflow import (
    GenreCandidateReviewArtifact,
    GenreCandidateReviewDecision,
    verify_genre_candidate_review_artifact,
)
from opennoise.taxonomy.open.label_graph_model import (
    OpenLabelGraphArtifact,
    verify_open_label_graph_model,
)


def _write(path: Path, artifact: GenreCandidateReviewArtifact) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic_bytes(path, (artifact.model_dump_json(indent=2) + "\n").encode())


def _decisions(path: Path) -> tuple[GenreCandidateReviewDecision, ...]:
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("review_decisions")
    if not isinstance(raw, list):
        raise TypeError("decision file must be a JSON array or contain a review_decisions array")
    return tuple(GenreCandidateReviewDecision.model_validate(item) for item in raw)


def _source(path: Path) -> OpenLabelGraphArtifact:
    artifact = OpenLabelGraphArtifact.model_validate_json(path.read_bytes())
    verify_open_label_graph_model(artifact)
    return artifact


def _emit(artifact: GenreCandidateReviewArtifact) -> None:
    sys.stdout.write(
        json.dumps(
            {"output_sha256": artifact.output_sha256, "coverage": artifact.coverage.model_dump()}
        )
        + "\n"
    )


def _queue(arguments: argparse.Namespace) -> int:
    artifact = genre_candidate_review_from_open_label_graph(_source(arguments.source_artifact))
    verify_genre_candidate_review_artifact(artifact)
    _write(arguments.output, artifact)
    _emit(artifact)
    return 0


def _apply(arguments: argparse.Namespace) -> int:
    queue = GenreCandidateReviewArtifact.model_validate_json(arguments.queue.read_bytes())
    source = _source(arguments.source_artifact)
    require_original_open_label_graph_queue(queue, source)
    artifact = genre_candidate_review_from_open_label_graph(
        source, _decisions(arguments.decisions), queue.policy
    )
    if artifact.source_candidate_artifact_sha256 != queue.source_candidate_artifact_sha256:
        raise ValueError("source candidate artifact does not match the review queue")
    verify_genre_candidate_review_artifact(artifact)
    _write(arguments.output, artifact)
    _emit(artifact)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Expose queue creation and decision application as separate local operations."""
    parser = argparse.ArgumentParser(prog="manage-genre-candidate-review")
    commands = parser.add_subparsers(dest="command", required=True)
    queue = commands.add_parser("queue")
    queue.add_argument("--source-artifact", type=Path, required=True)
    queue.add_argument("--output", type=Path, required=True)
    apply = commands.add_parser("apply")
    apply.add_argument("--source-artifact", type=Path, required=True)
    apply.add_argument("--queue", type=Path, required=True)
    apply.add_argument("--decisions", type=Path, required=True)
    apply.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    """Run one review-only candidate queue operation."""
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
