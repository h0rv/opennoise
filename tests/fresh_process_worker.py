"""Bounded one-method unittest transport worker; production guards stay intact."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import traceback
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

from tests import fresh_process

if TYPE_CHECKING:
    from typing import Any


class BoundedTranscript(io.StringIO):
    """Bound Python stdout/stderr before importing the selected test module."""

    def __init__(self) -> None:
        super().__init__()
        self.encoded_bytes = 0

    def write(self, value: str) -> int:
        addition = len(value.encode())
        if self.encoded_bytes + addition > fresh_process.MAX_TRANSCRIPT_BYTES:
            raise RuntimeError("fresh test Python transcript byte cap exceeded")
        self.encoded_bytes += addition
        return super().write(value)


class RecordedResult(unittest.TestResult):
    """Record categories and identities without retaining traceback objects."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict[str, Any]] = []
        self.started_ids: list[str] = []
        self.stopped_ids: list[str] = []
        self.event_bytes = 0

    def startTest(self, test: unittest.TestCase) -> None:
        super().startTest(test)
        self.started_ids.append(test.id())

    def stopTest(self, test: unittest.TestCase) -> None:
        self.stopped_ids.append(test.id())
        super().stopTest(test)

    def _record(
        self,
        kind: str,
        test: unittest.TestCase,
        err: fresh_process.ExceptionInfo | None = None,
        **fields: object,
    ) -> None:
        if len(self.events) >= fresh_process.MAX_EVENTS:
            raise RuntimeError("fresh test event cap exceeded")
        event = {
            "kind": kind,
            "test_id": test.id(),
            "display": str(test),
            "traceback": "".join(traceback.format_exception(*err)) if err is not None else None,
            "assertion_failure": bool(
                err is not None and issubclass(err[0], test.failureException)
            ),
            **fields,
        }
        addition = len(json.dumps(event, ensure_ascii=False).encode())
        if self.event_bytes + addition > fresh_process.MAX_PROTOCOL_BYTES // 2:
            raise RuntimeError("fresh test cumulative event byte cap exceeded")
        self.event_bytes += addition
        self.events.append(event)
        if self.failfast and (
            kind in {"error", "failure", "unexpected_success"}
            or (kind == "subtest" and err is not None)
        ):
            self.stop()

    def addSuccess(self, test: unittest.TestCase) -> None:
        self._record("success", test)

    def addError(self, test: unittest.TestCase, err: fresh_process.ExceptionInfo) -> None:
        self._record("error", test, err)

    def addFailure(self, test: unittest.TestCase, err: fresh_process.ExceptionInfo) -> None:
        self._record("failure", test, err)

    def addSkip(self, test: unittest.TestCase, reason: str) -> None:
        self._record("skip", test, reason=reason)

    def addExpectedFailure(self, test: unittest.TestCase, err: fresh_process.ExceptionInfo) -> None:
        self._record("expected_failure", test, err)

    def addUnexpectedSuccess(self, test: unittest.TestCase) -> None:
        self._record("unexpected_success", test)

    def addSubTest(
        self,
        test: unittest.TestCase,
        subtest: unittest.TestCase,
        err: fresh_process.ExceptionInfo | None,
    ) -> None:
        self._record("subtest", subtest, err)


def _single(suite: unittest.TestSuite) -> unittest.TestCase:
    """Reject loader failures, multiple identities and non-test suite entries."""
    tests = list(suite)
    if len(tests) != 1:
        raise ValueError("worker must load exactly one method")
    test = tests[0]
    if isinstance(test, unittest.TestSuite):
        return _single(test)
    if not isinstance(test, unittest.TestCase):
        raise ValueError("worker loaded a non-test entry")
    return test


def main() -> None:
    """Publish bounded protocol transport, including faithful failed outcomes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-id", required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--failfast", action="store_true")
    args = parser.parse_args()
    if list(sys.version_info[:2]) != fresh_process.PYTHON_VERSION:
        raise ValueError("resource-sensitive fixtures require actual Python3.13")
    transcript = BoundedTranscript()
    with contextlib.redirect_stdout(transcript), contextlib.redirect_stderr(transcript):
        test = _single(unittest.defaultTestLoader.loadTestsFromName(args.test_id))
        if test.id() != args.test_id or not isinstance(test, fresh_process.FreshProcessTestCase):
            raise ValueError("worker exact opted-in test identity differs")
        fresh_process._ACTIVE_METHOD_ID = args.test_id  # noqa: SLF001 - Exact dispatch guard.
        result = RecordedResult()
        result.failfast = args.failfast
        try:
            test.run(result)
        finally:
            fresh_process._ACTIVE_METHOD_ID = None  # noqa: SLF001 - Clear exact dispatch.
    peaks = [
        int(line.split()[1]) * 1024
        for line in Path("/proc/self/status").read_text().splitlines()
        if line.startswith("VmHWM:")
    ]
    if len(peaks) != 1:
        raise ValueError("actual Linux worker high-water evidence unavailable")
    protocol = {
        "schema": "opennoise.unittest-fresh-method.v1",
        "test_id": args.test_id,
        "tests_run": result.testsRun,
        "started_ids": result.started_ids,
        "stopped_ids": result.stopped_ids,
        "events": result.events,
        "python_version": list(sys.version_info[:2]),
        "worker_pid": os.getpid(),
        "argv": list(sys.orig_argv),
        "actual_proc_vmhwm_bytes_before_protocol_serialization": peaks[0],
        "python_transcript": transcript.getvalue(),
    }
    raw = (json.dumps(protocol, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    if len(raw) > fresh_process.MAX_PROTOCOL_BYTES:
        raise ValueError("fresh worker protocol byte cap exceeded")
    with args.result.open("xb") as stream:
        if stream.write(raw) != len(raw):
            raise OSError("short fresh worker protocol write")
        stream.flush()
        os.fsync(stream.fileno())


if __name__ == "__main__":
    main()
