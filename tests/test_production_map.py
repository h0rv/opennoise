import unittest

from musix.ml.production_map import ProductionMapGeometryError, build_production_map
from musix.ml.public_graph import build_public_model
from musix.models.modeling import (
    DirectMembershipEvidence,
    GenreHierarchyEdge,
    GenreIdentity,
    PublicArtifact,
    PublicModelInput,
    PublicModelSettings,
)
from musix.models.production import ProductionMapSettings
from musix.overview import build_overview_communities


def _inputs() -> PublicModelInput:
    identifiers = (
        ("Q1", "Electronic music"),
        ("Q2", "Techno"),
        ("Q3", "Detroit techno"),
        ("Q4", "Ambient music"),
        ("Q5", "Dark ambient"),
        ("Q6", "Hip hop music"),
        ("Q7", "Trap music"),
        ("Q8", "Cloud rap"),
    )
    return PublicModelInput(
        artifacts=(
            PublicArtifact(
                source="wikidata",
                snapshot="fixture",
                artifact_key="fixture:qualified",
                content_sha256="a" * 64,
                export_allowed=True,
            ),
        ),
        genres=tuple(
            GenreIdentity(
                genre_id=f"wikidata:genre:{identifier}",
                name=name,
                evidence_refs=(f"wd:{identifier}",),
            )
            for identifier, name in identifiers
        ),
        direct_memberships=tuple(
            DirectMembershipEvidence(
                artist_id=f"musicbrainz:artist:{index:08d}",
                genre_id=f"wikidata:genre:{identifier}",
                facet="wikidata_p136",
                value=1,
                evidence_ref=f"wd:membership:{identifier}",
            )
            for index, (identifier, _name) in enumerate(identifiers, start=1)
        ),
        hierarchy=(
            GenreHierarchyEdge(
                child_genre_id="wikidata:genre:Q2",
                parent_genre_id="wikidata:genre:Q1",
                evidence_ref="wd:Q2:P279:Q1",
            ),
            GenreHierarchyEdge(
                child_genre_id="wikidata:genre:Q3",
                parent_genre_id="wikidata:genre:Q2",
                evidence_ref="wd:Q3:P279:Q2",
            ),
            GenreHierarchyEdge(
                child_genre_id="wikidata:genre:Q4",
                parent_genre_id="wikidata:genre:Q1",
                evidence_ref="wd:Q4:P279:Q1",
            ),
            GenreHierarchyEdge(
                child_genre_id="wikidata:genre:Q5",
                parent_genre_id="wikidata:genre:Q4",
                evidence_ref="wd:Q5:P279:Q4",
            ),
            GenreHierarchyEdge(
                child_genre_id="wikidata:genre:Q7",
                parent_genre_id="wikidata:genre:Q6",
                evidence_ref="wd:Q7:P279:Q6",
            ),
            GenreHierarchyEdge(
                child_genre_id="wikidata:genre:Q8",
                parent_genre_id="wikidata:genre:Q7",
                evidence_ref="wd:Q8:P279:Q7",
            ),
        ),
    )


def _settings() -> ProductionMapSettings:
    return ProductionMapSettings(
        geometry_grid_size=5,
        minimum_central_span=0.05,
        minimum_occupied_cell_ratio=0.01,
        minimum_desktop_16x9_occupied_cell_ratio=0.01,
        maximum_desktop_16x9_cell_fraction=1.0,
        minimum_neighbor_preservation=0.0,
    )


class ProductionMapTests(unittest.TestCase):
    def test_builds_full_dag_display_tree_nested_lod_and_electronic_audit(self) -> None:
        inputs = _inputs()
        source = build_public_model(inputs, PublicModelSettings())
        first = build_production_map(inputs, source, _settings())
        second = build_production_map(inputs, source, _settings())

        self.assertEqual(first.output_sha256, second.output_sha256)
        self.assertEqual(first.metrics.coordinate_sha256, second.metrics.coordinate_sha256)
        self.assertTrue(first.metrics.exact_rerun)
        self.assertEqual(len(first.nodes), len(inputs.genres))
        self.assertEqual(
            len([edge for edge in first.edges if edge.kind == "taxonomy"]), len(inputs.hierarchy)
        )
        self.assertEqual(first.metrics.root_region_overlap_count, 0)
        self.assertEqual(first.metrics.hierarchy_containment_fraction, 1.0)
        self.assertEqual(first.electronic_branch.maximum_depth, 2)
        self.assertEqual(
            first.electronic_branch.root_genre_id,
            "wikidata:genre:Q1",
        )
        by_id = {item.genre_id: item for item in first.nodes}
        overview = build_overview_communities(first)
        overview_names = [community.name for community in overview]
        self.assertEqual(len(overview_names), len(set(overview_names)))
        electronic = next(
            community
            for community in overview
            if "wikidata:genre:Q2" in community.member_entity_ids
        )
        self.assertEqual(electronic.naming.anchor_entity_id, "wikidata:genre:Q1")
        self.assertEqual(
            electronic.naming.method,
            "canonical_taxonomy_ancestor_weighted_coverage_v1",
        )
        self.assertGreaterEqual(electronic.naming.weighted_coverage, 0.5)
        self.assertIn("wd:Q1", electronic.naming.provenance_refs)
        for node in first.nodes:
            if node.display_parent_id is None:
                self.assertEqual(node.lod_min, 0)
                continue
            parent = by_id[node.display_parent_id]
            self.assertLessEqual(parent.lod_min, node.lod_min)
            self.assertLessEqual(parent.region.x0, node.region.x0)
            self.assertLessEqual(node.region.x1, parent.region.x1)

    def test_fails_closed_when_declared_geometry_gates_do_not_pass(self) -> None:
        inputs = _inputs()
        source = build_public_model(inputs, PublicModelSettings())
        with self.assertRaises(ProductionMapGeometryError):
            build_production_map(inputs, source)


if __name__ == "__main__":
    unittest.main()
