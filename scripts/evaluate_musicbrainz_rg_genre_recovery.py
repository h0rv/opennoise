"""Run a local-only exact MusicBrainz release-group genre recovery holdout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from opennoise.analysis.musicbrainz_rg_genre_recovery import (
    evaluate_musicbrainz_rg_genre_recovery,
)

_SAMPLE = Path(".cache/musicbrainz-release-group-native-artist-support-v1")
_OUTPUT = Path(".cache/musicbrainz-rg-genre-recovery-v3/report.json")
_RECONCILIATION = Path(
    ".cache/seed-reconciliation/v3/objects/seed-reconciliation/"
    "ba2bba15c8fb1e5188dbd8c3406bba0a5064742de0d25e9be024cee49ebcd3f0/"
    "a9db9fb5d7a8dc1fdeae8e311b7e1d4556d98947a7d600ef4c331a86eba5bef0.json"
)


def main() -> int:
    """Write the deterministic feasibility report once under the local cache."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, default=_SAMPLE / "report.json")
    parser.add_argument("--reconciliation", type=Path, default=_RECONCILIATION)
    parser.add_argument("--output", type=Path, default=_OUTPUT)
    args = parser.parse_args()
    result = evaluate_musicbrainz_rg_genre_recovery(
        native_artist_support_path=args.sample,
        seed_reconciliation_path=args.reconciliation,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        output.write(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
        output.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
