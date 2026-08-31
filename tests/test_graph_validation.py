import unittest

from pydantic import ValidationError

from musix.ml.validation import build_graph_validation
from musix.models.modeling import (
    ArtistPairEvidence,
    DirectMembershipEvidence,
    GenreIdentity,
    PublicArtifact,
    PublicModelInput,
    PublicModelSettings,
)
from musix.models.validation import (
    GenreHierarchyEdge,
    GraphValidationInput,
    GraphValidationSettings,
    TemporalPairSnapshot,
)

_SHA_WD = "a" * 64


def _pair(left: str, right: str, day: int) -> ArtistPairEvidence:
    return ArtistPairEvidence(
        left_artist_id=left,
        right_artist_id=right,
        listener_day_support=day + 2,
        supporting_windows=1,
        evidence_refs=(f"lb:{day}:{left}:{right}",),
    )


def _snapshot(day: int) -> TemporalPairSnapshot:
    snapshot = f"2026-08-{day:02d}"
    return TemporalPairSnapshot(
        artifact=PublicArtifact(
            source="listenbrainz",
            snapshot=snapshot,
            artifact_key=f"listenbrainz:{day:064x}",
            content_sha256=f"{day:064x}",
            export_allowed=True,
        ),
        minimum_listened_at=day * 86_400,
        maximum_listened_at=(day + 1) * 86_400 - 1,
        listens_seen=100,
        listens_with_artist_mbid=80,
        distinct_artists=6,
        user_windows=20,
        pairs=(
            _pair("artist:a", "artist:e", day),
            _pair("artist:b", "artist:e", day),
            _pair("artist:c", "artist:f", day),
            _pair("artist:d", "artist:f", day),
        ),
    )


def _base_input() -> PublicModelInput:
    genres = tuple(
        GenreIdentity(
            genre_id=f"wikidata:genre:Q{index}",
            name=f"Genre {index}",
            evidence_refs=(f"wd:Q{index}",),
        )
        for index in range(1, 5)
    )
    memberships = tuple(
        DirectMembershipEvidence(
            artist_id=f"artist:{artist}",
            genre_id=f"wikidata:genre:Q{genre}",
            facet="wikidata_p136",
            value=1.0,
            evidence_ref=f"wd:{artist}:Q{genre}",
        )
        for artist, genre in (
            ("a", 1),
            ("b", 1),
            ("a", 2),
            ("b", 2),
            ("c", 3),
            ("d", 3),
            ("c", 4),
            ("d", 4),
        )
    )
    return PublicModelInput(
        artifacts=(
            PublicArtifact(
                source="wikidata",
                snapshot="wd-2026-08-31",
                artifact_key="wikidata:music-slice",
                content_sha256=_SHA_WD,
                export_allowed=True,
            ),
        ),
        genres=genres,
        direct_memberships=memberships,
    )


class GraphValidationTests(unittest.TestCase):
    def test_builds_deterministic_temporal_and_hierarchy_report(self) -> None:
        inputs = GraphValidationInput(
            base_inputs=_base_input(),
            snapshots=tuple(_snapshot(day) for day in range(24, 31)),
            hierarchy=(
                GenreHierarchyEdge(
                    child_genre_id="wikidata:genre:Q2",
                    parent_genre_id="wikidata:genre:Q1",
                    evidence_ref="wd:Q2:P279:Q1",
                ),
            ),
            input_database_bytes=12_345,
        )
        model_settings = PublicModelSettings(neighbors_per_genre=3)
        validation_settings = GraphValidationSettings(neighbors_per_genre=2)

        first = build_graph_validation(inputs, model_settings, validation_settings)
        second = build_graph_validation(inputs, model_settings, validation_settings)

        self.assertEqual(first.input_sha256, second.input_sha256)
        self.assertEqual(first.output_sha256, second.output_sha256)
        self.assertTrue(first.deterministic_rerun)
        self.assertTrue(first.export_allowed)
        self.assertEqual(len(first.snapshots), 7)
        self.assertEqual(first.hierarchy_edges, 1)
        self.assertEqual(len(first.temporal), 2)
        self.assertEqual(first.source_holdout.status, "unavailable")
        self.assertEqual(first.neighborhood.genres_evaluated, 4)
        self.assertEqual(first.resources.input_database_bytes, 12_345)
        self.assertEqual(first.community_stability.experiment_count, 3)

    def test_requires_a_real_temporal_split(self) -> None:
        with self.assertRaises(ValidationError):
            GraphValidationInput(
                base_inputs=_base_input(),
                snapshots=(_snapshot(29), _snapshot(30)),
                hierarchy=(),
                input_database_bytes=1,
            )


if __name__ == "__main__":
    unittest.main()
