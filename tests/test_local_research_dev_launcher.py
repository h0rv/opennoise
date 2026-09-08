import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.run_dev import ProductionLaunchPaths
from scripts.run_local_research_dev import main


class LocalResearchDevLauncherTests(unittest.TestCase):
    def test_launcher_passes_the_built_reverse_sidecar_to_the_loopback_server(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            production = ProductionLaunchPaths(root / "public.sqlite", root / "production-map.json")
            for relative_path in _REQUIRED_INPUTS:
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            with (
                patch("scripts.run_local_research_dev.Path.cwd", return_value=root),
                patch(
                    "scripts.run_local_research_dev.resolve_production_paths",
                    return_value=production,
                ),
                patch(
                    "scripts.run_local_research_dev.subprocess.run",
                    return_value=subprocess.CompletedProcess((), 0),
                ) as run,
            ):
                self.assertEqual(main(), 0)

        environment = run.call_args.kwargs["env"]
        self.assertEqual(
            environment["MUSIX_LOCAL_RESEARCH_ARTIST_REVERSE_LOOKUP_DATABASE"],
            str(root / _REQUIRED_INPUTS[2]),
        )
        self.assertEqual(
            environment["MUSIX_LOCAL_RESEARCH_ARTIST_REVERSE_LOOKUP_ARTIFACT"],
            str(root / _REQUIRED_INPUTS[3]),
        )
        self.assertEqual(environment["MUSIX_LOCAL_RESEARCH_ARTIST_EVIDENCE_ENABLED"], "true")

    def test_launcher_rejects_a_partial_reverse_sidecar(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            production = ProductionLaunchPaths(root / "public.sqlite", root / "production-map.json")
            for relative_path in _REQUIRED_INPUTS:
                if relative_path.endswith("artist-reverse-lookup-artifact.json"):
                    continue
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            with (
                patch("scripts.run_local_research_dev.Path.cwd", return_value=root),
                patch(
                    "scripts.run_local_research_dev.resolve_production_paths",
                    return_value=production,
                ),
                patch.object(sys, "stderr") as stderr,
            ):
                self.assertEqual(main(), 2)

        self.assertIn("requires both", stderr.write.call_args.args[0])


_REQUIRED_INPUTS = (
    ".cache/musicbrainz-release-group-evidence-candidate-v1/evidence.sqlite",
    ".cache/musicbrainz-release-group-evidence-candidate-v1/artifact.json",
    ".cache/musicbrainz-release-group-evidence-candidate-v1/artist-reverse-lookup.sqlite",
    ".cache/musicbrainz-release-group-evidence-candidate-v1/artist-reverse-lookup-artifact.json",
    ".cache/musicbrainz-full-seed-targets/pipeline/seed-reconciliation.json",
    ".cache/musicbrainz-full-seed-targets/pipeline/musicbrainz-model-adapter-report.json",
    ".cache/reviewed-alias-context-v1/artifact-v1.json",
    ".cache/reviewed-alias-combined-model-v1/receipt.json",
    ".cache/reviewed-alias-combined-model-v1/peer-similarity-local-research.sqlite",
    ".cache/musicbrainz-full-seed-targets/pipeline/peer-community-layout-v1.json",
    ".cache/musicbrainz-full-seed-targets/pipeline/peer-similarity-local-research.sqlite",
    ".cache/musicbrainz-release-group-artist-metadata-v1/metadata.sqlite",
    ".cache/musicbrainz-release-group-artist-metadata-v1/artifact.json",
)
