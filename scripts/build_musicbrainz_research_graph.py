"""Build or sealed-evaluate the local-only MusicBrainz name-seed graph."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from musix.ingest.musicbrainz_research_graph import (
    ResearchGraphBuildConfig,
    build_gate,
    build_musicbrainz_research_graph,
    evaluate_sealed_graph,
    write_research_graph,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser(
        "build", help="build a local-only graph from name seeds and MusicBrainz"
    )
    build.add_argument("--coverage", type=Path, required=True)
    build.add_argument("--reconstruction-inputs", type=Path, required=True)
    build.add_argument("--research-database", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--gate-report", type=Path, required=True)
    build.add_argument("--expected-genre-count", type=int, default=724)
    build.add_argument("--max-neighbors", type=int, default=12)
    build.add_argument("--landscape-iterations", type=int, default=80)
    evaluate = commands.add_parser(
        "evaluate", help="compare a sealed graph with a historical topology"
    )
    evaluate.add_argument("--graph", type=Path, required=True)
    evaluate.add_argument("--expected-graph-sha256", required=True)
    evaluate.add_argument("--historical-benchmark", type=Path, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    evaluate.add_argument("--neighbor-count", type=int, default=10)
    return parser.parse_args()


def main() -> int:
    """Execute one explicit build or post-sealing evaluation command."""
    arguments = _arguments()
    try:
        if arguments.command == "build":
            graph = build_musicbrainz_research_graph(
                arguments.coverage,
                arguments.reconstruction_inputs,
                arguments.research_database,
                config=ResearchGraphBuildConfig(
                    expected_genre_count=arguments.expected_genre_count,
                    max_neighbors=arguments.max_neighbors,
                    landscape_iterations=arguments.landscape_iterations,
                ),
            )
            byte_sha = write_research_graph(arguments.output, graph)
            gate = build_gate(graph)
            arguments.gate_report.parent.mkdir(parents=True, exist_ok=True)
            arguments.gate_report.write_text(
                gate.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
            sys.stdout.write(
                f"graph logical sha256: {graph.output_sha256}\ngraph byte sha256: {byte_sha}\n"
            )
        else:
            report = evaluate_sealed_graph(
                arguments.graph,
                arguments.historical_benchmark,
                expected_graph_sha256=arguments.expected_graph_sha256,
                neighbor_count=arguments.neighbor_count,
            )
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
            sys.stdout.write(report.model_dump_json(indent=2) + "\n")
    except (OSError, TypeError, ValueError) as error:
        sys.stderr.write(f"musicbrainz research graph failed: {error}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
