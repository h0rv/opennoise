"""Source increments share targets and cannot leak duplicated observations."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from opennoise.analysis.paired_feature_increment import (
    evaluate_paired_increment,
    evidence_component_diagnostics,
    prepare_paired_training,
    score_positive_rankings,
)
from opennoise.common import canonical_json
from opennoise.ml.emergent_topics import TopicSettings


def _feature(
    value: str, namespace: str = "artist_tag", ref: str = "artist-record"
) -> dict[str, object]:
    return {"namespace": namespace, "value": value, "weight": 1.0, "evidence_refs": [ref]}


def _inputs(directory: Path) -> tuple[Path, Path]:
    old, augmented = directory / "old.jsonl", directory / "augmented.jsonl"
    with old.open("wb") as left, augmented.open("wb") as right:
        for index in range(40):
            style, detail = ("ambient", "drone") if index % 2 else ("techno", "acid")
            row = {
                "artist_mbid": f"artist-{index}",
                "features": [_feature(style, "artist_genre"), _feature(detail)],
            }
            left.write(canonical_json(row) + b"\n")
            row["features"] = [
                *row["features"],
                _feature(style),
                _feature("electronic"),
            ]
            right.write(canonical_json(row) + b"\n")
    return old, augmented


class PairedFeatureIncrementTests(unittest.TestCase):
    def test_release_component_diagnostic_merges_shared_pair_credits_and_rejects_split(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            source = Path(temporary) / "features.jsonl"
            first = "release-group/00000000-0000-4000-8000-000000000001"
            second = "release-group/00000000-0000-4000-8000-000000000002"
            source.write_bytes(
                b"\n".join(
                    canonical_json(row)
                    for row in (
                        {
                            "artist_mbid": "a",
                            "features": [
                                _feature("ambient", "release_tag", first),
                                _feature("ambient", "release_tag", second),
                                _feature("drone", "release_tag", first),
                            ],
                        },
                        {
                            "artist_mbid": "b",
                            "features": [
                                _feature("acid", "release_tag", second),
                                _feature("techno"),
                            ],
                        },
                    )
                )
            )
            with self.assertRaisesRegex(ValueError, "split a global release"):
                evidence_component_diagnostics(source, [("a", "ambient")])
            result = evidence_component_diagnostics(
                source, [("a", "ambient"), ("a", "drone"), ("b", "acid")]
            )
            self.assertEqual(result["canonical_evidence_component_count"], 2)
            self.assertEqual(result["largest_held_component_positive_pair_count"], 3)
            self.assertEqual(result["canonical_positive_pair_count"], 4)

    def test_same_target_values_removed_from_every_old_and_new_facet(self) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            old, augmented = _inputs(directory)
            output = directory / "partition"
            output.mkdir()
            _old, _train, pairs, _proper = prepare_paired_training(old, augmented, output)
            self.assertTrue(pairs)
            targets = set(pairs)
            for name in ("old-training.jsonl", "augmented-training.jsonl"):
                for line in (output / name).read_bytes().splitlines():
                    row = json.loads(line)
                    for feature in row["features"]:
                        self.assertNotIn((row["artist_mbid"], feature["value"]), targets)

    def test_missing_old_fact_or_release_provenance_prevents_addition_only_claim(self) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            old, augmented = _inputs(directory)
            old.write_bytes(
                canonical_json({"artist_mbid": "a", "features": [_feature("drone")]}) + b"\n"
            )
            augmented.write_bytes(
                canonical_json({"artist_mbid": "a", "features": [_feature("ambient")]}) + b"\n"
            )
            with self.assertRaisesRegex(ValueError, "removed old musical values"):
                prepare_paired_training(old, augmented, directory)
            old.write_bytes(
                canonical_json(
                    {
                        "artist_mbid": "a",
                        "features": [
                            _feature(
                                "ambient",
                                "release_tag",
                                "release-group/00000000-0000-4000-8000-000000000001",
                            )
                        ],
                    }
                )
                + b"\n"
            )
            with self.assertRaisesRegex(ValueError, "lost prior release-group provenance"):
                prepare_paired_training(old, augmented, directory)

    def test_unseen_and_cold_targets_keep_the_same_denominator(self) -> None:
        totals: dict[str, dict[str, list[float]]] = {"cold": {}, "warm": {}}
        score_positive_rankings(
            {"cold": (), "warm": ("known-target",)},
            ("known-target", "unseen"),
            {"known-target": ("all",), "unseen": ("all", "new_global_value")},
            totals,
        )
        self.assertEqual(totals["cold"]["all"], [2, 0, 0])
        self.assertEqual(totals["warm"]["all"], [2, 1, 1])
        self.assertEqual(totals["warm"]["new_global_value"], [1, 0, 0])

    def test_actual_paired_fit_seals_shared_denominators_and_fixed_settings(self) -> None:
        cache = Path(__file__).resolve().parents[2] / ".cache"
        with TemporaryDirectory(dir=cache) as temporary:
            directory = Path(temporary)
            old, augmented = _inputs(directory)
            result = evaluate_paired_increment(
                old=old,
                augmented=augmented,
                output=directory / "evaluation",
                settings=TopicSettings(depths=(1, 2, 3), minimum_artists=2),
            )
            variants = cast("dict[str, dict[str, object]]", result["results"])
            denominators = []
            for variant in variants.values():
                metrics = cast("dict[str, dict[str, dict[str, float]]]", variant["metrics"])
                denominators.extend(
                    {key: row["positive_count"] for key, row in scorer.items()}
                    for scorer in metrics.values()
                )
            self.assertTrue(all(value == denominators[0] for value in denominators))
            declaration = cast("dict[str, object]", result["prespecification"])
            self.assertFalse(declaration["test_based_reselection"])
            self.assertEqual(
                cast("dict[str, object]", declaration["predictor_settings"])["smoothing"], 4
            )
            self.assertFalse(result["genre_truth_validated"])
