"""Check bound acceptance review testimony without inventing musical judgments."""

from __future__ import annotations

import hashlib
from datetime import date
from typing import TYPE_CHECKING, Final, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opennoise.pipeline.foundation import _safe_path

if TYPE_CHECKING:
    from pathlib import Path

SCOPE: Final = "full-open-foundation-every-noise"

# Each criterion needs an explicit review, not a file-presence or count threshold.
GATES: Final[dict[str, tuple[str, ...]]] = {
    "discovery-behavior": (
        "genre-to-artists-to-overlapping-genres navigation on actual export",
        "complete searchable lists, exact identities, missing-data abstentions",
    ),
    "full-corpus-rebuild": (
        "fresh offline reconstruction of declared full-corpus inputs and outputs",
        "input hashes, code revision, parameters, seeds, output hashes and replay verification",
    ),
    "legal-input-boundaries": (
        "source-level licenses and permitted projections verified against raw receipts",
        "optional NC/SA packs excluded from unrestricted core and correctly labeled derivatives",
        "dated Every Noise observations used only for separate evaluation",
    ),
    "genre-and-artist-coverage": (
        "reviewed broad, subgenre and microgenre labels across regions, languages and eras",
        (
            "full artist denominator, exact bridges, sparse/cold artists "
            "and unsupported labels retained"
        ),
    ),
    "independent-musical-relevance": (
        "independent blinded judgments of memberships and neighbors beyond source reconstruction",
        "prespecified stratified protocol, disagreements, uncertainty and unsuccessful cases",
    ),
    "held-out-source-reconstruction": (
        "frozen disjoint folds with no target leakage and independent replay",
        "baselines, cold artists, unseen labels and source-conditional denominators",
    ),
    "calibrated-overlapping-memberships": (
        "multiple broad/sub/micro memberships separated from direct observations",
        "held-out calibration, abstention and stability across evidence-volume strata",
    ),
    "acoustic-coverage-and-retrieval": (
        "diverse exact-credit sonic metadata with missingness, age and sample accounting",
        "independent sonic retrieval evaluation and separately evaluated cultural/sonic blend",
    ),
    "genre-and-artist-maps": (
        "stable independently assessed semantic neighborhoods and interpretable axes",
        "readable display layout separated from semantics, complete unpositioned alternatives",
    ),
    "defining-recordings": (
        (
            "exact recording credits distinct from release credits "
            "with sufficient discography coverage"
        ),
        "independent musical fit and diversity review of defining examples",
    ),
    "listening-and-playlists": (
        "permitted listening links with provider availability and missingness accounting",
        "independently assessed central, recent and emerging recording selections",
    ),
    "plain-accessible-interface": (
        "actual-export search, selection, full lists, history, deep links and reload",
        "keyboard and mobile tasks, source/inference distinctions, minimal readable interface",
    ),
}

# Portable examples and selected cohorts cannot witness these full-domain gates.
FULL_CORPUS_GATES: Final = frozenset(
    {
        "full-corpus-rebuild",
        "legal-input-boundaries",
        "genre-and-artist-coverage",
        "calibrated-overlapping-memberships",
        "acoustic-coverage-and-retrieval",
        "genre-and-artist-maps",
        "defining-recordings",
        "listening-and-playlists",
    }
)


class BoundArtifact(BaseModel):
    """An exact file byte binding with declared evidence and licensing scope."""

    model_config = ConfigDict(strict=True, extra="forbid")
    id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    scope: Literal[
        "full-corpus", "portable-example", "selected-cohort", "actual-export", "review-document"
    ]
    role: Literal["construction", "evaluation", "review"]
    source: str = Field(min_length=1)
    license: str = Field(min_length=1)
    pack: Literal["unrestricted-core", "optional-noncommercial", "evaluation-only", "review"]

    @model_validator(mode="after")
    def preserve_boundaries(self) -> Self:
        """Refuse explicit historical-training and NC-core declarations."""
        normalized_source = "".join(letter for letter in self.source.casefold() if letter.isalnum())
        if "everynoise" in normalized_source and (
            self.role != "evaluation" or self.pack != "evaluation-only"
        ):
            raise ValueError("Every Noise evidence must remain evaluation-only")
        if "NC" in self.license.upper() and self.pack == "unrestricted-core":
            raise ValueError("noncommercial evidence cannot be declared unrestricted core")
        return self


class GateReview(BaseModel):
    """A named human or external review assertion, never an automatic verdict."""

    model_config = ConfigDict(strict=True, extra="forbid")
    gate: str
    decision: Literal["recorded_pass", "missing", "blocked"]
    explanation: str = Field(min_length=1)
    evidence: list[str]
    criteria_covered: list[str]
    reviewer: str | None = None
    reviewed_at: str | None = None


