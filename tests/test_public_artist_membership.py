from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from musix.models.modeling import (
    ArtistPairEvidence,
    DirectMembershipEvidence,
    GenreIdentity,
    PublicArtifact,
    PublicModelInput,
)
from musix.public_artist_membership import (
    ApprovedPublicMembershipInput,
    IndependentPublicGoldLabel,
    IndependentPublicGoldSet,
    IndependentPublicGoldSource,
    NameUniverse,
    NameUniverseEntry,
    PromotionPolicy,
    PublicArtistMembershipSourcePolicy,
    build_public_artist_membership_candidate,
    build_public_artist_membership_candidate_from_seed_artifact,
    evaluate_public_artist_membership_promotion,
    load_name_universe,
    public_artist_membership_candidate_output_sha256,
    verify_public_artist_membership_candidate,
    write_public_artist_membership_candidate,
)
from musix.storage import LocalObjectStore


def _sha256(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _universe(*, collision: bool = False) -> NameUniverse:
    names = [
        NameUniverseEntry(source_item_id="seed:0000", external_id="external:0000", name="Jazz"),
        NameUniverseEntry(source_item_id="seed:0001", external_id="external:0001", name="Rock"),
    ]
    if collision:
        names[1] = NameUniverseEntry(
            source_item_id="seed:0001", external_id="external:0001", name="Jàzz"
        )
    names.extend(
        NameUniverseEntry(
            source_item_id=f"seed:{index:04d}",
            external_id=f"external:{index:04d}",
            name=f"Unmatched {index}",
        )
        for index in range(2, 6291)
    )
    return NameUniverse(source_content_sha256="a" * 64, names=tuple(names))


def _model_input(*, pairs: bool = True) -> PublicModelInput:
    artifacts = [
        PublicArtifact(
            source="musicbrainz",
            snapshot="public-fixture",
            artifact_key="musicbrainz-public.json",
            content_sha256="b" * 64,
            export_allowed=True,
        )
    ]
    if pairs:
        artifacts.append(
            PublicArtifact(
                source="listenbrainz",
                snapshot="public-fixture",
                artifact_key="listenbrainz-aggregate.json",
                content_sha256="c" * 64,
                export_allowed=True,
            )
        )
    return PublicModelInput(
        artifacts=tuple(artifacts),
        genres=(
            GenreIdentity(genre_id="genre:jazz", name="Jazz", evidence_refs=("public:jazz",)),
            GenreIdentity(genre_id="genre:rock", name="Rock", evidence_refs=("public:rock",)),
        ),
        direct_memberships=(
            DirectMembershipEvidence(
                artist_id="artist:alpha",
                genre_id="genre:jazz",
                facet="musicbrainz_tag",
                value=4.0,
                evidence_ref="musicbrainz:artist:alpha:tag:jazz",
            ),
        ),
        artist_pairs=(
            ArtistPairEvidence(
                left_artist_id="artist:alpha",
                right_artist_id="artist:beta",
                listener_day_support=25,
                supporting_windows=3,
                evidence_refs=("listenbrainz:aggregate:2026-09",),
            ),
        )
        if pairs
        else (),
    )


def _approved_input(*, pairs: bool = True) -> ApprovedPublicMembershipInput:
    model_input = _model_input(pairs=pairs)
    return ApprovedPublicMembershipInput(
        public_model_input=model_input,
        input_file_sha256="d" * 64,
        public_model_input_sha256=_sha256(model_input.model_dump(mode="json")),
        row_export_policy_sha256="e" * 64,
        aggregate_rows_export_allowed=pairs,
        declared_direct_row_count=len(model_input.direct_memberships),
        declared_aggregate_row_count=len(model_input.artist_pairs),
    )


class PublicArtistMembershipTests(unittest.TestCase):
    def test_name_universe_is_parsed_from_the_sealed_name_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "seed-artifact.json"
            document = {
                "artifact": {"source_id": "name-source", "content_sha256": "f" * 64},
                "genres": [
                    {
                        "source_item_id": f"seed:{index:04d}",
                        "external_id": f"external:{index:04d}",
                        "name": f"Name {index}",
                        "coordinate": [index, index],
                        "artist_memberships": ["must-not-be-read"],
                    }
                    for index in range(6291)
                ],
            }
            path.write_text(json.dumps(document), encoding="utf-8")
            universe = load_name_universe(path)
            artifact = build_public_artist_membership_candidate_from_seed_artifact(
                path, _approved_input(pairs=False), PublicArtistMembershipSourcePolicy()
            )
        self.assertEqual(universe.source_content_sha256, "f" * 64)
        self.assertEqual(len(universe.names), 6291)
        self.assertTrue(universe.artist_memberships_used is False)
        self.assertEqual(artifact.coverage.no_public_genre_identity_count, 6291)

    def test_full_universe_keeps_direct_propagated_and_abstained_states_disjoint(self) -> None:
        policy = PublicArtistMembershipSourcePolicy(
            aggregate_co_listen_publicly_permitted=True,
            aggregate_co_listen_export_allowed=True,
            include_aggregate_candidates=True,
        )
        first = build_public_artist_membership_candidate(_universe(), _approved_input(), policy)
        second = build_public_artist_membership_candidate(_universe(), _approved_input(), policy)

        self.assertEqual(first.output_sha256, second.output_sha256)
        self.assertEqual(
            first.output_sha256, public_artist_membership_candidate_output_sha256(first)
        )
        self.assertEqual(len(first.dispositions), 6291)
        self.assertEqual(len(first.directly_observed_memberships), 1)
        self.assertEqual(len(first.propagated_candidates), 1)
        self.assertEqual(first.propagated_candidates[0].artist_id, "artist:beta")
        self.assertEqual(
            tuple(item.facet for item in first.propagated_candidates[0].paths[0].evidence),
            ("musicbrainz_artist_genre_tag", "listenbrainz_privacy_safe_aggregate_co_listen"),
        )
        self.assertEqual(first.coverage.name_count, 6291)
        self.assertEqual(first.coverage.direct_genre_count, 1)
        self.assertEqual(first.coverage.abstained_genre_count, 6290)
        self.assertEqual(first.coverage.no_public_genre_identity_count, 6289)
        self.assertEqual(first.coverage.no_eligible_aggregate_candidate_count, 1)

    def test_normalized_name_collisions_abstain_without_last_writer_wins_assignment(self) -> None:
        artifact = build_public_artist_membership_candidate(
            _universe(collision=True),
            _approved_input(pairs=False),
            PublicArtistMembershipSourcePolicy(),
        )
        self.assertEqual(artifact.coverage.ambiguous_public_genre_identity_count, 2)
        self.assertEqual(len(artifact.directly_observed_memberships), 0)
        self.assertEqual(
            [item.status for item in artifact.dispositions[:2]], ["abstained", "abstained"]
        )

    def test_source_and_row_level_policy_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "aggregate rows require"):
            ApprovedPublicMembershipInput(
                public_model_input=_model_input(),
                input_file_sha256="d" * 64,
                public_model_input_sha256=_sha256(_model_input().model_dump(mode="json")),
                row_export_policy_sha256="e" * 64,
                declared_direct_row_count=1,
                declared_aggregate_row_count=1,
            )
        with self.assertRaisesRegex(ValueError, "outside source policy"):
            build_public_artist_membership_candidate(
                _universe(), _approved_input(), PublicArtistMembershipSourcePolicy()
            )

    def test_publication_and_promotion_reject_tampered_artifacts_and_gold_is_required(self) -> None:
        policy = PublicArtistMembershipSourcePolicy(
            aggregate_co_listen_publicly_permitted=True,
            aggregate_co_listen_export_allowed=True,
            include_aggregate_candidates=True,
        )
        artifact = build_public_artist_membership_candidate(_universe(), _approved_input(), policy)
        tampered = artifact.model_copy(
            update={
                "directly_observed_memberships": (
                    artifact.directly_observed_memberships[0].model_copy(update={"score": 0.5}),
                )
            }
        )
        with self.assertRaisesRegex(ValueError, "output hash"):
            verify_public_artist_membership_candidate(tampered)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "output hash"):
                write_public_artist_membership_candidate(
                    tampered,
                    output=root / "tampered.json",
                    store=LocalObjectStore(root / "objects"),
                )
            receipt = write_public_artist_membership_candidate(
                artifact, output=root / "candidate.json", store=LocalObjectStore(root / "objects")
            )
            self.assertEqual(receipt.artifact_output_sha256, artifact.output_sha256)
            self.assertTrue(
                receipt.artifact_object.key.value.endswith(f"{artifact.output_sha256}.json")
            )

        absent_gold = evaluate_public_artist_membership_promotion(
            artifact, PromotionPolicy(minimum_labeled_candidates=2)
        )
        self.assertFalse(absent_gold.promotion_eligible)
        self.assertEqual(absent_gold.quality_claim, "not_evaluated_without_independent_public_gold")
        labels = (
            IndependentPublicGoldLabel(
                artist_id="artist:alpha", genre_id="genre:jazz", is_member=True
            ),
            IndependentPublicGoldLabel(
                artist_id="artist:beta", genre_id="genre:jazz", is_member=True
            ),
        )
        gold = IndependentPublicGoldSet(
            source=IndependentPublicGoldSource(
                source_ref="https://example.test/independent-public-gold.json",
                records_sha256=_sha256([item.model_dump(mode="json") for item in labels]),
            ),
            labels=labels,
        )
        promoted = evaluate_public_artist_membership_promotion(
            artifact,
            PromotionPolicy(
                minimum_labeled_candidates=2, minimum_precision=1.0, minimum_recall=1.0
            ),
            gold,
        )
        self.assertTrue(promoted.promotion_eligible)
        self.assertEqual(promoted.labeled_candidate_count, 2)
        self.assertEqual(promoted.unlabeled_candidate_count, 0)

    def test_gold_labels_must_be_deterministically_sorted(self) -> None:
        labels = (
            IndependentPublicGoldLabel(artist_id="artist:z", genre_id="genre:jazz", is_member=True),
            IndependentPublicGoldLabel(
                artist_id="artist:a", genre_id="genre:jazz", is_member=False
            ),
        )
        with self.assertRaisesRegex(ValidationError, "sorted"):
            IndependentPublicGoldSet(
                source=IndependentPublicGoldSource(
                    source_ref="https://example.test/independent-public-gold.json",
                    records_sha256=_sha256([item.model_dump(mode="json") for item in labels]),
                ),
                labels=labels,
            )


if __name__ == "__main__":
    unittest.main()
