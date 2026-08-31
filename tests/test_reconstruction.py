import math
import tempfile
import unittest
from pathlib import Path
from typing import override

from pydantic import ValidationError

from musix.reconstruction import (
    EvidenceStatus,
    GenreArtistEdge,
    HistoricalClaim,
    HistoricalGenrePoint,
    HistoricalNeighborList,
    ParameterGrid,
    ReconstructionExperimentManifest,
    ReconstructionInputs,
    ReconstructionPoint,
    SimilarityMetric,
    SimilarityParameters,
    VersionedInput,
    align_to_historical_points,
    build_artist_overlap_similarity,
    evaluate_neighborhood_preservation,
    expand_parameter_grid,
    run_reconstruction_experiment,
)
from scripts.evaluate_reconstruction import MAX_MANIFEST_BYTES, read_manifest

ARTIFACT = VersionedInput(
    artifact_key="synthetic-memberships",
    revision="1",
    content_sha256="a" * 64,
)


def edge(genre_id: str, artist_id: str, weight: float = 1.0) -> GenreArtistEdge:
    """Build one synthetic membership edge."""
    return GenreArtistEdge(
        genre_id=genre_id,
        artist_id=artist_id,
        weight=weight,
        evidence_refs=(f"fixture:{genre_id}:{artist_id}",),
    )


class ReconstructionBoundaryTests(unittest.TestCase):
    def test_disclosed_claim_requires_evidence(self) -> None:
        with self.assertRaises(ValidationError):
            HistoricalClaim(
                claim_key="axes",
                statement="The map has disclosed axes.",
                evidence_status=EvidenceStatus.DISCLOSED,
            )

    def test_inferred_claim_requires_nonempty_unique_evidence(self) -> None:
        with self.assertRaises(ValidationError):
            HistoricalClaim(
                claim_key="axes",
                statement="The candidate axes may explain the historical output.",
                evidence_status=EvidenceStatus.INFERRED,
            )
        with self.assertRaises(ValidationError):
            GenreArtistEdge(
                genre_id="a",
                artist_id="one",
                evidence_refs=("fixture", "fixture"),
            )
        with self.assertRaises(ValidationError):
            GenreArtistEdge(genre_id="a", artist_id="one", evidence_refs=("",))

    def test_manifest_reader_rejects_oversized_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            manifest_path = Path(temporary_directory) / "manifest.json"
            manifest_path.write_bytes(b" " * (MAX_MANIFEST_BYTES + 1))
            with self.assertRaisesRegex(ValueError, "manifest exceeds"):
                read_manifest(manifest_path)

    def test_duplicate_membership_pair_is_rejected(self) -> None:
        duplicate = edge("a", "one")
        with self.assertRaises(ValidationError):
            ReconstructionInputs(
                membership_artifact=ARTIFACT,
                membership_edges=(duplicate, duplicate),
            )


class SimilarityBaselineTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.edges = (
            edge("a", "one", 2.0),
            edge("a", "two", 1.0),
            edge("b", "one", 1.0),
            edge("b", "three", 1.0),
            edge("c", "four", 1.0),
        )

    def test_weighted_jaccard_and_direct_overlap_graph(self) -> None:
        result = build_artist_overlap_similarity(
            self.edges,
            SimilarityParameters(
                metric=SimilarityMetric.WEIGHTED_JACCARD,
                max_neighbors=2,
            ),
        )
        self.assertEqual(result.candidate_pair_count, 1)
        self.assertEqual(result.retained_edge_count, 1)
        self.assertAlmostEqual(result.edges[0].score, 0.25)
        neighbors = {item.genre_id: item.neighbor_ids for item in result.neighbors}
        self.assertEqual(neighbors, {"a": ("b",), "b": ("a",), "c": ()})

    def test_weighted_cosine(self) -> None:
        result = build_artist_overlap_similarity(
            self.edges,
            SimilarityParameters(
                metric=SimilarityMetric.WEIGHTED_COSINE,
                max_neighbors=1,
            ),
        )
        self.assertAlmostEqual(result.edges[0].score, 2.0 / math.sqrt(10.0))

    def test_candidate_pair_bound_fails_before_unbounded_growth(self) -> None:
        with self.assertRaisesRegex(ValueError, "max_candidate_pairs"):
            build_artist_overlap_similarity(
                (
                    edge("a", "shared"),
                    edge("b", "shared"),
                    edge("c", "shared"),
                ),
                SimilarityParameters(
                    metric=SimilarityMetric.WEIGHTED_JACCARD,
                    max_neighbors=1,
                    max_candidate_pairs=1,
                ),
            )

    def test_pair_visit_bound_counts_repeated_candidate_pairs(self) -> None:
        with self.assertRaisesRegex(ValueError, "max_pair_visits"):
            build_artist_overlap_similarity(
                tuple(
                    edge(genre_id, f"shared-{artist_index}")
                    for artist_index in range(3)
                    for genre_id in ("a", "b", "c")
                ),
                SimilarityParameters(
                    metric=SimilarityMetric.WEIGHTED_JACCARD,
                    max_neighbors=1,
                    max_candidate_pairs=3,
                    max_pair_visits=8,
                ),
            )

    def test_grid_rejects_aggregate_output_and_work(self) -> None:
        with self.assertRaisesRegex(ValidationError, "aggregate candidate pair"):
            ParameterGrid(
                metrics=(SimilarityMetric.WEIGHTED_JACCARD,),
                max_neighbors=(1, 2, 3, 4, 5, 6),
                min_shared_artists=(1,),
            )
        with self.assertRaisesRegex(ValidationError, "aggregate pair visit"):
            ParameterGrid(
                metrics=(SimilarityMetric.WEIGHTED_JACCARD,),
                max_neighbors=(1, 2, 3, 4, 5, 6),
                min_shared_artists=(1,),
                max_candidate_pairs=50_000,
            )

    def test_coordinate_neighbor_fallback_is_bounded(self) -> None:
        point = HistoricalGenrePoint(genre_id="a", x=0.0, y=0.0, evidence_ref="fixture")

        with self.assertRaisesRegex(ValueError, "coordinate neighbor fallback exceeds"):
            evaluate_neighborhood_preservation((), (), (point,) * 10_001, 10)


