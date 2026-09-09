import unittest

from pydantic import ValidationError

from musix.evidence.reconstruction import (
    GenreArtistEdge,
    HistoricalGenrePoint,
    ReconstructionInputs,
    VersionedInput,
)
from musix.models.modeling import (
    ArtistPairEvidence,
    DirectMembershipEvidence,
    GenreIdentity,
    PublicArtifact,
    PublicModelInput,
)
from musix.peers.similarity.peer_similarity import (
    PeerSimilaritySettings,
    build_peer_similarity,
    build_peer_similarity_receipt,
    evaluate_peer_similarity_gate,
    public_model_input_from_reconstruction,
    replay_peer_similarity,
)
from musix.serving.public.public_artist_membership import (
    CandidateCoverage,
    GenreDisposition,
    NameUniverse,
    NameUniverseEntry,
    PublicArtistMembershipCandidateArtifact,
    PublicArtistMembershipSourcePolicy,
    public_artist_membership_candidate_output_sha256,
)


def _inputs(*, weak: bool = False) -> PublicModelInput:
    direct = tuple(
        DirectMembershipEvidence(
            artist_id=artist,
            genre_id=genre,
            facet="musicbrainz_tag",
            value=1.0,
            evidence_ref=f"mb:{genre}:{artist}",
        )
        for genre, artists in {
            "genre-a": ("artist-1", "artist-2"),
            "genre-b": ("artist-1", "artist-2"),
            "genre-c": ("artist-3",),
        }.items()
        for artist in artists
    )
    pairs = (
        ArtistPairEvidence(
            left_artist_id="artist-1",
            right_artist_id="artist-3",
            listener_day_support=1 if weak else 4,
            supporting_windows=1,
            evidence_refs=("lb:aggregate:1",),
        ),
    )
    artifacts = (
        PublicArtifact(
            source="musicbrainz",
            snapshot="fixture",
            artifact_key="tags",
            content_sha256="a" * 64,
            export_allowed=True,
        ),
        PublicArtifact(
            source="listenbrainz",
            snapshot="fixture",
            artifact_key="co-listens",
            content_sha256="b" * 64,
            export_allowed=True,
        ),
    )
    return PublicModelInput(
        artifacts=artifacts,
        genres=tuple(
            GenreIdentity(genre_id=name, name=name, evidence_refs=(f"id:{name}",))
            for name in ("genre-a", "genre-b", "genre-c")
        ),
        direct_memberships=direct,
        artist_pairs=pairs,
    )


def _empty_membership_candidate(
    *, outside_genre: bool = False
) -> PublicArtistMembershipCandidateArtifact:
    names = tuple(
        NameUniverseEntry(
            source_item_id=f"item-{index}",
            external_id=f"ext-{index}",
            name=f"name-{index}",
        )
        for index in range(6291)
    )
    universe = NameUniverse(source_content_sha256="c" * 64, names=names)
    dispositions = tuple(
        GenreDisposition(
            source_item_id=entry.source_item_id,
            name=entry.name,
            genre_id="unrelated" if outside_genre and index == 0 else None,
            status="abstained",
            abstention_reason="no_public_genre_identity",
            direct_candidate_count=0,
            aggregate_candidate_count=0,
        )
        for index, entry in enumerate(names)
    )
    coverage = CandidateCoverage(
        direct_candidate_count=0,
        aggregate_candidate_count=0,
        direct_genre_count=0,
        aggregate_only_genre_count=0,
        abstained_genre_count=6291,
        no_public_genre_identity_count=6291,
        ambiguous_public_genre_identity_count=0,
        no_approved_direct_evidence_count=0,
        no_eligible_aggregate_candidate_count=0,
        examined_candidate_path_count=0,
    )
    candidate = PublicArtistMembershipCandidateArtifact(
        input_sha256="a" * 64,
        policy_sha256="b" * 64,
        output_sha256="0" * 64,
        name_universe=universe,
        source_policy=PublicArtistMembershipSourcePolicy(),
        directly_observed_memberships=(),
        propagated_candidates=(),
        dispositions=dispositions,
        coverage=coverage,
    )
    return candidate.model_copy(
        update={"output_sha256": public_artist_membership_candidate_output_sha256(candidate)}
    )


