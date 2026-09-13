"""Write exact, renderer-neutral certification evidence for one production map."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from opennoise.ml.production_map_evidence import build_production_map_acceptance_evidence
from opennoise.ml.production_map_qa import evaluate_production_map
from opennoise.models.modeling import PublicModelArtifact
from opennoise.models.production import ProductionMapArtifact


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--source-model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args()


def _write_json(path: Path, value: object) -> None:
    """Write one deterministic JSON value, creating only its explicit parent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    """Build evidence and a report without pretending browser evidence exists."""
    arguments = _arguments()
    artifact = ProductionMapArtifact.model_validate_json(arguments.artifact.read_text())
    source_model = PublicModelArtifact.model_validate_json(arguments.source_model.read_text())
    evidence = build_production_map_acceptance_evidence(artifact, source_model)
    _write_json(arguments.output, evidence.model_dump(mode="json"))
    _write_json(arguments.report, asdict(evaluate_production_map(evidence)))


if __name__ == "__main__":
    main()
