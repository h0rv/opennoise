from __future__ import annotations

import unittest
from pathlib import Path

from opennoise.checkpoints.public_direct_bridge_candidate import CandidateInputs, DirectBridgeRow
from opennoise.checkpoints.public_direct_static_discovery_candidate import (
    PublicDirectStaticDiscoveryCandidateError,
    _genres,
    _memberships,
    _parse_p136_method,
    _ReviewObservation,
    build_public_direct_static_discovery_review_candidate,
)


def _bridge_row(
    *, evidence_id: int, artist_id: str = "12345678-1234-1234-1234-123456789abc"
) -> DirectBridgeRow:
    return DirectBridgeRow(
        catalog_genre_id=7,
        source_genre_ref="wikidata:genre:Q7",
        seed_id="item9",
        reconciliation_disposition="reconciled",
        artist_musicbrainz_id=artist_id,
        artist_catalog_id=5,
        evidence_id=evidence_id,
        source_key="wikidata",
        source_record_id="Q42",
        authorization_status="display_and_export_authorized",
        identifier_status="one_authorized_musicbrainz_artist_id",
    )


def _observation(*, evidence_id: int, source_key: str = "wikidata") -> _ReviewObservation:
    return _ReviewObservation(
        evidence_id=evidence_id,
        artist_catalog_id=5,
        catalog_genre_id=7,
        catalog_genre_name="Example genre",
        artist_name="Example artist",
        source_key=source_key,
        source_record_id="Q42",
        method_key="wikidata_p136",
        method_version="1",
        provenance_id=3,
    )


class PublicDirectStaticDiscoveryCandidateTests(unittest.TestCase):
    def test_memberships_retain_every_exact_source_claim(self) -> None:
        rows = (_bridge_row(evidence_id=11), _bridge_row(evidence_id=12))
        memberships = _memberships(
            rows, {11: _observation(evidence_id=11), 12: _observation(evidence_id=12)}
        )

        self.assertEqual(len(memberships), 1)
        membership = memberships[0]
        self.assertEqual(membership.binding, "one_to_one_reconciled_wikidata_genre")
        self.assertEqual(membership.node_id, "item9")
        self.assertEqual([item.evidence_id for item in membership.evidence], [11, 12])
        self.assertEqual([item.provenance_id for item in membership.evidence], [3, 3])
        self.assertEqual(_genres(memberships)[0].artist_ids, (membership.artist_id,))

    def test_memberships_reject_source_claim_drift(self) -> None:
        with self.assertRaisesRegex(
            PublicDirectStaticDiscoveryCandidateError, "does not match pinned bridge claim"
        ):
            _memberships(
                (_bridge_row(evidence_id=11),),
                {11: _observation(evidence_id=11, source_key="other")},
            )

    def test_review_observation_rejects_method_substitution(self) -> None:
        with self.assertRaisesRegex(
            PublicDirectStaticDiscoveryCandidateError, "not an exact Wikidata P136 claim"
        ):
            _parse_p136_method("other_method", "1")

    def test_memberships_reject_grouped_presentation_identity_drift(self) -> None:
        rows = (
            _bridge_row(evidence_id=11),
            _bridge_row(evidence_id=12).model_copy(update={"seed_id": "item10"}),
        )
        with self.assertRaisesRegex(
            PublicDirectStaticDiscoveryCandidateError, "share one presentation identity"
        ):
            _memberships(
                rows,
                {11: _observation(evidence_id=11), 12: _observation(evidence_id=12)},
            )

    def test_genres_reject_grouped_artist_mapping_drift(self) -> None:
        membership = _memberships(
            (_bridge_row(evidence_id=11),), {11: _observation(evidence_id=11)}
        )[0]
        mismatched_artist_membership = membership.model_copy(
            update={
                "artist_id": "abcdefab-cdef-cdef-cdef-abcdefabcdef",
                "node_id": "item10",
            }
        )
        with self.assertRaisesRegex(
            PublicDirectStaticDiscoveryCandidateError, "share one presentation identity"
        ):
            _genres((membership, mismatched_artist_membership))

    def test_review_candidate_has_no_static_output_writer(self) -> None:
        source = Path(
            "src/opennoise/checkpoints/public_direct_static_discovery_candidate.py"
        ).read_text()
        script = Path(
            "scripts/build_public_direct_static_discovery_review_candidate.py"
        ).read_text()
        self.assertIn("static_output_written: Literal[False] = False", source)
        self.assertIn("existing_static_discovery_modified: Literal[False] = False", source)
        self.assertNotIn("write_atomic_bytes", source)
        self.assertNotIn("--output", script)

    @unittest.skipUnless(
        Path(".cache/seed-reconciliation/v3/seed-reconciliation.json").exists(),
        "optional local reconciliation cache absent",
    )
    def test_real_pinned_projection_preserves_source_observation_count(self) -> None:
        candidate = build_public_direct_static_discovery_review_candidate(
            CandidateInputs(
                public_database=Path("data/public.sqlite"),
                static_discovery=Path(
                    "dist/assets/static-discovery.b4ff2b1bcebb0bb6b1fd63b78caf9a416dbf5bb0c3050c0fa05e434fd0c700e8.json"
                ),
                reconciliation=Path(".cache/seed-reconciliation/v3/seed-reconciliation.json"),
                canonical_layout=Path(".cache/semantic-map-layout-v3/artifact.json"),
            )
        )
        self.assertEqual(candidate.coverage.positioned_genre_count, 84)
        self.assertEqual(candidate.coverage.membership_count, 862)
        self.assertEqual(candidate.coverage.direct_observation_count, 959)
        self.assertEqual(candidate.coverage.artist_count, 536)
        self.assertEqual(candidate.coverage.net_new_artist_count, 118)
        self.assertTrue(all(membership.evidence for membership in candidate.memberships))
