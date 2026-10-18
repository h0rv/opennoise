"""Real retained input export and exact-credit aggregation boundaries."""

import json
import tempfile
import unittest
from pathlib import Path
from typing import override
from unittest.mock import patch
from uuid import UUID

from opennoise.ml import ab178_portable as portable
from opennoise.ml.ab178_artist_export import aggregate, export_artists

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/examples/native-sonic"
CONTRACT = ROOT / "data/recipes/ab178-portable-v1/pilot-contract.json"


class ArtistExportTests(unittest.TestCase):
    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.bank = cls.root / "bank"
        cls.bundle = cls.root / "bundle"
        cls.source_pin = portable.bank.digest(SOURCE / "receipt.json")
        portable.bank.build(SOURCE, cls.bank)
        cls.pin = portable.export_bundle(
            SOURCE,
            cls.source_pin,
            cls.bank,
            portable.bank.digest(cls.bank / "receipt.json"),
            CONTRACT,
            portable.bank.digest(CONTRACT),
            0,
            cls.bundle,
        )

    def test_real_source_export_preserves_abstentions_and_never_refits(self) -> None:
        output = self.root / "export"
        with patch.object(portable.engine, "fit_frame", side_effect=AssertionError("no fit")):
            pin = export_artists(SOURCE, self.source_pin, self.bundle, self.pin, output)
            second = self.root / "replay"
            self.assertEqual(
                pin, export_artists(SOURCE, self.source_pin, self.bundle, self.pin, second)
            )
        self.assertEqual(
            (output / "artists.json").read_bytes(), (second / "artists.json").read_bytes()
        )
        report = json.loads((output / "artists.json").read_bytes())
        self.assertEqual(report["counts"]["nominated_recordings"], 100)
        self.assertEqual(report["counts"]["verified_credited_artists"], 17)
        self.assertEqual(report["counts"]["recordings_without_verified_credits"], 45)
        self.assertEqual(report["counts"]["emitted_by_query_role"]["heldout"], 0)
        self.assertEqual(report["counts"]["emitted_by_query_role"]["fit_member"], 4)
        self.assertTrue(all(not row["neighbor_evidence"]["heldout"] for row in report["artists"]))
        self.assertEqual(report["scope"]["genre_state"], "unsupported_by_ab178_model")
        self.assertEqual(report["scope"]["genre_memberships"], [])
        unknown = [r for r in report["recordings"] if not r["credited_artist_mbids"]]
        self.assertTrue(all(r["query_role"] == "unresolved_identity" for r in unknown))
        self.assertTrue(all("vector" not in row for row in report["recordings"]))

    def test_wrong_external_pin_never_publishes_output(self) -> None:
        for name, source_pin, bundle_pin in (
            ("bad-source", "0" * 64, self.pin),
            ("bad-bundle", self.source_pin, "0" * 64),
        ):
            output = self.root / name
            with self.assertRaises(ValueError):
                export_artists(SOURCE, source_pin, self.bundle, bundle_pin, output)
            self.assertFalse(output.exists())

    def test_every_verified_credit_receives_evidence_without_selection_join(self) -> None:
        a, b, c, nomination = [str(UUID(int=i)) for i in range(1, 5)]
        body = {
            "frame": {"heldout_fold": 0},
            "roster": [
                {
                    "recording_mbid": "query",
                    "credited_artist_mbids": [a, b],
                    "cohort_artist_mbid": nomination,
                    "evidence": {"identity_state": "matched"},
                },
                {"recording_mbid": "candidate", "credited_artist_mbids": [c]},
                {"recording_mbid": "unknown", "credited_artist_mbids": None},
            ],
        }
        result = {
            "rows": [
                {
                    "recording_mbid": "query",
                    "fold": 0,
                    "fit_member": False,
                    "outcome": "emitted",
                    "neighbors": [{"recording_mbid": "candidate", "distance": 1.25}],
                },
                {
                    "recording_mbid": "unknown",
                    "fold": 0,
                    "fit_member": False,
                    "outcome": "missing_http_404",
                    "neighbors": [],
                },
            ]
        }
        report = aggregate(body, result)
        artists = {row["artist_mbid"]: row for row in report["artists"]}
        self.assertNotIn(nomination, artists)
        for artist in (a, b):
            edge = artists[artist]["neighbor_evidence"]["heldout"][0]
            self.assertEqual(edge["artist_mbid"], c)
            self.assertEqual(edge["query_recording_count"], 1)
            self.assertEqual(edge["observations"][0]["distance"], 1.25)
        self.assertEqual(report["recordings"][1]["query_role"], "unresolved_identity")

    def test_credit_bound_is_not_silently_truncated(self) -> None:
        body = {
            "roster": [
                {
                    "recording_mbid": "query",
                    "credited_artist_mbids": [str(UUID(int=i)) for i in range(17)],
                }
            ]
        }
        with self.assertRaisesRegex(ValueError, "credit bound"):
            aggregate(body, {"rows": []})
