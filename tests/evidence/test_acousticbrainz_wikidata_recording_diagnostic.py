from __future__ import annotations

import bz2
import hashlib
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from opennoise.evidence.acousticbrainz_wikidata_recording_diagnostic import (
    _HEADER,
    diagnose_positive_only_recordings,
    verify_frozen_wikidata_predictions,
    write_frozen_wikidata_predictions,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


class AcousticBrainzWikidataRecordingDiagnosticTests(unittest.TestCase):
    def test_prediction_outputs_are_rejected_from_dist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source, credit, public = self._inputs(directory)
            dist = directory / "dist"
            dist.mkdir()

            with (
                patch(
                    "opennoise.evidence.acousticbrainz_wikidata_recording_diagnostic._REPOSITORY_ROOT",
                    directory,
                ),
                self.assertRaisesRegex(ValueError, "must not be written under dist"),
            ):
                write_frozen_wikidata_predictions(
                    source, credit, public, dist / "prediction.json", directory / "receipt.json"
                )

    def test_prediction_is_written_and_verified_before_positive_labels_are_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source, credit, public = self._inputs(directory)
            prediction = directory / "prediction.json"
            receipt = directory / "receipt.json"
            calls: list[str] = []
            original_measure = (
                "opennoise.evidence.acousticbrainz_wikidata_recording_diagnostic."
                "_measure_positive_labels_after_verification"
            )

            def freeze(*_args: object) -> tuple[tuple[str, str, str], ...]:
                calls.append("credit")
                return ((self.recording, self.release_group, self.artist),)

            def direct_p136(*_args: object) -> tuple[dict[str, frozenset[str]], frozenset[str]]:
                calls.append("p136")
                return {self.artist: frozenset({"jazz"})}, frozenset({"jazz"})

            def measure(*_args: object) -> dict[str, int]:
                calls.append("labels")
                self.assertTrue(prediction.is_file())
                self.assertTrue(receipt.is_file())
                return {
                    "source_label_occurrence_count": 1,
                    "source_distinct_label_count": 1,
                    "positive_rows_with_unique_target_label": 1,
                    "positive_label_occurrences_with_unique_target_label": 1,
                    "predicted_exact_label_overlap_count": 1,
                }

            with (
                self._pinned(source, credit, public),
                patch(
                    "opennoise.evidence.acousticbrainz_wikidata_recording_diagnostic."
                    "_freeze_exact_credit_cohort",
                    freeze,
                ),
                patch(
                    "opennoise.evidence.acousticbrainz_wikidata_recording_diagnostic."
                    "_freeze_direct_p136_predictions",
                    direct_p136,
                ),
                patch(original_measure, measure),
            ):
                artifact, construction = write_frozen_wikidata_predictions(
                    source, credit, public, prediction, receipt
                )
                prediction_sha256 = hashlib.sha256(prediction.read_bytes()).hexdigest()
                diagnostic = diagnose_positive_only_recordings(
                    source, credit, public, prediction, receipt
                )

        self.assertEqual(len(artifact.predictions), 1)
        self.assertEqual(construction.prediction_file_sha256, prediction_sha256)
        self.assertEqual(calls, ["credit", "p136", "credit", "p136", "labels"])
        self.assertEqual(diagnostic.predicted_exact_label_overlap_count, 1)
        self.assertFalse(diagnostic.negative_labels_used)
        self.assertFalse(diagnostic.artist_genre_gold_created)
        self.assertFalse(diagnostic.public_or_model_use_allowed)

    def test_verifier_rejects_a_receipt_with_a_missing_forbidden_input_exclusion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source, credit, public = self._inputs(directory)
            prediction = directory / "prediction.json"
            receipt = directory / "receipt.json"

            with (
                self._pinned(source, credit, public),
                patch(
                    "opennoise.evidence.acousticbrainz_wikidata_recording_diagnostic."
                    "_freeze_exact_credit_cohort",
                    return_value=((self.recording, self.release_group, self.artist),),
                ),
                patch(
                    "opennoise.evidence.acousticbrainz_wikidata_recording_diagnostic."
                    "_freeze_direct_p136_predictions",
                    return_value=({self.artist: frozenset({"jazz"})}, frozenset({"jazz"})),
                ),
            ):
                write_frozen_wikidata_predictions(source, credit, public, prediction, receipt)
                payload = json.loads(receipt.read_text(encoding="utf-8"))
                payload["forbidden_input_exclusions"] = payload["forbidden_input_exclusions"][:-1]
                receipt.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "does not exclude every forbidden input"):
                    verify_frozen_wikidata_predictions(source, credit, public, prediction, receipt)

    recording = "00000000-0000-4000-8000-000000000001"
    release_group = "10000000-0000-4000-8000-000000000001"
    artist = "20000000-0000-4000-8000-000000000001"

    def _inputs(self, directory: Path) -> tuple[Path, Path, Path]:
        source = directory / "source.tsv.bz2"
        row = [self.recording, self.release_group, "jazz", *("" for _ in range(18))]
        source.write_bytes(
            bz2.compress(("\t".join(_HEADER) + "\n" + "\t".join(row) + "\n").encode())
        )
        credit = directory / "credit.sqlite"
        public = directory / "public.sqlite"
        credit.write_bytes(b"credit")
        public.write_bytes(b"public")
        return source, credit, public

    @staticmethod
    @contextmanager
    def _pinned(source: Path, credit: Path, public: Path) -> Iterator[None]:
        hashes = tuple(
            hashlib.sha256(path.read_bytes()).hexdigest() for path in (source, credit, public)
        )
        with patch.multiple(
            "opennoise.evidence.acousticbrainz_wikidata_recording_diagnostic",
            _SOURCE_SHA256=hashes[0],
            _CREDIT_SHA256=hashes[1],
            _PUBLIC_SHA256=hashes[2],
        ):
            yield
