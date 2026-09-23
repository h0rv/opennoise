"""Run the local hash-sampled MusicBrainz release-group genre holdout."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from opennoise.analysis.musicbrainz_rg_genre_recovery_v2 import (
    evaluate_musicbrainz_rg_genre_recovery_v2,
)
from opennoise.pipeline.source_cache import load_source_cache_receipt

_ARCHIVE = Path(
    ".cache/musicbrainz-release-group-source-objects/source-artifacts/sha256/"
    "6f153846228dc6034b2f8f43b472b088792cc2e242b09783a8968fa8d4bd7a43"
)
_SOURCE_RECEIPT = Path(".cache/musicbrainz-release-group-source-receipt.json")
_RECONCILIATION = Path(
    ".cache/seed-reconciliation/v3/objects/seed-reconciliation/"
    "ba2bba15c8fb1e5188dbd8c3406bba0a5064742de0d25e9be024cee49ebcd3f0/"
    "a9db9fb5d7a8dc1fdeae8e311b7e1d4556d98947a7d600ef4c331a86eba5bef0.json"
)
_OUTPUT = Path(".cache/musicbrainz-rg-genre-recovery-hash-sample-v2/report.json")


def main() -> int:
    """Write one verified report without replacing an earlier result."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=_ARCHIVE)
    parser.add_argument("--source-cache-receipt", type=Path, default=_SOURCE_RECEIPT)
    parser.add_argument("--reconciliation", type=Path, default=_RECONCILIATION)
    parser.add_argument("--output", type=Path, default=_OUTPUT)
    parser.add_argument("--progress", action="store_true")
    arguments = parser.parse_args()
    if arguments.progress:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
    report = evaluate_musicbrainz_rg_genre_recovery_v2(
        archive_path=arguments.archive,
        source_cache_receipt=load_source_cache_receipt(arguments.source_cache_receipt),
        seed_reconciliation_path=arguments.reconciliation,
        progress=arguments.progress,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("x", encoding="utf-8") as output:
        output.write(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))
        output.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
