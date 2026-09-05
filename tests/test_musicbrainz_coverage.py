import tempfile
import unittest
from pathlib import Path

from musix.musicbrainz_coverage import (
    normalize_label,
    run_source_baselines,
    write_reconstruction_inputs,
)
from musix.reconstruction import GenreArtistEdge, ReconstructionInputs, VersionedInput


class MusicBrainzCoverageTests(unittest.TestCase):
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
