import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np

from opennoise.ml import jamendo_human_mood as mood


def row(identity: int, *, happy: int = 2, tags: tuple[str, ...] = ()) -> mood.Observation:
    """Construct synthetic identities and an ordered three-vote target."""
    return mood.Observation(
        identity,
        identity,
        identity,
        f"{identity % 100:02d}/{identity}.mp3",
        "30",
        tags,
        ("happy",) * happy + ("not_happy",) * (3 - happy),
    )


class HumanMoodTests(unittest.TestCase):
    def test_fractional_component_weights_and_absence_likelihood(self) -> None:
        rows = [row(1, happy=3, tags=("genre---x",)), row(2, happy=0), row(3, happy=1)]
        groups = {1: 1, 2: 1, 3: 3}
        model = mood.fit(rows, groups)
        self.assertIsNotNone(model)
        assert model is not None
        # Component masses are1 and1; positive fractional mass=.5+1/3.
        self.assertAlmostEqual(model.prior, (1 + 0.5 + 1 / 3) / 4)
        self.assertAlmostEqual(model.happy[0], 1.5 / (2 + 0.5 + 1 / 3))
        self.assertAlmostEqual(model.not_happy[0], 1 / (2 + 0.5 + 2 / 3))
        predicted = mood.predict(model, row(4))[1]
        h = model.prior * (1 - model.happy[0])
        n = (1 - model.prior) * (1 - model.not_happy[0])
        self.assertAlmostEqual(predicted, h / (h + n))
        self.assertNotAlmostEqual(predicted, model.prior)

    def test_empty_vocabulary_and_privileged_input_separation(self) -> None:
        model = mood.fit(
            [row(1, tags=("genre---same",)), row(2, tags=("genre---same",))], {1: 1, 2: 2}
        )
        assert model is not None
        self.assertEqual(model.vocabulary, ())
        prediction = mood.predict(model, row(3, tags=("mood/theme---happy", "other---x")))
        self.assertEqual(prediction[:2], [model.prior, model.prior])
        self.assertEqual(prediction[2], 1)
        self.assertIsNone(mood.fit([], {}))

    def test_artist_album_bridge_and_disjoint_namespaces(self) -> None:
        rows = [
            row(10),
            replace(row(20), artist_id=10),
            replace(row(30), album_id=20),
            replace(row(40), artist_id=20, album_id=40),
        ]
        self.assertEqual(mood.components(rows), {10: 10, 20: 10, 30: 10, 40: 40})
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            mood.components([row(1), row(1)])

    def test_heldout_labels_never_change_predictions_or_fit(self) -> None:
        rows = [row(i, tags=(f"genre---{i % 3}",)) for i in range(1, 40)]
        heldout = mood.fold(1)
        changed = [
            replace(r, votes=("happy",) * 3) if mood.fold(r.track_id) == heldout else r
            for r in rows
        ]
        first, models = mood.predictions(rows)
        second, changed_models = mood.predictions(changed)
        self.assertEqual(models[heldout], changed_models[heldout])
        self.assertEqual(
            [r["probabilities"] for r in first if r["fold"] == heldout],
            [r["probabilities"] for r in second if r["fold"] == heldout],
        )

    def test_vote_brier_not_mean_target_error_and_missing_denominators(self) -> None:
        np.testing.assert_allclose(mood.losses([0.5], 2 / 3), [[0.25, 1 / 36]])
        rows = [row(i) for i in range(1, 20)] + [replace(row(99), votes=None)]
        predictions, _ = mood.predictions(rows)
        result = mood.evaluation(predictions)
        self.assertEqual(result["nominated"], 20)
        self.assertEqual(result["eligible"], 19)
        self.assertEqual(result["disagreement"], 19)
        self.assertEqual(result["eligibility_reasons"]["missing_votes"], 1)
        self.assertEqual(mood.vote_reason(("happy",)), "wrong_vote_count")
        self.assertEqual(mood.vote_reason(("happy", "bad", "not_happy")), "invalid_vote")
        empty, _ = mood.predictions([replace(row(1), votes=None)])
        report = mood.evaluation(empty)
        self.assertIsNone(report["methods"]["human_prior"]["component_equal_vote_brier"])
        self.assertEqual(
            report["nb_minus_prior"]["component_equal_vote_brier"]["undefined_draws"], 2000
        )

    def test_component_equal_metric_and_paired_bootstrap(self) -> None:
        records = []
        for i, component in enumerate([1, 1, 1, 2]):
            records.append(
                {
                    "track_id": i,
                    "component_id": component,
                    "eligibility_reason": None,
                    "probabilities": [0.0, 1.0 if component == 1 else 0.0, 0.0],
                    "happy_fraction": 1.0,
                }
            )
        report = mood.summarize(records, 4)
        self.assertEqual(
            report["methods"]["genre_instrument_nb"]["component_equal_vote_brier"], 0.5
        )
        self.assertEqual(report["methods"]["genre_instrument_nb"]["track_vote_brier"], 0.25)
        self.assertEqual(report["nb_minus_prior"]["component_equal_vote_brier"]["difference"], -0.5)
        self.assertEqual(
            report["nb_minus_prior"]["component_equal_vote_brier"]["valid_draws"], 2000
        )

    def test_identity_stage_ignores_votes_and_sequence_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "human.tsv"
            p.write_text(
                "TRACK_ID\tARTIST_ID\tALBUM_ID\tPATH\tDURATION\tANNOTATIONS\n"
                "track_001\tartist_02\talbum_003\t01/1.mp3\t30.0\t"
                "mood_happy---happy,not_happy,happy\tother---never\n"
            )
            identity = mood.parse(p, human=True, identity_only=True)[0]
            self.assertIsNone(identity.votes)
            actual = mood.parse(p, human=True, identity_only=False)[0]
            self.assertEqual(actual.votes, ("happy", "not_happy", "happy"))
            self.assertEqual(actual.tags, ())
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                mood.join([replace(actual, artist_id=9)], [actual])
            p.write_text(
                p.read_text() + p.read_text().splitlines()[1].replace("track_001", "track_1") + "\n"
            )
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                mood.parse(p, human=True, identity_only=True)

    def test_prepare_evaluate_replay_and_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            metadata = root / "meta.tsv"
            human = root / "human.tsv"
            header = "TRACK_ID\tARTIST_ID\tALBUM_ID\tPATH\tDURATION\t"
            metadata.write_text(header + "TAGS\n")
            human.write_text(header + "ANNOTATIONS\n")
            for i in range(1, 10):
                identity = f"track_{i}\tartist_{i}\talbum_{i}\t{i:02d}/{i}.mp3\t30\t"
                with metadata.open("a") as f:
                    f.write(identity + f"genre---x{i % 2}\n")
                with human.open("a") as f:
                    f.write(identity + "mood_happy---happy,not_happy,happy\n")
            with patch.object(mood, "sources", return_value=(metadata, human)):
                prepared = root / "prepared"
                out = root / "output"
                seal = mood.prepare(root / "protocol", root / "receipt", "test", prepared)
                self.assertFalse(seal["labels_interpreted"])
                self.assertNotIn("happy", (prepared / "cohort.json").read_text())
                pin = mood.digest(prepared / "seal.json")
                mood.evaluate(prepared, pin, out)
                mood.replay(prepared, pin, out)
                original_receipt = (out / "receipt.json").read_text()
                forged = json.loads(original_receipt)
                forged["research_only"] = False
                (out / "receipt.json").write_text(json.dumps(forged))
                with self.assertRaisesRegex(ValueError, "rights"):
                    mood.replay(prepared, pin, out)
                (out / "receipt.json").write_text(original_receipt)
                with self.assertRaisesRegex(ValueError, "Fresh"):
                    mood.evaluate(prepared, pin, out)
                original_model = (out / "models.json").read_text()
                false_model = json.loads(original_model)
                false_model[0]["prior"] = 0.999
                (out / "models.json").write_text(json.dumps(false_model))
                forged = json.loads(original_receipt)
                forged["files"]["models.json"] = {
                    "bytes": (out / "models.json").stat().st_size,
                    "sha256": mood.digest(out / "models.json"),
                }
                (out / "receipt.json").write_text(json.dumps(forged))
                with self.assertRaisesRegex(ValueError, "Numerical replay"):
                    mood.replay(prepared, pin, out)
                (out / "receipt.json").write_text(original_receipt)
                (out / "models.json").write_text("{}")
                with self.assertRaisesRegex(ValueError, "content differs"):
                    mood.replay(prepared, pin, out)
                cohort = json.loads((prepared / "cohort.json").read_text())
                cohort[0]["fold"] = 99
                (prepared / "cohort.json").write_text(json.dumps(cohort))
                with self.assertRaisesRegex(ValueError, "identities"):
                    mood.evaluate(prepared, pin, root / "other")

    def test_external_receipt_pin_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "protocol"
            p.write_text("{}")
            with self.assertRaisesRegex(ValueError, "Protocol or acquisition"):
                mood.sources(p, p, "wrong")

    def test_output_budget_rejected_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "existing").write_bytes(b"x" * 30)
            with (
                patch.object(mood, "MAX_OUTPUT_BYTES", 40),
                self.assertRaisesRegex(ValueError, "Combined output"),
            ):
                mood._write(root / "new.json", {"data": "x" * 20})  # noqa: SLF001 - bounded writer regression.
            self.assertFalse((root / "new.json").exists())

    def test_runtime_change_rejected_before_label_load(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "cohort.json").write_text("[]")
            seal = {
                "code": mood._code(),  # noqa: SLF001 - seal regression.
                "versions": {"python": "wrong"},
                "labels_interpreted": False,
                "cohort_sha256": mood.digest(root / "cohort.json"),
            }
            (root / "seal.json").write_text(json.dumps(seal))
            with self.assertRaisesRegex(ValueError, "implementation changed"):
                mood._load(root, mood.digest(root / "seal.json"))  # noqa: SLF001 - early runtime guard.

    def test_no_training_eligible_and_heldout_only_feature(self) -> None:
        one = row(1, tags=("genre---heldout_only",))
        predictions, models = mood.predictions([one])
        self.assertIsNone(predictions[0]["probabilities"])
        self.assertEqual(predictions[0]["prediction_reason"], "no_training_eligible")
        self.assertEqual(models[mood.fold(1)]["vocabulary"], [])
        other = next(i for i in range(2, 100) if mood.fold(i) != mood.fold(1))
        _, fitted = mood.predictions([one, row(other)])
        self.assertNotIn("genre---heldout_only", fitted[mood.fold(1)]["vocabulary"])
