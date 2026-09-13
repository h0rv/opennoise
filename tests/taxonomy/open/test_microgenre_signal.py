from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from musix.taxonomy.open.microgenre_signal import (
    MicrogenreSignalSettings,
    OpenEvidenceRef,
    SourceNeutralMicrogenreInput,
    build_microgenre_signal_checkpoint,
    load_source_neutral_microgenre_input,
    source_neutral_input_sha256,
    verify_microgenre_signal_checkpoint,
)

_ROOT = Path(__file__).resolve().parents[3]
_FIXTURE = _ROOT / "tests/fixtures/microgenre_signal_diverse.json"


class MicrogenreSignalCheckpointTests(unittest.TestCase):
    def test_diverse_fixture_has_all_signal_views_and_replays(self) -> None:
        graph = load_source_neutral_microgenre_input(_FIXTURE)
        self.assertEqual(len(graph.nodes), 19)
        self.assertTrue(any(node.node_id == "genre:idm" for node in graph.nodes))
        self.assertTrue(any(edge.source_id == "genre:post-punk" for edge in graph.edges))
        self.assertTrue(any(edge.source_id == "genre:afrobeat" for edge in graph.edges))
        self.assertEqual(
            sum(
                edge.relation == "hierarchy" and edge.target_id == "genre:post-punk"
                for edge in graph.edges
            ),
            2,
        )
        artifact = build_microgenre_signal_checkpoint(
            graph,
            MicrogenreSignalSettings(
                split_seed=29,
                heldout_fraction=0.4,
                score_threshold=0.2,
                evaluation_k=3,
                max_generated_candidates_per_relation=0,
            ),
        )
        verify_microgenre_signal_checkpoint(artifact)
        self.assertEqual(artifact.coverage.open_edge_count, len(graph.edges))
        self.assertEqual(artifact.coverage.immutable_legacy_name_count, 3)
        self.assertFalse(artifact.coverage.historical_memberships_read)
        self.assertEqual(
            {metric.relation for metric in artifact.relation_metrics},
            {"membership", "similarity", "hierarchy", "lineage"},
        )
        metrics = {metric.relation: metric for metric in artifact.relation_metrics}
        self.assertTrue(all(metric.heldout_open_edge_count for metric in metrics.values()))
        self.assertEqual(metrics["membership"].heldout_open_edge_count, 3)
        self.assertEqual(metrics["membership"].scoreable_heldout_edge_count, 1)
        self.assertEqual(metrics["similarity"].scoreable_heldout_edge_count, 0)
        self.assertEqual(metrics["membership"].heldout_recall, 1 / 3)
        self.assertIsNotNone(metrics["membership"].heldout_positive_hit_rate_at_k)
        self.assertIsNotNone(metrics["membership"].heldout_recall_at_k)
        self.assertIn(
            ("membership", "genre:post-punk", "artist:joy-division"),
            {(row.relation, row.source_id, row.target_id) for row in artifact.predictions},
        )
        self.assertTrue(
            any(
                row.relation == "similarity" and row.reason == "no_train_signal"
                for row in artifact.abstentions
            )
        )

    def test_abstentions_and_overlap_are_explicit(self) -> None:
        graph = load_source_neutral_microgenre_input(_FIXTURE)
        artifact = build_microgenre_signal_checkpoint(
            graph,
            MicrogenreSignalSettings(
                split_seed=29,
                heldout_fraction=0.4,
                score_threshold=1.0,
                evaluation_k=2,
                max_generated_candidates_per_relation=3,
            ),
        )
        self.assertGreater(artifact.coverage.abstained_candidate_count, 0)
        self.assertEqual(
            artifact.coverage.candidate_pair_count,
            artifact.coverage.emitted_candidate_count + artifact.coverage.abstained_candidate_count,
        )
        self.assertTrue(any(row.reason == "no_train_signal" for row in artifact.abstentions))

    def test_historical_source_is_rejected_and_tampering_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "historical"):
            OpenEvidenceRef(source_id="every_noise_snapshot", record_id="forbidden")
        graph = load_source_neutral_microgenre_input(_FIXTURE)
        artifact = build_microgenre_signal_checkpoint(graph)
        with self.assertRaisesRegex(ValueError, "hash"):
            verify_microgenre_signal_checkpoint(
                artifact.model_copy(update={"output_sha256": "0" * 64})
            )
        raw = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        raw["nodes"][0]["label"] = "Tampered Rock"
        with self.assertRaisesRegex(ValueError, "hash"):
            SourceNeutralMicrogenreInput.model_validate_json(json.dumps(raw))

    def test_hierarchy_does_not_require_granularity_labels(self) -> None:
        graph = load_source_neutral_microgenre_input(_FIXTURE)
        unlabeled = graph.model_copy(
            update={
                "nodes": tuple(
                    node.model_copy(update={"evaluation_level": None})
                    if node.kind == "genre"
                    else node
                    for node in graph.nodes
                ),
                "input_sha256": "0" * 64,
            }
        )
        unlabeled = unlabeled.model_copy(
            update={"input_sha256": source_neutral_input_sha256(unlabeled)}
        )
        artifact = build_microgenre_signal_checkpoint(
            unlabeled,
            MicrogenreSignalSettings(
                split_seed=29,
                heldout_fraction=0.4,
                score_threshold=0.2,
                max_generated_candidates_per_relation=2,
            ),
        )
        hierarchy = next(
            metric for metric in artifact.relation_metrics if metric.relation == "hierarchy"
        )
        self.assertGreater(hierarchy.heldout_open_edge_count, 0)
        self.assertFalse(artifact.coverage.historical_inputs_read)

    def test_open_hierarchy_input_rejects_a_cycle_without_level_labels(self) -> None:
        graph = load_source_neutral_microgenre_input(_FIXTURE)
        cycle_edge = graph.edges[0].model_copy(
            update={
                "edge_id": "hierarchy:post-punk:rock",
                "relation": "hierarchy",
                "source_id": "genre:post-punk",
                "target_id": "genre:rock",
            }
        )
        cyclic = graph.model_copy(
            update={"edges": (*graph.edges, cycle_edge), "input_sha256": "0" * 64}
        )
        cyclic = cyclic.model_copy(update={"input_sha256": source_neutral_input_sha256(cyclic)})
        with self.assertRaisesRegex(ValueError, "acyclic"):
            SourceNeutralMicrogenreInput.model_validate_json(cyclic.model_dump_json())

    def test_cli_writes_a_replayable_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "checkpoint.json"
            completed = subprocess.run(  # noqa: S603
                [
                    sys.executable,
                    "scripts/build_microgenre_signal_checkpoint.py",
                    "--input",
                    str(_FIXTURE),
                    "--output",
                    str(output),
                    "--split-seed",
                    "29",
                    "--heldout-fraction",
                    "0.4",
                    "--score-threshold",
                    "0.2",
                    "--max-generated-candidates-per-relation",
                    "0",
                ],
                cwd=_ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("heldout_positive_hit_rate_at_k", completed.stdout)
            artifact = build_microgenre_signal_checkpoint(
                load_source_neutral_microgenre_input(_FIXTURE),
                MicrogenreSignalSettings(
                    split_seed=29,
                    heldout_fraction=0.4,
                    score_threshold=0.2,
                    max_generated_candidates_per_relation=0,
                ),
            )
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8"))["output_sha256"],
                artifact.output_sha256,
            )
