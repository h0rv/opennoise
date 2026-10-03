"""Role/seal isolation, fixed-fit reuse, multilabel denominators and unknown abstention."""

from __future__ import annotations

import io
import json
import os
import shutil
import unittest
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

import zstandard

from opennoise.ml import wikidata_selected_rule_diagnostic as diagnostic
from opennoise.ml import wikidata_source_recovery_calibration as calibration
from opennoise.ml import wikidata_training_experiment as training
from tests.fresh_process import FreshProcessTestCase
from tests.test_wikidata_selected_rule_diagnostic import seal
from tests.test_wikidata_training_experiment import raw_row

ROLE_ARTISTS = 8
QUERY_ROLES = 2
HELD_LABELS = 2
HALF_RECALL = 0.5


def run_prepared(
    source: Path, pin: str, selection: Path, selection_pin: str, output: Path
) -> dict[str, Any]:
    """Exercise the required externally sealed preparation before each synthetic fit."""
    preparation = output.parent / (output.name + "-prefit")
    receipt = calibration.prepare(source, pin, selection, selection_pin, preparation)
    return calibration.run(
        source,
        pin,
        selection,
        selection_pin,
        output,
        preparation=preparation,
        preparation_pin=receipt["preparation_receipt_sha256"],
    )


def _reseal_preparation(root: Path) -> str:
    """Keep preparation stage/revision while simulating externally pinned forged bytes."""
    receipt = json.loads((root / "receipt.json").read_bytes())
    receipt["files"] = {
        path.name: {"bytes": path.stat().st_size, "sha256": training.sha(path)}
        for path in root.iterdir()
        if path.name != "receipt.json"
    }
    (root / "receipt.json").write_text(json.dumps(receipt))
    return training.sha(root / "receipt.json")


def fixture(root: Path, *, changed_development: bool = False) -> tuple[Path, str, Path, str]:
    """Build exact disjoint role cohorts and deliberately uninterpretable outer labels."""
    source, selection = root / "source", root / "selection"
    source.mkdir()
    selection.mkdir()
    rows = []
    counts: Counter[str] = Counter()
    index = 0
    while (
        min((counts[name] for name in ("fit", "calibrate", "development_assess")), default=0)
        < ROLE_ARTISTS
    ):
        raw = raw_row(index, ("Q1", "Q2", "Q3", "Q4"))
        index += 1
        name = calibration.role(str(raw["artist_mbid"]))
        if counts[name] >= ROLE_ARTISTS:
            continue
        if name != "fit" and counts[name] == 0:
            raw = raw_row(index - 1, ())
        elif name != "fit" and counts[name] == 1:
            raw = raw_row(index - 1, ("Q999",))
        elif name == "development_assess" and changed_development:
            raw = raw_row(index - 1, ("Q777", "Q888"))
        counts[name] += 1
        rows.append(raw)
    outer = raw_row(0, (), "confirmation")
    outer["observed_genre_qids"] = {"this": "must never decode into a training row"}
    rows.append(outer)
    (source / "artist-fold-targets.jsonl.zst").write_bytes(
        zstandard.ZstdCompressor().compress(
            b"".join((json.dumps(raw) + "\n").encode() for raw in rows)
        )
    )
    (source / "implementation.py").write_text(
        'SEED = "opennoise-artist-completion-v1-frozen"\n'
        "TRAIN_BUCKETS = 6\nCALIBRATION_BOUNDARY = 8\n"
    )
    (selection / "implementation.py").write_bytes(Path(training.__file__).read_bytes())
    (selection / "frozen-policy.json").write_text("{}")
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


def model() -> training.Counts:
    """Use a source-supported pair and one explicitly outside-vocabulary identity."""
    return training.Counts(
        100,
        Counter({"Q1": 80, "Q2": 80, "Q3": 2}),
        {"Q1": Counter({"Q2": 80}), "Q2": Counter({"Q1": 80})},
        ("Q1", "Q2"),
    )


