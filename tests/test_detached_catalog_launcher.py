"""Detached-launch wiring is verified without starting an HTTP process."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class LauncherTests(unittest.TestCase):
    def test_stale_sentinels_and_aliases_are_rejected_before_spawn(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "scripts/launch_recovered_recording_capture.py"
        )
        spec = importlib.util.spec_from_file_location("guarded_launcher", source)
        if spec is None or spec.loader is None:
            self.fail("launcher source unavailable")
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        for case in ["spawned", "finished", "alias"]:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                output = root / "pack"
                output.mkdir()
                prefix = root / "run"
                if case == "alias":
                    alias = root / "alias"
                    alias.symlink_to(output, target_is_directory=True)
                    prefix = alias / "run"
                else:
                    (root / f"run-launch-{case}.json").write_text("{}")
                invocation = root / "invocation.json"
                invocation.write_text(
                    json.dumps(
                        {
                            "argv": [sys.executable, "-u", "-c", "pass"],
                            "environment": {},
                            "output_directory": str(output),
                            "working_directory": str(root),
                        }
                    )
                )
                argv = [
                    "launch",
                    "--invocation",
                    str(invocation),
                    "--invocation-sha256",
                    hashlib.sha256(invocation.read_bytes()).hexdigest(),
                    "--prefix",
                    str(prefix),
                ]
                with (
                    patch.object(sys, "argv", argv),
                    patch.object(subprocess, "Popen") as process,
                    self.assertRaises((ValueError, FileExistsError)),
                ):
                    launcher.main()
                process.assert_not_called()

    def test_detached_no_pty_regular_exclusive_logs_and_durable_prelaunch(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "scripts/launch_recovered_recording_capture.py"
        )
        spec = importlib.util.spec_from_file_location("catalog_launcher", source)
        if spec is None or spec.loader is None:
            self.fail("launcher source unavailable")
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "pack"
            output.mkdir()
            invocation = root / "invocation.json"
            invocation.write_text(
                json.dumps(
                    {
                        "argv": [sys.executable, "-u", "-c", "pass"],
                        "environment": {"PYTHONUNBUFFERED": "1"},
                        "working_directory": str(root),
                        "output_directory": str(output),
                    }
                )
            )
            prefix = root / "run"
            argv = [
                "launch",
                "--invocation",
                str(invocation),
                "--invocation-sha256",
                hashlib.sha256(invocation.read_bytes()).hexdigest(),
                "--prefix",
                str(prefix),
            ]

            def spawned(*_args: object, **_kwargs: object) -> SimpleNamespace:
                self.assertTrue((root / "run-launch-requested.json").is_file())
                return SimpleNamespace(pid=31415)

            with (
                patch.object(sys, "argv", argv),
                patch.object(subprocess, "Popen", side_effect=spawned) as process,
                patch("os.getsid", return_value=31415),
            ):
                launcher.main()
            options = process.call_args.kwargs
            self.assertTrue(options["start_new_session"])
            self.assertEqual(options["stdin"], subprocess.DEVNULL)
            for field in ["stdout", "stderr"]:
                path = Path(options[field].name)
                self.assertTrue(stat.S_ISREG(path.stat().st_mode))
                self.assertNotIn(output, path.parents)
            proof = json.loads((root / "run-launch-spawned.json").read_bytes())
            self.assertEqual(proof["session_id"], 31415)
            wrapper = (root / "run-detached-wrapper.sh").read_text()
            self.assertIn("run-launch-spawned.json", wrapper)
            self.assertIn("</dev/null", wrapper)
            self.assertIn("capture_rc=$?", wrapper)
            # Earlier launch artifacts cannot be overwritten by a repeat launch.
            with patch.object(sys, "argv", argv), self.assertRaises(FileExistsError):
                launcher.main()


if __name__ == "__main__":
    unittest.main()
