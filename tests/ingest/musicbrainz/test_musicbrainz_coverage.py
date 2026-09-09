import sqlite3
import tempfile
import unittest
from pathlib import Path

from musix.evidence.reconstruction import GenreArtistEdge, ReconstructionInputs, VersionedInput
from musix.ingest.musicbrainz.musicbrainz_coverage import (
    build_reconstruction_inputs,
    evaluate_coverage,
    normalize_label,
    run_source_baselines,
    write_reconstruction_inputs,
)


class MusicBrainzCoverageTests(unittest.TestCase):
    def test_coverage_reports_genre_and_tag_facets_separately(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            seed = root / "seed.sqlite"
            research = root / "research.sqlite"
            with sqlite3.connect(seed) as connection:
                connection.execute(
                    "CREATE TABLE genres (id INTEGER PRIMARY KEY, entity_kind TEXT, name TEXT)"
                )
                connection.executemany(
                    "INSERT INTO genres VALUES (?, 'genre', ?)",
                    [(1, "Electric blues"), (2, "Micro-genre"), (3, "Unmatched")],
                )
            with sqlite3.connect(research) as connection:
                connection.executescript(
                    """
                    CREATE TABLE genres (id INTEGER PRIMARY KEY, name TEXT);
                    CREATE TABLE catalog_entities (id INTEGER PRIMARY KEY, entity_kind TEXT);
                    CREATE TABLE artists (id INTEGER PRIMARY KEY);
                    CREATE TABLE identifier_types (id INTEGER PRIMARY KEY, type_key TEXT);
                    CREATE TABLE entity_identifiers (
                        entity_id INTEGER, identifier_type_id INTEGER,
                        normalized_value TEXT
                    );
                    CREATE TABLE entity_names (entity_id INTEGER, name TEXT, name_kind TEXT);
                    CREATE TABLE artist_genre_evidence (
                        id INTEGER PRIMARY KEY, artist_id INTEGER, genre_id INTEGER,
                        evidence_value REAL, source_key TEXT
                    );
                    """
                )
                connection.executemany(
                    "INSERT INTO identifier_types VALUES (?, ?)",
                    [(1, "musicbrainz_genre_id"), (2, "musicbrainz_tag_name"), (3, "source_id")],
                )
                connection.executemany(
                    "INSERT INTO catalog_entities VALUES (?, 'genre')", [(10,), (11,)]
                )
                connection.executemany(
                    "INSERT INTO genres VALUES (?, ?)",
                    [(10, "Electric blues"), (11, "Micro-genre")],
                )
                connection.execute("INSERT INTO artists VALUES (20)")
                connection.executemany(
                    "INSERT INTO entity_identifiers VALUES (?, ?, ?)",
                    [
                        (10, 1, "genre-uuid"),
                        (11, 2, "tag:micro-genre"),
                        (20, 3, "artist-1"),
                    ],
                )
                connection.executemany(
                    "INSERT INTO entity_names VALUES (?, ?, 'primary')",
                    [(10, "Electric blues"), (11, "Micro-genre")],
                )
                connection.executemany(
                    "INSERT INTO artist_genre_evidence VALUES (?, 20, ?, ?, 'fixture')",
                    [(1, 10, 4.0), (2, 11, 3.0), (3, 11, 0.0)],
                )

            report = evaluate_coverage(research, seed, source_key="fixture")
            reconstruction = build_reconstruction_inputs(research, report, source_key="fixture")

        self.assertEqual(report.facet_metrics["genre"].imported_count, 1)
        self.assertEqual(report.facet_metrics["tag"].imported_count, 1)
        self.assertEqual(report.facet_metrics["tag"].positive_evidence_count, 1)
        self.assertEqual({match.facet for match in report.matches}, {"genre", "tag"})
        self.assertEqual({edge.facet for edge in reconstruction.membership_edges}, {"genre", "tag"})
        self.assertIn(
            "musicbrainz:tag:tag:micro-genre",
            {edge.genre_id for edge in reconstruction.membership_edges},
        )

    def test_normalization_is_case_accent_punctuation_and_space_stable(self) -> None:
        self.assertEqual(normalize_label("  Bé-bop / Jazz  "), "be bop jazz")
        self.assertEqual(normalize_label("BÉ BOP JAZZ"), "be bop jazz")

    def test_source_baselines_are_deterministic_and_weighted(self) -> None:
        inputs = ReconstructionInputs(
            membership_artifact=VersionedInput(
                artifact_key="fixture",
                revision="1",
                content_sha256="a" * 64,
            ),
            membership_edges=(
                GenreArtistEdge(
                    genre_id="g1",
                    artist_id="a1",
                    weight=2.0,
                    evidence_refs=("e1",),
                ),
                GenreArtistEdge(
                    genre_id="g2",
                    artist_id="a1",
                    weight=1.0,
                    evidence_refs=("e2",),
                ),
            ),
        )
        first = run_source_baselines(inputs)
        second = run_source_baselines(inputs)
        self.assertEqual(first, second)
        self.assertEqual(first[0].pair_visit_count, 1)
        self.assertEqual(first[0].retained_edge_count, 1)
        self.assertEqual(first[0].edges[0].score, 1.0 / 2.0)

    def test_written_inputs_are_valid_json_and_hash_is_reproducible(self) -> None:
        inputs = ReconstructionInputs(
            membership_artifact=VersionedInput(
                artifact_key="fixture",
                revision="1",
                content_sha256="a" * 64,
            ),
            membership_edges=(
                GenreArtistEdge(
                    genre_id="g1",
                    artist_id="a1",
                    evidence_refs=("e1",),
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inputs.json"
            first = write_reconstruction_inputs(path, inputs)
            second = write_reconstruction_inputs(path, inputs)
            self.assertEqual(first, second)
            self.assertEqual(path.read_bytes(), path.read_bytes())


if __name__ == "__main__":
    unittest.main()
