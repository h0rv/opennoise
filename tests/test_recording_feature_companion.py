"""Exact native joins retain missingness and replay against both original sources."""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from opennoise.ingest.acousticbrainz.native_sonic import verify_native_sonic
from opennoise.ingest.acousticbrainz.projection import NUMERIC_PATHS
from opennoise.pipeline import recording_feature_companion as companion
from opennoise.serving.metadata import normalized_recording_dataset as normalized
from opennoise.serving.metadata.recording_facts import replay_recording_facts
from tests import test_normalized_recording_dataset as normalized_fixtures

ROOT = Path(__file__).resolve().parents[1]
FACTS = ROOT / "data/examples/recording-facts"
SONIC = ROOT / "data/examples/native-sonic"
OTHER = "11111111-1111-4111-8111-111111111111"
JOINED_ROWS = 24


def _joined_pair() -> tuple[dict[str, Any], dict[str, Any]]:
    record = next(
        row for row in verify_native_sonic(SONIC)["records"] if row["state"] == "available"
    )
    fact = record["exact_credit"]["fact"]
    return {
        "artist_mbid": fact["credited_artist_mbids"][0],
        "recording_mbid": fact["recording_mbid"],
        "credited_artist_mbids": fact["credited_artist_mbids"].copy(),
        "source": {"capture_sequence": 1, "row_index": 0},
    }, record


