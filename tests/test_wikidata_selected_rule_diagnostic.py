"""Small split/mask, fit-seal, leakage, replay and unknown-coverage regressions."""

from __future__ import annotations

import io
import json
import unittest
from collections import Counter, defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import zstandard

from opennoise.ml import wikidata_selected_rule_diagnostic as diagnostic
from opennoise.ml import wikidata_training_experiment as training
from tests.test_wikidata_training_experiment import raw_row

TRAIN_ARTISTS = 10
OUTER_QUERIES = 4
CALIBRATION_QUERIES = 2
UNKNOWN_TEST_QUERIES = 3
UNKNOWN_TEST_POSITIVES = 2


def seal(root: Path) -> str:
    """Write a synthetic closed inventory and return its explicit receipt pin."""
    (root / "receipt.json").write_text(
        json.dumps(
            {
                "files": {
                    path.name: {"bytes": path.stat().st_size, "sha256": training.sha(path)}
                    for path in root.iterdir()
                    if path.name != "receipt.json"
                }
            }
        )
    )
    return training.sha(root / "receipt.json")


def fixtures(root: Path) -> tuple[Path, str, Path, str]:
    """Include positive, missing, sparse, unseen and unsupported outer queries."""
    source, selection = root / "source", root / "selection"
    source.mkdir()
    selection.mkdir()
    rows = [raw_row(index, ("Q1", "Q2")) for index in range(TRAIN_ARTISTS)]
    rows.extend(
        [
            raw_row(0, (), "calibration"),
            raw_row(1, ("Q999",), "calibration"),
            raw_row(0, ("Q1", "Q2", "Q999"), "confirmation"),
            raw_row(1, ("Q777", "Q888"), "confirmation"),
        ]
    )
    payload = b"".join((json.dumps(row) + "\n").encode() for row in rows)
    (source / "artist-fold-targets.jsonl.zst").write_bytes(
        zstandard.ZstdCompressor().compress(payload)
    )
    (source / "implementation.py").write_text(
        'SEED = "opennoise-artist-completion-v1-frozen"\n'
        "TRAIN_BUCKETS = 6\nCALIBRATION_BOUNDARY = 8\n"
    )
    (selection / "implementation.py").write_bytes(Path(training.__file__).read_bytes())
    (selection / "frozen-policy.json").write_text("{}\n")
    (selection / "report.json").write_text(
        json.dumps(
            {
                "selected_arm_training_only": diagnostic.SELECTED,
                "confirmation_evaluation": False,
                "selected_model_refit": False,
                "input_sha256": training.sha(source / "artist-fold-targets.jsonl.zst"),
                "mean_innerfold_recall_at_10": {diagnostic.SELECTED: 0.73, diagnostic.PRIOR: 0.61},
            }
        )
    )
    return source, seal(source), selection, seal(selection)


