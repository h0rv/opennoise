"""Small leakage, scoring, artifact freezing, and denominator regression checks."""

from __future__ import annotations

import hashlib
import io
import itertools
import json
import unittest
from collections import Counter, defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID

import zstandard

from opennoise.ml import wikidata_training_experiment as training


def exact_identity(index: int, split: str) -> str:
    """Find an exact UUID in the original split with an independent hash replay."""
    accepted = 0
    train_boundary = 6
    calibration_boundary = 8
    for number in itertools.count(1):
        mbid = str(UUID(int=number))
        bucket = (
            int(
                hashlib.sha256(
                    f"opennoise-artist-completion-v1-frozen:{mbid}".encode()
                ).hexdigest(),
                16,
            )
            % 10
        )
        actual = (
            "train"
            if bucket < train_boundary
            else "calibration"
            if bucket < calibration_boundary
            else "confirmation"
        )
        if actual == split:
            if accepted == index:
                return mbid
            accepted += 1
    raise AssertionError("identity enumeration must terminate")


def raw_row(index: int, labels: tuple[str, ...], split: str = "train") -> dict[str, object]:
    """Independently generate the saved original mask for an exact identity."""
    mbid = exact_identity(index, split)
    target = min(
        labels,
        key=lambda qid: hashlib.sha256(
            f"opennoise-artist-completion-v1-frozen:mask:{mbid}:{qid}".encode()
        ).digest(),
        default=None,
    )
    return {
        "artist_mbid": mbid,
        "split": split,
        "observed_genre_qids": labels,
        "masked_observed_target": target,
        "seed_genre_qids": tuple(qid for qid in labels if qid != target),
    }


def source_pack(root: Path, rows: list[dict[str, object]]) -> None:
    """Write a closed source inventory with uninterpretable outer label bytes."""
    payload = b"".join((json.dumps(row) + "\n").encode() for row in rows)
    for split in ("calibration", "confirmation"):
        payload += (
            '{"artist_mbid":"'
            + exact_identity(0, split)
            + '","split":"'
            + split
            + '","observed_genre_qids":NEVER_DECODE_THIS}\n'
        ).encode()
    path = root / "artist-fold-targets.jsonl.zst"
    path.write_bytes(zstandard.ZstdCompressor().compress(payload))
    (root / "receipt.json").write_text(
        json.dumps(
            {"files": {path.name: {"bytes": path.stat().st_size, "sha256": training.sha(path)}}}
        )
    )


