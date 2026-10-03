"""Check actual exec transport categories, exact identity, bounds and subtests."""

from __future__ import annotations

import os
import unittest

from tests import fresh_process
from tests import fresh_process_fixtures as fixtures


class CountingResult(unittest.TestResult):
    """Observe success and subtests alongside ordinary unittest accounting."""

    def __init__(self) -> None:
        super().__init__()
        self.successful_ids: list[str] = []
        self.subtest_ids: list[str] = []

    def addSuccess(self, test: unittest.TestCase) -> None:
        self.successful_ids.append(test.id())
        super().addSuccess(test)

    def addSubTest(
        self,
        test: unittest.TestCase,
        subtest: unittest.TestCase,
        err: fresh_process.ExceptionInfo | None,
    ) -> None:
        self.subtest_ids.append(subtest.id())
        super().addSubTest(test, subtest, err)


def run_probe(name: str, *, failfast: bool = False) -> CountingResult:
    """Capture deliberate probe outcomes without adding them to discovery."""
    result = CountingResult()
    result.failfast = failfast
    fixtures.ProbeTests(name).run(result)
    return result


class FreshProcessTests(unittest.TestCase):
    def test_success_failure_error_identity_counts_and_cleanup(self) -> None:
        success = run_probe("test_success")
        self.assertEqual(success.testsRun, 1)
        self.assertTrue(success.wasSuccessful())
        evidence = success.__dict__["fresh_process_evidence"]
        protocol = evidence[0]
        identity = "tests.fresh_process_fixtures.ProbeTests.test_success"
        self.assertEqual(success.successful_ids, [identity])
        self.assertEqual(protocol["test_id"], identity)
        self.assertEqual(protocol["started_ids"], [identity])
        self.assertEqual(protocol["stopped_ids"], [identity])
        self.assertEqual(protocol["python_version"], [3, 13])
        self.assertNotEqual(protocol["worker_pid"], os.getpid())
        self.assertEqual(protocol["argv"], protocol["parent_argv"])
        self.assertGreater(protocol["actual_proc_vmhwm_bytes_before_protocol_serialization"], 0)
        self.assertIn("fixture-output", protocol["python_transcript"])
        self.assertIn("fixture-cleanup-ran", protocol["python_transcript"])
        failure = run_probe("test_failure")
        self.assertEqual(failure.testsRun, 1)
        self.assertEqual(len(failure.failures), 1)
        self.assertEqual(failure.errors, [])
        self.assertIn("native-fixture-failure", failure.failures[0][1])
        error = run_probe("test_error")
        self.assertEqual(error.testsRun, 1)
        self.assertEqual(len(error.errors), 1)
        self.assertEqual(error.failures, [])
        self.assertIn("ValueError: native-fixture-error", error.errors[0][1])

    def test_skip_expected_failure_and_unexpected_success(self) -> None:
        skipped = run_probe("test_skip")
        self.assertEqual(skipped.testsRun, 1)
        self.assertEqual(len(skipped.skipped), 1)
        self.assertEqual(skipped.skipped[0][1], "transport-probe-skip")
        expected = run_probe("test_expected_failure")
        self.assertEqual(expected.testsRun, 1)
        self.assertEqual(len(expected.expectedFailures), 1)
        self.assertTrue(expected.wasSuccessful())
        unexpected = run_probe("test_unexpected_success")
        self.assertEqual(unexpected.testsRun, 1)
        self.assertEqual(len(unexpected.unexpectedSuccesses), 1)
        self.assertFalse(unexpected.wasSuccessful())

    def test_successful_failed_error_and_skipped_subtests_forward(self) -> None:
        result = run_probe("test_subtests")
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(len(result.subtest_ids), 3)
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(len(result.skipped), 1)
        self.assertIn("(index=0)", result.subtest_ids[0])
        self.assertIn("(index=1)", result.failures[0][0].id())
        self.assertIn("(index=2)", result.errors[0][0].id())
        self.assertIn("(index=3)", result.skipped[0][0].id())
        evidence = result.__dict__["fresh_process_evidence"]
        self.assertEqual(len(evidence[0]["events"]), 4)

    def test_subtest_failfast_stops_remaining_children_outcomes(self) -> None:
        result = run_probe("test_subtests", failfast=True)
        self.assertEqual(result.testsRun, 1)
        self.assertTrue(result.shouldStop)
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.skipped, [])
        self.assertEqual(len(result.subtest_ids), 2)

    def test_nonzero_exit_and_unopted_identity_fail_honestly(self) -> None:
        result = run_probe("test_process_exit")
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("fresh worker exit 7", result.errors[0][1])
        with self.assertRaises(RuntimeError):
            fresh_process._execute(  # noqa: SLF001 - Exercise exact transport admission.
                "tests.fresh_process_fixtures.NonIsolatedProbe.test_noop",
                failfast=False,
                timeout=5,
            )

    def test_protocol_rejects_forged_pid_boolean_count_and_foreign_subtest(self) -> None:
        result = run_probe("test_success")
        protocol = result.__dict__["fresh_process_evidence"][0]
        identity = protocol["test_id"]
        argv = protocol["parent_argv"]
        worker_pid = protocol["worker_pid"]
        for fields in (
            {"worker_pid": worker_pid + 1},
            {"tests_run": True},
            {
                "events": [
                    {
                        "kind": "subtest",
                        "test_id": "foreign.case.test_method (index=0)",
                        "display": "foreign subtest",
                        "assertion_failure": False,
                        "traceback": None,
                    }
                ]
            },
        ):
            with self.subTest(fields=fields), self.assertRaises(RuntimeError):
                fresh_process._validate_protocol(  # noqa: SLF001 - Exact protocol rejection.
                    dict(protocol, **fields), identity, argv, worker_pid
                )

    def test_raw_output_cap_and_timeout_return_errors(self) -> None:
        overflow = run_probe("test_raw_output_overflow")
        self.assertEqual(overflow.testsRun, 1)
        self.assertEqual(len(overflow.errors), 1)
        self.assertIn("stdout/stderr byte cap", overflow.errors[0][1])
        result = CountingResult()
        fixtures.TimeoutProbe("test_wait").run(result)
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("fresh test exceeded", result.errors[0][1])


if __name__ == "__main__":
    unittest.main()
