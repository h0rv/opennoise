"""Write a bounded local-only no-score readiness checkpoint for RG positive tags."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from opennoise.analysis.musicbrainz_rg_tag_context_readiness import (
    audit_musicbrainz_rg_positive_tag_context,
)

_SAMPLE = Path(".cache/musicbrainz-rg-genre-recovery-hash-sample-v2/report.json")
_FIXTURE_GOLD = Path("tests/fixtures/independent_artist_genre_gold_fixture_v1.json")
_P136_DATABASE = Path("data/public.sqlite")
_SEED_RECONCILIATION = Path(
    ".cache/musicbrainz-full-seed-targets/pipeline/seed-reconciliation.json"
)
_OUTPUT = Path(".cache/musicbrainz-rg-positive-tag-context-readiness-v2/report.json")


def main() -> int:
    """Write a new checkpoint without replacing an earlier result."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-report", type=Path, default=_SAMPLE)
    parser.add_argument("--wikidata-p136-database", type=Path, default=_P136_DATABASE)
    parser.add_argument("--seed-reconciliation", type=Path, default=_SEED_RECONCILIATION)
    parser.add_argument("--independent-gold", type=Path, action="append", default=[_FIXTURE_GOLD])
    parser.add_argument("--output", type=Path, default=_OUTPUT)
    arguments = parser.parse_args()
    report = audit_musicbrainz_rg_positive_tag_context(
        sample_report_path=arguments.sample_report,
        wikidata_p136_database_path=arguments.wikidata_p136_database,
        seed_reconciliation_path=arguments.seed_reconciliation,
        independent_gold_paths=tuple(arguments.independent_gold),
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("x", encoding="utf-8") as stream:
        json.dump(report.model_dump(mode="json"), stream, indent=2, sort_keys=True)
        stream.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
