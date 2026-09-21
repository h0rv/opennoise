"""Regenerate the sealed v1 discovery fixture after ``dist`` moves to v2."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path
from tempfile import TemporaryDirectory

from opennoise.common import sha256_hex
from opennoise.deployment.semantic_pages import static_discovery_v1_bytes_from_layout

_PINNED_V1_SHA256 = "b4ff2b1bcebb0bb6b1fd63b78caf9a416dbf5bb0c3050c0fa05e434fd0c700e8"
_SEALED_LAYOUT = Path(".cache/semantic-map-layout-v3/artifact.json")
_PUBLIC_DATABASE = Path("data/public.sqlite")
_UNAVAILABLE = Path(".pinned-v1-discovery-unavailable")


@dataclass(frozen=True)
class _PinnedV1Fixture:
    path: Path
    temporary_directory: TemporaryDirectory[str] | None


@cache
def _pinned_v1_fixture() -> _PinnedV1Fixture:
    if not _SEALED_LAYOUT.is_file() or not _PUBLIC_DATABASE.is_file():
        return _PinnedV1Fixture(_UNAVAILABLE, None)
    temporary_directory = TemporaryDirectory(prefix="opennoise-pinned-v1-discovery-")
    path = Path(temporary_directory.name) / "static-discovery.json"
    payload = static_discovery_v1_bytes_from_layout(
        semantic_layout_path=_SEALED_LAYOUT, database=_PUBLIC_DATABASE
    )
    if sha256_hex(payload) != _PINNED_V1_SHA256:
        raise AssertionError("regenerated v1 static discovery does not match the sealed hash")
    path.write_bytes(payload)
    return _PinnedV1Fixture(path, temporary_directory)


def pinned_v1_discovery_path() -> Path:
    """Return a retained exact v1 fixture path, or a non-file skip sentinel."""
    return _pinned_v1_fixture().path
