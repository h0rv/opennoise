"""Clean-exec isolation for selected resource-bounded unittest methods.

No production resource checks change. Parent discovery keeps method accounting;
a bounded worker protocol forwards outcomes and exact subtest identities.
"""

from __future__ import annotations

import json
import os
import selectors
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, override

if TYPE_CHECKING:
    from types import TracebackType
    from typing import Any, ClassVar

MAX_TRANSCRIPT_BYTES = 65_536
MAX_PROTOCOL_BYTES = 262_144
MAX_EVENTS = 1024
PYTHON_VERSION = [3, 13]
READ_BYTES = 8192
POLL_SECONDS = 0.05
KILL_WAIT_SECONDS = 3
_ACTIVE_METHOD_ID: str | None = None

type ExceptionInfo = tuple[type[BaseException], BaseException, TracebackType | None]


class RemoteAssertionError(AssertionError):
    """Child assertion traceback transported without traceback-object sharing."""


class RemoteTestError(RuntimeError):
    """Child error traceback transported without traceback-object sharing."""


class RemoteSubTest(unittest.TestCase):
    """Preserve a remote subtest's exact ID and displayed parameters."""

    def __init__(self, identity: str, display: str) -> None:
        """Bind the exact child subtest identity and display text."""
        super().__init__()
        self.identity = identity
        self.display = display

    @override
    def id(self) -> str:
        return self.identity

    @override
    def __str__(self) -> str:
        """Display the original child method and subtest parameters."""
        return self.display

    @override
    def shortDescription(self) -> None:
        return None


def _remote_error(event: dict[str, Any], protocol: dict[str, Any]) -> ExceptionInfo:
    """Retain original child exception text and bounded captured output."""
    exception = RemoteAssertionError if event["assertion_failure"] else RemoteTestError
    message = event["traceback"]
    captured = protocol["python_transcript"] + protocol["transcript"]
    if captured:
        message += "\nCaptured child output:\n" + captured
    return exception, exception(message), None


def _capture(
    process: subprocess.Popen[bytes], identity: str, *, timeout: float
) -> tuple[int, bytes]:
    """Drain bounded pipes and kill failed transport without orphaning workers."""
    if process.stdout is None:
        raise RuntimeError("fresh worker stdout pipe unavailable")
    started = time.monotonic()
    transcript = bytearray()
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                if time.monotonic() - started > timeout:
                    raise TimeoutError(f"fresh test exceeded {timeout} seconds: {identity}")
                for _, _events in selector.select(timeout=POLL_SECONDS):
                    raw = os.read(process.stdout.fileno(), READ_BYTES)
                    if not raw:
                        selector.unregister(process.stdout)
                        continue
                    if len(transcript) + len(raw) > MAX_TRANSCRIPT_BYTES:
                        raise RuntimeError(f"fresh worker stdout/stderr byte cap: {identity}")
                    transcript.extend(raw)
            remaining = max(0.01, timeout - (time.monotonic() - started))
            returncode = process.wait(timeout=remaining)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=KILL_WAIT_SECONDS)
    return returncode, bytes(transcript)


def _validate_events(events: object, identity: str) -> None:
    """Reject malformed outcome records before forwarding any parent callback."""
    if not isinstance(events, list) or not events or len(events) > MAX_EVENTS:
        raise RuntimeError("fresh worker events missing or oversized")
    allowed = {
        "success",
        "failure",
        "error",
        "skip",
        "expected_failure",
        "unexpected_success",
        "subtest",
    }
    for event in events:
        if (
            not isinstance(event, dict)
            or event.get("kind") not in allowed
            or not isinstance(event.get("test_id"), str)
            or not isinstance(event.get("display"), str)
            or not isinstance(event.get("assertion_failure"), bool)
        ):
            raise RuntimeError("fresh worker event malformed")
        kind = event["kind"]
        if kind not in {"subtest", "skip"} and event["test_id"] != identity:
            raise RuntimeError("fresh worker outcome method identity differs")
        if kind in {"subtest", "skip"} and not (
            event["test_id"] == identity or event["test_id"].startswith(identity + " ")
        ):
            raise RuntimeError("fresh worker subtest identity differs")
        if kind in {"failure", "error", "expected_failure"} and not isinstance(
            event.get("traceback"), str
        ):
            raise RuntimeError("fresh worker exception text missing")
        if (
            kind == "subtest"
            and event.get("traceback") is not None
            and not isinstance(event["traceback"], str)
        ):
            raise RuntimeError("fresh worker subtest exception malformed")
        if kind == "skip" and not isinstance(event.get("reason"), str):
            raise RuntimeError("fresh worker skip reason missing")


