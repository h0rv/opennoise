import unittest

from pydantic import ValidationError

from musix.ml.public_graph import PublicModelLimitError, build_public_model
from musix.models.modeling import (
    ArtistPairEvidence,
    DirectMembershipEvidence,
    GenreIdentity,
    MetadataCandidate,
    PublicArtifact,
    PublicModelInput,
    PublicModelSettings,
)

_SHA_A = "a" * 64
_SHA_B = "b" * 64
_SHA_C = "c" * 64


def _input() -> PublicModelInput:
    return PublicModelInput(
        artifacts=(
            PublicArtifact(
                source="listenbrainz",
                snapshot="2026-08-30",
                artifact_key="incremental.tar.zst",
                content_sha256=_SHA_A,
                export_allowed=True,
            ),
            PublicArtifact(
                source="musicbrainz",
                snapshot="2026-08-29",
                artifact_key="artist.tar.xz",
                content_sha256=_SHA_B,
                export_allowed=False,
            ),
            PublicArtifact(
                source="wikidata",
                snapshot="2026-08-31",
                artifact_key="music-slice.json",
                content_sha256=_SHA_C,
                export_allowed=True,
            ),
        ),
        genres=tuple(
            GenreIdentity(
                genre_id=f"genre:{name}",
                name=name.title(),
                evidence_refs=(f"wd:genre:{name}",),
            )
            for name in ("jazz", "punk", "rock", "soul")
        ),
        direct_memberships=(
            DirectMembershipEvidence(
                artist_id="artist:a",
                genre_id="genre:punk",
                facet="musicbrainz_tag",
                value=8,
                evidence_ref="mb:a:punk",
            ),
            DirectMembershipEvidence(
                artist_id="artist:a",
                genre_id="genre:rock",
                facet="musicbrainz_tag",
                value=10,
                evidence_ref="mb:a:rock",
            ),
            DirectMembershipEvidence(
                artist_id="artist:a",
                genre_id="genre:rock",
                facet="wikidata_p136",
                value=1,
                evidence_ref="wd:a:rock",
            ),
            DirectMembershipEvidence(
                artist_id="artist:b",
                genre_id="genre:punk",
                facet="musicbrainz_tag",
                value=4,
                evidence_ref="mb:b:punk",
            ),
            DirectMembershipEvidence(
                artist_id="artist:b",
                genre_id="genre:rock",
                facet="musicbrainz_tag",
                value=5,
                evidence_ref="mb:b:rock",
            ),
            DirectMembershipEvidence(
                artist_id="artist:c",
                genre_id="genre:jazz",
                facet="wikidata_p136",
                value=1,
                evidence_ref="wd:c:jazz",
            ),
            DirectMembershipEvidence(
                artist_id="artist:c",
                genre_id="genre:soul",
                facet="musicbrainz_tag",
                value=3,
                evidence_ref="mb:c:soul",
            ),
            DirectMembershipEvidence(
                artist_id="artist:d",
                genre_id="genre:jazz",
                facet="wikidata_p136",
                value=1,
                evidence_ref="wd:d:jazz",
            ),
            DirectMembershipEvidence(
                artist_id="artist:d",
                genre_id="genre:soul",
                facet="musicbrainz_tag",
                value=2,
                evidence_ref="mb:d:soul",
            ),
        ),
        artist_pairs=(
            ArtistPairEvidence(
                left_artist_id="artist:a",
                right_artist_id="artist:e",
                listener_day_support=12,
                supporting_windows=2,
                evidence_refs=("lb:day:1:a:e", "lb:day:2:a:e"),
            ),
            ArtistPairEvidence(
                left_artist_id="artist:c",
                right_artist_id="artist:f",
                listener_day_support=8,
                supporting_windows=2,
                evidence_refs=("lb:day:1:c:f", "lb:day:2:c:f"),
            ),
        ),
        metadata_candidates=(
            MetadataCandidate(
                entity_kind="artist",
                entity_id="artist:a",
                genre_id="genre:rock",
                name="Alpha",
                direct_evidence_value=10,
                source_count=2,
                evidence_refs=("mb:a:rock", "wd:a:rock"),
            ),
            MetadataCandidate(
                entity_kind="release_group",
                entity_id="release:1",
                genre_id="genre:rock",
                name="First Record",
                direct_evidence_value=2,
                source_count=1,
                evidence_refs=("wd:release:1:rock",),
            ),
        ),
    )


