"""Feature holdouts remove duplicated facets before fitting and keep rankings honest."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

import numpy as np

from opennoise.analysis.emergent_topic_holdout import (
    TopicFitterBinding,
    evaluate_topic_feature_holdout,
    partition_feature_file,
    rank_positive_features,
)
from opennoise.common import canonical_json
from opennoise.ml.emergent_topics import FeatureMatrix, TopicSettings, fit_topics


def _feature(namespace: str, value: str, reference: str = "artist-record") -> dict[str, object]:
    return {"namespace": namespace, "value": value, "weight": 1.0, "evidence_refs": [reference]}


class EmergentTopicHoldoutTests(unittest.TestCase):
    def test_all_copies_of_withheld_values_are_removed_but_context_is_retained(self) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "features.jsonl"
            source.write_bytes(
                b"\n".join(
                    canonical_json(
                        {
                            "artist_mbid": f"artist-{index}",
                            "features": [
                                _feature("artist_tag", "ambient"),
                                _feature("artist_genre", "Ambient"),
                                _feature("artist_tag", "drone"),
                                _feature("area", "England"),
                            ],
                        }
                    )
                    for index in range(100)
                )
            )
            destination = directory / "training.jsonl"
            profiles, _proper, hidden, _values = partition_feature_file(source, destination)
            self.assertTrue(hidden)
            targets = {(fact.artist_id, fact.feature_id) for fact in hidden}
            other_profiles, _proper, other_hidden, _values = partition_feature_file(
                source, directory / "other-split.jsonl", salt="independent-prespecified-split"
            )
            other_targets = {(fact.artist_id, fact.feature_id) for fact in other_hidden}
            self.assertNotEqual(targets, other_targets)
            self.assertFalse(
                other_targets
                & {(artist, value) for artist, values in other_profiles.items() for value in values}
            )
            for line in destination.read_text().splitlines():
                row = json.loads(line)
                artist = row["artist_mbid"]
                self.assertIn(_feature("area", "England"), row["features"])
                for feature in row["features"]:
                    if feature["namespace"] != "area":
                        self.assertNotIn((artist, feature["value"].casefold()), targets)
                self.assertFalse(set(profiles[artist]) & {v for a, v in targets if a == artist})

    def test_release_group_features_cannot_be_split_across_credits_or_values(self) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "features.jsonl"
            reference = "release-group/00000000-0000-4000-8000-000000000001"
            source.write_bytes(
                b"\n".join(
                    canonical_json(
                        {
                            "artist_mbid": artist,
                            "features": [
                                _feature("release_tag", "ambient", reference),
                                _feature("release_tag", "drone", reference),
                            ],
                        }
                    )
                    for artist in ("a", "b")
                )
            )
            profiles, _proper, hidden, _values = partition_feature_file(
                source, directory / "train.jsonl"
            )
            self.assertIn(len(hidden), (0, 4))
            self.assertEqual(profiles["a"], profiles["b"])
            source.write_bytes(
                canonical_json(
                    {"artist_mbid": "a", "features": [_feature("release_tag", "ambient")]}
                )
            )
            with self.assertRaisesRegex(ValueError, "release-group provenance"):
                partition_feature_file(source, directory / "invalid.jsonl")

    def test_ranking_excludes_known_and_nonpositive_scores_with_stable_cutoff_ties(self) -> None:
        scores = np.ones(20)
        scores[15] = 4
        scores[16] = -2
        self.assertEqual(rank_positive_features(scores, np.array([15])), tuple(range(10)))
        self.assertEqual(scores[15], 4)

    def test_real_train_refit_counts_every_held_positive_and_seals_configuration(self) -> None:
        cache = Path(__file__).resolve().parents[2] / ".cache"
        with TemporaryDirectory(dir=cache) as temporary:
            directory = Path(temporary)
            source = directory / "features.jsonl"
            source.write_bytes(
                b"\n".join(
                    canonical_json(
                        {
                            "artist_mbid": f"artist-{index}",
                            "features": [
                                _feature("artist_genre", "ambient" if index % 2 else "techno"),
                                _feature("artist_tag", "drone" if index % 2 else "acid"),
                                _feature("artist_tag", "electronic"),
                            ],
                        }
                    )
                    for index in range(40)
                )
            )
            report = evaluate_topic_feature_holdout(
                features_path=source,
                output=directory / "run",
                settings=TopicSettings(depths=(1, 2, 3), minimum_artists=2),
            )
            targets = json.loads((directory / "run/held-out-pairs.json").read_bytes())
            self.assertEqual(report["positive_pair_count"], len(targets))
            metrics = cast("dict[str, dict[str, dict[str, object]]]", report["metrics"])
            for scorer in metrics.values():
                self.assertEqual(scorer["all"]["positive_count"], len(targets))
            self.assertTrue((directory / "run/pre-fit-declaration.json").exists())
            self.assertFalse(report["test_based_reselection"])
            self.assertFalse(report["genre_names_validated"])

    def test_alternative_fitter_sees_only_training_and_requires_unchanged_code(self) -> None:
        cache = Path(__file__).resolve().parents[2] / ".cache"
        with TemporaryDirectory(dir=cache) as temporary:
            directory = Path(temporary)
            source = directory / "features.jsonl"
            source.write_bytes(
                b"\n".join(
                    canonical_json(
                        {
                            "artist_mbid": f"artist-{index}",
                            "features": [
                                _feature("artist_genre", "ambient"),
                                _feature("artist_tag", "drone"),
                            ],
                        }
                    )
                    for index in range(30)
                )
            )
            dependency = directory / "implementation.py"
            dependency.write_text("frozen implementation")
            mutate = False

            def alternative(
                data: FeatureMatrix, settings: TopicSettings, *, include_centroids: bool
            ) -> tuple[dict[str, object], dict[str, list[dict[str, object]]]]:
                output = directory / ("mutated" if mutate else "run")
                hidden = json.loads((output / "held-out-pairs.json").read_bytes())
                profiles = dict(zip(data.artists, data.musical_profiles, strict=True))
                self.assertTrue(hidden)
                self.assertTrue(all(value not in profiles[artist] for artist, value in hidden))
                self.assertTrue((output / "pre-fit-declaration.json").exists())
                if mutate:
                    dependency.write_text("changed during fit")
                return fit_topics(data, settings, include_centroids=include_centroids)

            binding = TopicFitterBinding("fixture", alternative, (dependency,))
            settings = TopicSettings(depths=(1, 2, 3), minimum_artists=2)
            report = evaluate_topic_feature_holdout(
                features_path=source,
                output=directory / "run",
                settings=settings,
                fitter_binding=binding,
            )
            self.assertEqual(
                report["alternative_fitter"],
                {"name": "fixture", "implementation_bindings": binding.code_bindings()},
            )
            mutate = True
            with self.assertRaisesRegex(ValueError, "alternative fitter code changed"):
                evaluate_topic_feature_holdout(
                    features_path=source,
                    output=directory / "mutated",
                    settings=settings,
                    fitter_binding=binding,
                )
            self.assertFalse((directory / "mutated/report.json").exists())
