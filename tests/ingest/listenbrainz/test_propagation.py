"""Behavioral tests for the bounded ListenBrainz propagation artifact."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Literal, cast

from opennoise.ingest.listenbrainz.propagation import (
    ListenBrainzPropagationSettings,
    PropagationInputFingerprint,
    build_listenbrainz_propagation,
    merge_direct_memberships,
    musicbrainz_seed_target_memberships,
    publish_listenbrainz_propagation,
    verify_listenbrainz_propagation,
)
from opennoise.ingest.musicbrainz.seed_targets import (
    MusicBrainzSeedTargetArtifact,
    SeedTargetEvidence,
)
from opennoise.models.modeling import (
    ArtistPairEvidence,
    DirectMembershipEvidence,
    GenreIdentity,
    PublicArtifact,
    PublicModelInput,
)
from opennoise.serving.public.artist_membership import NameUniverse, NameUniverseEntry
from opennoise.storage import LocalObjectStore
from scripts.build_listenbrainz_propagation import _require_qualified_snapshot

if TYPE_CHECKING:
    from collections.abc import Iterator


def _universe() -> NameUniverse:
    names = tuple(
        NameUniverseEntry(
            source_item_id=f"item-{index}",
            external_id=f"external-{index}",
            name=("a" if index == 0 else "b" if index == 1 else f"unmatched {index}"),
        )
        for index in range(6291)
    )
    return NameUniverse(source_content_sha256="a" * 64, names=names)


def _inputs() -> PublicModelInput:
    return PublicModelInput(
        artifacts=(
            PublicArtifact(
                source="listenbrainz",
                snapshot="fixture",
                artifact_key="fixture-listens",
                content_sha256="b" * 64,
                export_allowed=True,
            ),
            PublicArtifact(
                source="wikidata",
                snapshot="fixture",
                artifact_key="fixture-direct",
                content_sha256="c" * 64,
                export_allowed=True,
            ),
        ),
        genres=(
            GenreIdentity(genre_id="genre:a", name="A", evidence_refs=("genre:a",)),
            GenreIdentity(genre_id="genre:b", name="B", evidence_refs=("genre:b",)),
        ),
        direct_memberships=(
            DirectMembershipEvidence(
                artist_id="artist:one",
                genre_id="genre:a",
                facet="wikidata_p136",
                value=1.0,
                evidence_ref="direct:one:a",
            ),
            DirectMembershipEvidence(
                artist_id="artist:two",
                genre_id="genre:b",
                facet="musicbrainz_tag",
                value=2.0,
                evidence_ref="direct:two:b",
            ),
            DirectMembershipEvidence(
                artist_id="artist:three",
                genre_id="genre:a",
                facet="musicbrainz_genre",
                value=2.0,
                evidence_ref="direct:three:a",
            ),
        ),
        artist_pairs=(
            ArtistPairEvidence(
                left_artist_id="artist:one",
                right_artist_id="artist:two",
                listener_day_support=20,
                supporting_windows=2,
                evidence_refs=("listen:1",),
            ),
            ArtistPairEvidence(
                left_artist_id="artist:three",
                right_artist_id="artist:two",
                listener_day_support=20,
                supporting_windows=2,
                evidence_refs=("listen:2",),
            ),
        ),
    )


def _fingerprint() -> PropagationInputFingerprint:
    return PropagationInputFingerprint(
        catalog_database_sha256="d" * 64,
        listenbrainz_database_sha256="e" * 64,
        name_universe_source_sha256="a" * 64,
        musicbrainz_seed_target_output_sha256="b" * 64,
        musicbrainz_seed_target_file_sha256="c" * 64,
        public_input_sha256="f" * 64,
    )


class ListenBrainzPropagationTests(unittest.TestCase):
    def test_cli_snapshot_boundary_requires_one_hash_locked_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            qualified = root / "qualified.sqlite"
            qualified.write_bytes(b"qualified fixture")
            other = root / "other.sqlite"
            other.write_bytes(b"other fixture")
            digest = hashlib.sha256(qualified.read_bytes()).hexdigest()
            self.assertEqual(
                _require_qualified_snapshot(qualified, digest, qualified, digest), digest
            )
            with self.assertRaisesRegex(ValueError, "same qualified snapshot"):
                _require_qualified_snapshot(qualified, digest, other, digest)
            with self.assertRaisesRegex(ValueError, "expected hashes"):
                _require_qualified_snapshot(qualified, digest, qualified, "0" * 64)
            with self.assertRaisesRegex(ValueError, "bytes do not match"):
                _require_qualified_snapshot(qualified, "0" * 64, qualified, "0" * 64)

    def test_candidates_are_deterministic_review_evidence_with_6291_coverage(self) -> None:
        settings = ListenBrainzPropagationSettings(holdout_modulus=2, maximum_artist_degree=10)
        first = build_listenbrainz_propagation(_inputs(), _universe(), _fingerprint(), settings)
        second = build_listenbrainz_propagation(_inputs(), _universe(), _fingerprint(), settings)
        self.assertEqual(first.output_sha256, second.output_sha256)
        self.assertEqual(
            first.membership_semantics, "derived_review_evidence_not_factual_membership"
        )
        self.assertEqual(first.coverage.name_universe_count, 6291)
        self.assertEqual(first.coverage.uniquely_matched_name_universe_genre_count, 2)
        self.assertGreater(first.coverage.candidate_count, 0)
        self.assertTrue(
            all(
                path.normalized_edge_weight <= 1.0
                for item in first.candidates
                for path in item.paths
            )
        )
        self.assertEqual(
            first.heldout_anchor_recovery.heldout_anchor_count
            + first.heldout_anchor_recovery.training_anchor_count,
            first.heldout_anchor_recovery.direct_anchor_count,
        )
        verify_listenbrainz_propagation(first)

    def test_hub_cap_abstains_from_high_degree_pairs(self) -> None:
        artifact = build_listenbrainz_propagation(
            _inputs(),
            _universe(),
            _fingerprint(),
            ListenBrainzPropagationSettings(maximum_artist_degree=1),
        )
        self.assertEqual(artifact.coverage.hub_capped_artist_count, 1)
        self.assertEqual(artifact.coverage.retained_artist_pair_count, 0)
        self.assertEqual(artifact.coverage.candidate_count, 0)

    def test_seed_cap_bounds_walk_without_discarding_direct_anchor_ledger(self) -> None:
        inputs = _inputs().model_copy(
            update={
                "direct_memberships": (
                    *_inputs().direct_memberships,
                    DirectMembershipEvidence(
                        artist_id="artist:one",
                        genre_id="genre:b",
                        facet="musicbrainz_tag",
                        value=0.5,
                        evidence_ref="direct:one:b",
                    ),
                )
            }
        )
        artifact = build_listenbrainz_propagation(
            inputs,
            _universe(),
            _fingerprint(),
            ListenBrainzPropagationSettings(maximum_seed_anchors_per_artist=1),
        )
        self.assertEqual(artifact.coverage.direct_anchor_count, 4)
        self.assertEqual(artifact.coverage.seed_anchor_capped_count, 1)

    def test_direct_source_union_is_monotonic_and_rejects_duplicate_evidence(self) -> None:
        inputs = _inputs()
        musicbrainz = tuple(
            item for item in inputs.direct_memberships if item.facet != "wikidata_p136"
        )
        wikidata = tuple(
            item for item in inputs.direct_memberships if item.facet == "wikidata_p136"
        )
        merged = merge_direct_memberships(musicbrainz, wikidata)
        self.assertEqual(set(merged), set(inputs.direct_memberships))
        with self.assertRaisesRegex(ValueError, "duplicate source evidence"):
            merge_direct_memberships(musicbrainz, (*wikidata, wikidata[0]))

    def test_streamed_musicbrainz_rows_preserve_facets_and_monotonic_union(self) -> None:
        artist = "00000000-0000-0000-0000-000000000001"

        def evidence(
            *, facet: Literal["genre", "tag"], target_identity: str, reference: str
        ) -> SeedTargetEvidence:
            return SeedTargetEvidence(
                seed_source_item_id="item-0",
                seed_source_external_id="external-0",
                seed_name="a",
                seed_normalized_name="a",
                facet=facet,
                target_namespace=(
                    "musicbrainz_genre_id" if facet == "genre" else "musicbrainz_tag_name"
                ),
                target_identity=target_identity,
                target_name="a",
                artist_id=artist,
                source_record_id="record",
                source_record_ordinal=1,
                source_record_sha256="d" * 64,
                source_record_byte_length=1,
                evidence_ref=reference,
                positive_weight=1.0,
                match_kind="exact",
            )

        class StreamOnlyRows:
            def __iter__(self) -> Iterator[SeedTargetEvidence]:
                return iter(
                    (
                        evidence(facet="genre", target_identity="genre:one", reference="first"),
                        evidence(facet="genre", target_identity="genre:two", reference="second"),
                        evidence(facet="tag", target_identity="tag:one", reference="tag"),
                    )
                )

            def __len__(self) -> int:
                raise AssertionError("propagation adapter must not materialize source evidence")

        source = cast("MusicBrainzSeedTargetArtifact", SimpleNamespace(evidence=StreamOnlyRows()))
        musicbrainz = musicbrainz_seed_target_memberships(source, {f"musicbrainz:artist:{artist}"})
        self.assertEqual(len(musicbrainz), 2)
        self.assertEqual(
            {item.facet for item in musicbrainz}, {"musicbrainz_genre", "musicbrainz_tag"}
        )
        wikidata = (_inputs().direct_memberships[0],)
        merged = merge_direct_memberships(musicbrainz, wikidata)
        self.assertTrue(set(musicbrainz) <= set(merged))
        self.assertTrue(set(wikidata) <= set(merged))

    def test_publication_binds_logical_and_file_hashes(self) -> None:
        artifact = build_listenbrainz_propagation(
            _inputs(), _universe(), _fingerprint(), ListenBrainzPropagationSettings()
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt, write = publish_listenbrainz_propagation(
                artifact,
                output_path=root / "propagation.json",
                store=LocalObjectStore(root / "objects"),
            )
            self.assertEqual(receipt.logical_output_sha256, artifact.output_sha256)
            self.assertEqual(receipt.artifact_sha256, write.sha256)
            self.assertTrue(write.key.value.startswith("listenbrainz-propagation/"))


if __name__ == "__main__":
    unittest.main()
