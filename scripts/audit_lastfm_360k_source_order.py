"""Write a non-overwriting, counts-only Last.fm source-order receipt."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.analysis.lastfm_360k import audit_lastfm_360k_source_order


def main() -> int:
    """Replay the verified plays member without opening the profile member."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        raise FileExistsError("source-order output already exists")
    audit = audit_lastfm_360k_source_order(archive_path=arguments.archive)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(audit.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
