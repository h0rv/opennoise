"""Behavioral checks for normalized microgenre feature construction."""

from __future__ import annotations

import unittest

from opennoise.ml.microgenre_features import (
    build_artist_name_overlay,
    build_microgenre_features,
    normalize_value,
)

_ARTIST = "4a2f8c72-2e6f-4c0d-8dc6-7ee33d352c62"
_CREDITED_ARTIST = "4a2f8c72-2e6f-4c0d-8dc6-7ee33d352c63"


class MicrogenreFeatureTests(unittest.TestCase):
    def test_normalizes_and_collapses_duplicate_votes_without_losing_refs(self) -> None:
        rows, rejected = build_microgenre_features(
            [
                {
                    "artist_mbid": _ARTIST,
                    "source_response_sha256": "page-a",
                    "tags": [{"name": "  IDM ", "count": 10}, {"name": "IDM", "count": 100}],
                },
                {
                    "artist_mbid": _ARTIST,
                    "source_response_sha256": "page-b",
                    "tags": [{"name": "idm", "count": 1}],
                },
            ]
        )
        features = rows[0]["features"]
        self.assertEqual(len(features), 1)
        self.assertEqual(features[0]["value"], "idm")
        self.assertEqual(features[0]["weight"], 2.15378)
        self.assertEqual(features[0]["evidence_refs"], ["page-a", "page-b"])
        self.assertEqual(rejected, [])

    def test_filters_junk_explicitly_and_keeps_musical_tags(self) -> None:
        rows, rejected = build_microgenre_features(
            [{"artist_mbid": _ARTIST, "tags": ["seen live", "female vocalists", "microhouse"]}]
        )
        self.assertEqual([item["value"] for item in rows[0]["features"]], ["microhouse"])
        self.assertEqual(
            {item["raw_value"] for item in rejected}, {"seen live", "female vocalists"}
        )
        self.assertTrue(all(item["reason"] == "nonmusical_or_technical_tag" for item in rejected))

    def test_release_context_is_a_separate_facet_and_requires_readable_genre(self) -> None:
        rows, rejected = build_microgenre_features(
            [],
            release_records=[
                {
                    "artist_mbid": _ARTIST,
                    "release_group_mbid": "release-1",
                    "genres": [{"name": "Ambient"}],
                    "tags": [{"name": "dub techno", "count": 2}],
                }
            ],
            proper_genre_claims=[
                {
                    "artist_mbid": _ARTIST,
                    "genre_id": "genre-id",
                    "source_evidence_ref": "artist-record",
                }
            ],
            genre_labels={"genre-id": "Ambient"},
        )
        self.assertEqual(
            [(item["namespace"], item["value"]) for item in rows[0]["features"]],
            [
                ("artist_genre", "ambient"),
                ("release_genre", "ambient"),
                ("release_tag", "dub techno"),
            ],
        )
        self.assertEqual(rows[0]["features"][0]["evidence_refs"], ["artist-record"])
        self.assertEqual(rejected, [])

    def test_area_and_decade_are_secondary_features(self) -> None:
        rows, _ = build_microgenre_features(
            [
                {
                    "artist_mbid": _ARTIST,
                    "area": {"name": "Berlin"},
                    "life_span": {"begin": "1984-01-01"},
                }
            ]
        )
        self.assertEqual(
            [(item["namespace"], item["value"]) for item in rows[0]["features"]],
            [("area", "berlin"), ("decade", "1980s")],
        )

    def test_named_native_artist_genre_survives_without_direct_label_join(self) -> None:
        rows, rejected = build_microgenre_features(
            [{"artist_mbid": _ARTIST, "genres": [{"id": "native-id", "name": "electronic music"}]}]
        )
        self.assertEqual(rows[0]["features"][0]["value"], "electronic music")
        self.assertEqual(rejected, [])

    def test_nonpositive_vote_counts_are_rejected_and_unknown_counts_remain(self) -> None:
        rows, rejected = build_microgenre_features(
            [
                {
                    "artist_mbid": _ARTIST,
                    "tags": [
                        {"name": "zero-count tag", "count": 0},
                        {"name": "unknown-count tag"},
                    ],
                }
            ],
            release_records=[
                {
                    "artist_mbid": _ARTIST,
                    "release_group_mbid": "rg-1",
                    "genres": [{"name": "withdrawn genre", "count": -1}],
                }
            ],
        )
        self.assertEqual([item["value"] for item in rows[0]["features"]], ["unknown-count tag"])
        self.assertEqual({item["reason"] for item in rejected}, {"nonpositive_source_count"})

    def test_pure_places_are_rejected_and_decades_use_context_facet(self) -> None:
        rows, rejected = build_microgenre_features(
            [
                {
                    "artist_mbid": _ARTIST,
                    "area": {"name": "London"},
                    "tags": ["London", "British", "UK garage", {"name": "80s", "count": 2}],
                }
            ]
        )
        self.assertEqual(
            [(item["namespace"], item["value"]) for item in rows[0]["features"]],
            [("area", "london"), ("artist_tag", "uk garage"), ("decade", "1980s")],
        )
        self.assertEqual(
            {item["reason"] for item in rejected},
            {"place_or_nationality_tag_use_context_facet"},
        )

    def test_release_group_features_keep_credit_context_and_source_facets(self) -> None:
        rows, rejected = build_microgenre_features(
            [],
            release_records=[
                {
                    "release_group_mbid": "rg-1",
                    "artist_mbids": [_ARTIST, _CREDITED_ARTIST],
                    "first_release_date": "1984-02-01",
                    "genres": [{"id": "genre-id", "name": "Drum and bass", "count": 4}],
                    "tags": [{"name": "liquid funk", "count": 3}],
                    "evidence_refs": ["release-group/rg-1", "source:sha256"],
                    "evidence_group_ids": ["release_group:rg-1"],
                }
            ],
            genre_labels={"genre-id": "drum and bass"},
        )
        self.assertEqual([row["artist_mbid"] for row in rows], [_ARTIST, _CREDITED_ARTIST])
        for row in rows:
            self.assertEqual(
                [(item["namespace"], item["value"]) for item in row["features"]],
                [
                    ("decade", "1980s"),
                    ("release_genre", "drum and bass"),
                    ("release_tag", "liquid funk"),
                ],
            )
            self.assertEqual(
                row["features"][1]["evidence_refs"], ["release-group/rg-1", "source:sha256"]
            )
        self.assertEqual(rejected, [])

    def test_normalization_is_nfc_casefold_and_whitespace_stable(self) -> None:
        self.assertEqual(normalize_value("  E\u0301lectronica\t"), "électronica")

    def test_name_overlay_is_separate_and_reports_missing_names(self) -> None:
        names, missing = build_artist_name_overlay(
            [{"artist_mbid": _ARTIST, "name": "Four Tet", "source_response_sha256": "page"}],
            [_ARTIST, "4a2f8c72-2e6f-4c0d-8dc6-7ee33d352c63"],
        )
        self.assertEqual(names[0]["name"], "Four Tet")
        self.assertEqual(missing[0]["reason"], "no_verified_display_name_in_metadata_overlay")

    def test_exact_artist_name_tag_is_rejected(self) -> None:
        rows, rejected = build_microgenre_features(
            [{"artist_mbid": _ARTIST, "name": "Four Tet", "tags": ["Four Tet", "microhouse"]}]
        )
        self.assertEqual([item["value"] for item in rows[0]["features"]], ["microhouse"])
        self.assertIn("exact_artist_name_tag", {item["reason"] for item in rejected})


if __name__ == "__main__":
    unittest.main()
