"""Explicit transport probes; this filename is outside test*.py discovery."""

from __future__ import annotations

import os
import sys
import threading
import unittest
from pathlib import Path

from tests import fresh_process


class ProbeTests(fresh_process.FreshProcessTestCase):
    """Exercise transport categories without entering normal test discovery."""

    def test_success(self) -> None:
        self.assertEqual(
            fresh_process._ACTIVE_METHOD_ID, self.id()  # noqa: SLF001 - Exact worker identity.
        )
        self.assertNotIn("tests.test_wikidata_source_recovery_calibration", sys.modules)
        self.assertNotIn("numpy", sys.modules)
        self.assertIn("VmHWM:", Path("/proc/self/status").read_text())
        self.addCleanup(sys.stdout.write, "fixture-cleanup-ran\n")
        sys.stdout.write("fixture-output\n")

    def test_failure(self) -> None:
        self.fail("native-fixture-failure")

    def test_error(self) -> None:
        raise ValueError("native-fixture-error")

    @unittest.skip("transport-probe-skip")
    def test_skip(self) -> None:
        self.fail("skip decorator did not run")

    @unittest.expectedFailure
    def test_expected_failure(self) -> None:
        self.fail("transport-probe-expected-failure")

    @unittest.expectedFailure
    def test_unexpected_success(self) -> None:
        self.assertTrue(True)

    def test_subtests(self) -> None:
        failure_index, error_index, skip_index = 1, 2, 3
        for index in range(4):
            with self.subTest(index=index):
                if index == failure_index:
                    self.fail("subtest-failure")
                if index == error_index:
                    raise ValueError("subtest-error")
                if index == skip_index:
                    self.skipTest("subtest-skip")

    def test_process_exit(self) -> None:
        os._exit(7)  # noqa: SLF001 - Deliberate worker transport failure.

    def test_raw_output_overflow(self) -> None:
        os.write(1, b"x" * (fresh_process.MAX_TRANSCRIPT_BYTES + 1))


class TimeoutProbe(fresh_process.FreshProcessTestCase):
    """A short transport timeout, separate from all production source budgets."""

    fresh_process_timeout = 0.05

    def test_wait(self) -> None:
        threading.Event().wait(1)


class NonIsolatedProbe(unittest.TestCase):
    """Prove that unopted-in method identities are rejected by the worker."""

    def test_noop(self) -> None:
        self.assertTrue(True)
