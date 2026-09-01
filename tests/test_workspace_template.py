import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from musix.exploration import GenreDetail
from musix.layouts import DerivedCoordinateSpace, HistoricCoordinateSpace, PublishedLayout
from musix.models import MapPoint, SearchHit, map_view

TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / "src" / "musix" / "templates"


class WorkspaceTemplateTests(unittest.TestCase):
    """Assert that one workspace render owns all navigable UI state."""

    def test_layout_links_preserve_focus_and_search_state(self) -> None:
        """Keep the selected genre and query when changing coordinate lenses."""
        environment = Environment(
            loader=FileSystemLoader(TEMPLATE_ROOT),
            autoescape=select_autoescape(enabled_extensions=("html",)),
        )
        rendered = environment.get_template("workspace.html").render(
            active_layout=None,
            genre=GenreDetail(
                entity_id=7,
                slug="idm",
                name="IDM",
                description=None,
                evidence=(),
            ),
            hits=(SearchHit(entity_id=7, entity_kind="genre", name="IDM"),),
            layout_key="classic",
            layouts=(
                PublishedLayout(
                    layout_key="classic",
                    point_count=1,
                    coordinate_space=HistoricCoordinateSpace(
                        source_ref="fixture", units="source_pixels"
                    ),
                ),
                PublishedLayout(
                    layout_key="generated",
                    point_count=1,
                    coordinate_space=DerivedCoordinateSpace(units="layout_units"),
                ),
            ),
            map=map_view(
                [
                    MapPoint(
                        entity_id=7,
                        entity_kind="genre",
                        name="IDM",
                        x=0.0,
                        y=0.0,
                        display_weight=None,
                        color_hex=None,
                    )
                ],
                7,
            ),
            search_query="idm & glitch",
        )

        self.assertIn('href="/genres/7?layout=generated&amp;q=idm%20%26%20glitch"', rendered)
        self.assertIn(
            'hx-get="/fragments/workspace?layout=generated&amp;focus=7&amp;q=idm%20%26%20glitch"',
            rendered,
        )
        self.assertIn('name="layout" type="hidden" value="classic"', rendered)
        self.assertIn('value="idm &amp; glitch" hx-get="/fragments/search"', rendered)
        self.assertIn('href="/genres/7?layout=classic&amp;q=idm%20%26%20glitch"', rendered)
        self.assertEqual(rendered.count('id="search"'), 1)
        self.assertEqual(rendered.count('id="results"'), 1)
        self.assertEqual(rendered.count('id="map-zoom"'), 1)
        self.assertIn('type="radio" checked', rendered)
        self.assertIn('aria-describedby="map-pan-help"', rendered)
        self.assertNotIn("<audio", rendered)

    def test_public_layout_keys_have_compact_product_labels(self) -> None:
        labels = {
            key: PublishedLayout(
                layout_key=key,
                point_count=1,
                coordinate_space=DerivedCoordinateSpace(units="layout_units"),
            ).label
            for key in ("public", "public-direct", "public-community", "public-taxonomy")
        }

        self.assertEqual(
            labels,
            {
                "public": "Related",
                "public-direct": "Direct",
                "public-community": "Communities",
                "public-taxonomy": "Taxonomy",
            },
        )


if __name__ == "__main__":
    unittest.main()
