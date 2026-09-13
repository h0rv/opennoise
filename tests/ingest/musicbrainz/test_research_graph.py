import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from opennoise.evidence.reconstruction import GenreArtistEdge, ReconstructionInputs, VersionedInput
from opennoise.ingest.musicbrainz.coverage import CoverageMatch, CoverageReport
from opennoise.ingest.musicbrainz.research_graph import (
    ResearchGraphBuildConfig,
    build_gate,
    build_musicbrainz_research_graph,
    evaluate_sealed_graph,
    write_research_graph,
)


class MusicBrainzResearchGraphTests(unittest.TestCase):
    def _coverage(self) -> CoverageReport:
        matches = tuple(
            CoverageMatch(
                seed_name=name,
                match_kind="exact",
                musicbrainz_genre_ids=(genre_id,),
                positive_artist_count=2,
                positive_evidence_count=2,
            )
            for name, genre_id in (("Alpha", "g1"), ("Beta", "g2"), ("Gamma", "g3"))
        )
        return CoverageReport(
            research_database="research.sqlite",
            seed_database="seeds.sqlite",
            source_key="fixture",
            seed_name_count=3,
            imported_genre_count=3,
            imported_genre_alias_count=0,
            imported_name_count=3,
            imported_positive_genre_count=3,
            imported_positive_artist_count=3,
            imported_positive_evidence_count=6,
            imported_positive_weight_sum=6.0,
            imported_positive_weight_distribution={"1": 6},
            exact_match_count=3,
            normalized_match_count=3,
            exact_positive_match_count=3,
            normalized_positive_match_count=3,
            distinct_matched_genre_count=3,
            distinct_positive_artist_count=3,
            positive_evidence_count=6,
            positive_weight_sum=6.0,
            positive_weight_distribution={"1": 6},
            normalized_rule="fixture",
            matches=matches,
            unmatched_seed_names=(),
            runtime_seconds=0.0,
        )

    def _inputs(self) -> ReconstructionInputs:
        return ReconstructionInputs(
            membership_artifact=VersionedInput(
                artifact_key="fixture-musicbrainz", revision="1", content_sha256="a" * 64
            ),
            membership_edges=(
                GenreArtistEdge(
                    genre_id="musicbrainz:genre:g1",
                    artist_id="musicbrainz:artist:a1",
                    evidence_refs=("e1",),
                ),
                GenreArtistEdge(
                    genre_id="musicbrainz:genre:g1",
                    artist_id="musicbrainz:artist:a2",
                    evidence_refs=("e2",),
                ),
                GenreArtistEdge(
                    genre_id="musicbrainz:genre:g2",
                    artist_id="musicbrainz:artist:a1",
                    evidence_refs=("e3",),
                ),
                GenreArtistEdge(
                    genre_id="musicbrainz:genre:g2",
                    artist_id="musicbrainz:artist:a3",
                    evidence_refs=("e4",),
                ),
                GenreArtistEdge(
                    genre_id="musicbrainz:genre:g3",
                    artist_id="musicbrainz:artist:a2",
                    evidence_refs=("e5",),
                ),
                GenreArtistEdge(
                    genre_id="musicbrainz:genre:g3",
                    artist_id="musicbrainz:artist:a3",
                    evidence_refs=("e6",),
                ),
            ),
        )

    def _research_database(self, path: Path) -> None:
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE artist_genre_evidence (id TEXT, source_key TEXT, evidence_value REAL)"
            )
            connection.executemany(
                "INSERT INTO artist_genre_evidence VALUES (?, 'fixture', 1.0)",
                ((f"e{number}",) for number in range(1, 7)),
            )

    def test_build_is_deterministic_local_only_and_evaluable_after_sealing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            coverage_path = root / "coverage.json"
            inputs_path = root / "inputs.json"
            database_path = root / "research.sqlite"
            graph_path = root / "graph.json"
            benchmark_path = root / "historical.json"
            coverage_path.write_text(self._coverage().model_dump_json(), encoding="utf-8")
            inputs_path.write_text(self._inputs().model_dump_json(), encoding="utf-8")
            self._research_database(database_path)
            config = ResearchGraphBuildConfig(expected_genre_count=3, max_neighbors=2)
            first = build_musicbrainz_research_graph(
                coverage_path, inputs_path, database_path, config=config
            )
            second = build_musicbrainz_research_graph(
                coverage_path, inputs_path, database_path, config=config
            )
            self.assertEqual(first, second)
            self.assertEqual(first.quality.genre_count, 3)
            self.assertEqual(first.quality.membership_count, 6)
            self.assertFalse(first.quality.exportable_public_model)
            self.assertTrue(first.inputs.historical_coordinates_excluded)
            self.assertEqual(len(first.landscape), 3)
            self.assertEqual(build_gate(first).graph_sha256, first.output_sha256)
            write_research_graph(graph_path, first)
            benchmark_path.write_text(
                json.dumps(
                    {
                        "nodes": [
                            {"genre_id": "h1", "name": "Alpha", "x": 99},
                            {"genre_id": "h2", "name": "Beta", "x": 98},
                            {"genre_id": "h3", "name": "Gamma", "x": 97},
                        ],
                        "neighbors": [
                            {"genre_id": "h1", "neighbor_genre_id": "h2", "rank": 1},
                            {"genre_id": "h2", "neighbor_genre_id": "h1", "rank": 1},
                            {"genre_id": "h3", "neighbor_genre_id": "h1", "rank": 1},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            report = evaluate_sealed_graph(
                graph_path,
                benchmark_path,
                expected_graph_sha256=first.output_sha256,
            )
            self.assertEqual(report.overlap_by_normalized_name_count, 3)
            self.assertFalse(report.historical_coordinates_read)
            self.assertFalse(report.historical_artist_assignments_read)

    def test_evaluation_requires_the_declared_sealed_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            coverage_path = root / "coverage.json"
            inputs_path = root / "inputs.json"
            database_path = root / "research.sqlite"
            graph_path = root / "graph.json"
            benchmark_path = root / "benchmark.json"
            coverage_path.write_text(self._coverage().model_dump_json(), encoding="utf-8")
            inputs_path.write_text(self._inputs().model_dump_json(), encoding="utf-8")
            self._research_database(database_path)
            graph = build_musicbrainz_research_graph(
                coverage_path,
                inputs_path,
                database_path,
                config=ResearchGraphBuildConfig(expected_genre_count=3),
            )
            write_research_graph(graph_path, graph)
            benchmark_path.write_text('{"nodes": [], "neighbors": []}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "expected graph hash"):
                evaluate_sealed_graph(
                    graph_path,
                    benchmark_path,
                    expected_graph_sha256="0" * 64,
                )


if __name__ == "__main__":
    unittest.main()
