from __future__ import annotations

import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from opennoise.checkpoints.public_direct_bridge_candidate import (
    CandidateInputs,
    build_public_direct_bridge_candidate,
)
from opennoise.checkpoints.public_direct_production_bridge import (
    _CANDIDATE_SHA256,
    _PRIMARY_SELECTION_SHA256,
    PublicDirectProductionBridgeError,
    _index_observations,
    _require_pinned_candidate,
    build_public_direct_production_bridge,
    production_bridge_sha256,
)
from tests._pinned_v1_discovery import pinned_v1_discovery_path

_INPUTS = CandidateInputs(
    public_database=Path("data/public.sqlite"),
    static_discovery=pinned_v1_discovery_path(),
    reconciliation=Path(".cache/seed-reconciliation/v3/seed-reconciliation.json"),
    canonical_layout=Path(".cache/semantic-map-layout-v3/artifact.json"),
)


class PublicDirectProductionBridgeTests(unittest.TestCase):
    def test_real_pinned_bridge_is_factual_and_hash_replayable(self) -> None:
        receipt = build_public_direct_production_bridge(_INPUTS)

        self.assertEqual(receipt.coverage.positioned_genre_count, 84)
        self.assertEqual(receipt.coverage.grouped_membership_count, 862)
        self.assertEqual(receipt.coverage.direct_observation_count, 959)
        self.assertEqual(receipt.coverage.artist_count, 536)
        self.assertEqual(receipt.coverage.net_new_artist_count, 118)
        self.assertEqual(receipt.output_sha256, production_bridge_sha256(receipt))
        self.assertTrue(all(item.evidence for item in receipt.memberships))
        self.assertEqual(receipt.public_direct_candidate_sha256, _CANDIDATE_SHA256)
        self.assertEqual(receipt.primary_selection_sha256, _PRIMARY_SELECTION_SHA256)
        self.assertEqual(
            Counter(item.reconciliation_disposition for item in receipt.memberships),
            Counter({"reconciled": 638, "public_only": 224}),
        )
        self.assertTrue(
            all(item.binding == "one_to_one_qid_position_binding" for item in receipt.memberships)
        )
        self.assertTrue(
            all(
                item.artist_musicbrainz_url.endswith(item.artist_musicbrainz_id)
                for item in receipt.memberships
            )
        )
        self.assertTrue(
            all(
                item.artist_wikidata_url.endswith(item.artist_wikidata_id)
                for item in receipt.memberships
            )
        )

    def test_same_count_candidate_row_drift_fails_closed_against_selection_pin(self) -> None:
        candidate = build_public_direct_bridge_candidate(_INPUTS)
        changed = candidate.rows[0].model_copy(update={"source_key": "tampered"})
        tampered = candidate.model_copy(update={"rows": (changed, *candidate.rows[1:])})

        with (
            patch(
                "opennoise.checkpoints.public_direct_production_bridge.build_public_direct_bridge_candidate",
                return_value=tampered,
            ),
            self.assertRaisesRegex(PublicDirectProductionBridgeError, "candidate selection"),
        ):
            build_public_direct_production_bridge(_INPUTS)

    def test_primary_selection_pin_is_checked_separately(self) -> None:
        candidate = build_public_direct_bridge_candidate(_INPUTS).model_copy(
            update={"primary_selection_sha256": "0" * 64}
        )

        with (
            patch(
                "opennoise.checkpoints.public_direct_production_bridge.candidate_sha256",
                return_value=_CANDIDATE_SHA256,
            ),
            self.assertRaisesRegex(PublicDirectProductionBridgeError, "primary selection"),
        ):
            _require_pinned_candidate(candidate)

    def test_tampered_base_static_hash_fails_closed(self) -> None:
        candidate = build_public_direct_bridge_candidate(_INPUTS).model_copy(
            update={"static_discovery_sha256": "0" * 64}
        )

        with (
            patch(
                "opennoise.checkpoints.public_direct_production_bridge.build_public_direct_bridge_candidate",
                return_value=candidate,
            ),
            patch(
                "opennoise.checkpoints.public_direct_production_bridge.candidate_sha256",
                return_value=_CANDIDATE_SHA256,
            ),
            self.assertRaisesRegex(PublicDirectProductionBridgeError, "additive base pin"),
        ):
            build_public_direct_production_bridge(_INPUTS)

    def test_duplicate_authorized_result_rows_fail_before_evidence_indexing(self) -> None:
        with self.assertRaisesRegex(PublicDirectProductionBridgeError, "duplicate or missing"):
            _index_observations(({}, {}), (1,))

    def test_contract_never_loads_a_review_json_or_writes_an_asset(self) -> None:
        source = Path("src/opennoise/checkpoints/public_direct_production_bridge.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("build_public_direct_bridge_candidate", source)
        self.assertIn("mode=ro&immutable=1", source)
        self.assertNotIn("write_atomic_bytes", source)
        self.assertNotIn("public-direct-bridge-candidate.json", source)


if __name__ == "__main__":
    unittest.main()
