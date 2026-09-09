"""Minimal SQLite helpers with explicit modes."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from pathlib import Path


def connect_readonly(path: Path) -> sqlite3.Connection:
    """Open a SQLite database read-only via URI."""
    return sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)


def connect_readwrite(path: Path) -> sqlite3.Connection:
    """Open a SQLite database read-write, creating it if needed."""
    return sqlite3.connect(f"file:{path.resolve()}?mode=rwc", uri=True)


def write_atomic_bytes(path: Path, payload: bytes) -> None:
    """Write bytes atomically via a temp file in the same directory."""
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.partial")
    try:
        temporary.write_bytes(payload)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
