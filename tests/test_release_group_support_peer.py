from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np
from scipy.sparse import csr_matrix

from musix.release_group_support_h3_evaluation import SupportPeerH3Report, evaluate_support_peer_h3
from musix.release_group_support_peer import (
    SupportPeerArtifact,
    SupportPeerEdge,
    _edges,
    artifact_neighbors,
    logical_sha,
)


class ReleaseGroupSupportPeerTests(unittest.TestCase):
    def test_edges_are_canonical_symmetric_and_use_stable_ties(self) -> None:
        edges, support_genres = _edges(
            csr_matrix(np.array([[1, 1, 1], [1, 0, 0], [0, 1, 0]], dtype=np.int64)),
            ("g1", "g2", "g3"),
        )
        self.assertEqual(support_genres, 3)
        self.assertEqual(
            [(edge.source_genre_id, edge.target_genre_id) for edge in edges],
            [("g1", "g2"), ("g1", "g3")],
        )
        self.assertTrue(all(edge.source_genre_id < edge.target_genre_id for edge in edges))
        self.assertTrue(all(edge.source_genre_id != edge.target_genre_id for edge in edges))

    def test_int64_overlap_does_not_wrap(self) -> None:
        edges, _ = _edges(csr_matrix(np.ones((2, 300), dtype=np.int64)), ("g1", "g2"))
        self.assertEqual(edges[0].shared_supported_artist_count, 300)

    def test_adapter_returns_deterministic_directed_neighborhoods(self) -> None:
        self.assertEqual(
            artifact_neighbors(_artifact(), genre_ids={"g1", "g2", "g3"}, k=25),
            {"g1": ("g2",), "g2": ("g1",)},
        )

    def test_evaluator_fails_closed_on_tampered_logical_hash(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "candidate.json"
            path.write_text(
                _artifact().model_copy(update={"output_sha256": "f" * 64}).model_dump_json()
            )
            with self.assertRaisesRegex(ValueError, "logical hash"):
                _evaluate(path)

    def test_evaluator_replay_is_deterministic_with_fixed_adapter_inputs(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "candidate.json"
            path.write_text(_artifact().model_dump_json())
            report = _evaluate(path, patched=True)
            replay = _evaluate(path, patched=True)
        self.assertEqual(report.metrics.micro_recall_at_25, 1.0)
        self.assertEqual(report.metrics.precision_at_25, None)
        self.assertEqual(report.model_dump(mode="json"), replay.model_dump(mode="json"))


def _artifact() -> SupportPeerArtifact:
    edge = SupportPeerEdge(
        source_genre_id="g1",
        target_genre_id="g2",
        score=1.0,
        component_kind="release_group_artist_overlap",
        shared_supported_artist_count=1,
        support_binary_jaccard_score=1.0,
    )
    preliminary = SupportPeerArtifact(
        database_sha256="a" * 64,
        reconciliation_sha256="b" * 64,
        membership_table="release_group_support",
        component_kind="release_group_artist_overlap",
        seed_count=2,
        support_membership_count=2,
        support_genre_count=2,
        empty_input_seed_count=0,
        seeds_without_qualifying_neighbors_count=0,
        artist_count=1,
        pair_visit_upper_bound=1,
        candidates=(edge,),
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(
        update={
            "output_sha256": logical_sha(
                preliminary.model_dump(mode="json", exclude={"output_sha256"})
            )
        }
    )


def _evaluate(path: Path, *, patched: bool = False) -> SupportPeerH3Report:
    reconciliation = path.parent / "reconciliation.json"
    public_input = path.parent / "public.json"
    reconciliation.write_text("{}")
    public_input.write_text("{}")
    if not patched:
        with patch("musix.release_group_support_h3_evaluation.file_sha", return_value="b" * 64):
            return evaluate_support_peer_h3(
                candidate_path=path,
                reconciliation_path=reconciliation,
                public_input_path=public_input,
                bridge_path=Path("b"),
                bridge_receipt_path=Path("br"),
                bridge_receipt_sha256="a" * 64,
                historical_database_path=Path("h"),
            )
    bridge = type(
        "Bridge",
        (),
        {
            "header": type(
                "Header", (), {"output_sha256": "c" * 64, "historical_database_sha256": "b" * 64}
            )(),
            "conflicts": (),
            "close": lambda self: None,  # noqa: ARG005
        },
    )()
    counters = {
        "h3_observation_count": 2,
        "h3_mapped_positive_count": 2,
        "h3_unmapped_genre_observation_count": 0,
        "h3_unbridged_artist_observation_count": 0,
        "h3_conflicted_artist_observation_count": 0,
    }
    with (
        patch("musix.release_group_support_h3_evaluation.file_sha", return_value="b" * 64),
        patch("musix.release_group_support_h3_evaluation.PublicModelInput") as public,
        patch(
            "musix.release_group_support_h3_evaluation.load_receipted_musicbrainz_spotify_bridge",
            return_value=bridge,
        ),
        patch(
            "musix.release_group_support_h3_evaluation.iter_accepted_spotify_to_musicbrainz",
            return_value=iter(()),
        ),
        patch(
            "musix.release_group_support_h3_evaluation._load_positives",
            return_value=({"g1": {"a"}, "g2": {"a"}}, counters),
        ),
    ):
        public.model_validate_json.return_value.genres = []
        return evaluate_support_peer_h3(
            candidate_path=path,
            reconciliation_path=reconciliation,
            public_input_path=public_input,
            bridge_path=Path("b"),
            bridge_receipt_path=Path("br"),
            bridge_receipt_sha256="a" * 64,
            historical_database_path=Path("h"),
        )