class RecordingFeatureCompanionTests(unittest.TestCase):
    def test_checked_in_native_join_preserves_full_denominator_and_null_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "features"
            report = companion.build_companion(FACTS, SONIC, output)
            self.assertEqual(report["observation_rows"], 36)
            self.assertEqual(
                report["join_states"],
                {"joined": 24, "no_companion_recording": 5, "unavailable_sonic_source": 7},
            )
            self.assertEqual(report["complete_feature_rows"], 0)
            self.assertEqual(
                sum(count == JOINED_ROWS for count in report["observed_rows_per_column"]), 14
            )
            self.assertEqual(sum(count == 0 for count in report["observed_rows_per_column"]), 3)
            self.assertEqual(companion.replay_companion(FACTS, SONIC, output), report)
            rows = [
                json.loads(line)
                for line in gzip.decompress(
                    (output / "features.jsonl.gz").read_bytes()
                ).splitlines()
            ]
            self.assertEqual(len(rows), 36)
            for row in rows:
                self.assertEqual(row["observed"], [value is not None for value in row["values"]])
                if row["join_state"] != "joined":
                    self.assertEqual(row["values"], [None] * len(NUMERIC_PATHS))
            self.assertFalse(report["policy"]["model_fit_performed"])

    def test_credit_conflict_quarantines_even_when_requested_artist_is_shared(self) -> None:
        observation, record = _joined_pair()
        record["exact_credit"]["fact"]["credited_artist_mbids"].append(OTHER)
        result = companion.join_observation(observation, record)
        self.assertEqual(result["join_state"], "credit_conflict")
        self.assertFalse(any(result["observed"]))
        self.assertEqual(result["companion"]["credit_fact"], record["exact_credit"]["fact"])

    def test_joint_artist_observations_remain_separate_without_cohort_inference(self) -> None:
        observation, record = _joined_pair()
        observation["credited_artist_mbids"].append(OTHER)
        record["exact_credit"]["fact"]["credited_artist_mbids"].append(OTHER)
        record["cohort_artist_mbid"] = "not a join key"
        first = companion.join_observation(observation, record)
        second_observation = copy.deepcopy(observation)
        second_observation["artist_mbid"] = OTHER
        second_observation["source"]["capture_sequence"] = 2
        second_observation["credited_artist_mbids"].reverse()
        second = companion.join_observation(second_observation, record)
        self.assertEqual(first["join_state"], "joined")
        self.assertEqual(second["join_state"], "joined")
        self.assertEqual(first["values"], second["values"])
        self.assertNotEqual(first["source"], second["source"])
        self.assertNotEqual(first["artist_mbid"], second["artist_mbid"])

    def test_unverified_identity_and_absent_credits_never_emit_features(self) -> None:
        for case, expected in (
            ("identity", "unavailable_sonic_source"),
            ("observation_credit", "missing_observation_credit"),
            ("companion_credit", "missing_companion_credit"),
        ):
            with self.subTest(case=case):
                observation, record = _joined_pair()
                if case == "identity":
                    record["identity_state"] = "mismatched"
                elif case == "observation_credit":
                    observation["credited_artist_mbids"] = None
                else:
                    record["exact_credit"]["fact"] = None
                result = companion.join_observation(observation, record)
                self.assertEqual(result["join_state"], expected)
                self.assertFalse(any(result["observed"]))

    def test_zero_is_observed_and_feature_schema_cannot_be_reordered(self) -> None:
        observation, record = _joined_pair()
        record["descriptors"][0]["value"] = 0.0
        result = companion.join_observation(observation, record)
        self.assertEqual(result["values"][0], 0.0)
        self.assertTrue(result["observed"][0])
        record["descriptors"].reverse()
        with self.assertRaisesRegex(ValueError, "descriptor order"):
            companion.join_observation(observation, record)

    def test_wrong_recording_identity_cannot_join(self) -> None:
        observation, record = _joined_pair()
        record["recording_mbid"] = OTHER
        with self.assertRaisesRegex(ValueError, "exact recording"):
            companion.join_observation(observation, record)

    def test_failed_fact_capture_stays_in_denominator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "facts"
            receipt = json.loads((FACTS / "receipt.json").read_bytes())
            missing = receipt["captures"][0]
            missing_name = Path(missing.pop("path")).name
            shutil.copytree(FACTS, source, ignore=shutil.ignore_patterns(missing_name))
            missing.update(outcome="network_error", status_code=None, bytes=0)
            missing.pop("sha256")
            receipt_path = source / "receipt.json"
            projection = replay_recording_facts(
                source, json.loads((source / "selection.json").read_bytes()), receipt["captures"]
            )
            body = json.dumps(projection).encode()
            (source / "recording-facts.json").write_bytes(body)
            receipt["projection_sha256"] = hashlib.sha256(body).hexdigest()
            receipt_path.write_text(json.dumps(receipt))
            # This altered copy is a synthetic failure fixture, never empirical evidence.
            report = companion.build_companion(source, SONIC, Path(temporary) / "output")
            self.assertEqual(report["observation_rows"], 36)
            self.assertEqual(report["join_states"]["missing_observation_credit"], 1)

    def test_normalized_adapter_replays_sources_and_keeps_zero_row_artists(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(normalized, "verify_source", return_value={"verified": True}),
            patch.object(normalized, "_check_memory", return_value=1),
        ):
            root = Path(temporary)
            source = normalized_fixtures.NormalizedDatasetTests().fixture(root)
            dataset, output = root / "dataset", root / "features"
            normalized.export_dataset(source, root, dataset)
            report = companion.build_companion(
                dataset, SONIC, output, native_source=source, root=root
            )
            self.assertEqual(report["observation_rows"], 501)
            self.assertEqual(
                sorted(sum(v.values()) for v in report["artist_join_states"].values()), [0, 501]
            )
            self.assertEqual(
                report["inputs"]["observation_kind"], "normalized_recording_observations"
            )
            self.assertEqual(
                companion.replay_companion(dataset, SONIC, output, native_source=source, root=root),
                report,
            )
            receipt = json.loads((dataset / "receipt.json").read_bytes())
            receipt["source_receipt_sha256"] = "0" * 64
            (dataset / "receipt.json").write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError, "closed contract"):
                companion.build_companion(
                    dataset, SONIC, root / "bad", native_source=source, root=root
                )

    def test_resealed_feature_tampering_cannot_pass_native_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "features"
            report = companion.build_companion(FACTS, SONIC, output)
            feature_path = output / "features.jsonl.gz"
            rows = [
                json.loads(line) for line in gzip.decompress(feature_path.read_bytes()).splitlines()
            ]
            rows[0]["values"][0] = 99999.0
            with (
                feature_path.open("wb") as raw,
                gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as stream,
            ):
                stream.write(b"".join((json.dumps(row) + "\n").encode() for row in rows))
            report["features"] = {
                "sha256": hashlib.sha256(feature_path.read_bytes()).hexdigest(),
                "bytes": feature_path.stat().st_size,
            }
            (output / "report.json").write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, "native replay"):
                companion.replay_companion(FACTS, SONIC, output)

    def test_native_byte_tampering_is_rejected_before_output_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sonic = root / "sonic"
            shutil.copytree(SONIC, sonic)
            next((sonic / "raw/sonic").iterdir()).write_bytes(b"{}")
            with self.assertRaises(ValueError):
                companion.build_companion(FACTS, sonic, root / "features")
            self.assertFalse((root / "features").exists())

    def test_budgets_fail_without_a_success_report(self) -> None:
        for control in ("MAX_ROWS", "MAX_OUTPUT_BYTES"):
            with tempfile.TemporaryDirectory() as temporary, patch.object(companion, control, 1):
                output = Path(temporary) / "features"
                with self.assertRaisesRegex(ValueError, "budget exceeded"):
                    companion.build_companion(FACTS, SONIC, output)
                self.assertFalse((output / "report.json").exists())

    def test_source_directory_and_existing_outputs_are_preserved(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside source custody"):
            companion.build_companion(FACTS, SONIC, FACTS / "forbidden")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with self.assertRaisesRegex(ValueError, "fresh"):
                companion.build_companion(FACTS, SONIC, output)


if __name__ == "__main__":
    unittest.main()
