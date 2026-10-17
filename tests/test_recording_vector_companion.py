"""Exact identity and observation preservation, with verified retained fixtures."""

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import patch

from opennoise.ingest.acousticbrainz.vector_bank import build as build_bank
from opennoise.pipeline.recording_vector_companion import build, join, replay

ROOT = Path(__file__).resolve().parents[1]


class VectorCompanionTests(unittest.TestCase):
    def test_identity_and_credit_states(self) -> None:
        observation = {
            "recording_mbid": "r",
            "artist_mbid": "a",
            "credited_artist_mbids": ["a", "b"],
        }
        row: dict[str, Any] = {
            "recording_mbid": "r",
            "state": "available",
            "identity_state": "matched",
            "values": [0.0, None],
            "exact_credit": {"fact": {"recording_mbid": "r", "credited_artist_mbids": ["b", "a"]}},
        }
        self.assertEqual(join(observation, row, 2)["values"], [0.0, None])
        self.assertEqual(join(observation, None, 2)["join_state"], "not_nominated")
        missing = {**observation, "credited_artist_mbids": None}
        self.assertEqual(join(missing, row, 2)["join_state"], "missing_observation_credit")
        no_credit = {**row, "exact_credit": {"fact": None}}
        self.assertEqual(join(observation, no_credit, 2)["join_state"], "missing_companion_credit")
        wrong_artist = {**observation, "artist_mbid": "not-credited"}
        self.assertEqual(join(wrong_artist, row, 2)["join_state"], "credit_conflict")
        changed = deepcopy(row)
        changed["exact_credit"]["fact"]["credited_artist_mbids"] = ["a"]
        self.assertEqual(join(observation, changed, 2)["join_state"], "credit_conflict")
        self.assertEqual(join(observation, changed, 2)["values"], [None, None])
        changed["state"] = "missing_http_404"
        self.assertEqual(join(observation, changed, 2)["join_state"], "unavailable_source")
        changed["recording_mbid"] = "other"
        with self.assertRaises(ValueError):
            join(observation, changed, 2)

    def test_retained_replay_and_tampering(self) -> None:
        source = ROOT / "data/examples/native-sonic"
        observations = ROOT / "data/examples/recording-facts"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_bank(source, root / "bank")
            result = build(observations, source, root / "bank", root / "out")
            self.assertGreater(result["observation_rows"], 0)
            self.assertEqual(result, replay(observations, source, root / "bank", root / "out"))
            (root / "out/report.json").write_text("{}")
            with self.assertRaises(ValueError):
                replay(observations, source, root / "bank", root / "out")

    def test_metadata_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            observations = root / "observations"
            observations.mkdir()
            external = root / "external"
            external.write_text("{}")
            metadata = observations / "selection.json"
            metadata.symlink_to(external)
            with patch(
                "opennoise.pipeline.recording_vector_companion.verify_recording_fact_pack"
            ) as verifier:
                with self.assertRaises(ValueError):
                    build(observations, root / "source", root / "bank", root / "out")
                verifier.assert_not_called()
            metadata.unlink()
            with metadata.open("wb") as stream:
                stream.truncate(2_000_001)
            with patch(
                "opennoise.pipeline.recording_vector_companion.verify_recording_fact_pack"
            ) as verifier:
                with self.assertRaises(ValueError):
                    build(observations, root / "source", root / "bank", root / "out")
                verifier.assert_not_called()
