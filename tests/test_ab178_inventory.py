"""Pre-fit yield is replayed from native custody without fitting."""

import unittest
from pathlib import Path
from unittest.mock import patch

from opennoise.ml import ab178_portable as portable
from opennoise.ml.ab178_inventory import inventory

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/examples/native-sonic"
CONTRACT = ROOT / "data/recipes/ab178-portable-v1/pilot-contract.json"


class InventoryTests(unittest.TestCase):
    def test_real_source_yield_and_no_fit(self) -> None:
        with patch.object(
            portable.engine, "fit_frame", side_effect=AssertionError("fit forbidden")
        ):
            report = inventory(
                SOURCE,
                portable.bank.digest(SOURCE / "receipt.json"),
                CONTRACT,
                portable.bank.digest(CONTRACT),
            )
        self.assertEqual(report["nominated_recordings"], 100)
        self.assertEqual(sum(report["state_counts"].values()), 100)
        self.assertEqual(report["state_counts"]["joined"], 12)
        self.assertEqual(report["state_counts"]["missing_http_404"], 45)
        self.assertEqual(report["compatible_coordinate_observation_counts"], [12] * 178)
        cohorts = report["clean_identity_verified_cohorts"]
        self.assertTrue(cohorts)
        ids = []
        for pin, group in cohorts.items():
            self.assertEqual(portable.hash_value(portable.contract(group["contract"])), pin)
            ids.extend(group["recording_mbids"])
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(report["records"]), 100)
        self.assertTrue(all("values" not in row for row in report["records"]))

    def test_external_pins_fail_before_projection(self) -> None:
        with patch.object(portable.bank, "project") as project:
            with self.assertRaisesRegex(ValueError, "receipt"):
                inventory(SOURCE, "0" * 64, CONTRACT, portable.bank.digest(CONTRACT))
            with self.assertRaisesRegex(ValueError, "pin"):
                inventory(SOURCE, portable.bank.digest(SOURCE / "receipt.json"), CONTRACT, "0" * 64)
        project.assert_not_called()
