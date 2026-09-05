import unittest

from musix.ml.public_graph import build_public_model, public_model_output_sha256
from musix.ml.public_model_gate import (
    PublicModelGateError,
    evaluate_public_model,
    require_public_model_gate,
)
from musix.models.modeling import (
    ArtistPairEvidence,
    DirectMembershipEvidence,
    GenreIdentity,
    PublicArtifact,
    PublicModelInput,
    PublicModelSettings,
)


def _artifact():  # noqa: ANN202
    inputs = PublicModelInput(
        artifacts=(
            PublicArtifact(
                source="musicbrainz",
                snapshot="test-musicbrainz",
                artifact_key="artists.json",
                content_sha256="a" * 64,
                export_allowed=True,
            ),
            PublicArtifact(
                source="wikidata",
                snapshot="test-wikidata",
                artifact_key="genres.json",
                content_sha256="b" * 64,
                export_allowed=True,
            ),
            PublicArtifact(
                source="listenbrainz",
                snapshot="test-listenbrainz",
                artifact_key="pairs.sqlite",
                content_sha256="c" * 64,
                export_allowed=True,
            ),
        ),
        genres=tuple(
            GenreIdentity(
                genre_id=f"genre:{name}", name=name.title(), evidence_refs=(f"wd:{name}",)
            )
            for name in ("a", "b", "c")
        ),
        direct_memberships=(
            DirectMembershipEvidence(
                artist_id="artist:x",
                genre_id="genre:a",
                facet="musicbrainz_tag",
                value=3,
                evidence_ref="mb:x:a",
            ),
            DirectMembershipEvidence(
                artist_id="artist:x",
                genre_id="genre:b",
                facet="musicbrainz_tag",
                value=2,
                evidence_ref="mb:x:b",
            ),
            DirectMembershipEvidence(
                artist_id="artist:y",
                genre_id="genre:b",
                facet="wikidata_p136",
                value=1,
                evidence_ref="wd:y:b",
            ),
            DirectMembershipEvidence(
                artist_id="artist:y",
                genre_id="genre:c",
                facet="wikidata_p136",
                value=1,
                evidence_ref="wd:y:c",
            ),
        ),
        artist_pairs=(
            ArtistPairEvidence(
                left_artist_id="artist:x",
                right_artist_id="artist:z",
                listener_day_support=2,
                supporting_windows=1,
                evidence_refs=("lb:window:1",),
            ),
        ),
    )
    return build_public_model(
        inputs,
        PublicModelSettings(minimum_pair_support=1, neighbors_per_genre=3),
    )


class PublicModelGateTests(unittest.TestCase):
    def test_reports_independent_sources_traceability_and_separate_hashes(self) -> None:
        artifact = _artifact()
        report = require_public_model_gate(artifact)

        self.assertTrue(report.passed)
        self.assertEqual(report.neighbor_evidence_coverage, 1.0)
        self.assertGreater(report.one_hop_membership_count, 0)
        self.assertEqual(report.layout_coverage, 1.0)
        self.assertNotEqual(report.evidence_sha256, report.coordinate_sha256)
        self.assertNotEqual(report.evidence_sha256, report.layout_version_sha256)
        self.assertEqual(report, evaluate_public_model(artifact))

    def test_rejects_rewritten_neighbor_score(self) -> None:
        artifact = _artifact()
        original = next(
            neighbor for neighbor in artifact.neighbors if neighbor.metric == "weighted_jaccard"
        )
        changed_neighbor = original.model_copy(update={"score": original.score / 2})
        changed = artifact.model_copy(
            update={
                "neighbors": tuple(
                    changed_neighbor if item is original else item for item in artifact.neighbors
                )
            }
        )
        changed = changed.model_copy(update={"output_sha256": public_model_output_sha256(changed)})

        report = evaluate_public_model(changed)
        self.assertFalse(report.passed)
        self.assertTrue(any("score mismatch" in item for item in report.failures))
        with self.assertRaises(PublicModelGateError):
            require_public_model_gate(changed)

    def test_rejects_historical_provenance_vocabulary(self) -> None:
        artifact = _artifact()
        changed = artifact.model_copy(
            update={
                "artifacts": (
                    artifact.artifacts[0].model_copy(update={"snapshot": "historical-input"}),
                    *artifact.artifacts[1:],
                )
            }
        )
        changed = changed.model_copy(update={"output_sha256": public_model_output_sha256(changed)})

        report = evaluate_public_model(changed)
        self.assertFalse(report.passed)
        self.assertEqual(report.forbidden_terms, ("historical",))


if __name__ == "__main__":
    unittest.main()
