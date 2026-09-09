"""Audit why a stale Wikidata exact-QID query cannot expand a sealed hierarchy."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from musix.taxonomy.relations.expansion import TaxonomyRelationExpansionArtifact
from musix.taxonomy.relations.identity_audit import (
    audit_taxonomy_relation_identity,
)


def main() -> int:
    """Audit one sealed expansion against its current and stale queries."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expansion", type=Path, required=True)
    parser.add_argument("--current-query", type=Path, required=True)
    parser.add_argument("--stale-query", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        sys.stderr.write("output already exists\n")
        return 1
    report = audit_taxonomy_relation_identity(
        TaxonomyRelationExpansionArtifact.model_validate_json(args.expansion.read_bytes()),
        current_query=args.current_query.read_text(encoding="utf-8"),
        stale_query=args.stale_query.read_text(encoding="utf-8"),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