class ReconstructionEvaluationTests(unittest.TestCase):
    def test_procrustes_recovers_rotation_scale_and_translation(self) -> None:
        candidate = (
            ReconstructionPoint(genre_id="a", x=0.0, y=0.0),
            ReconstructionPoint(genre_id="b", x=1.0, y=0.0),
            ReconstructionPoint(genre_id="c", x=0.0, y=1.0),
        )
        historical = (
            HistoricalGenrePoint(genre_id="a", x=5.0, y=-2.0, evidence_ref="fixture"),
            HistoricalGenrePoint(genre_id="b", x=5.0, y=0.0, evidence_ref="fixture"),
            HistoricalGenrePoint(genre_id="c", x=3.0, y=-2.0, evidence_ref="fixture"),
        )
        result = align_to_historical_points(candidate, historical)
        self.assertAlmostEqual(result.scale, 2.0)
        self.assertAlmostEqual(result.rotation_radians, math.pi / 2.0)
        self.assertAlmostEqual(result.translation_x, 5.0)
        self.assertAlmostEqual(result.translation_y, -2.0)
        self.assertAlmostEqual(result.root_mean_square_error, 0.0, places=12)

    def test_grid_order_and_experiment_result_are_deterministic(self) -> None:
        historical_artifact = VersionedInput(
            artifact_key="synthetic-history",
            revision="1",
            content_sha256="b" * 64,
        )
        manifest = ReconstructionExperimentManifest(
            experiment_key="synthetic-grid",
            claims=(
                HistoricalClaim(
                    claim_key="axes",
                    statement="The historical axes were described publicly.",
                    evidence_status=EvidenceStatus.DISCLOSED,
                    evidence_refs=("fixture:claim",),
                ),
            ),
            inputs=ReconstructionInputs(
                membership_artifact=ARTIFACT,
                membership_edges=(
                    edge("a", "one"),
                    edge("b", "one"),
                    edge("b", "two"),
                    edge("c", "two"),
                ),
                historical_artifact=historical_artifact,
                historical_points=(
                    HistoricalGenrePoint(genre_id="a", x=0.0, y=0.0, evidence_ref="fixture"),
                    HistoricalGenrePoint(genre_id="b", x=1.0, y=0.0, evidence_ref="fixture"),
                    HistoricalGenrePoint(genre_id="c", x=2.0, y=0.0, evidence_ref="fixture"),
                ),
                historical_neighbors=(
                    HistoricalNeighborList(
                        genre_id="a", neighbor_ids=("b",), evidence_ref="fixture"
                    ),
                    HistoricalNeighborList(
                        genre_id="b", neighbor_ids=("a", "c"), evidence_ref="fixture"
                    ),
                    HistoricalNeighborList(
                        genre_id="c", neighbor_ids=("b",), evidence_ref="fixture"
                    ),
                ),
            ),
            grid=ParameterGrid(
                metrics=(
                    SimilarityMetric.WEIGHTED_JACCARD,
                    SimilarityMetric.WEIGHTED_COSINE,
                ),
                max_neighbors=(1, 2),
                min_shared_artists=(1,),
            ),
            candidate_artifact=VersionedInput(
                artifact_key="synthetic-candidate-layout",
                revision="layout-v1",
                content_sha256="c" * 64,
            ),
            candidate_points=(
                ReconstructionPoint(genre_id="a", x=0.0, y=0.0),
                ReconstructionPoint(genre_id="b", x=1.0, y=0.0),
                ReconstructionPoint(genre_id="c", x=2.0, y=0.0),
            ),
            evaluation_neighbor_count=1,
        )
        expanded = expand_parameter_grid(manifest.grid)
        self.assertEqual(
            [(item.metric, item.max_neighbors) for item in expanded],
            [
                (SimilarityMetric.WEIGHTED_JACCARD, 1),
                (SimilarityMetric.WEIGHTED_JACCARD, 2),
                (SimilarityMetric.WEIGHTED_COSINE, 1),
                (SimilarityMetric.WEIGHTED_COSINE, 2),
            ],
        )
        result = run_reconstruction_experiment(manifest)
        self.assertFalse(result.exact_historical_recovery_claimed)
        self.assertEqual(result.claims, manifest.claims)
        self.assertEqual(result.membership_artifact, ARTIFACT)
        self.assertEqual(result.historical_artifact, historical_artifact)
        self.assertEqual(result.candidate_artifact, manifest.candidate_artifact)
        self.assertEqual(result.evaluation_neighbor_count, 1)
        self.assertEqual(len(result.runs), 4)
        preservation = result.runs[0].neighborhood_preservation
        if preservation is None:
            self.fail("historical neighbors should produce preservation metrics")
        self.assertEqual(
            preservation.mean_recall,
            1.0,
        )
        self.assertEqual(
            result.model_dump_json(), run_reconstruction_experiment(manifest).model_dump_json()
        )

    def test_candidate_points_require_versioned_artifact(self) -> None:
        with self.assertRaises(ValidationError):
            ReconstructionExperimentManifest(
                experiment_key="unversioned-candidate",
                inputs=ReconstructionInputs(
                    membership_artifact=ARTIFACT,
                    membership_edges=(edge("a", "one"),),
                ),
                grid=ParameterGrid(
                    metrics=(SimilarityMetric.WEIGHTED_JACCARD,),
                    max_neighbors=(1,),
                    min_shared_artists=(1,),
                ),
                candidate_points=(
                    ReconstructionPoint(genre_id="a", x=0.0, y=0.0),
                    ReconstructionPoint(genre_id="b", x=1.0, y=0.0),
                ),
            )

    def test_duplicate_claim_keys_are_rejected(self) -> None:
        claim = HistoricalClaim(
            claim_key="axes",
            statement="The historical axes were described publicly.",
            evidence_status=EvidenceStatus.DISCLOSED,
            evidence_refs=("fixture:claim",),
        )
        with self.assertRaises(ValidationError):
            ReconstructionExperimentManifest(
                experiment_key="duplicate-claims",
                claims=(claim, claim),
                inputs=ReconstructionInputs(
                    membership_artifact=ARTIFACT,
                    membership_edges=(edge("a", "one"),),
                ),
                grid=ParameterGrid(
                    metrics=(SimilarityMetric.WEIGHTED_JACCARD,),
                    max_neighbors=(1,),
                    min_shared_artists=(1,),
                ),
            )


if __name__ == "__main__":
    unittest.main()
