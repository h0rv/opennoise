"""Canonical JSON hashing for sealed artifacts."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from opennoise.types import (
    Sha256,  # noqa: TC001  # Pydantic resolves this Annotated alias at runtime.
)

if TYPE_CHECKING:
    from pathlib import Path


def canonical_json(value: object) -> bytes:
    """Encode a JSON-compatible value in one canonical form."""
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def sha256_hex(payload: bytes) -> Sha256:
    """Hash one byte payload."""
    return hashlib.sha256(payload).hexdigest()


def sha256_json(value: object) -> Sha256:
    """Hash a JSON-compatible value in canonical form."""
    return sha256_hex(canonical_json(value))


def sha256_file(path: Path) -> tuple[Sha256, int]:
    """Hash a file by streaming, returning its digest and byte count."""
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1_048_576):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size
