from __future__ import annotations

import unittest
from pathlib import Path

from musix.public_artist_membership_adapter import (
    CertifiedPublicDirectSelector,
    CertifiedPublicMembershipAdapterPolicy,
    adapt_certified_public_membership_input,
)


class PublicArtistMembershipAdapterTests(unittest.TestCase):
    def test_direct_source_union_is_explicitly_paired(self) -> None:
        policy = CertifiedPublicMembershipAdapterPolicy(
            direct_selectors=(
                CertifiedPublicDirectSelector(
                    source="wikidata",
                    facet="wikidata_p136",
                    source_key_prefix="wikidata_phase3_artists_",
                    method_key="wikidata_p136",
                    required_license="CC0-1.0",
                ),
                CertifiedPublicDirectSelector(
                    source="musicbrainz",
                    facet="musicbrainz_tag",
                    source_key_prefix="musicbrainz_",
                    method_key="musicbrainz_artist_tag",
                    required_license="CC-BY-SA-3.0",
                ),
            )
        )
        self.assertEqual(policy.effective_direct_sources, ("wikidata", "musicbrainz"))

        with self.assertRaisesRegex(ValueError, "at least one"):
            CertifiedPublicMembershipAdapterPolicy(
                direct_selectors=(),
            )

    def test_certified_release_counts_and_provenance_bindings(self) -> None:
        database = Path(
            "/home/h0rv/projects/musix/.cache/public-release-custody-integrated/objects/"
            "cache/sha256/282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866.sqlite"
        )
        if not database.exists():
            self.skipTest("certified public release is not present")
        adaptation = adapt_certified_public_membership_input(
            database,
            CertifiedPublicMembershipAdapterPolicy(include_aggregate_candidates=True),
        )
        self.assertEqual(adaptation.receipt.direct_row_count, 4948)
        self.assertEqual(adaptation.receipt.aggregate_pair_count, 13175)
        self.assertEqual(adaptation.receipt.aggregate_emitted_pairs, 30903)
        self.assertEqual(len(adaptation.receipt.direct_source_bindings), 8)
        self.assertTrue(
            all(
                item.policy_key.startswith("manifest:wikidata_phase3_artists_")
                for item in adaptation.receipt.direct_source_bindings
            )
        )
        self.assertEqual(
            adaptation.approved_input.input_file_sha256, adaptation.receipt.database_file_sha256
        )


if __name__ == "__main__":
    unittest.main()
