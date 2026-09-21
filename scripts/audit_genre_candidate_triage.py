"""Write a sealed, non-publishing triage audit for source-bound genre candidates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.common import write_atomic_bytes
from opennoise.taxonomy.candidates.audit import (
    audit_open_label_graph_candidates,
    verify_genre_candidate_triage_audit,
)
from opennoise.taxonomy.open.label_graph_model import OpenLabelGraphArtifact


def main() -> int:
    """Audit one sealed open-label graph artifact without writing a review decision."""
    parser = argparse.ArgumentParser(prog="audit-genre-candidate-triage")
    parser.add_argument("--source-artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    source = OpenLabelGraphArtifact.model_validate_json(arguments.source_artifact.read_bytes())
    audit = audit_open_label_graph_candidates(source)
    verify_genre_candidate_triage_audit(audit)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    write_atomic_bytes(arguments.output, (audit.model_dump_json(indent=2) + "\n").encode())
    sys.stdout.write(
        json.dumps(
            {
                "revision": audit.revision,
                "output_sha256": audit.output_sha256,
                "coverage": audit.coverage.model_dump(),
            }
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
