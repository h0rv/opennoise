import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.run_local_research_dev import main


class LocalResearchDevLauncherTests(unittest.TestCase):
    def test_launcher_starts_the_map_without_artist_evidence_sidecars(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative_path in _REQUIRED_INPUTS:
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            with (
                patch("scripts.run_local_research_dev.Path.cwd", return_value=root),
                patch(
                    "scripts.run_local_research_dev.subprocess.run",
                    return_value=subprocess.CompletedProcess((), 0),
                ) as run,
            ):
                self.assertEqual(main(), 0)

        environment = run.call_args.kwargs["env"]
        self.assertEqual(environment["OPENNOISE_LOCAL_RESEARCH_ARTIST_EVIDENCE_ENABLED"], "false")
        self.assertNotIn("OPENNOISE_LOCAL_RESEARCH_ARTIST_REVERSE_LOOKUP_DATABASE", environment)


_REQUIRED_INPUTS = (
    ".cache/musicbrainz-full-seed-targets/pipeline/seed-reconciliation.json",
    ".cache/musicbrainz-full-seed-targets/pipeline/peer-community-layout-v1.json",
    ".cache/musicbrainz-full-seed-targets/pipeline/peer-similarity-local-research.sqlite",
)
