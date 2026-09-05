import re
import unittest

from scripts.render_ui_qa import fixture_html, inspect_fixture


class UiQaTests(unittest.TestCase):
    def test_fixture_is_deterministic_accessible_and_bounded(self) -> None:
        first = fixture_html()
        second = fixture_html()
        inspection = inspect_fixture(first)

        self.assertEqual(first, second)
        self.assertLess(inspection.html_bytes, 64 * 1024)
        self.assertLess(inspection.css_bytes, 16 * 1024)
        self.assertLess(inspection.element_count, 1_000)
        self.assertLess(inspection.focusable_count, 200)
        self.assertNotIn("<audio", first.casefold())
        self.assertNotIn("<video", first.casefold())
        self.assertNotIn("<canvas", first.casefold())
        self.assertIsNone(re.search(r'href="/static/app\.css(?:\?[^" ]*)?"', first))
        self.assertNotIn("player", first.casefold())
        self.assertNotIn("preview", first.casefold())
        self.assertEqual(first.count('id="semantic-map"'), 1)
        self.assertEqual(first.count('id="layout-lenses"'), 1)
        for layout_key in ("public", "public-direct", "public-community", "public-taxonomy"):
            self.assertIn(f'href="/?layout={layout_key}"', first)


if __name__ == "__main__":
    unittest.main()