class PublicGraphTests(unittest.TestCase):
    def test_builds_explainable_deterministic_artifacts(self) -> None:
        inputs = _input()
        settings = PublicModelSettings(neighbors_per_genre=3)

        first = build_public_model(inputs, settings)
        second = build_public_model(inputs, settings)

        self.assertEqual(first.input_sha256, second.input_sha256)
        self.assertEqual(first.settings_sha256, second.settings_sha256)
        self.assertEqual(first.output_sha256, second.output_sha256)
        self.assertFalse(first.export_allowed)
        self.assertEqual(first.coordinates, second.coordinates)
        self.assertEqual(first.coverage.input_artists, 6)
        self.assertEqual(first.coverage.input_genres, 4)
        self.assertEqual(first.coverage.direct_observations, 9)
        self.assertEqual(first.coverage.direct_memberships, 8)
        self.assertEqual(first.coverage.inferred_memberships, 4)
        self.assertEqual(first.coverage.coordinate_genres, 4)
        self.assertEqual(first.coverage.unplaced_genres, ())
        self.assertEqual(first.coverage.representative_items, 2)

        inferred = {
            (item.artist_id, item.genre_id)
            for profile in first.profiles
            if profile.profile_kind == "one_hop"
            for item in profile.memberships
        }
        self.assertEqual(
            inferred,
            {
                ("artist:e", "genre:punk"),
                ("artist:e", "genre:rock"),
                ("artist:f", "genre:jazz"),
                ("artist:f", "genre:soul"),
            },
        )
        rock_neighbors = [
            item
            for item in first.neighbors
            if item.genre_id == "genre:rock"
            and item.profile_kind == "direct"
            and item.metric == "weighted_jaccard"
        ]
        self.assertEqual(rock_neighbors[0].neighbor_genre_id, "genre:punk")
        self.assertGreater(rock_neighbors[0].score, 0.0)
        self.assertEqual(first.representatives[0].name, "Alpha")

        agreement = first.facet_agreement[0]
        self.assertEqual(agreement.intersection_count, 1)
        self.assertEqual(agreement.union_count, 8)

    def test_rejects_noncanonical_and_duplicate_pairs(self) -> None:
        with self.assertRaises(ValidationError):
            ArtistPairEvidence(
                left_artist_id="artist:z",
                right_artist_id="artist:a",
                listener_day_support=2,
                supporting_windows=1,
                evidence_refs=("lb:1",),
            )
        base = _input()
        with self.assertRaises(ValidationError):
            PublicModelInput(
                artifacts=base.artifacts,
                genres=base.genres,
                direct_memberships=base.direct_memberships,
                artist_pairs=(base.artist_pairs[0], base.artist_pairs[0]),
            )

    def test_fails_closed_on_work_limits(self) -> None:
        with self.assertRaisesRegex(PublicModelLimitError, "propagation visits"):
            build_public_model(
                _input(),
                PublicModelSettings(max_propagation_visits=1),
            )
        with self.assertRaisesRegex(PublicModelLimitError, "similarity pair visits"):
            build_public_model(
                _input(),
                PublicModelSettings(max_similarity_pair_visits=1),
            )

    def test_places_genres_without_shared_memberships(self) -> None:
        inputs = PublicModelInput(
            artifacts=(
                PublicArtifact(
                    source="musicbrainz",
                    snapshot="isolated",
                    artifact_key="artists.json",
                    content_sha256=_SHA_A,
                    export_allowed=True,
                ),
            ),
            genres=(
                GenreIdentity(genre_id="genre:a", name="A", evidence_refs=("wd:a",)),
                GenreIdentity(genre_id="genre:b", name="B", evidence_refs=("wd:b",)),
            ),
            direct_memberships=(
                DirectMembershipEvidence(
                    artist_id="artist:a",
                    genre_id="genre:a",
                    facet="musicbrainz_tag",
                    value=1,
                    evidence_ref="mb:a:a",
                ),
                DirectMembershipEvidence(
                    artist_id="artist:b",
                    genre_id="genre:b",
                    facet="musicbrainz_tag",
                    value=1,
                    evidence_ref="mb:b:b",
                ),
            ),
        )

        artifact = build_public_model(inputs, PublicModelSettings())

        self.assertEqual(len(artifact.neighbors), 0)
        self.assertEqual(artifact.coverage.direct_observations, 2)
        self.assertEqual(len(artifact.coordinates), 2)
        self.assertEqual({item.component for item in artifact.coordinates}, {0, 1})


if __name__ == "__main__":
    unittest.main()
