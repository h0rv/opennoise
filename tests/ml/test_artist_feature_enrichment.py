"""Train-only support, canonicalization, inference roles, and model custody tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from opennoise.common import canonical_json, sha256_json
from opennoise.ml.artist_feature_enrichment import (
    MAX_BATCH,
    EnrichmentSettings,
    fit_enrichment,
    load_enrichment,
    read_profiles,
    save_enrichment,
)
from scripts.evaluate_artist_feature_enrichment import evaluate
from scripts.export_artist_feature_proposals import export_proposals


def _fixture() -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    profiles = {
        "one": ("ambient", "drone"),
        "two": ("ambient", "drone"),
        "three": ("rock", "punk"),
        "four": ("rock", "punk"),
        "sparse": ("ambient",),
        "cold": (),
    }
    return profiles, {
        artist: tuple(value for value in values if value in {"ambient", "rock"})
        for artist, values in profiles.items()
    }


class ArtistFeatureEnrichmentTests(unittest.TestCase):
    def test_sparse_proposals_exclude_known_values_and_cold_profiles_abstain(self) -> None:
        profiles, proper = _fixture()
        model = fit_enrichment(profiles, proper)
        predictions = model.rank_batch({"sparse": ("ambient",), "cold": ()}, proper)
        self.assertEqual(predictions, {"cold": (), "sparse": ("drone",)})
        self.assertEqual(model.rank_batch({"new": ("never observed",)}, {}), {"new": ()})
        with self.assertRaisesRegex(ValueError, "batch"):
            model.rank_batch({str(i): () for i in range(MAX_BATCH + 1)}, {})

    def test_duplicate_facets_votes_and_context_do_not_increase_music_support(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "features.jsonl"
            features = [
                {
                    "namespace": namespace,
                    "value": value,
                    "weight": weight,
                    "evidence_refs": ["source:exact-reference"],
                }
                for namespace, value, weight in [
                    ("artist_genre", " Ambient ", 1),
                    ("artist_tag", "AMBIENT", 99),
                    ("release_tag", "ambient", 2),
                    ("artist_tag", "seen live", 1),
                    ("area", "tokyo", 1),
                    ("decade", "1990s", 1),
                ]
            ]
            path.write_text(json.dumps({"artist_mbid": "one", "features": features}) + "\n")
            profiles, proper = read_profiles(path)
        self.assertEqual(profiles, {"one": ("ambient",)})
        self.assertEqual(proper, profiles)
        model = fit_enrichment(
            profiles, proper, settings=EnrichmentSettings(minimum_joint_support=1)
        )
        np.testing.assert_array_equal(model.target_support, [1])
        np.testing.assert_array_equal(model.cue_support, [1, 1])

    def test_query_evidence_and_training_counts_explain_inferred_proposal(self) -> None:
        profiles, proper = _fixture()
        model = fit_enrichment(profiles, proper, training_sha256="source-binding")
        proposals = model.proposals(
            {
                "artist_mbid": "sparse",
                "features": [
                    {"namespace": "artist_genre", "value": "ambient", "evidence_refs": ["native:1"]}
                ],
            }
        )
        proposal = proposals[0]
        self.assertEqual(proposal["value"], "drone")
        self.assertEqual(proposal["role"], "inferred_feature_proposal")
        self.assertFalse(proposal["native_fact"])
        self.assertFalse(proposal["score_calibrated"])
        self.assertEqual(proposal["training_source_sha256"], "source-binding")
        evidence = proposal["evidence"]
        assert isinstance(evidence, list)
        self.assertEqual({item["training_joint_artist_support"] for item in evidence}, {2})
        self.assertTrue(all(item["query_evidence_refs"] == ["native:1"] for item in evidence))

    def test_training_only_vocabulary_and_support_are_invariant_to_query_features(self) -> None:
        profiles, proper = _fixture()
        model = fit_enrichment(profiles, proper)
        before = model.target_support.copy()
        model.rank_batch({"query": ("ambient", "held out positive")}, {"query": ("ambient",)})
        np.testing.assert_array_equal(before, model.target_support)
        self.assertNotIn("held out positive", model.vocabulary)
        with self.assertRaisesRegex(ValueError, "subset"):
            fit_enrichment(profiles, {"sparse": ("held out positive",)})

    def test_round_trip_hash_verification_and_no_overwrite(self) -> None:
        cache = Path(__file__).resolve().parents[2] / ".cache"
        with TemporaryDirectory(dir=cache) as temporary:
            destination = Path(temporary) / "model"
            profiles, proper = _fixture()
            model = fit_enrichment(profiles, proper)
            save_enrichment(model, destination)
            replay = load_enrichment(destination)
            self.assertEqual(
                replay.rank_batch(profiles, proper), model.rank_batch(profiles, proper)
            )
            with self.assertRaises(FileExistsError):
                save_enrichment(model, destination)
            with (destination / "model.json").open("ab") as stream:
                stream.write(b" ")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                load_enrichment(destination)

    def test_dense_profile_work_is_rejected_before_sparse_pair_multiplication(self) -> None:
        profile = tuple(f"value {i}" for i in range(512))
        with self.assertRaisesRegex(ValueError, "pair-count work bound"):
            fit_enrichment({str(i): profile for i in range(200)}, {})

    def test_receipt_self_identity_and_mandatory_model_settings_are_verified(self) -> None:
        cache = Path(__file__).resolve().parents[2] / ".cache"
        with TemporaryDirectory(dir=cache) as temporary:
            profiles, proper = _fixture()
            output = Path(temporary) / "model"
            original = save_enrichment(fit_enrichment(profiles, proper), output)
            path = output / "receipt.json"
            altered = {**original, "scope": "public"}
            path.write_bytes(canonical_json(altered))
            with self.assertRaisesRegex(ValueError, "self identity"):
                load_enrichment(output)
            settings = original["settings"]
            assert isinstance(settings, dict)
            altered = {**original, "settings": {**settings, "smoothing": 99}}
            altered["output_sha256"] = sha256_json(
                {key: value for key, value in altered.items() if key != "output_sha256"}
            )
            path.write_bytes(canonical_json(altered))
            with self.assertRaisesRegex(ValueError, "settings or identity"):
                load_enrichment(output)
            altered = {
                key: value
                for key, value in original.items()
                if key not in {"model_sha256", "output_sha256"}
            }
            altered["output_sha256"] = sha256_json(altered)
            path.write_bytes(canonical_json(altered))
            with self.assertRaisesRegex(ValueError, "mandatory enrichment model"):
                load_enrichment(output)

    def test_nested_run_retains_cold_positives_and_freezes_selection_before_outer_scores(
        self,
    ) -> None:
        cache = Path(__file__).resolve().parents[2] / ".cache"
        with TemporaryDirectory(dir=cache) as temporary:
            source = Path(temporary) / "source.jsonl"
            rows = [
                {
                    "artist_mbid": f"artist-{i:03}",
                    "features": [
                        {"namespace": namespace, "value": value, "evidence_refs": [f"source:{i}"]}
                        for namespace, value in [
                            ("artist_genre", "ambient"),
                            ("artist_tag", "ambient"),
                            ("artist_tag", "drone"),
                        ]
                    ],
                }
                for i in range(60)
            ]
            source.write_text("".join(json.dumps(row) + "\n" for row in rows))
            output = Path(temporary) / "run"
            report = evaluate(source, output)
            self.assertTrue((output / "selected-before-outer-scoring.json").exists())
            self.assertTrue((output / "selected-model/receipt.json").exists())
            self.assertTrue(report["cold_positives_retained"])
            self.assertTrue(report["all_duplicate_facets_removed_before_fit"])
            metrics = report["outer_metrics"]
            assert isinstance(metrics, dict)
            model_metrics = metrics["artist_feature_enrichment"]
            self.assertEqual(
                model_metrics["all"]["positive_count"], report["outer_positive_pair_count"]
            )
            self.assertGreater(model_metrics["cold_artist"]["positive_count"], 0)
            self.assertEqual(model_metrics["cold_artist"]["recall_at_10"], 0)
            self.assertFalse(report["independent_source_gold"])
            self.assertFalse(report["absence_is_negative"])

    def test_full_export_shards_bind_source_model_and_inferred_only_proposals(self) -> None:
        cache = Path(__file__).resolve().parents[2] / ".cache"
        with TemporaryDirectory(dir=cache) as temporary:
            source = Path(temporary) / "features.jsonl"
            selection = Path(temporary) / "selection.json"
            rows = [
                {
                    "artist_mbid": f"00-{i}",
                    "features": [
                        {
                            "namespace": "artist_genre" if value == "ambient" else "artist_tag",
                            "value": value,
                            "evidence_refs": [f"source:{i}"],
                        }
                        for value in (("ambient", "drone") if i in (0, 1) else ("ambient",))
                    ],
                }
                for i in range(3)
            ]
            source.write_text("".join(json.dumps(row) + "\n" for row in rows))
            selection.write_text(json.dumps({"settings": {"smoothing": 4}}))
            output = Path(temporary) / "export"
            receipt = export_proposals(features=source, selection=selection, output=output)
            counts = receipt["counts"]
            assert isinstance(counts, dict)
            self.assertEqual(counts["artist_count"], len(rows))
            self.assertEqual(receipt["shard_count"], 256)
            self.assertEqual(
                receipt["output_sha256"],
                sha256_json(
                    {key: value for key, value in receipt.items() if key != "output_sha256"}
                ),
            )
            shard = json.loads((output / "feature-proposals/00.json").read_text())
            proposal = shard["artists"]["00-2"]["feature_proposals"][0]
            self.assertEqual(proposal["value"], "drone")
            self.assertEqual(proposal["training_input_sha256"], receipt["training_sha256"])
            self.assertEqual(proposal["source_model_sha256"], receipt["model_sha256"])
            self.assertFalse(proposal["native_fact"])
            self.assertEqual(shard["artists"]["00-2"]["observed_music_values"], ["ambient"])


if __name__ == "__main__":
    unittest.main()
