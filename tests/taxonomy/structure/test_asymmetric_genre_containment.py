from __future__ import annotations

import hashlib
import json
import unittest

from pydantic import ValidationError

from musix.evidence.reconstruction import GenreArtistEdge, ReconstructionInputs, VersionedInput
from musix.models.modeling import (
    DirectMembershipEvidence,
    GenreIdentity,
    PublicArtifact,
    PublicModelInput,
)
from musix.serving.public.public_taxonomy_expansion import (
    ConnectivityCoverage,
    ExpansionEdge,
    ExpansionEdgeEvidence,
    ExpansionNode,
    PublicTaxonomyExpansionArtifact,
    PublicTaxonomyExpansionConfig,
    PublicTaxonomyExpansionCoverage,
)
from musix.taxonomy.structure.asymmetric_genre_containment import (
    AsymmetricGenreContainmentPolicy,
    GenreContainmentBridge,
    GenreContainmentBridgeEntry,
    build_asymmetric_genre_containment,
    build_asymmetric_genre_containment_from_reconstruction_inputs,
    verify_asymmetric_genre_containment,
)


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


def _taxonomy(*, include_cycle: bool = False) -> PublicTaxonomyExpansionArtifact:
    nodes = (
        ExpansionNode(
            node_id="catalog:genre:child",
            node_kind="public_catalog_genre",
            name="Child",
            catalog_id="genre:child",
        ),
        ExpansionNode(
            node_id="catalog:genre:parent",
            node_kind="public_catalog_genre",
            name="Parent",
            catalog_id="genre:parent",
        ),
        ExpansionNode(
            node_id="legacy:child",
            node_kind="legacy_name_seed",
            name="Child",
            legacy_source_item_id="child",
            taxonomy_status="canonical_exact",
        ),
        ExpansionNode(
            node_id="legacy:parent",
            node_kind="legacy_name_seed",
            name="Parent",
            legacy_source_item_id="parent",
            taxonomy_status="canonical_exact",
        ),
    )
    hierarchy = tuple(
        [
            ExpansionEdge(
                edge_id=f"{letter}" * 64,
                source_node_id=f"catalog:genre:{source}",
                target_node_id=f"catalog:genre:{target}",
                kind="public_catalog_taxonomy_parent",
                factual_relationship=True,
                review_candidate=False,
                evidence=ExpansionEdgeEvidence(
                    source="cc0_public_catalog",
                    taxonomy_artifact_sha256="a" * 64,
                    public_catalog_sha256="b" * 64,
                    catalog_child_id=f"genre:{source}",
                    catalog_parent_id=f"genre:{target}",
                    relation_id=letter,
                    note="fixture",
                ),
            )
            for letter, source, target in (("1", "child", "parent"),)
        ]
    )
    if include_cycle:
        hierarchy += (
            ExpansionEdge(
                edge_id="2" * 64,
                source_node_id="catalog:genre:parent",
                target_node_id="catalog:genre:child",
                kind="public_catalog_taxonomy_parent",
                factual_relationship=True,
                review_candidate=False,
                evidence=ExpansionEdgeEvidence(
                    source="cc0_public_catalog",
                    taxonomy_artifact_sha256="a" * 64,
                    public_catalog_sha256="b" * 64,
                    catalog_child_id="genre:parent",
                    catalog_parent_id="genre:child",
                    relation_id="2",
                    note="fixture",
                ),
            ),
        )
    hierarchy_count = len(hierarchy)
    identity = tuple(
        ExpansionEdge(
            edge_id=f"{letter}" * 64,
            source_node_id=f"legacy:{genre}",
            target_node_id=f"catalog:genre:{genre}",
            kind="canonical_catalog_identity",
            factual_relationship=True,
            review_candidate=False,
            evidence=ExpansionEdgeEvidence(
                source="sealed_public_taxonomy",
                taxonomy_artifact_sha256="a" * 64,
                public_catalog_sha256="b" * 64,
                catalog_parent_id=f"genre:{genre}",
                taxonomy_status="canonical_exact",
                note="fixture",
            ),
        )
        for letter, genre in (("3", "child"), ("4", "parent"))
    )
    coverage = PublicTaxonomyExpansionCoverage(
        legacy_seed_node_count=2,
        catalog_node_count=2,
        canonical_identity_edge_count=2,
        catalog_taxonomy_edge_count=hierarchy_count,
        compositional_review_edge_count=0,
        ambiguous_identity_review_edge_count=0,
        exact_identity_legacy_seed_count=2,
        compositional_review_legacy_seed_count=0,
        ambiguous_review_legacy_seed_count=0,
        abstained_legacy_seed_count=0,
        factual_only=ConnectivityCoverage(
            component_count=1 if hierarchy_count else 2,
            isolated_node_count=0 if hierarchy_count else 2,
            connected_legacy_seed_count=2 if hierarchy_count else 0,
            isolated_legacy_seed_count=0 if hierarchy_count else 2,
        ),
        review_enabled=ConnectivityCoverage(
            component_count=1 if hierarchy_count else 2,
            isolated_node_count=0 if hierarchy_count else 2,
            connected_legacy_seed_count=2 if hierarchy_count else 0,
            isolated_legacy_seed_count=0 if hierarchy_count else 2,
        ),
    )
    preliminary = PublicTaxonomyExpansionArtifact(
        taxonomy_artifact_sha256="a" * 64,
        taxonomy_logical_output_sha256="c" * 64,
        public_catalog_sha256="b" * 64,
        config=PublicTaxonomyExpansionConfig(expected_legacy_seed_count=2),
        nodes=nodes,
        edges=(*hierarchy, *identity),
        coverage=coverage,
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(
        update={
            "output_sha256": _sha(preliminary.model_dump(mode="json", exclude={"output_sha256"}))
        }
    )


def _memberships(*, sparse: bool = False) -> PublicModelInput:
    rows = [("a", "genre:child"), ("b", "genre:child")]
    if sparse:
        rows = [("a", "genre:child"), ("a", "genre:parent")]
    else:
        rows.extend([("a", "genre:parent"), ("b", "genre:parent"), ("c", "genre:parent")])
    return PublicModelInput(
        artifacts=(
            PublicArtifact(
                source="wikidata",
                snapshot="fixture",
                artifact_key="memberships",
                content_sha256="d" * 64,
                export_allowed=True,
            ),
        ),
        genres=(
            GenreIdentity(genre_id="genre:child", name="Child", evidence_refs=("genre:child",)),
            GenreIdentity(genre_id="genre:parent", name="Parent", evidence_refs=("genre:parent",)),
        ),
        direct_memberships=tuple(
            DirectMembershipEvidence(
                artist_id=artist,
                genre_id=genre,
                facet="wikidata_p136",
                value=1.0,
                evidence_ref=f"evidence:{artist}:{genre}",
            )
            for artist, genre in rows
        ),
    )


class AsymmetricGenreContainmentTests(unittest.TestCase):
    def test_directionality_follows_child_to_parent_taxonomy_edge(self) -> None:
        artifact = build_asymmetric_genre_containment(_taxonomy(), _memberships())
        (forward,) = artifact.candidates
        self.assertEqual(
            (forward.child_genre_id, forward.parent_genre_id),
            ("genre:child", "genre:parent"),
        )
        self.assertEqual(forward.status, "accepted")
        self.assertGreater(forward.components.directionality_gap, 0.0)

    def test_taxonomy_cycles_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "acyclic"):
            build_asymmetric_genre_containment(_taxonomy(include_cycle=True), _memberships())

    def test_reconstruction_tag_edges_are_not_relabelled_as_genres(self) -> None:
        reconstruction = ReconstructionInputs(
            membership_artifact=VersionedInput(
                artifact_key="local-facets", revision="v1", content_sha256="c" * 64
            ),
            membership_edges=(
                GenreArtistEdge(
                    genre_id="musicbrainz:genre:child",
                    facet="tag",
                    artist_id="artist",
                    evidence_refs=("tag-ref",),
                ),
            ),
        )
        bridge_entry = GenreContainmentBridgeEntry(
            source_item_id="child",
            musicbrainz_genre_id="musicbrainz:genre:child",
            catalog_genre_id="genre:child",
            seed_name="Child",
            catalog_name="Child",
            evidence_ref="bridge-ref",
        )
        bridge = GenreContainmentBridge(
            entries=(bridge_entry,),
            bridge_sha256=_sha([bridge_entry.model_dump(mode="json")]),
        )
        with self.assertRaisesRegex(ValueError, "genre edges only"):
            build_asymmetric_genre_containment_from_reconstruction_inputs(
                _taxonomy(), reconstruction, bridge
            )

    def test_bridge_requires_name_agreement_and_a_content_hash(self) -> None:
        entry = GenreContainmentBridgeEntry(
            source_item_id="child",
            musicbrainz_genre_id="musicbrainz:genre:child",
            catalog_genre_id="genre:child",
            seed_name="Child",
            catalog_name="Child",
            evidence_ref="bridge:child",
        )
        bridge_hash = _sha([entry.model_dump(mode="json")])
        self.assertEqual(
            GenreContainmentBridge(entries=(entry,), bridge_sha256=bridge_hash).bridge_sha256,
            bridge_hash,
        )
        with self.assertRaises(ValidationError):
            GenreContainmentBridgeEntry(
                source_item_id="child",
                musicbrainz_genre_id="musicbrainz:genre:child",
                catalog_genre_id="genre:child",
                seed_name="Child",
                catalog_name="Different",
                evidence_ref="bridge:child",
            )

    def test_review_taxonomy_edges_never_become_containment_candidates(self) -> None:
        taxonomy = _taxonomy()
        review = ExpansionEdge(
            edge_id="5" * 64,
            source_node_id="legacy:child",
            target_node_id="catalog:genre:parent",
            kind="compositional_review_anchor",
            factual_relationship=False,
            review_candidate=True,
            evidence=ExpansionEdgeEvidence(
                source="sealed_public_taxonomy",
                taxonomy_artifact_sha256="a" * 64,
                public_catalog_sha256="b" * 64,
                catalog_parent_id="genre:parent",
                taxonomy_status="anchored_compositional",
                note="review fixture",
            ),
        )
        coverage = taxonomy.coverage.model_copy(update={"compositional_review_edge_count": 1})
        preliminary = taxonomy.model_copy(
            update={
                "edges": (*taxonomy.edges, review),
                "coverage": coverage,
                "output_sha256": "0" * 64,
            }
        )
        sealed = preliminary.model_copy(
            update={
                "output_sha256": _sha(
                    preliminary.model_dump(mode="json", exclude={"output_sha256"})
                )
            }
        )
        artifact = build_asymmetric_genre_containment(sealed, _memberships())
        self.assertEqual(len(artifact.candidates), 1)
        self.assertEqual(artifact.coverage.taxonomy_edge_count, 1)

    def test_tampered_output_hash_fails_closed(self) -> None:
        artifact = build_asymmetric_genre_containment(_taxonomy(), _memberships())
        with self.assertRaisesRegex(ValueError, "output hash"):
            verify_asymmetric_genre_containment(
                artifact.model_copy(update={"output_sha256": "e" * 64})
            )

    def test_insufficient_artist_evidence_is_an_explicit_abstention(self) -> None:
        artifact = build_asymmetric_genre_containment(_taxonomy(), _memberships(sparse=True))
        self.assertEqual(artifact.coverage.insufficient_artist_membership_evidence_count, 1)
        self.assertTrue(all(item.status == "abstained" for item in artifact.candidates))

    def test_replay_and_inputs_are_unchanged(self) -> None:
        taxonomy = _taxonomy()
        memberships = _memberships()
        taxonomy_before = taxonomy.model_dump(mode="json")
        memberships_before = memberships.model_dump(mode="json")
        first = build_asymmetric_genre_containment(
            taxonomy, memberships, AsymmetricGenreContainmentPolicy()
        )
        second = build_asymmetric_genre_containment(
            taxonomy, memberships, AsymmetricGenreContainmentPolicy()
        )
        self.assertEqual(first, second)
        self.assertEqual(first.output_sha256, second.output_sha256)
        verify_asymmetric_genre_containment(first)
        self.assertEqual(taxonomy.model_dump(mode="json"), taxonomy_before)
        self.assertEqual(memberships.model_dump(mode="json"), memberships_before)
