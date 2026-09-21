"""Focused tests for the local MusicBrainz direct-tag lower-bound audit."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType


def _audit_module() -> ModuleType:
    path = Path("scripts/audit_musicbrainz_prefilter_unplaced_lower_bound.py")
    specification = importlib.util.spec_from_file_location("prefilter_audit", path)
    if specification is None or specification.loader is None:
        raise RuntimeError("could not load the pre-filter audit script")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


class MusicBrainzPrefilterUnplacedLowerBoundTests(unittest.TestCase):
    """Keep exact and normalized direct tag claims distinct and non-public."""

    def test_exact_and_normalized_rows_are_counted_separately(self) -> None:
        module = _audit_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            layout = directory / "layout.json"
            artifact = directory / "artifact.json"
            layout.write_text(
                json.dumps(
                    {
                        "output_sha256": "1" * 64,
                        "unplaced": [
                            {"seed_id": "unplaced-exact", "name": "exact tag"},
                            {"seed_id": "unplaced-normalized", "name": "other tag"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            artifact.write_text(
                json.dumps(
                    {
                        "output_sha256": "2" * 64,
                        "evidence": [
                            _tag_row("unplaced-exact", "exact tag", "exact tag", "exact"),
                            _tag_row("unplaced-normalized", "other tag", "Other Tag", "normalized"),
                            _tag_row("placed", "placed", "placed", "exact"),
                            {"facet": "genre"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            result = module.audit(layout_path=layout, artifact_path=artifact)
        self.assertEqual(result.unplaced_seed_count, 2)
        self.assertEqual(result.direct_tag_rows_scanned, 3)
        self.assertEqual(result.direct_tag_rows_for_unplaced, 2)
        self.assertEqual(result.exact_spelling_tag_rows_for_unplaced, 1)
        self.assertEqual(result.normalized_or_reviewed_tag_rows_for_unplaced, 1)
        self.assertEqual(result.publishable_membership_count, 0)
        self.assertEqual(
            result.source_completeness, "not_a_prefilter_slice; absence_is_not_measured"
        )
        self.assertIn("pre-filter MusicBrainz artist JSON", result.missing_input)


def _tag_row(seed_id: str, seed_name: str, target_name: str, match_kind: str) -> dict[str, str]:
    return {
        "facet": "tag",
        "seed_source_item_id": seed_id,
        "artist_id": "artist",
        "source_record_id": "record",
        "target_name": target_name,
        "seed_name": seed_name,
        "match_kind": match_kind,
    }


if __name__ == "__main__":
    unittest.main()
