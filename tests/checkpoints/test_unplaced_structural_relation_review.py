"""Tests for the local unplaced structural-relation review packet."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opennoise.analysis.musicbrainz_unplaced_colisten_edges import (
    CoListenReviewProposal,
    MusicBrainzUnplacedCoListenReport,
)
from opennoise.checkpoints import unplaced_structural_relation_review
from opennoise.checkpoints.unplaced_structural_relation_review import (
    ReviewInputPin,
    StructuralRelationReviewRow,
    UnplacedStructuralRelationReviewCoverage,
    UnplacedStructuralRelationReviewError,
    UnplacedStructuralRelationReviewPacket,
    _colisten_rows,
    _hierarchy_rows,
    _LayoutRow,
    _require_pinned_inputs,
    write_unplaced_structural_relation_review_packet,
)
from opennoise.taxonomy.structure.hierarchy_candidates import (
    GenreHierarchyCandidate,
    GenreHierarchyCandidateArtifact,
    HierarchyComponent,
    HierarchyScoreComponents,
)


def _candidate() -> GenreHierarchyCandidate:
    component = HierarchyComponent(raw_value=0.0, normalized_value=0.0, evidence_refs=("fixture",))
    return GenreHierarchyCandidate(
        child_genre_id="unplaced",
        parent_genre_id="placed",
        status="review",
        reason="lexical_review_prior",
        score=0.1,
        components=HierarchyScoreComponents(
            factual_public_taxonomy=component,
            lexical_head_review_prior=component,
            artist_set_containment=component,
            support_distinctness=component,
            child_artist_count=0,
            parent_artist_count=0,
            shared_artist_count=0,
            child_coverage=0.0,
            parent_coverage=0.0,
            directionality_gap=0.0,
        ),
        evidence_refs=("hierarchy:fixture",),
    )


class UnplacedStructuralRelationReviewTests(unittest.TestCase):
    """Keep review signals separate from factual placement evidence."""

    def test_hierarchy_rows_preserve_review_status_and_layout_state(self) -> None:
        rows = _hierarchy_rows(
            GenreHierarchyCandidateArtifact.model_construct(candidates=(_candidate(),)),
            placed={"placed": _LayoutRow(seed_id="placed", name="Placed")},
            unplaced={"unplaced": _LayoutRow(seed_id="unplaced", name="Unplaced")},
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].category, "hierarchy_review_candidate")
        self.assertFalse(rows[0].factual_structural_evidence)
        self.assertEqual(rows[0].placement_abstention, "no_supported_structural_relation")

    def test_colisten_rows_require_an_unplaced_to_placed_pair(self) -> None:
        proposal = CoListenReviewProposal(
            unplaced_seed_id="unplaced",
            placed_seed_id="placed",
            distinct_exact_artist_pair_support_count=2,
            summed_pair_user_support=10,
            score=1.0,
        )
        report = MusicBrainzUnplacedCoListenReport.model_construct(
            output_sha256="a" * 64,
            source_tag_artifact_sha256="b" * 64,
            lastfm_artifact_sha256="c" * 64,
            proposals=(proposal,),
        )
        rows = _colisten_rows(
            report,
            placed={"placed": _LayoutRow(seed_id="placed", name="Placed")},
            unplaced={"unplaced": _LayoutRow(seed_id="unplaced", name="Unplaced")},
        )
        self.assertEqual(rows[0].category, "colisten_context_only")
        self.assertIn("not_factual", rows[0].reason)
        with self.assertRaisesRegex(UnplacedStructuralRelationReviewError, "unplaced-to-placed"):
            _colisten_rows(
                report,
                placed={},
                unplaced={"unplaced": _LayoutRow(seed_id="unplaced", name="Unplaced")},
            )

    def test_writer_rejects_existing_or_non_cache_output(self) -> None:
        row = StructuralRelationReviewRow(
            category="hierarchy_review_candidate",
            reason="fixture",
            child_seed_id="unplaced",
            child_name="Unplaced",
            parent_seed_id="placed",
            parent_name="Placed",
            parent_state="placed",
            source_refs=("fixture",),
        )
        packet = UnplacedStructuralRelationReviewPacket.model_construct(
            hierarchy_input=ReviewInputPin(file_sha256="a" * 64, logical_sha256="a" * 64),
            colisten_input=ReviewInputPin(file_sha256="b" * 64, logical_sha256="b" * 64),
            layout_input=ReviewInputPin(file_sha256="c" * 64, logical_sha256="c" * 64),
            coverage=UnplacedStructuralRelationReviewCoverage(
                layout_unplaced_seed_count=1,
                hierarchy_review_seed_count=1,
                hierarchy_review_row_count=1,
                colisten_review_seed_count=0,
                colisten_review_row_count=0,
                total_row_count=1,
            ),
            rows=(row,),
            output_sha256="d" * 64,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / ".cache"
            cache.mkdir()
            output = cache / "packet.json"
            with patch.object(unplaced_structural_relation_review, "_PROJECT_CACHE_ROOT", cache):
                output.write_text("exists", encoding="utf-8")
                with self.assertRaisesRegex(
                    UnplacedStructuralRelationReviewError, "already exists"
                ):
                    write_unplaced_structural_relation_review_packet(output, packet)
                external = root / "external"
                external.mkdir()
                (cache / "escaped").symlink_to(external, target_is_directory=True)
                with self.assertRaisesRegex(
                    UnplacedStructuralRelationReviewError, "below the project"
                ):
                    write_unplaced_structural_relation_review_packet(
                        cache / "escaped" / "packet.json", packet
                    )

    def test_input_gate_rejects_replaced_bytes(self) -> None:
        with self.assertRaisesRegex(UnplacedStructuralRelationReviewError, "retained pins"):
            _require_pinned_inputs(
                hierarchy_input=(b"replacement", "a" * 64),
                colisten_input=(b"replacement", "b" * 64),
                layout_input=(b"replacement", "c" * 64),
                colisten_layout_sha256="d" * 64,
            )
