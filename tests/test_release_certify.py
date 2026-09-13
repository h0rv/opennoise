import tempfile
import unittest
from pathlib import Path

from scripts.release_certify import (
    ReleaseCertificationError,
    _require_file,
    _require_semantic_release_renderer,
    resolve_cache_database,
)


class ReleaseCertificationTests(unittest.TestCase):
    def test_uses_retained_cache_only_when_conventional_cache_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary = root / "data" / "phase3-public-qualified.sqlite"
            retained = root / ".cache" / "listenbrainz-qualified-input" / "sha256" / "cache.sqlite"
            retained.parent.mkdir(parents=True)
            retained.touch()

            self.assertEqual(resolve_cache_database(primary, retained), retained)

            primary.parent.mkdir(parents=True)
            primary.touch()
            self.assertEqual(resolve_cache_database(primary, retained), primary)

    def test_missing_retained_cache_keeps_the_release_boundary_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.sqlite"

            with self.assertRaisesRegex(
                ReleaseCertificationError, r"cache-only prerequisite missing: sealed cache database"
            ):
                _require_file(missing, "sealed cache database")

    def test_public_release_is_closed_until_semantic_canvas_is_publishable(self) -> None:
        with self.assertRaisesRegex(ReleaseCertificationError, "publishable semantic-map artifact"):
            _require_semantic_release_renderer()


if __name__ == "__main__":
    unittest.main()
