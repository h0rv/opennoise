from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from musix.public_artist_membership_historical import (
    evaluate_public_artist_membership_historical,
)

_PUBLIC_DATABASE = Path(
    "/home/h0rv/projects/musix/.cache/public-release-custody-integrated/objects/cache/sha256/"
    "282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866.sqlite"
)
_HISTORICAL_DATABASE = Path(
    "/home/h0rv/projects/musix/.cache/historical-custody-vault/historical-h3/membership/sha256/"
    "098dc8780b3f4a8daf1240d36bec7eb7be563dc2275d998dbc7509c3fb1859df.sqlite"
)


class PublicArtistMembershipHistoricalTests(unittest.TestCase):
    def test_real_evaluation_is_positive_only_and_hash_bound(self) -> None:
        candidate = Path(".cache/public-artist-membership-real-input/candidate.json")
        approved = Path(".cache/public-artist-membership-real-input/approved-input.json")
        if not all(
            path.exists() for path in (_PUBLIC_DATABASE, _HISTORICAL_DATABASE, candidate, approved)
        ):
            self.skipTest("real custody artifacts are not present")
        report = evaluate_public_artist_membership_historical(
            candidate, approved, _PUBLIC_DATABASE, _HISTORICAL_DATABASE
        )
        self.assertFalse(report.absence_is_negative)
        self.assertFalse(report.independent_public_gold)
        self.assertEqual(report.historical_source_membership_count, 306136)
        self.assertEqual(report.historical_source_genre_count, 6289)
        self.assertEqual(report.matched_genre_count, 292)

    def test_candidate_input_hash_tampering_is_rejected(self) -> None:
        candidate = Path(".cache/public-artist-membership-real-input/candidate.json")
        approved = Path(".cache/public-artist-membership-real-input/approved-input.json")
        if not all(
            path.exists() for path in (_PUBLIC_DATABASE, _HISTORICAL_DATABASE, candidate, approved)
        ):
            self.skipTest("real custody artifacts are not present")
        with tempfile.TemporaryDirectory() as directory:
            tampered = Path(directory) / "candidate.json"
            document = json.loads(candidate.read_text(encoding="utf-8"))
            document["input_sha256"] = "0" * 64
            tampered.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(ValueError):
                evaluate_public_artist_membership_historical(
                    tampered, approved, _PUBLIC_DATABASE, _HISTORICAL_DATABASE
                )


if __name__ == "__main__":
    unittest.main()
