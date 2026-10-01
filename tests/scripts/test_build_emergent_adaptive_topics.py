"""CLI variant identity, safety-budget isolation, and indivisible-profile behavior."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import opennoise.ml.emergent_adaptive_topics as adaptive_runtime
from opennoise.common import sha256_file
from opennoise.ml.emergent_topics import TopicSettings, load_features
from scripts.build_emergent_adaptive_topics import _fit_variant


def _write_profiles(directory: Path) -> Path:
    features = directory / "features.jsonl"
    facts = [
        {"namespace": "artist_tag", "value": value, "weight": 1, "evidence_refs": ["native:tag"]}
        for value in ("jazz", "bebop")
    ]
    features.write_text(
        "".join(
            json.dumps({"artist_mbid": f"artist-{i}", "features": facts}) + "\n" for i in range(40)
        )
    )
    return features


class AdaptiveTopicCliTests(unittest.TestCase):
    def test_expanded_cli_has_one_natural_group_and_leaves_default_unchanged(self) -> None:
        model_paths = [
            Path("src/opennoise/ml") / (name + ".py")
            for name in (
                "emergent_topics",
                "emergent_feature_graph",
                "emergent_lexical_topics",
                "emergent_adaptive_topics",
            )
        ]
        before = {path: sha256_file(path)[0] for path in model_paths}
        with TemporaryDirectory(dir=".cache") as temporary:
            directory = Path(temporary)
            features = _write_profiles(directory)
            (directory / "receipt.json").write_text('{"role":"test_source"}\n')
            reports = {}
            for variant, flags in (("expanded", ["--expanded-coarse-budget"]), ("default", [])):
                output = directory / variant
                subprocess.run(  # noqa: S603
                    [
                        sys.executable,
                        "scripts/build_emergent_adaptive_topics.py",
                        "--features",
                        str(features),
                        "--output",
                        str(output),
                        *flags,
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                report = json.loads((output / "report.json").read_text())
                reports[variant] = report
                self.assertEqual(report["coverage"]["community_count_by_level"], {"broad": 1})
                self.assertEqual(report["coverage"]["assigned_artist_count"], 40)
                self.assertEqual(report["native_genre_memberships_added"], 0)
                self.assertFalse(report["public_export_authorized"])
                self.assertEqual(report["features_sha256"], sha256_file(features)[0])
                self.assertEqual(
                    report["feature_receipt_sha256"], sha256_file(directory / "receipt.json")[0]
                )
                self.assertEqual(
                    report["research_builder_sha256"],
                    sha256_file(Path("scripts/build_emergent_adaptive_topics.py"))[0],
                )
                for filename, binding in report["files"].items():
                    self.assertEqual(sha256_file(output / filename)[0], binding["sha256"])
            self.assertEqual(
                reports["expanded"]["adaptive_coarse_cut"]["maximum_broad_communities"], 1024
            )
            self.assertEqual(
                reports["default"]["adaptive_coarse_cut"]["maximum_broad_communities"], 128
            )
            self.assertNotEqual(reports["expanded"]["revision"], reports["default"]["revision"])
            override = next(iter(reports["expanded"]["runtime_overrides"].values()))
            self.assertEqual(override["on_disk_default"], 128)
            self.assertEqual(override["process_local_value"], 1024)
            self.assertEqual(
                reports["expanded"]["predictive_evaluation_for_this_variant"],
                "not_run_construction_only_experiment",
            )
            self.assertNotIn("runtime_overrides", reports["default"])
            self.assertEqual(
                (directory / "expanded" / "assignments.jsonl").read_bytes(),
                (directory / "default" / "assignments.jsonl").read_bytes(),
            )
        self.assertEqual(before, {path: sha256_file(path)[0] for path in model_paths})
        fresh = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from opennoise.ml.emergent_adaptive_topics import MAXIMUM_BROAD_COMMUNITIES; "
                    "print(MAXIMUM_BROAD_COMMUNITIES)"
                ),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(fresh.stdout.strip(), "128")

    def test_failed_fit_restores_process_default(self) -> None:
        with TemporaryDirectory(dir=".cache") as temporary:
            data = load_features(_write_profiles(Path(temporary)))
            with (
                patch(
                    "scripts.build_emergent_adaptive_topics.fit_adaptive_topics",
                    side_effect=RuntimeError("fit interrupted"),
                ),
                self.assertRaisesRegex(RuntimeError, "fit interrupted"),
            ):
                _fit_variant(data, TopicSettings(), expanded=True)
        self.assertEqual(adaptive_runtime.MAXIMUM_BROAD_COMMUNITIES, 128)
