"""Compact prefix search shares the complete sorted browse pages."""

from __future__ import annotations

import json
import unicodedata
from typing import TYPE_CHECKING

from opennoise.common import canonical_json

if TYPE_CHECKING:
    from pathlib import Path

FORMAT = "browse-page-bounds-v1"
PAGE_SIZE = 500


def normalize_name(name: str) -> str:
    """Normalize a search key, never a join or genre label."""
    return unicodedata.normalize("NFKC", name).casefold()


def _bounds(output: Path) -> list[list[str | int]]:
    browse = json.loads((output / "browse/index.json").read_bytes())
    result: list[list[str | int]] = []
    for number, path in enumerate(browse["pages"]):
        if path != f"browse/{number:06d}.json":
            raise ValueError("compact search requires canonical complete browse page paths")
        rows = json.loads((output / path).read_bytes())
        if not rows:
            raise ValueError("compact search cannot index an empty browse page")
        result.append([normalize_name(rows[0][1]), normalize_name(rows[-1][1]), len(rows)])
    return result


def export_compact_search(output: Path) -> int:
    """Write lexical page bounds; no duplicate identities or per-prefix files."""
    directory = output / "search"
    directory.mkdir(exist_ok=True)
    browse = json.loads((output / "browse/index.json").read_bytes())
    index = {
        "format": FORMAT,
        "normalization": "NFKC casefold",
        "count": browse["count"],
        "page_size": PAGE_SIZE,
        "pages": _bounds(output),
    }
    with (directory / "index.json").open("xb") as stream:
        stream.write(canonical_json(index))
    return len(index["pages"])


def validate_compact_search(output: Path) -> None:
    """Replay every lexical bound from complete native browse rows."""
    index = json.loads((output / "search/index.json").read_bytes())
    browse = json.loads((output / "browse/index.json").read_bytes())
    if index != {
        "format": FORMAT,
        "normalization": "NFKC casefold",
        "count": browse["count"],
        "page_size": PAGE_SIZE,
        "pages": _bounds(output),
    }:
        raise ValueError("compact search coverage, lexical bounds or denominator differs")