class PeerSimilarityTests(unittest.TestCase):
    def test_cross_facet_evidence_counts_one_shared_artist(self) -> None:
        """Genre and tag corroboration can add weight but not duplicate an artist."""
        memberships = tuple(
            DirectMembershipEvidence(
                artist_id="artist:one",
                genre_id=genre_id,
                facet=facet,
                value=1.0,
                evidence_ref=f"{genre_id}:{facet}",
            )
            for genre_id in ("genre-a", "genre-b")
            for facet in ("musicbrainz_genre", "musicbrainz_tag")
        )
        inputs = PublicModelInput(
            artifacts=(
                PublicArtifact(
                    source="musicbrainz",
                    snapshot="fixture",
                    artifact_key="cross-facet",
                    content_sha256="c" * 64,
                    export_allowed=False,
                ),
            ),
            genres=tuple(
                GenreIdentity(genre_id=genre_id, name=genre_id, evidence_refs=(genre_id,))
                for genre_id in ("genre-a", "genre-b")
            ),
            direct_memberships=memberships,
        )

        candidate = build_peer_similarity(
            inputs,
            PeerSimilaritySettings(minimum_shared_artists=1, aggregate_component_weight=0.0),
        ).candidates[0]

        self.assertEqual(candidate.shared_direct_artist_count, 1)
        self.assertEqual(candidate.direct_score, 1.0)

    def test_pairs_are_canonical_symmetric_and_bounded(self) -> None:
        result = build_peer_similarity(_inputs())
        self.assertEqual(result.similarity_per_seed_accounting, "unbridged")
        self.assertEqual(
            [(item.source_genre_id, item.target_genre_id) for item in result.candidates],
            [("genre-a", "genre-b"), ("genre-a", "genre-c"), ("genre-b", "genre-c")],
        )
        self.assertTrue(
            all(item.source_genre_id < item.target_genre_id for item in result.candidates)
        )
        self.assertTrue(all(0.0 < item.score <= 1.0 for item in result.candidates))
        direct_candidate = next(
            item
            for item in result.candidates
            if (item.source_genre_id, item.target_genre_id) == ("genre-a", "genre-b")
        )
        self.assertEqual(
            set(direct_candidate.evidence_refs),
            {
                "mb:genre-a:artist-1",
                "mb:genre-a:artist-2",
                "mb:genre-b:artist-1",
                "mb:genre-b:artist-2",
            },
        )
        self.assertTrue(
            evaluate_peer_similarity_gate(result, _inputs(), PeerSimilaritySettings()).passed
        )
        self.assertEqual(len(result.directional_neighbors), 6)
        self.assertEqual(result.coverage.directional_neighbor_count, 6)

    def test_directional_view_uses_maximum_neighbors_and_replays(self) -> None:
        inputs = _inputs()
        settings = PeerSimilaritySettings(maximum_neighbors=1)
        result = build_peer_similarity(inputs, settings)
        by_source: dict[str, list[int]] = {}
        for neighbor in result.directional_neighbors:
            by_source.setdefault(neighbor.source_genre_id, []).append(neighbor.rank)
        self.assertTrue(all(ranks == [1] for ranks in by_source.values()))
        self.assertEqual(len(result.directional_neighbors), len(by_source))
        self.assertTrue(evaluate_peer_similarity_gate(result, inputs, settings).passed)
        tampered = result.model_copy(
            update={"directional_neighbors": result.directional_neighbors[:-1]}
        )
        self.assertFalse(evaluate_peer_similarity_gate(tampered, inputs, settings).passed)

    def test_weak_observed_pair_is_explicitly_abstained(self) -> None:
        result = build_peer_similarity(_inputs(weak=True))
        self.assertTrue(
            any(item.reason == "insufficient_aggregate_support" for item in result.abstentions)
        )
        self.assertFalse(
            any(
                item.source_genre_id == "genre-a" and item.target_genre_id == "genre-c"
                for item in result.candidates
            )
        )

    def test_exact_replay_and_receipt(self) -> None:
        inputs = _inputs()
        settings = PeerSimilaritySettings()
        result = build_peer_similarity(inputs, settings)
        self.assertEqual(replay_peer_similarity(inputs, settings, result), result)
        receipt = build_peer_similarity_receipt(inputs, settings, result)
        self.assertEqual(receipt.output_sha256, result.output_sha256)

    def test_local_reconstruction_adapter_is_explicitly_non_exportable(self) -> None:
        reconstruction = ReconstructionInputs(
            membership_artifact=VersionedInput(
                artifact_key="local-tags", revision="v1", content_sha256="c" * 64
            ),
            membership_edges=(
                GenreArtistEdge(
                    genre_id="genre-a",
                    artist_id="artist-1",
                    evidence_refs=("ref-one", "ref-two"),
                ),
            ),
        )
        inputs = public_model_input_from_reconstruction(reconstruction)
        self.assertFalse(inputs.artifacts[0].export_allowed)
        self.assertIn("ref-one", inputs.direct_memberships[0].evidence_ref)
        self.assertIn("ref-two", inputs.direct_memberships[0].evidence_ref)
        result = build_peer_similarity(inputs)
        self.assertFalse(result.coverage.all_inputs_export_allowed)

    def test_reconstruction_facets_remain_distinct_in_public_input(self) -> None:
        reconstruction = ReconstructionInputs(
            membership_artifact=VersionedInput(
                artifact_key="local-tags", revision="v1", content_sha256="c" * 64
            ),
            membership_edges=(
                GenreArtistEdge(
                    genre_id="genre-a",
                    facet="genre",
                    artist_id="artist-1",
                    evidence_refs=("genre-ref",),
                ),
                GenreArtistEdge(
                    genre_id="genre-b",
                    facet="tag",
                    artist_id="artist-2",
                    evidence_refs=("tag-ref",),
                ),
            ),
        )
        inputs = public_model_input_from_reconstruction(reconstruction)
        self.assertEqual(
            {item.facet for item in inputs.direct_memberships},
            {"musicbrainz_genre", "musicbrainz_tag"},
        )

    def test_reconstruction_allows_same_ids_when_facets_differ(self) -> None:
        reconstruction = ReconstructionInputs(
            membership_artifact=VersionedInput(
                artifact_key="local-facets", revision="v1", content_sha256="c" * 64
            ),
            membership_edges=(
                GenreArtistEdge(
                    genre_id="same",
                    facet="genre",
                    artist_id="artist",
                    evidence_refs=("genre-ref",),
                ),
                GenreArtistEdge(
                    genre_id="same",
                    facet="tag",
                    artist_id="artist",
                    evidence_refs=("tag-ref",),
                ),
            ),
        )
        self.assertEqual(len(reconstruction.membership_edges), 2)

    def test_reconstruction_adapter_rejects_historical_evaluation_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "historical observations"):
            reconstruction = ReconstructionInputs(
                membership_artifact=VersionedInput(
                    artifact_key="local-tags", revision="v1", content_sha256="c" * 64
                ),
                membership_edges=(
                    GenreArtistEdge(
                        genre_id="genre-a", artist_id="artist-1", evidence_refs=("ref",)
                    ),
                ),
                historical_artifact=VersionedInput(
                    artifact_key="historical", revision="v1", content_sha256="d" * 64
                ),
                historical_points=(
                    HistoricalGenrePoint(
                        genre_id="genre-a", x=0.0, y=1.0, evidence_ref="historical"
                    ),
                ),
            )
            public_model_input_from_reconstruction(reconstruction)

    def test_pair_visit_bound_is_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "maximum_pair_visits"):
            build_peer_similarity(_inputs(), PeerSimilaritySettings(maximum_pair_visits=1))

    def test_tampered_output_fails_gate(self) -> None:
        inputs = _inputs()
        result = build_peer_similarity(inputs)
        tampered = result.model_copy(update={"output_sha256": "0" * 64})
        report = evaluate_peer_similarity_gate(tampered, inputs, PeerSimilaritySettings())
        self.assertFalse(report.passed)
        self.assertIn("output hash", " ".join(report.failures))

    def test_candidate_attachment_must_reference_same_public_input(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside peer input"):
            build_peer_similarity(
                _inputs(), candidate_artifact=_empty_membership_candidate(outside_genre=True)
            )
        sealed = build_peer_similarity(_inputs(), candidate_artifact=_empty_membership_candidate())
        self.assertEqual(sealed.similarity_per_seed_accounting, "sealed_membership_bridge-v1")

    def test_aggregate_rows_are_typed_privacy_safe_observations(self) -> None:
        pair = _inputs().artist_pairs[0]
        self.assertNotIn("user_id", pair.model_dump(mode="json"))
        with self.assertRaises(ValidationError):
            ArtistPairEvidence(
                left_artist_id="artist-2",
                right_artist_id="artist-1",
                listener_day_support=3,
                supporting_windows=1,
                evidence_refs=("lb:aggregate:2",),
            )


if __name__ == "__main__":
    unittest.main()
