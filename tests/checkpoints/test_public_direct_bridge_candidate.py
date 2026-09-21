from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

from opennoise.checkpoints.public_direct_bridge_candidate import (
    CandidateInputs,
    PublicDirectBridgeCandidateError,
    _LegacyDisposition,
    _LegacyPublicIdentity,
    _LegacyReconciliation,
    _safe_positioned_links,
    build_public_direct_bridge_candidate,
)

if TYPE_CHECKING:
    from opennoise.ml.semantic_layout.contracts import SemanticLayoutArtifact


class PublicDirectBridgeCandidateTests(unittest.TestCase):
    def test_pinned_input_tamper_fails_before_report_construction(self) -> None:
        with self.assertRaisesRegex(PublicDirectBridgeCandidateError, "public database"):
            build_public_direct_bridge_candidate(
                CandidateInputs(
                    public_database=Path(__file__),
                    static_discovery=Path(__file__),
                    reconciliation=Path(__file__),
                    canonical_layout=Path(__file__),
                )
            )

    def test_reconciliation_requires_one_qid_and_positioned_seed(self) -> None:
        reconciliation = _LegacyReconciliation(
            seed_count=4,
            output_sha256="a" * 64,
            dispositions=(
                _LegacyDisposition(
                    source_item_id="item1",
                    disposition="reconciled",
                    public_identities=(
                        _LegacyPublicIdentity(
                            namespace="wikidata_genre_qid", identifier="wikidata:genre:Q1"
                        ),
                    ),
                ),
                _LegacyDisposition(
                    source_item_id="item2",
                    disposition="reconciled",
                    public_identities=(
                        _LegacyPublicIdentity(
                            namespace="wikidata_genre_qid", identifier="wikidata:genre:Q2"
                        ),
                        _LegacyPublicIdentity(
                            namespace="wikidata_genre_qid", identifier="wikidata:genre:Q3"
                        ),
                    ),
                ),
                _LegacyDisposition(
                    source_item_id="item3",
                    disposition="public_only",
                    public_identities=(
                        _LegacyPublicIdentity(
                            namespace="wikidata_genre_qid", identifier="wikidata:genre:Q3"
                        ),
                    ),
                ),
                _LegacyDisposition(
                    source_item_id="item4",
                    disposition="reconciled",
                    public_identities=(
                        _LegacyPublicIdentity(
                            namespace="wikidata_genre_qid", identifier="wikidata:genre:Q4"
                        ),
                    ),
                ),
            ),
        )
        layout = cast(
            "SemanticLayoutArtifact",
            SimpleNamespace(
                coordinates=(SimpleNamespace(seed_id="item1"), SimpleNamespace(seed_id="item2"))
            ),
        )
        with patch(
            "opennoise.checkpoints.public_direct_bridge_candidate._resolved_genre_ids",
            return_value={
                "wikidata:genre:Q1": 10,
                "wikidata:genre:Q2": 20,
                "wikidata:genre:Q3": 30,
                "wikidata:genre:Q4": 40,
            },
        ):
            links, resolved, positioned = _safe_positioned_links(
                Path("unused.sqlite"), reconciliation, layout
            )
        self.assertEqual(links, {10: ("wikidata:genre:Q1", "item1", "reconciled")})
        self.assertEqual(resolved, 3)
        self.assertEqual(positioned, 1)

    def test_multiple_positioned_seeds_for_one_db_genre_are_excluded(self) -> None:
        def disposition(seed: str) -> _LegacyDisposition:
            return _LegacyDisposition(
                source_item_id=seed,
                disposition="reconciled",
                public_identities=(
                    _LegacyPublicIdentity(
                        namespace="wikidata_genre_qid", identifier="wikidata:genre:Q1"
                    ),
                ),
            )

        reconciliation = _LegacyReconciliation(
            seed_count=2,
            output_sha256="a" * 64,
            dispositions=(disposition("item1"), disposition("item2")),
        )
        layout = cast(
            "SemanticLayoutArtifact",
            SimpleNamespace(
                coordinates=(SimpleNamespace(seed_id="item1"), SimpleNamespace(seed_id="item2"))
            ),
        )
        with patch(
            "opennoise.checkpoints.public_direct_bridge_candidate._resolved_genre_ids",
            return_value={"wikidata:genre:Q1": 10},
        ):
            links, resolved, positioned = _safe_positioned_links(
                Path("unused.sqlite"), reconciliation, layout
            )
        self.assertEqual(links, {})
        self.assertEqual((resolved, positioned), (2, 2))

    def test_builder_has_no_historical_input_or_output_writer(self) -> None:
        source = Path("src/opennoise/checkpoints/public_direct_bridge_candidate.py").read_text()
        script = Path("scripts/build_public_direct_bridge_candidate.py").read_text()
        self.assertIn("historical_inputs_used: Literal[False] = False", source)
        self.assertNotIn("write_atomic_bytes", source)
        self.assertNotIn("--output", script)

    def test_direct_rows_require_both_permissions_and_one_exact_mbid(self) -> None:
        source = Path("src/opennoise/checkpoints/public_direct_bridge_candidate.py").read_text()
        self.assertIn("type.type_key = 'musicbrainz_artist_id'", source)
        self.assertIn("identifier.namespace = 'musicbrainz'", source)
        self.assertIn("HAVING count(DISTINCT identifier.normalized_value) = 1", source)
        self.assertIn("export_permission.use_kind = 'export'", source)
        self.assertIn("display_permission.use_kind = 'display'", source)
        self.assertIn("evidence.method_key = 'wikidata_p136'", source)
        self.assertIn("evidence.method_version = '1'", source)

    @unittest.skipUnless(
        Path(".cache/seed-reconciliation/v3/seed-reconciliation.json").exists(),
        "optional local reconciliation cache absent",
    )
    def test_real_pinned_input_smoke(self) -> None:
        candidate = build_public_direct_bridge_candidate(
            CandidateInputs(
                public_database=Path("data/public.sqlite"),
                static_discovery=Path(
                    "dist/assets/static-discovery.b4ff2b1bcebb0bb6b1fd63b78caf9a416dbf5bb0c3050c0fa05e434fd0c700e8.json"
                ),
                reconciliation=Path(".cache/seed-reconciliation/v3/seed-reconciliation.json"),
                canonical_layout=Path(".cache/semantic-map-layout-v3/artifact.json"),
            )
        )
        self.assertEqual(candidate.coverage.new_direct_catalog_genre_count, 84)
        self.assertEqual(candidate.coverage.exact_direct_pair_count, 959)