class TrainingExperimentTests(unittest.TestCase):
    def test_routes_ignore_nested_and_escaped_split_keys(self) -> None:
        payload = {
            "artist_mbid": exact_identity(0, "train"),
            "nested": {"split": "confirmation"},
            "text": 'a ,"split":"confirmation" string',
            "split": "train",
        }
        assert training.route(json.dumps(payload).encode()) == "train"
        with self.assertRaisesRegex(ValueError, "duplicate"):
            training.route(b'{"split":"train","split":"confirmation"}')

    def test_outer_labels_are_never_json_decoded(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_pack(root, [raw_row(0, ("Q1", "Q2"))])
            rows, routes = training.load_training(root / "artist-fold-targets.jsonl.zst")
        assert len(rows) == 1
        assert routes == {"calibration": 1, "confirmation": 1, "train": 1}
        assert rows[0].labels == ("Q1", "Q2")

    def test_saved_masks_and_exact_ids_are_validated(self) -> None:
        raw = raw_row(0, ("Q1", "Q2"))
        raw["masked_observed_target"] = "Q999"
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_pack(root, [raw])
            with self.assertRaisesRegex(ValueError, "mask differs"):
                training.load_training(root / "artist-fold-targets.jsonl.zst")
        assert training.inner_fold(str(UUID(int=1))) == training.inner_fold(str(UUID(int=1)))

    def test_held_innerfold_cannot_change_support_pairs_or_vocabulary(self) -> None:
        rows = [
            training.Row(str(UUID(int=index + 1)), ("Q1", "Q2"), (), None, 1) for index in range(5)
        ]
        held = training.Row(str(UUID(int=100)), ("Q999",), (), "Q999", 0)
        before = training.fit(rows, 0)
        after = training.fit([*rows, held], 0)
        assert before == after
        assert after.support == {"Q1": 5, "Q2": 5}
        assert after.pairs == {"Q1": {"Q2": 5}, "Q2": {"Q1": 5}}

    def test_smoothing_aggregation_and_prior_blend_change_ranks(self) -> None:
        model = training.Counts(
            100,
            Counter({"Q1": 10, "Q2": 10, "Q3": 80, "Q4": 20}),
            {"Q1": Counter({"Q3": 1, "Q4": 8}), "Q2": Counter({"Q3": 6})},
            ("Q1", "Q2", "Q3", "Q4"),
        )
        seeds = ("Q1", "Q2")
        assert training.rank(model, seeds, training.ARMS[0]) == ("Q3", "Q4")
        assert training.rank(model, seeds, training.Arm("max", 1, "max", 1)) == ("Q4", "Q3")
        assert training.rank(model, seeds, training.Arm("mean", 1, "mean", 1)) == ("Q3", "Q4")
        assert training.rank(model, seeds, training.Arm("smooth", 100, "max", 1)) == ("Q3", "Q4")
        assert training.rank(model, seeds, training.Arm("blend", 1, "max", 0.25)) == ("Q3", "Q4")

    def test_cold_seeds_use_prior_and_candidate_ties_use_exact_qid(self) -> None:
        model = training.Counts(10, Counter({"Q1": 5, "Q2": 5}), {}, ("Q1", "Q2"))
        for arm in training.ARMS:
            assert training.rank(model, (), arm) == ("Q1", "Q2")
            assert training.rank(model, ("Q999",), arm) == ("Q1", "Q2")
            assert training.rank(model, ("Q1",), arm) == ("Q2",)

    def test_missing_unseen_sparse_and_rare_queries_stay_visible(self) -> None:
        model = training.Counts(10, Counter({"Q1": 5, "Q2": 2}), {}, ("Q1",))
        rows = [
            training.Row(str(UUID(int=1)), (), (), None, 0),
            training.Row(str(UUID(int=2)), ("Q999",), (), "Q999", 0),
            training.Row(str(UUID(int=3)), ("Q2",), (), "Q2", 0),
        ]
        totals: dict[str, dict[str, Counter[str]]] = {
            arm.name: defaultdict(Counter) for arm in training.ARMS
        }
        events = list(training._fold_events(rows, 0, model, totals))  # noqa: SLF001
        metrics = training.summarize(totals[training.ARMS[0].name]["all"])
        assert len(events) == len(rows)
        assert metrics["all_exact_training_queries"] == len(rows)
        assert metrics["masked_source_positive_queries"] == len(rows) - 1
        assert metrics["missing_source_target_unknown_queries"] == 1
        assert metrics["recall"]["10"] == 0
        assert "unseen_target" in events[1]["strata"]
        assert "rare_target_1_to_10_innertrain_artists" in events[2]["strata"]
        assert "target_outside_innertrain_vocabulary" in events[2]["strata"]

    def test_freeze_precedes_training_read_and_all_queries_are_serialized(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            output = root / "output"
            sample_size = 100
            source_pack(source, [raw_row(index, ("Q1", "Q2")) for index in range(sample_size)])
            original_loader = training.load_training

            def guarded_loader(path: Path) -> tuple[list[training.Row], dict[str, int]]:
                policy = json.loads((output / "frozen-policy.json").read_bytes())
                assert policy["input_sha256"] == training.sha(path)
                assert policy["implementation_sha256"] == training.sha(output / "implementation.py")
                return original_loader(path)

            with (
                patch.object(training, "load_training", side_effect=guarded_loader),
                patch.object(training, "_bounds", return_value=1),
            ):
                report = training.experiment(source, output, training.sha(source / "receipt.json"))
            assert report["all_original_training_queries"] == sample_size
            assert report["selected_arm_training_only"] == "unconditional_prior"
            assert report["confirmation_evaluation"] is False
            assert report["selected_model_refit"] is False
            assert report["routing_counts_only"] == {
                "train": 100,
                "calibration": 1,
                "confirmation": 1,
            }
            with (
                (output / "innerfold-queries.jsonl.zst").open("rb") as raw,
                zstandard.ZstdDecompressor().stream_reader(raw) as stream,
            ):
                saved = [json.loads(line) for line in io.TextIOWrapper(stream)]
            assert len(saved) == sample_size
            assert len({row["artist_mbid"] for row in saved}) == sample_size
            receipt = json.loads((output / "receipt.json").read_bytes())
            assert set(receipt["files"]) == {
                "implementation.py",
                "frozen-policy.json",
                "innerfold-queries.jsonl.zst",
                "report.json",
            }
            with self.assertRaises(FileExistsError):
                training.experiment(source, output, training.sha(source / "receipt.json"))

    def test_rehashed_forged_train_route_is_rejected_before_label_decode(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            raw = raw_row(0, ("Q999",), "confirmation")
            raw["split"] = "train"
            source_pack(root, [raw])
            with self.assertRaisesRegex(ValueError, "original exact-UUID outer split"):
                training.experiment(root, root / "output", training.sha(root / "receipt.json"))

    def test_pinned_receipt_mismatch_creates_no_output(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_pack(root, [raw_row(0, ("Q1",))])
            output = root / "output"
            with self.assertRaisesRegex(ValueError, "pinned expected SHA256"):
                training.experiment(root, output, "0" * 64)
            assert not output.exists()

    def test_decoded_input_budget_is_bounded(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_pack(root, [raw_row(0, ("Q1",))])
            with (
                patch.object(training, "MAX_DECODED_BYTES", 1),
                self.assertRaisesRegex(ValueError, "routing bounds"),
            ):
                training.load_training(root / "artist-fold-targets.jsonl.zst")

    def test_memory_and_output_bounds_fail_closed(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory)
            with (
                patch.object(training, "_peak_rss", return_value=training.MAX_RSS_BYTES + 1),
                self.assertRaisesRegex(ValueError, "RSS bound"),
            ):
                training._bounds(output)  # noqa: SLF001
            (output / "small.json").write_bytes(b"{}")
            with (
                patch.object(training, "_peak_rss", return_value=1),
                patch.object(training, "MAX_OUTPUT_BYTES", 1),
                self.assertRaisesRegex(ValueError, "output byte bound"),
            ):
                training._bounds(output)  # noqa: SLF001
