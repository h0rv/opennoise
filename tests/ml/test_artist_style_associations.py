"""Source-role authority, sparse cue aggregation, and inference-only style contracts."""

from __future__ import annotations

import gzip
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from scipy import sparse

from opennoise.analysis.emergent_topic_holdout import partition_feature_file
from opennoise.ml.artist_style_associations import (
    FineStyleSettings,
    StyleAssociationModel,
    StyleProfiles,
    fit_style_associations,
    load_style_model,
    read_style_profiles,
    save_style_model,
)
from scripts.evaluate_artist_style_associations import CANDIDATES, _score, evaluate_styles


def _feature(value: str, namespace: str = "artist_tag") -> dict[str, object]:
    return {
        "namespace": namespace,
        "value": value,
        "evidence_refs": [f"source:{namespace}:{value}"],
    }


def _rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    rock_artist_count = 10
    for i in range(100):
        features = [_feature("rock" if i < rock_artist_count else "jazz", "artist_genre")]
        if i in (0, 1, 2):
            features.extend(
                [
                    _feature("micro texture"),
                    _feature("rock"),
                    _feature("release context only", "release_tag"),
                ]
            )
        rows.append({"artist_mbid": f"artist-{i:03}", "features": features})
    return rows


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


class ArtistStyleAssociationTests(unittest.TestCase):
    def test_artist_tag_targets_context_auxiliary_and_native_duplicates_suppressed(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "features.jsonl"
            _write(path, _rows())
            profiles = read_style_profiles(path)
            model = fit_style_associations(
                profiles,
                FineStyleSettings(
                    minimum_target_support=3,
                    maximum_target_share=0.1,
                    minimum_joint_support=2,
                    smoothing=4,
                ),
            )
        self.assertEqual(model.targets, ("micro texture",))
        self.assertNotIn("release context only", model.targets)
        self.assertEqual(profiles.authority["artist-000"]["rock"], 1)
        self.assertEqual(profiles.authority["artist-000"]["release context only"], 0.2)
        self.assertEqual(
            model.rank_batch(profiles, ["artist-003"]), {"artist-003": ("micro texture",)}
        )
        self.assertEqual(model.rank_batch(profiles, ["artist-000"]), {"artist-000": ()})

    def test_many_weak_cues_cannot_outvote_a_strong_primary_cue(self) -> None:
        cues = ("primary", *(f"weak{i:02}" for i in range(30)))
        scores = sparse.csr_matrix(
            ([1, *([0.1] * 30)], ([0, *range(1, 31)], [0, *([1] * 30)])), shape=(31, 2)
        )
        model = StyleAssociationModel(
            FineStyleSettings(),
            cues,
            ("fine", "broad"),
            scores,
            scores.copy(),
            np.ones(31),
            np.array([10, 10]),
            ({}, {}),
            "fixture",
            100,
        )
        profiles = StyleProfiles(
            {"artist": cues},
            {"artist": ("primary",)},
            {"artist": ()},
            {"artist": ("primary",)},
            {"artist": dict.fromkeys(cues, 1)},
            "query",
        )
        self.assertEqual(model.rank_batch(profiles, ["artist"], limit=1), {"artist": ("fine",)})
        cold = StyleProfiles(
            profiles.music,
            {"artist": ()},
            profiles.artist_tags,
            {"artist": ()},
            profiles.authority,
            "cold-context-only",
        )
        self.assertEqual(model.rank_batch(cold, ["artist"]), {"artist": ()})

    def test_proposals_explain_source_tag_counts_and_never_claim_taxonomy_or_native_facts(
        self,
    ) -> None:
        cache = Path(__file__).resolve().parents[2] / ".cache"
        with TemporaryDirectory(dir=cache) as temporary:
            path = Path(temporary) / "source.jsonl"
            rows = _rows()
            _write(path, rows)
            profiles = read_style_profiles(path)
            model = fit_style_associations(
                profiles,
                FineStyleSettings(
                    minimum_target_support=3,
                    maximum_target_share=0.1,
                    minimum_joint_support=2,
                    smoothing=4,
                ),
            )
            output = Path(temporary) / "model"
            save_style_model(model, output)
            replay = load_style_model(output)
            self.assertEqual(
                model.rank_batch(profiles, list(profiles.music)),
                replay.rank_batch(profiles, list(profiles.music)),
            )
            proposal = replay.proposals(rows[3], profiles)[0]
            self.assertEqual(proposal["training_artist_tag_support"], 3)
            self.assertFalse(proposal["native_fact"])
            self.assertFalse(proposal["score_calibrated"])
            self.assertFalse(proposal["genre_identity_validated"])
            self.assertEqual(proposal["target_scope"], "source_artist_tag_style_candidate")
            with (output / "associations.npz").open("ab") as stream:
                stream.write(b"altered")
            with self.assertRaisesRegex(ValueError, "file hash"):
                load_style_model(output)

    def test_rare_or_unanchored_source_targets_do_not_enter_style_pool(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "features.jsonl"
            _write(path, _rows())
            profiles = read_style_profiles(path)
            model = fit_style_associations(profiles)
        self.assertEqual(model.targets, ())
        self.assertEqual(model.rank_batch(profiles, ["artist-003"]), {"artist-003": ()})

    def test_fixed_grid_support_share_anchor_and_proper_signature_gates(self) -> None:
        rows: list[dict[str, object]] = []
        rock_artists = 20
        supported_artists = 5
        insufficient_artists = 4
        excessive_artists = 11
        rare_share = 0.005
        for i in range(2000):
            features = [_feature("rock" if i < rock_artists else "jazz", "artist_genre")]
            if i < supported_artists:
                features.append(_feature("fine texture"))
            if i < insufficient_artists:
                features.append(_feature("insufficient texture"))
            if i < excessive_artists:
                features.append(_feature("too common texture"))
            if i in (0, 1, 20, 21, 22):
                features.append(_feature("unanchored texture"))
            if i < supported_artists:
                features.extend([_feature("post-rock", "artist_genre"), _feature("post rock")])
            rows.append({"artist_mbid": f"artist-{i:04}", "features": features})
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "features.jsonl"
            _write(path, rows)
            profiles = read_style_profiles(path)
            model = fit_style_associations(profiles)
        self.assertEqual(model.targets, ("fine texture",))
        self.assertTrue(
            all(settings.minimum_target_support >= supported_artists for settings in CANDIDATES)
        )
        self.assertTrue(all(settings.maximum_target_share == rare_share for settings in CANDIDATES))
        self.assertEqual(tuple(settings.strongest_cues for settings in CANDIDATES), (2, 2, 1))
        query = StyleProfiles(
            {"artist": ("rock", "fine-texture")},
            {"artist": ("rock",)},
            {"artist": ()},
            {"artist": ("rock",)},
            {"artist": {"rock": 1, "fine-texture": 0.8}},
            "query",
        )
        self.assertEqual(model.rank_batch(query, ["artist"]), {"artist": ()})

    def test_duplicate_facets_and_connected_release_groups_are_partitioned_together(self) -> None:
        group_one = "00000000-0000-0000-0000-000000000001"
        group_two = "00000000-0000-0000-0000-000000000002"

        def release(value: str, groups: tuple[str, ...]) -> dict[str, object]:
            return {
                "namespace": "release_tag",
                "value": value,
                "evidence_refs": [f"release-group:{group}" for group in groups],
            }

        rows: list[dict[str, object]] = [
            {
                "artist_mbid": "artist-a",
                "features": [
                    _feature("micro texture"),
                    release(" MICRO   TEXTURE ", (group_one,)),
                    release("bridge", (group_one, group_two)),
                ],
            },
            {
                "artist_mbid": "artist-b",
                "features": [_feature("echo"), release("echo", (group_two,))],
            },
        ]
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.jsonl"
            _write(path, rows)
            saw_hidden = False
            for i in range(20):
                destination = Path(temporary) / f"training-{i}.jsonl"
                profiles, _, targets, _ = partition_feature_file(
                    path, destination, salt=f"test-salt-{i}"
                )
                pairs = {(fact.artist_id, fact.feature_id) for fact in targets}
                if pairs:
                    saw_hidden = True
                    self.assertEqual(
                        pairs,
                        {
                            ("artist-a", "micro texture"),
                            ("artist-a", "bridge"),
                            ("artist-b", "echo"),
                        },
                    )
                    self.assertEqual(profiles, {"artist-a": (), "artist-b": ()})
                    training_rows = [
                        json.loads(line) for line in destination.read_text().splitlines()
                    ]
                    self.assertFalse(any(row["features"] for row in training_rows))
                else:
                    self.assertEqual(profiles["artist-a"], ("bridge", "micro texture"))
            self.assertTrue(saw_hidden)

    def test_independent_cues_cannot_create_zero_score_proposals(self) -> None:
        with self.assertRaisesRegex(ValueError, "lift bounds"):
            FineStyleSettings(minimum_association_lift=1)

    def test_rare_slice_keeps_zero_support_and_excludes_proper_spelling_duplicates(self) -> None:
        profiles = StyleProfiles(
            {"cold": (), "warm": ("rock",)},
            {"cold": (), "warm": ("rock",)},
            {"cold": (), "warm": ()},
            {"cold": (), "warm": ("rock",)},
            {"cold": {}, "warm": {"rock": 1}},
            "training",
        )
        pairs = (("cold", "never observed texture"), ("warm", "post rock"))
        metrics = _score({"cold": (), "warm": ()}, pairs, profiles, {"post-rock"}, set(pairs))
        rare = metrics["rare_source_artist_tag_only"]
        self.assertEqual(rare["positive_count"], 1)
        self.assertEqual(rare["zero_training_support_positive_count"], 1)
        self.assertEqual(rare["hits_at_10"], 0)
        self.assertEqual(metrics["artist_primary_cold"]["positive_count"], 1)

    def test_fresh_nested_pipeline_retains_unseen_and_cold_denominators(self) -> None:
        cache = Path(__file__).resolve().parents[2] / ".cache"
        with TemporaryDirectory(dir=cache) as temporary:
            path = Path(temporary) / "source.jsonl"
            rows: list[dict[str, object]] = []
            rock_artists = 100
            tagged_artists = 10
            for i in range(3000):
                features = [_feature("rock" if i < rock_artists else "jazz", "artist_genre")]
                if i < tagged_artists:
                    features.append(_feature("micro texture"))
                rows.append({"artist_mbid": f"artist-{i:04}", "features": features})
            _write(path, rows)
            output = Path(temporary) / "run"
            report = evaluate_styles(features=path, output=output)
            self.assertTrue((output / "pre-fit-declaration.json").exists())
            self.assertTrue((output / "selected-before-outer-scoring.json").exists())
            self.assertTrue((output / "frozen-code/artist_style_associations.py").exists())
            self.assertFalse(list(output.glob("*-rankings-*.json")))
            with gzip.open(output / "outer-target-outcomes.jsonl.gz", "rt") as stream:
                outcomes = [json.loads(line) for line in stream]
            self.assertEqual(len(outcomes), report["outer_positive_pair_count"])
            metrics = report["outer_metrics"]
            assert isinstance(metrics, dict)
            style = metrics["authority_aware_style"]
            self.assertEqual(style["all"]["positive_count"], report["outer_positive_pair_count"])
            self.assertGreater(style["artist_primary_cold"]["positive_count"], 0)
            self.assertEqual(style["artist_primary_cold"]["hits_at_10"], 0)
            self.assertTrue(report["cold_and_unseen_positives_retained"])
            self.assertFalse(report["test_based_reselection"])
            self.assertFalse(report["native_fact"])
            hits = sum(row["rank_at_10"]["authority_aware_style"] is not None for row in outcomes)
            self.assertEqual(hits, style["all"]["hits_at_10"])
            reciprocal = sum(
                1 / rank
                for row in outcomes
                if (rank := row["rank_at_10"]["authority_aware_style"]) is not None
            )
            self.assertAlmostEqual(
                reciprocal / len(outcomes), style["all"]["mrr_at_10_per_positive"]
            )


if __name__ == "__main__":
    unittest.main()
