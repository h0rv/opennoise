import unittest
from datetime import UTC, datetime

from pydantic import TypeAdapter, ValidationError

from opennoise.evidence.contracts import (
    AlbumGenreEvidence,
    AlbumGenreRankingArtifact,
    AlbumGenreRankingItem,
    DirectGenreEvidence,
    RankingComponent,
)
from opennoise.serving.map.layouts import LayoutBuildRequest, LayoutStrategyVersion


class ExperimentContractTests(unittest.TestCase):
    def test_layout_inputs_require_version_and_content_fingerprint(self) -> None:
        version = LayoutStrategyVersion(key="source_coordinates", revision="1")
        request = LayoutBuildRequest(
            layout_key="default",
            input_fingerprint="a" * 64,
            entities=(1, 2),
        )

        self.assertEqual(version.revision, "1")
        self.assertEqual(request.input_fingerprint, "a" * 64)
        with self.assertRaises(ValidationError):
            LayoutBuildRequest(
                layout_key="default",
                input_fingerprint="not-a-hash",
                entities=(),
            )

    def test_album_ranking_exposes_components_and_evidence(self) -> None:
        evidence = DirectGenreEvidence(
            evidence_ref="musicbrainz:release-group:1:genre:idm",
            provenance_id=1,
            source_key="musicbrainz",
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
            source_genre_name="IDM",
            source_count=12,
        )
        component = RankingComponent(
            component_key="direct_tag_support",
            raw_value=12.0,
            transformed_value=1.0,
            transform_key="cap",
            transform_version="1",
            evidence_refs=(evidence.evidence_ref,),
        )
        artifact = AlbumGenreRankingArtifact(
            run_ref="album-genre:1",
            method_key="fixture",
            method_version="1",
            config_sha256="c" * 64,
            input_fingerprint="b" * 64,
            policy_id=1,
            generated_at=datetime(2026, 1, 1, tzinfo=UTC),
            membership_threshold=0.5,
            eligibility_rule="At least one direct source observation.",
            items=(
                AlbumGenreRankingItem(
                    genre_id=1,
                    release_group_id=5,
                    rank=1,
                    score=1.0,
                    membership_confidence=1.0,
                    evidence_coverage=1.0,
                    components=(component,),
                    evidence=(evidence,),
                    explanation="MusicBrainz reports 12 direct genre tags.",
                    missing_features=(),
                ),
            ),
        )

        parsed = TypeAdapter(AlbumGenreEvidence).validate_python(evidence)
        self.assertEqual(parsed.evidence_kind, "direct")
        self.assertEqual(artifact.items[0].components[0].raw_value, 12.0)


if __name__ == "__main__":
    unittest.main()