class AcceptanceDossier(BaseModel):
    """All twelve reviews under the full foundation's explicit acceptance scope."""

    model_config = ConfigDict(strict=True, extra="forbid")
    version: int = Field(ge=1, le=1)
    scope: Literal["full-open-foundation-every-noise"]
    artifacts: list[BoundArtifact]
    reviews: list[GateReview]

    @model_validator(mode="after")
    def check_references(self) -> Self:
        """Require complete unique gates and valid, unrepeated artifact references."""
        ids = [artifact.id for artifact in self.artifacts]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate artifact id")
        gates = [review.gate for review in self.reviews]
        if len(gates) != len(set(gates)) or set(gates) != set(GATES):
            raise ValueError("dossier must review each of the twelve gates exactly once")
        for review in self.reviews:
            if len(review.evidence) != len(set(review.evidence)) or not set(
                review.evidence
            ).issubset(ids):
                raise ValueError(f"invalid evidence references for {review.gate}")
            if len(review.criteria_covered) != len(set(review.criteria_covered)) or not set(
                review.criteria_covered
            ).issubset(GATES[review.gate]):
                raise ValueError(f"invalid criterion references for {review.gate}")
        return self


def _verify_artifact(root: Path, artifact: BoundArtifact) -> dict[str, object]:
    try:
        path = _safe_path(root, artifact.path)
        if not path.is_file():
            return {"id": artifact.id, "valid": False, "reason": "missing regular file"}
        actual_size = path.stat().st_size
        if actual_size != artifact.size_bytes:
            return {"id": artifact.id, "valid": False, "reason": "size mismatch"}
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        actual_hash = digest.hexdigest()
    except (OSError, ValueError) as error:
        return {"id": artifact.id, "valid": False, "reason": str(error)}
    result = cast("dict[str, object]", artifact.model_dump())
    result.update(
        valid=actual_hash == artifact.sha256,
        reason="bytes verified" if actual_hash == artifact.sha256 else "sha256 mismatch",
        actual_sha256=actual_hash,
    )
    return result


def _valid_review_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def inspect_acceptance(root: Path, dossier: dict[str, object]) -> dict[str, object]:
    """Verify evidence bindings and report missing, blocked or recorded review states.

    Valid hashes establish custody only. Scope labels, review decisions and
    criterion coverage remain explicit testimony, not verified musical truth.
    """
    parsed = AcceptanceDossier.model_validate(dossier)
    evidence = {item.id: _verify_artifact(root, item) for item in parsed.artifacts}
    gates: list[dict[str, object]] = []
    for review in parsed.reviews:
        reasons: list[str] = []
        invalid = [key for key in review.evidence if not evidence[key]["valid"]]
        state = review.decision
        if invalid:
            reasons.append(f"invalid evidence: {', '.join(invalid)}")
        if review.decision == "recorded_pass":
            if not review.reviewer or not review.reviewer.strip() or not review.reviewed_at:
                reasons.append("recorded_pass requires reviewer and review date")
            if review.reviewed_at and not _valid_review_date(review.reviewed_at):
                reasons.append("review date must be an ISO calendar date")
            if set(review.criteria_covered) != set(GATES[review.gate]):
                reasons.append("recorded_pass must explicitly cover every gate criterion")
            if not review.evidence:
                reasons.append("recorded_pass requires byte-bound evidence")
            scopes = {evidence[key].get("scope") for key in review.evidence}
            if review.gate in FULL_CORPUS_GATES and "full-corpus" not in scopes:
                reasons.append(
                    "full-corpus evidence required; portable/cohort evidence is insufficient"
                )
            if review.gate in {"discovery-behavior", "plain-accessible-interface"} and (
                "actual-export" not in scopes
            ):
                reasons.append("actual-export evidence required")
        gates.append(
            {
                **review.model_dump(),
                "criteria_required": list(GATES[review.gate]),
                "status": "invalid_evidence"
                if invalid
                else "incomplete_review"
                if reasons
                else state,
                "binding_or_review_gaps": reasons,
                "automatic_semantic_pass": False,
            }
        )
    return {
        "version": parsed.version,
        "scope": SCOPE,
        "evidence_valid": all(item["valid"] for item in evidence.values()),
        "all_gates_recorded_pass": all(gate["status"] == "recorded_pass" for gate in gates),
        "automatic_semantic_pass": False,
        "interpretation": "Hashes verify custody; recorded_pass and scope are review testimony.",
        "artifacts": list(evidence.values()),
        "gates": gates,
    }