class SelectedRuleDiagnosticTests(unittest.TestCase):
    def test_scores_replay_pinned_selected_rule_and_prior(self) -> None:
        model = training.Counts(
            100,
            Counter({"Q1": 10, "Q2": 10, "Q3": 80, "Q4": 20}),
            {"Q1": Counter({"Q3": 1, "Q4": 8}), "Q2": Counter({"Q3": 6})},
            ("Q1", "Q2", "Q3", "Q4"),
        )
        for seeds in ((), ("Q999",), ("Q1",), ("Q1", "Q2")):
            for arm in diagnostic.ARMS:
                original_arm = next(value for value in training.ARMS if value.name == arm)
                scores = diagnostic.scored(model, seeds, arm)
                assert tuple(qid for qid, _ in scores[:10]) == training.rank(
                    model, seeds, original_arm
                )
                assert not set(seeds).intersection(qid for qid, _ in scores)
        assert diagnostic.scored(model, (), diagnostic.PRIOR) == diagnostic.scored(
            model, ("Q999",), diagnostic.SELECTED
        )

    def test_freeze_fit_seal_precedes_outer_decode_and_replay_is_complete(self) -> None:
        with TemporaryDirectory(dir="/dev/shm") as directory:
            root = Path(directory)
            source, source_pin, selection, selection_pin = fixtures(root)
            output = root / "output"
            original_loader, original_outer = training.load_training, diagnostic.outer_rows

            def guarded_training(path: Path) -> tuple[list[training.Row], dict[str, int]]:
                policy = json.loads((output / "frozen-policy.json").read_bytes())
                assert tuple(arm["name"] for arm in policy["arms"]) == diagnostic.ARMS
                assert policy["implementation_sha256"] == training.sha(output / "implementation.py")
                assert not (output / "fitted-training-model.json").exists()
                return original_loader(path)

            def guarded_outer(path: Path, fitted: Path, pin: str) -> object:
                fit_seal = json.loads((output / "training-fit-seal.json").read_bytes())
                assert fit_seal["model_sha256"] == pin == training.sha(fitted)
                assert fit_seal["outer_label_decoding_started"] is False
                assert fit_seal["fit_artists"] == TRAIN_ARTISTS
                return original_outer(path, fitted, pin)

            with (
                patch.object(training, "load_training", side_effect=guarded_training),
                patch.object(diagnostic, "outer_rows", side_effect=guarded_outer),
                patch.object(training, "_bounds", return_value=1),
            ):
                report = diagnostic.diagnostic(source, source_pin, selection, selection_pin, output)
            with (
                (output / "outer-queries.jsonl.zst").open("rb") as raw,
                zstandard.ZstdDecompressor().stream_reader(raw) as stream,
                io.TextIOWrapper(stream) as text,
            ):
                events = [json.loads(line) for line in text]
            assert len(events) == OUTER_QUERIES
            assert report["fitted_training_artists"] == TRAIN_ARTISTS
            assert report["fresh_confirmation"] is False
            assert report["acceptance_gate_pass"] is False
            assert report["calibrated_musical_probability"] is False
            assert (
                report["unknown_global_source_coverage"]["global_genre_coverage_estimate"] is None
            )
            calibration = report["outer_splits"]["calibration"]["arms"][diagnostic.PRIOR]["all"]
            assert calibration["all_exact_outer_queries"] == CALIBRATION_QUERIES
            assert calibration["masked_source_positive_queries"] == 1
            assert calibration["missing_source_target_unknown_queries"] == 1
            assert calibration["recall"]["10"] == 0
            assert "missing_source_target_unknown" in events[0]["strata"]
            assert "unseen_target" in events[1]["strata"]
            diagnostic.verify_pack(output, training.sha(output / "receipt.json"))

    def test_outer_label_changes_cannot_change_training_fit(self) -> None:
        with TemporaryDirectory(dir="/dev/shm") as directory:
            root = Path(directory)
            source, _, _, _ = fixtures(root)
            path = source / "artist-fold-targets.jsonl.zst"
            before, _ = training.load_training(path)
            payload = zstandard.ZstdDecompressor().decompress(path.read_bytes())
            rows = [json.loads(line) for line in payload.splitlines()]
            for index, row in enumerate(rows):
                if row["split"] != "train":
                    rows[index] = raw_row(index, ("Q12345",), row["split"])
            path.write_bytes(
                zstandard.ZstdCompressor().compress(
                    b"".join((json.dumps(row) + "\n").encode() for row in rows)
                )
            )
            after, _ = training.load_training(path)
            assert diagnostic.model_value(training.fit(before, -1)) == diagnostic.model_value(
                training.fit(after, -1)
            )

    def test_saved_outer_split_mask_and_unsealed_model_are_rejected(self) -> None:
        with TemporaryDirectory(dir="/dev/shm") as directory:
            root = Path(directory)
            source, _, _, _ = fixtures(root)
            fitted = root / "model.json"
            fitted.write_text("{}")
            pin = training.sha(fitted)
            fitted.write_text('{"changed":true}')
            with self.assertRaisesRegex(ValueError, "sealed"):
                list(diagnostic.outer_rows(source / "artist-fold-targets.jsonl.zst", fitted, pin))
            row = raw_row(0, ("Q1", "Q2"), "confirmation")
            row["split"] = "calibration"
            with self.assertRaisesRegex(ValueError, "original exact-UUID"):
                training.route(json.dumps(row).encode())
            row["split"] = "confirmation"
            row["masked_observed_target"] = "Q999"
            with self.assertRaisesRegex(ValueError, "mask differs"):
                training._train_row(row)  # noqa: SLF001

    def test_selection_and_input_hash_tampering_are_rejected(self) -> None:
        with TemporaryDirectory(dir="/dev/shm") as directory:
            source, pin, selection, selection_pin = fixtures(Path(directory))
            (source / "implementation.py").write_text("changed")
            with self.assertRaisesRegex(ValueError, "sealed member"):
                diagnostic.verify_pack(source, pin)
            (selection / "report.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "sealed member"):
                diagnostic.selected_evidence(selection, selection_pin)

    def test_unknown_and_outside_vocabulary_targets_remain_in_denominators(self) -> None:
        model = training.Counts(10, Counter({"Q1": 5, "Q2": 2}), {}, ("Q1",))
        totals: dict[str, dict[str, Counter[str]]] = {
            arm: defaultdict(Counter) for arm in diagnostic.ARMS
        }
        paired = defaultdict(Counter)
        for index, labels in enumerate(((), ("Q999",), ("Q2",))):
            row = training._train_row(raw_row(index, labels, "confirmation"))  # noqa: SLF001
            diagnostic._event("confirmation", row, model, totals, paired)  # noqa: SLF001
        values = diagnostic.metrics(totals[diagnostic.PRIOR]["all"])
        assert values["all_exact_outer_queries"] == UNKNOWN_TEST_QUERIES
        assert values["masked_source_positive_queries"] == UNKNOWN_TEST_POSITIVES
        assert values["missing_source_target_unknown_queries"] == 1
        assert values["recall"]["10"] == 0
        assert paired["unseen_target"]["positive"] == 1
        assert paired["target_outside_training_vocabulary"]["positive"] == UNKNOWN_TEST_POSITIVES
        assert diagnostic.wilson(0, 0) is None
        interval = diagnostic.wilson(0, 2)
        assert interval is not None
        assert interval[1] > 0
        assert (
            diagnostic.paired_metrics(paired["all"])["cutoffs"]["10"]["selected_minus_prior"] == 0
        )


if __name__ == "__main__":
    unittest.main()
