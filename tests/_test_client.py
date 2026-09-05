"""Test-client support for environments without cross-thread socket wakeups."""

from __future__ import annotations

import asyncio
import selectors
import unittest
from typing import TYPE_CHECKING, Any, override

from litestar.testing import TestClient

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from litestar import Litestar


class _PollingSelector(selectors.SelectSelector):
    """Poll briefly when a sandbox drops selector self-pipe wakeups."""

    @override
    def select(self, timeout: float | None = None) -> list[tuple[selectors.SelectorKey, int]]:
        """Bound idle waits so portal callbacks are observed without a socket wakeup."""
        bounded_timeout = 0.01 if timeout is None else min(timeout, 0.01)
        return super().select(bounded_timeout)


def _polling_loop_factory() -> asyncio.AbstractEventLoop:
    """Create an asyncio loop that does not require cross-thread wakeups."""
    return asyncio.SelectorEventLoop(_PollingSelector())


def run_async[ResultT](coroutine: Coroutine[Any, Any, ResultT]) -> ResultT:
    """Run one async test operation without relying on cross-thread wakeups."""
    with asyncio.Runner(loop_factory=_polling_loop_factory) as runner:
        return runner.run(coroutine)


class PollingIsolatedAsyncioTestCase(unittest.IsolatedAsyncioTestCase):
    """Use polling event loops for async tests in restricted runners."""

    loop_factory = staticmethod(_polling_loop_factory)


def create_test_client(app: Litestar) -> TestClient[Litestar]:
    """Create a Litestar client with bounded polling for the test sandbox."""
    return TestClient(app, backend_options={"loop_factory": _polling_loop_factory})
