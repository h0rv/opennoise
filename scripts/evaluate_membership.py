"""Evaluate one artist-to-genre membership artifact against explicit fixtures."""

import argparse
import json
from pathlib import Path

from pydantic import Field, field_validator

from musix.evidence.membership import (
    EvaluationClaim,
    EvaluationPrediction,
    MembershipEvaluation,
    evaluate_predictions,
)
from musix.models import FrozenModel

MAX_EVALUATION_BYTES = 1_000_000
MAX_EVALUATION_ITEMS = 100_000


class EvaluationDocument(FrozenModel):
    """Parse all evaluation inputs and fixed denominators at one boundary."""

    predictions: tuple[EvaluationPrediction, ...] = Field(max_length=MAX_EVALUATION_ITEMS)
    known_claims: tuple[EvaluationClaim, ...] = Field(max_length=MAX_EVALUATION_ITEMS)
    previous_predictions: tuple[EvaluationPrediction, ...] = Field(
        default=(), max_length=MAX_EVALUATION_ITEMS
    )
    eligible_artist_refs: frozenset[str] = Field(min_length=1, max_length=MAX_EVALUATION_ITEMS)
    expected_source_keys: frozenset[str] = Field(min_length=1, max_length=MAX_EVALUATION_ITEMS)

    @field_validator("eligible_artist_refs", "expected_source_keys")
    @classmethod
    def require_normalized_sets(cls, value: frozenset[str]) -> frozenset[str]:
        """Reject blank or padded fixed-denominator identifiers."""
        if any(not item.strip() or item != item.strip() for item in value):
            raise ValueError("fixed-denominator identifiers must be nonblank and unpadded")
        return value


def evaluate_document(document: EvaluationDocument) -> MembershipEvaluation:
    """Evaluate a parsed document without consulting mutable external state."""
    return evaluate_predictions(
        document.predictions,
        document.known_claims,
        document.previous_predictions,
        eligible_artist_refs=document.eligible_artist_refs,
        expected_source_keys=document.expected_source_keys,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate explainable artist-to-genre membership predictions."
    )
    parser.add_argument("input", type=Path, help="Validated evaluation JSON document")
    return parser


def main() -> None:
    """Parse a local JSON document and print stable metric JSON."""
    arguments = _parser().parse_args()
    if arguments.input.stat().st_size > MAX_EVALUATION_BYTES:
        raise ValueError("evaluation document exceeds byte limit")
    payload = arguments.input.read_text(encoding="utf-8")
    document = EvaluationDocument.model_validate_json(payload)
    result = evaluate_document(document)
    print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))  # noqa: T201


if __name__ == "__main__":
    main()