def _validate_protocol(
    protocol: dict[str, Any], identity: str, argv: list[str], worker_pid: int
) -> None:
    """Bind protocol to this exact exec, Python runtime and single method."""
    peak = protocol.get("actual_proc_vmhwm_bytes_before_protocol_serialization")
    if (
        protocol.get("schema") != "opennoise.unittest-fresh-method.v1"
        or protocol.get("test_id") != identity
        or type(protocol.get("tests_run")) is not int
        or protocol["tests_run"] != 1
        or protocol.get("started_ids") != [identity]
        or protocol.get("stopped_ids") != [identity]
        or protocol.get("python_version") != PYTHON_VERSION
        or type(protocol.get("worker_pid")) is not int
        or protocol["worker_pid"] != worker_pid
        or protocol.get("argv") != argv
        or not isinstance(protocol.get("python_transcript"), str)
        or type(peak) is not int
        or peak <= 0
    ):
        raise RuntimeError("fresh worker identity/runtime/count evidence differs")
    _validate_events(protocol.get("events"), identity)


def _execute(identity: str, *, failfast: bool, timeout: float) -> dict[str, Any]:
    """Exec one method with bounded output, protocol bytes and elapsed time."""
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="opennoise-fresh-test-") as temporary:
        protocol_path = Path(temporary) / "result.json"
        argv = [
            sys.executable,
            "-m",
            "tests.fresh_process_worker",
            "--test-id",
            identity,
            "--result",
            str(protocol_path),
        ]
        if failfast:
            argv.append("--failfast")
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONPATH"] = os.pathsep.join((str(root), str(root / "src")))
        with subprocess.Popen(  # noqa: S603 - Exact interpreter/module argv; no shell.
            argv,
            cwd=root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
        ) as process:
            worker_pid = process.pid
            returncode, transcript = _capture(process, identity, timeout=timeout)
        if returncode != 0:
            output = transcript.decode(errors="replace")
            raise RuntimeError(f"fresh worker exit {returncode}: {identity}\n{output}")
        if (
            not protocol_path.is_file()
            or protocol_path.is_symlink()
            or protocol_path.stat().st_size > MAX_PROTOCOL_BYTES
        ):
            raise RuntimeError("fresh worker protocol missing, nonregular or oversized")
        protocol = json.loads(protocol_path.read_bytes())
        if not isinstance(protocol, dict):
            raise TypeError("fresh worker protocol must be an object")
        _validate_protocol(protocol, identity, argv, worker_pid)
        protocol["parent_argv"] = argv
        protocol["worker_returncode"] = returncode
        protocol["transcript"] = transcript.decode(errors="replace")
        return protocol


def _forward(
    result: unittest.TestResult, test: unittest.TestCase, protocol: dict[str, Any]
) -> None:
    """Forward outcomes and successful, failed, error and skipped subtests."""
    for event in protocol["events"]:
        kind = event["kind"]
        if kind == "success":
            result.addSuccess(test)
        elif kind == "failure":
            result.addFailure(test, _remote_error(event, protocol))
        elif kind == "error":
            result.addError(test, _remote_error(event, protocol))
        elif kind == "skip":
            skipped = (
                test
                if event["test_id"] == test.id()
                else RemoteSubTest(event["test_id"], event["display"])
            )
            result.addSkip(skipped, event["reason"])
        elif kind == "expected_failure":
            result.addExpectedFailure(test, _remote_error(event, protocol))
        elif kind == "unexpected_success":
            result.addUnexpectedSuccess(test)
        elif kind == "subtest":
            subtest = RemoteSubTest(event["test_id"], event["display"])
            error = _remote_error(event, protocol) if event["traceback"] is not None else None
            result.addSubTest(test, subtest, error)


class FreshProcessTestCase(unittest.TestCase):
    """Opt in to one clean exec per method, keeping per-method fixture cleanup.

    Adopted classes have no class/module fixtures; their method fixtures,
    decorators and cleanups execute in the worker, with native guards intact.
    """

    fresh_process_timeout: ClassVar[float] = 120.0

    @override
    def run(self, result: unittest.TestResult | None = None) -> unittest.TestResult:
        if self.id() == _ACTIVE_METHOD_ID:
            return super().run(result)
        created_result = result is None
        if result is None:
            result = self.defaultTestResult()
            result.startTestRun()
        result.startTest(self)
        try:
            protocol = _execute(
                self.id(), failfast=result.failfast, timeout=self.fresh_process_timeout
            )
            evidence = getattr(result, "fresh_process_evidence", None)
            if evidence is None:
                evidence = []
                result.__dict__["fresh_process_evidence"] = evidence
            evidence.append(protocol)
            _forward(result, self, protocol)
        except Exception as error:  # noqa: BLE001 - Forward every transport error into TestResult.
            result.addError(self, (type(error), error, error.__traceback__))
        finally:
            result.stopTest(self)
            if created_result:
                result.stopTestRun()
        return result
