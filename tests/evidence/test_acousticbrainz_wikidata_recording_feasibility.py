from __future__ import annotations

import bz2
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opennoise.evidence.acousticbrainz_wikidata_recording_feasibility import (
    _HEADER,
    audit_acousticbrainz_wikidata_recording_feasibility,
)


class AcousticBrainzWikidataRecordingFeasibilityTests(unittest.TestCase):
    def test_freezes_credit_and_prediction_cohorts_before_opening_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "source.tsv.bz2"
            credit = directory / "credit.sqlite"
            public = directory / "public.sqlite"
            credit.write_bytes(b"credit")
            public.write_bytes(b"public")
            row = [
                "00000000-0000-4000-8000-000000000001",
                "10000000-0000-4000-8000-000000000001",
                "jazz",
                *("" for _ in range(18)),
            ]
            source.write_bytes(
                bz2.compress(("\t".join(_HEADER) + "\n" + "\t".join(row) + "\n").encode())
            )
            hashes = tuple(
                hashlib.sha256(path.read_bytes()).hexdigest() for path in (source, credit, public)
            )
            calls: list[str] = []

            def freeze(*_args: object) -> tuple[tuple[str, str, str], ...]:
                calls.append("credit")
                return ((row[0], row[1], "artist-mbid"),)

            def predictions(*_args: object) -> tuple[dict[str, frozenset[str]], dict[str, int]]:
                calls.append("prediction")
                return {"artist-mbid": frozenset({"jazz"})}, {"jazz": 1}

            with (
                patch(
                    "opennoise.evidence.acousticbrainz_wikidata_recording_feasibility._SOURCE_SHA256",
                    hashes[0],
                ),
                patch(
                    "opennoise.evidence.acousticbrainz_wikidata_recording_feasibility._CREDIT_SHA256",
                    hashes[1],
                ),
                patch(
                    "opennoise.evidence.acousticbrainz_wikidata_recording_feasibility._PUBLIC_SHA256",
                    hashes[2],
                ),
                patch(
                    "opennoise.evidence.acousticbrainz_wikidata_recording_feasibility._freeze_exact_credit_cohort",
                    freeze,
                ),
                patch(
                    "opennoise.evidence.acousticbrainz_wikidata_recording_feasibility._freeze_wikidata_predictions",
                    predictions,
                ),
            ):
                report = audit_acousticbrainz_wikidata_recording_feasibility(source, credit, public)

        self.assertEqual(calls, ["credit", "prediction"])
        self.assertEqual(report.frozen_recording_count, 1)
        self.assertEqual(report.source_label_occurrence_count, 1)
        self.assertEqual(report.direct_wikidata_p136_exact_label_hits, 1)
        self.assertFalse(report.independent_artist_genre_gold_ready)
        self.assertTrue(report.source_labels_interpreted_after_freeze)

    def test_rejects_unpinned_inputs_before_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "untrusted.tsv.bz2"
            source.write_bytes(bz2.compress(b"untrusted"))
            with self.assertRaisesRegex(ValueError, "pinned hashes"):
                audit_acousticbrainz_wikidata_recording_feasibility(source, source, source)
