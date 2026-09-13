"""Evaluate a local MusicBrainz artist partition against Every Noise names."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.ingest.musicbrainz.coverage import (
    BaselineReport,
    BaselineRun,
    ReconstructionArtifactReport,
    build_reconstruction_inputs,
    evaluate_coverage,
    run_source_baselines,
    write_reconstruction_inputs,
)


def main() -> int:
    """Parse options, evaluate coverage, and optionally run source-only baselines."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research-database", type=Path, required=True)
    parser.add_argument("--seed-database", type=Path, default=Path("data/opennoise.sqlite"))
    parser.add_argument("--source-key", default="musicbrainz_json_artist_research_20260829")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--baseline-report", type=Path)
    arguments = parser.parse_args()

    coverage = evaluate_coverage(
        arguments.research_database,
        arguments.seed_database,
        source_key=arguments.source_key,
    )
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(
        coverage.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    output: dict[str, object] = {"coverage": coverage.model_dump(mode="json")}
    if arguments.inputs is not None:
        inputs = build_reconstruction_inputs(
            arguments.research_database,
            coverage,
            source_key=arguments.source_key,
        )
        artifact_sha = write_reconstruction_inputs(arguments.inputs, inputs)
        baselines = run_source_baselines(inputs)
        baseline_report = BaselineReport(
            artifact_sha256=artifact_sha,
            runs=tuple(
                BaselineRun(
                    metric=result.parameters.metric,
                    genre_count=result.genre_count,
                    candidate_pair_count=result.candidate_pair_count,
                    pair_visit_count=result.pair_visit_count,
                    retained_edge_count=result.retained_edge_count,
                    neighbor_count=len(result.neighbors),
                )
                for result in baselines
            ),
        )
        artifact_report = ReconstructionArtifactReport(
            inputs_path=str(arguments.inputs),
            inputs_sha256=artifact_sha,
            seed_matched_genre_count=len(
                {genre_id for match in coverage.matches for genre_id in match.musicbrainz_genre_ids}
            ),
            edge_count=len(inputs.membership_edges),
            artist_count=len({edge.artist_id for edge in inputs.membership_edges}),
            weighted_jaccard_neighbor_count=len(baselines[0].neighbors),
            weighted_cosine_neighbor_count=len(baselines[1].neighbors),
            weighted_jaccard_pair_visits=baselines[0].pair_visit_count,
            weighted_cosine_pair_visits=baselines[1].pair_visit_count,
        )
        if arguments.baseline_report is not None:
            arguments.baseline_report.parent.mkdir(parents=True, exist_ok=True)
            arguments.baseline_report.write_text(
                json.dumps(
                    {
                        "artifact": artifact_report.model_dump(mode="json"),
                        "baselines": baseline_report.model_dump(mode="json"),
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
        output["artifact"] = artifact_report.model_dump(mode="json")
        output["baselines"] = baseline_report.model_dump(mode="json")
    sys.stdout.write(json.dumps(output, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
