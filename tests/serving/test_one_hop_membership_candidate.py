import unittest

from opennoise.models.modeling import (
    ArtistPairEvidence,
    DirectMembershipEvidence,
    GenreHierarchyEdge,
    GenreIdentity,
    PublicArtifact,
    PublicModelInput,
)
from opennoise.serving.one_hop_membership_candidate import (
    OneHopMembershipCandidatePolicy,
    build_one_hop_membership_candidate,
)


def _inputs(*, support: int = 15, hierarchy: bool = True) -> PublicModelInput:
    return PublicModelInput(
        artifacts=(
            PublicArtifact(
                source="listenbrainz",
                snapshot="fixture",
                artifact_key="fixture",
                content_sha256="a" * 64,
                export_allowed=True,
            ),
        ),
        genres=(
            GenreIdentity(genre_id="genre:a", name="A", evidence_refs=("a",)),
            GenreIdentity(genre_id="genre:b", name="B", evidence_refs=("b",)),
        ),
        direct_memberships=(
            DirectMembershipEvidence(
                artist_id="artist:one",
                genre_id="genre:a",
                facet="musicbrainz_tag",
                value=10,
                evidence_ref="direct:one:a",
            ),
            DirectMembershipEvidence(
                artist_id="artist:two",
                genre_id="genre:b",
                facet="musicbrainz_tag",
                value=10,
                evidence_ref="direct:two:b",
            ),
        ),
        artist_pairs=(
            ArtistPairEvidence(
                left_artist_id="artist:one",
                right_artist_id="artist:two",
                listener_day_support=support,
                supporting_windows=2,
                evidence_refs=("listenbrainz:fixture",),
            ),
        ),
        hierarchy=(
            GenreHierarchyEdge(
                child_genre_id="genre:a", parent_genre_id="genre:b", evidence_ref="taxonomy:a:b"
            ),
        )
        if hierarchy
        else (),
    )


class OneHopMembershipCandidateTests(unittest.TestCase):
    def test_seals_deterministic_public_only_memberships(self) -> None:
        policy = OneHopMembershipCandidatePolicy(minimum_genre_direct_seed_count=1)
        first = build_one_hop_membership_candidate(_inputs(), policy)
        second = build_one_hop_membership_candidate(_inputs(), policy)
        self.assertEqual(first.output_sha256, second.output_sha256)
        self.assertTrue(first.non_production_experiment)
        self.assertFalse(first.policy.external_reference_used_for_construction)
        self.assertEqual(
            {(item.artist_id, item.genre_id) for item in first.memberships},
            {("artist:one", "genre:b"), ("artist:two", "genre:a")},
        )
        self.assertTrue(
            all(
                path.edge_type == "listenbrainz_privacy_safe_co_listen"
                for item in first.memberships
                for path in item.paths
            )
        )

    def test_abstains_for_weak_edges_and_missing_taxonomy_anchor(self) -> None:
        policy = OneHopMembershipCandidatePolicy(minimum_genre_direct_seed_count=1)
        weak = build_one_hop_membership_candidate(_inputs(support=14), policy)
        missing = build_one_hop_membership_candidate(_inputs(hierarchy=False), policy)
        self.assertEqual(weak.coverage.accepted_membership_count, 0)
        self.assertEqual(
            {item.reason: item.count for item in weak.coverage.abstentions}["edge_support"], 2
        )
        self.assertEqual(missing.coverage.accepted_membership_count, 0)
        self.assertEqual(
            {item.reason: item.count for item in missing.coverage.abstentions}[
                "target_taxonomy_distance"
            ],
            2,
        )


if __name__ == "__main__":
    unittest.main()
