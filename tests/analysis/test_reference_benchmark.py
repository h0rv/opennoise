"""Independent reference coverage cannot manufacture parity from missing evidence."""

import unittest

from opennoise.analysis.reference_benchmark import (
    MAX_PAGE_BYTES,
    evaluate_reference_contract,
    parse_archived_artist_page,
)


class ReferenceBenchmarkTests(unittest.TestCase):
    def test_archive_strips_media_and_extracts_only_identified_direct_names(self) -> None:
        raw = (
            b"<div class='genre scanme' "
            b"onclick=\"window.open('spotify:artist:1234567890123456789012')\" "
            b"preview_url='secret'>Artist &amp; Name<a>extra</a></div>"
            b"<div class='scanme'>Unknown</div>"
        )
        result = parse_archived_artist_page(raw, genre_name="pop")
        self.assertEqual(
            result["members"],
            [{"source_artist_id": "1234567890123456789012", "artist_name": "Artist & Name"}],
        )
        self.assertNotIn("secret", str(result))
        self.assertEqual(
            result["membership_completeness"], "unverified_bounded_positive_observations"
        )

    def test_archive_rejects_duplicate_ids_and_oversized_page(self) -> None:
        raw = (
            b"""<div class="scanme" onclick="go('spotify:artist:1234567890123456789012')">A</div>"""
        )
        with self.assertRaises(ValueError):
            parse_archived_artist_page(raw + raw, genre_name="pop")
        with self.assertRaises(ValueError):
            parse_archived_artist_page(b"x" * (MAX_PAGE_BYTES + 1), genre_name="pop")

    def test_unknown_membership_stays_unknown_and_missing_neighbors_are_failures(self) -> None:
        reference = {
            "role": "evaluation_only_no_construction_or_training",
            "source_sha256": "a" * 64,
            "genres": ["Pop", "Rock"],
            "representatives": [{"genre_name": "Pop", "artist_name": "A"}],
            "memberships": [],
            "geometry_neighbors": {"Pop": ["Rock"], "Rock": ["Pop"]},
        }
        candidate = {
            "genres": ["pop"],
            "representatives": [{"genre_name": "pop", "artist_name": "a"}],
            "geometry_neighbors": {"pop": ["rock"]},
        }
        report = evaluate_reference_contract(reference, candidate)
        self.assertEqual(report["genre_coverage"]["recall"], 0.5)
        self.assertIsNone(report["membership_positive_recovery"]["recall"])
        self.assertEqual(report["representative_artist_recovery"]["recall"], 1.0)
        self.assertEqual(report["display_neighbor_recovery"]["recall"], 0.5)
        self.assertFalse(report["overall_parity"])
        self.assertIsNone(report["overall_percentage"])

    def test_invalid_projection_rejected(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_reference_contract({"genres": "pop"}, {"genres": []})
        reference = {
            "genres": ["pop"],
            "source_sha256": "a" * 64,
            "role": "evaluation_only_no_construction_or_training",
        }
        with self.assertRaises(ValueError):
            evaluate_reference_contract(reference, {"genres": [], "memberships": [{}]})
