"""Complete indexed source groups are required for richer preview lineage."""

import unittest

from opennoise.deployment.community_preview import require_feature_bindings

_CORE = {
    key: {}
    for key in (
        "artist_name_enrichment_receipt",
        "candidate_catalog_database",
        "candidate_catalog_receipt",
        "direct_genre_claim_object",
        "direct_genre_receipt",
        "genre_labels",
    )
}


def _group(index: int) -> dict[str, object]:
    key = f"open_artist_features_{index}"
    return {key: {}, key + "_receipt": {}, key + "_manifest": {}}


class MultiSourceLineageTests(unittest.TestCase):
    def test_bulk_projection_requires_raw_sources_and_selected_cohort(self) -> None:
        bulk = {
            "bulk_artist_tags_0" + suffix: {}
            for suffix in ("", "_receipt", "_core_prefix", "_derived_archive", "_selection")
        }
        require_feature_bindings(_CORE | _group(0) | bulk)
        for missing in bulk:
            with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, "bulk"):
                require_feature_bindings(
                    _CORE
                    | _group(0)
                    | {key: value for key, value in bulk.items() if key != missing}
                )

    def test_bulk_orphan_and_index_gap_are_rejected(self) -> None:
        for orphan in ("bulk_artist_tags_0_license", "bulk_artist_tags_1_receipt"):
            with self.subTest(orphan=orphan), self.assertRaisesRegex(ValueError, "bulk"):
                require_feature_bindings(_CORE | _group(0) | {orphan: {}})

    def test_complete_multiple_sources_are_accepted(self) -> None:
        require_feature_bindings(_CORE | _group(0) | _group(1))

    def test_index_gap_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "mandatory"):
            require_feature_bindings(_CORE | _group(0) | _group(2))

    def test_orphan_manifest_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "mandatory"):
            require_feature_bindings(_CORE | _group(0) | {"open_artist_features_1_manifest": {}})

    def test_original_source_does_not_hide_incomplete_indexed_group(self) -> None:
        original = {
            key: {}
            for key in (
                "open_artist_features",
                "open_artist_features_receipt",
                "open_artist_source_manifest",
            )
        }
        with self.assertRaisesRegex(ValueError, "mandatory"):
            require_feature_bindings(_CORE | original | {"open_artist_features_0": {}})