class SourceRecoveryCalibrationTests(FreshProcessTestCase):
    def test_seals_precede_later_decoding_roles_disjoint_and_all_queries_retained(self) -> None:
        with TemporaryDirectory(dir="/dev/shm") as directory:
            root = Path(directory)
            source, pin, selection, selection_pin = fixture(root)
            output = root / "output"
            original = training._train_row  # noqa: SLF001 - Guard exact decode boundary.

            def guarded(raw: dict[str, object]) -> training.Row:
                assert raw["split"] == "train"
                assert (output / "frozen-policy.json").exists()
                name = calibration.role(str(raw["artist_mbid"]))
                if name != "fit":
                    fit_seal = json.loads((output / "fixed-fit-seal.json").read_bytes())
                    assert fit_seal["model_sha256"] == training.sha(output / "fixed-fit-model.json")
                if name == "development_assess":
                    cal_seal = json.loads((output / "calibration-seal.json").read_bytes())
                    assert cal_seal["calibrator_sha256"] == training.sha(
                        output / "fixed-fit-calibrator.json"
                    )
                return original(raw)

            with (
                patch.object(training, "_train_row", side_effect=guarded),
                patch.object(calibration.os, "fsync", wraps=os.fsync) as fsync,
            ):
                report = run_prepared(source, pin, selection, selection_pin, output)
            assert fsync.call_count > 0
            assert report["role_counts"] == {"fit": 8, "calibrate": 8, "development_assess": 8}
            ids = json.loads((output / "exact-role-artists.json").read_bytes())
            assert not set(ids["fit"]).intersection(ids["calibrate"] + ids["development_assess"])
            assert not set(ids["calibrate"]).intersection(ids["development_assess"])
            with (
                (output / "all-query-ranks.jsonl.zst").open("rb") as raw,
                zstandard.ZstdDecompressor().stream_reader(raw) as stream,
                io.TextIOWrapper(stream) as text,
            ):
                events = [json.loads(line) for line in text]
            assert len(events) == ROLE_ARTISTS * QUERY_ROLES
            assert any(not event["held_observed_source_positives"] for event in events)
            assert any(event["held_observed_source_positives"] == ["Q999"] for event in events)
            restored, calibrator = calibration.load_reusable(
                output, training.sha(output / "receipt.json")
            )
            assert restored.artists == ROLE_ARTISTS
            assert calibrator == report["calibration"]
            assessed = report["metrics"]["development_assess"][diagnostic.SELECTED]
            assert assessed["counts"]["all_queries"] == ROLE_ARTISTS
            assert assessed["counts"]["missing_source_queries_unknown"] == 1
            assert assessed["counts"]["target_coverage:unseen_source_identity_unknown"] == 1
            assert assessed["ranking"]["raw"]["micro_recall"]["10"] == 12 / 13
            assert assessed["ranking"]["emitted"]["micro_recall"]["10"] == 0
            assert (
                calibration.predict(
                    restored, calibrator, ("Q1",), diagnostic.SELECTED, source_observed=True
                )["individual_membership_probability"]
                is None
            )
            with (
                patch.object(calibration, "MIN_LOWER_EVENT_RATE", 0.9),
                self.assertRaisesRegex(ValueError, "inference policy"),
            ):
                calibration.load_reusable(output, training.sha(output / "receipt.json"))
            (output / "implementation.py").write_bytes(b"changed producing inference source")
            with self.assertRaisesRegex(ValueError, "implementation/dependency pin"):
                calibration.load_reusable(output, seal(output))

    def test_development_labels_cannot_change_fixed_fit_or_calibration(self) -> None:
        with TemporaryDirectory(dir="/dev/shm") as directory:
            root = Path(directory)
            snapshots = []
            for version, changed in (("first", False), ("changed", True)):
                case = root / version
                case.mkdir()
                source, pin, selection, selection_pin = fixture(case, changed_development=changed)
                output = case / "output"
                run_prepared(source, pin, selection, selection_pin, output)
                snapshots.append(
                    {
                        name: json.loads((output / name).read_bytes())
                        for name in ("fixed-fit-model.json", "fixed-fit-calibrator.json")
                    }
                )
            assert snapshots[0]["fixed-fit-model.json"] == snapshots[1]["fixed-fit-model.json"]
            # Artifact policy pins change with source bytes; the learned arm bins must not.
            assert (
                snapshots[0]["fixed-fit-calibrator.json"]["arms"]
                == snapshots[1]["fixed-fit-calibrator.json"]["arms"]
            )

    def test_unknown_unsupported_and_no_seed_abstain_without_inventing_membership(self) -> None:
        fitted = model()
        calibrator = calibration.calibrate(fitted, iter([]))
        for seeds, observed, reason in (
            (("Q1",), False, "missing_source_observation_unknown"),
            ((), True, "no_observed_seed"),
            (("Q999",), True, "unsupported_observed_seed"),
            (("Q1", "Q3"), True, "unsupported_observed_seed"),
        ):
            result = calibration.predict(
                fitted, calibrator, seeds, diagnostic.SELECTED, source_observed=observed
            )
            assert result["abstention_reason"] == reason
            assert result["emitted_source_suggestions"] == []
            assert result["estimated_source_recovery_event_rate"] is None
            assert result["musical_probability"] is None
        assert calibration.label_coverage(fitted, "Q999") == "unseen_source_identity_unknown"
        assert calibration.label_coverage(fitted, "Q3") == "outside_fitted_vocabulary_unknown"

    def test_multilabel_metrics_keep_unseen_targets_and_mask_retains_overlap(self) -> None:
        raw = raw_row(0, ("Q1", "Q2", "Q3", "Q999"))
        row = training._train_row(raw)  # noqa: SLF001 - Test independent original-mask admission.
        query = calibration.multilabel_query(row)
        assert set(query.seeds).isdisjoint(query.targets)
        assert set(query.seeds + query.targets) == set(row.labels)
        assert len(query.targets) == len(query.seeds) == HELD_LABELS
        metrics = calibration.retrieval_metrics([("Q1", 0.9), ("Q2", 0.8)], ("Q1", "Q999"))
        assert metrics["recall"][10] == HALF_RECALL
        assert metrics["target_count"] == HELD_LABELS
        assert metrics["unmatched_candidates_are_unknown_membership"] is True
        assert calibration.retrieval_metrics([], ("Q1",))["recall"][10] == 0
        assert calibration.retrieval_metrics([], ())["recall"] is None

    def test_fixed_bin_support_and_bound_control_emission_not_raw_ranks(self) -> None:
        fitted = model()
        good = [
            calibration.Query(str(raw_row(i, ())["artist_mbid"]), ("Q1",), ("Q2",))
            for i in range(50)
        ]
        calibrator = calibration.calibrate(fitted, iter(good))
        prediction = calibration.predict(
            fitted, calibrator, ("Q1",), diagnostic.SELECTED, source_observed=True
        )
        assert prediction["calibrated_event"] == calibration.EVENT
        assert prediction["estimated_source_recovery_event_rate"] == 51 / 52
        assert prediction["emitted_source_suggestions"] == ["Q2"]
        failed = [calibration.Query(query.mbid, query.seeds, ("Q999",)) for query in good]
        rejected = calibration.predict(
            fitted,
            calibration.calibrate(fitted, iter(failed)),
            ("Q1",),
            diagnostic.SELECTED,
            source_observed=True,
        )
        assert rejected["abstention_reason"] == "source_recovery_lower_bound_below_frozen_threshold"
        assert (
            rejected["raw_overlapping_candidate_ranking"]
            == prediction["raw_overlapping_candidate_ranking"]
        )
        low_support = calibration.predict(
            fitted,
            calibration.calibrate(fitted, iter(good[:49])),
            ("Q1",),
            diagnostic.SELECTED,
            source_observed=True,
        )
        assert low_support["abstention_reason"] == "insufficient_calibration_artists"
        with self.assertRaisesRegex(ValueError, "unique exact artists"):
            calibration.calibrate(fitted, iter([good[0], good[0]]))

    def test_unsealed_fit_calibrator_and_source_tampering_fail_before_label_decode(self) -> None:
        with TemporaryDirectory(dir="/dev/shm") as directory:
            root = Path(directory)
            source, pin, selection, selection_pin = fixture(root)
            with self.assertRaisesRegex(ValueError, "inventory subtrees"):
                run_prepared(source, pin, selection, selection_pin, source / "new-output")
            alias = root / "alias"
            alias.symlink_to(source, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink ancestors"):
                run_prepared(source, pin, selection, selection_pin, alias / "new-output")
            bounded = root / "bounded"
            bounded.mkdir()
            with (
                (bounded / "bytes").open("xb", buffering=0) as raw,
                patch.object(calibration, "MAX_OUTPUT_BYTES", 4),
                self.assertRaisesRegex(ValueError, "hard output cap"),
            ):
                calibration._BoundedWriter(raw, bounded).write(b"12345")  # noqa: SLF001 - Actual write boundary.
            assert (bounded / "bytes").stat().st_size == 0
            preparation = root / "native-positive-preparation"
            with (
                patch.object(
                    training, "_train_row", side_effect=AssertionError("prepare decoded a label")
                ),
                patch.object(training, "fit", side_effect=AssertionError("prepare fitted")),
            ):
                prepared = calibration.prepare(source, pin, selection, selection_pin, preparation)
            assert prepared["source_labels_decoded"] is False
            assert prepared["model_fit_performed"] is False
            assert not (preparation / "fixed-fit-model.json").exists()
            with self.assertRaisesRegex(ValueError, "receipt differs"):
                calibration.run(
                    source,
                    pin,
                    selection,
                    selection_pin,
                    root / "rejected-pin",
                    preparation=preparation,
                    preparation_pin="f" * 64,
                )
            forged = root / "forged"
            shutil.copytree(preparation, forged)
            policy = json.loads((forged / "frozen-policy.json").read_bytes())
            policy["minimum_lower_event_rate"] = 0.9
            (forged / "frozen-policy.json").write_text(json.dumps(policy))
            with self.assertRaisesRegex(ValueError, "preparation policy differs"):
                calibration.run(
                    source,
                    pin,
                    selection,
                    selection_pin,
                    root / "rejected-policy",
                    preparation=forged,
                    preparation_pin=_reseal_preparation(forged),
                )
            (forged / "frozen-policy.json").write_bytes(
                (preparation / "frozen-policy.json").read_bytes()
            )
            (forged / "implementation.py").write_bytes(b"forged inference code")
            with self.assertRaisesRegex(ValueError, "code snapshot differs"):
                calibration.run(
                    source,
                    pin,
                    selection,
                    selection_pin,
                    root / "rejected-code",
                    preparation=forged,
                    preparation_pin=_reseal_preparation(forged),
                )
            with self.assertRaisesRegex(ValueError, "fixed fit"):
                list(
                    calibration.rows_for_role(source / "artist-fold-targets.jsonl.zst", "calibrate")
                )
            fitted = root / "fit.json"
            fitted.write_text("{}")
            with self.assertRaisesRegex(ValueError, "calibrator"):
                list(
                    calibration.rows_for_role(
                        source / "artist-fold-targets.jsonl.zst",
                        "development_assess",
                        fitted,
                        training.sha(fitted),
                    )
                )
            (source / "implementation.py").write_text("tampered")
            with self.assertRaisesRegex(ValueError, "sealed member"):
                run_prepared(source, pin, selection, selection_pin, root / "output")
            assert not (root / "output").exists()

    def test_preparation_keeps_real_rss_budget_enforced(self) -> None:
        with TemporaryDirectory(dir="/dev/shm") as directory:
            root = Path(directory)
            source, pin, selection, selection_pin = fixture(root)
            with (
                patch.object(training, "_peak_rss", return_value=training.MAX_RSS_BYTES + 1),
                self.assertRaisesRegex(ValueError, "exceeded RSS bound"),
            ):
                calibration.prepare(source, pin, selection, selection_pin, root / "prepared")


if __name__ == "__main__":
    unittest.main()
