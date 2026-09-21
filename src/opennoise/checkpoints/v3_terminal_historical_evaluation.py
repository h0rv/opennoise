"""Terminal, positive-only comparison of a fixed local v3 model with history.

This adapter is intentionally separate from the sealed current-lineage evaluator.
It validates every local v3 candidate input before opening the historical signal,
then uses that signal only as an observed-positive reference.  It neither builds
nor modifies a model, database, or release artifact.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unicodedata
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from pydantic import Field, model_validator

from opennoise.common import canonical_json, sha256_file, sha256_hex
from opennoise.ml.public_graph import public_model_output_sha256
from opennoise.models import FrozenModel
from opennoise.models.historical_signal import HistoricalSignalArtifact
from opennoise.models.modeling import PublicModelArtifact
from opennoise.pipeline.candidate_public_projection import CandidatePublicProjectionV3Report
from opennoise.types import Sha256  # noqa: TC001

_REVISION: Final = "v3-terminal-historical-positive-only-v1"
_RECEIPT_REVISION: Final = "v3-terminal-historical-positive-only-receipt-v1"
_V3_MODEL_FILE_SHA256: Final = "c430b9948b863404827dd346fed6324a38b650ab2a827608078fc145b79fd1ba"
_V3_RECEIPT_FILE_SHA256: Final = "3bd6adb0d213a4e95ed06e78426f47e85b7ac20e3e0b662de7ee1097140008af"
_V3_SERVING_DATABASE_SHA256: Final = (
    "1fca548fa214aae999f7b2462fd2ebf3e265a7f5195a3d6d76b5393f06bd8df9"
)
_V3_MANIFEST_SHA256: Final = "795992807586432e2b285e2ddca9a24a00a16e9fc83b6c382a3e914539333232"
_V3_CANDIDATE_SHA256: Final = "327bbf377cb9ad8a1ed48821718979606622175f255ece5958d674146aba6763"
_V3_HISTORICAL_BINDING_SHA256: Final = (
    "ddaf45593ad78a6c6535691bf499c003d86e36227dd1bceb3e97e60dfae9d6a6"
)
_V3_SOURCE_ARTIFACT_SET_SHA256: Final = (
    "5faa89fb81d69de534b985fb15b4d35cd3402191e4048569540a95778ac34f0a"
)
_HISTORICAL_SIGNAL_FILE_SHA256: Final = (
    "9f77b3aff73f8a2ca0d201e4e7ad3931f7778815b9788917df52c871cd984d82"
)
_TMP_ROOT: Final = Path(tempfile.gettempdir()).resolve()


class V3TerminalHistoricalEvaluationError(ValueError):
    """A v3 candidate is not fixed or a terminal reference is invalid."""


class FileBinding(FrozenModel):
    """A byte and logical binding for one terminal input."""

    role: str = Field(min_length=1)
    bytes_sha256: Sha256
    byte_count: int = Field(gt=0)
    logical_sha256: Sha256


class ExactNameCoverage(FrozenModel):
    """Account for exact identifiers, exact names, and explicit abstentions."""

    candidate_genre_count: int = Field(ge=0)
    historical_genre_count: int = Field(ge=0)
    exact_identifier_match_count: int = Field(ge=0)
    unique_exact_name_match_count: int = Field(ge=0)
    ambiguous_name_abstention_count: int = Field(ge=0)
    candidate_abstention_count: int = Field(ge=0)
    historical_abstention_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _replay(self) -> ExactNameCoverage:
        if self.exact_identifier_match_count > self.unique_exact_name_match_count:
            raise ValueError("identifier matches must be a subset of accepted exact-name matches")
        if (
            self.candidate_abstention_count + self.unique_exact_name_match_count
            != self.candidate_genre_count
        ):
            raise ValueError("candidate exact-name coverage does not replay")
        if (
            self.historical_abstention_count + self.unique_exact_name_match_count
            != self.historical_genre_count
        ):
            raise ValueError("historical exact-name coverage does not replay")
        return self


class PositiveOverlap(FrozenModel):
    """Observed-positive overlap; no precision or negative inference is available."""

    candidate_positive_count: int = Field(ge=0)
    mapped_candidate_positive_count: int = Field(ge=0)
    historical_positive_count: int = Field(ge=0)
    overlap_count: int = Field(ge=0)
    historical_observed_positive_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    candidate_precision: None = None
    denominator_note: str = Field(min_length=1)

    @model_validator(mode="after")
    def _replay(self) -> PositiveOverlap:
        if self.mapped_candidate_positive_count > self.candidate_positive_count:
            raise ValueError("mapped positives cannot exceed candidate positives")
        if self.overlap_count > min(
            self.mapped_candidate_positive_count, self.historical_positive_count
        ):
            raise ValueError("positive overlap cannot exceed either positive set")
        expected = (
            self.overlap_count / self.historical_positive_count
            if self.historical_positive_count
            else None
        )
        if self.historical_observed_positive_coverage != expected:
            raise ValueError("observed-positive coverage does not replay")
        return self


class V3TerminalHistoricalEvaluation(FrozenModel):
    """A fixed-v3, evaluation-only historical report with explicit abstentions."""

    revision: Literal["v3-terminal-historical-positive-only-v1"] = _REVISION
    candidate_model: FileBinding
    candidate_receipt: FileBinding
    candidate_serving_database: FileBinding
    historical_reference: FileBinding
    candidate_fixed_before_historical_opened: Literal[True] = True
    historical_reference_used_for_construction: Literal[False] = False
    historical_reference_used_for_evaluation: Literal[True] = True
    historical_absence_is_negative: Literal[False] = False
    release_gate_evaluated: Literal[False] = False
    exact_name_coverage: ExactNameCoverage
    membership_seed_presence: PositiveOverlap
    neighborhoods: PositiveOverlap
    output_sha256: Sha256


class V3TerminalHistoricalEvaluationReceipt(FrozenModel):
    """Bind deterministic terminal-report bytes to the logical report."""

    revision: Literal["v3-terminal-historical-positive-only-receipt-v1"] = _RECEIPT_REVISION
    artifact_sha256: Sha256
    artifact_byte_count: int = Field(gt=0)
    logical_output_sha256: Sha256


@dataclass(frozen=True, slots=True)
class V3TerminalHistoricalEvaluationInputs:
    """The complete fixed candidate and terminal-reference input set."""

    model: Path
    receipt: Path
    serving_database: Path
    historical_reference: Path


def v3_terminal_historical_evaluation_sha256(report: V3TerminalHistoricalEvaluation) -> Sha256:
    """Return the logical report hash excluding only its self-hash."""
    return sha256_hex(canonical_json(report.model_dump(mode="json", exclude={"output_sha256"})))


def verify_v3_terminal_historical_evaluation(report: V3TerminalHistoricalEvaluation) -> None:
    """Fail closed if a terminal report loses its positive-only boundary."""
    if report.output_sha256 != v3_terminal_historical_evaluation_sha256(report):
        raise V3TerminalHistoricalEvaluationError("terminal evaluation hash does not replay")
    if report.historical_reference_used_for_construction:
        raise V3TerminalHistoricalEvaluationError(
            "historical reference crossed the construction boundary"
        )


def build_v3_terminal_historical_evaluation(
    inputs: V3TerminalHistoricalEvaluationInputs,
) -> V3TerminalHistoricalEvaluation:
    """Fix and verify v3 inputs before opening the historical reference."""
    model, receipt, _database = _load_fixed_v3_candidate(inputs)
    # Historical data is deliberately unavailable to every candidate-loading helper above.
    historical, historical_binding = _load_historical(inputs.historical_reference)
    name_mapping, coverage = _exact_name_mapping(model, historical)
    mapped_candidate_ids = set(name_mapping)

    candidate_membership = {profile.genre_id for profile in model.profiles if profile.memberships}
    historical_membership = {
        node.genre_id for node in historical.nodes if node.membership_count > 0
    }
    candidate_pairs = {
        _canonical_pair(edge.genre_id, edge.neighbor_genre_id) for edge in model.neighbors
    }
    historical_pairs = {
        _canonical_pair(edge.genre_id, edge.neighbor_genre_id) for edge in historical.neighbors
    }
    mapped_pairs = {
        _canonical_pair(name_mapping[left], name_mapping[right])
        for left, right in candidate_pairs
        if left in mapped_candidate_ids and right in mapped_candidate_ids
    }
    base = V3TerminalHistoricalEvaluation(
        candidate_model=_binding("v3_model", inputs.model, model.output_sha256),
        candidate_receipt=_binding("v3_receipt", inputs.receipt, receipt.receipt_logical_sha256),
        candidate_serving_database=_binding(
            "v3_serving_database", inputs.serving_database, receipt.serving_database_sha256
        ),
        historical_reference=historical_binding,
        exact_name_coverage=coverage,
        membership_seed_presence=_positive_overlap(
            candidate_positive=candidate_membership,
            mapped_candidate_positive=candidate_membership & mapped_candidate_ids,
            historical_positive=historical_membership,
            overlap={name_mapping[item] for item in candidate_membership & mapped_candidate_ids}
            & historical_membership,
            note=(
                "A candidate genre is positive when it has at least one published profile. "
                "Historical node membership_count>0 is the observed-positive denominator; "
                "unmatched names and historical absence remain abstentions."
            ),
        ),
        neighborhoods=_positive_overlap(
            candidate_positive=candidate_pairs,
            mapped_candidate_positive={
                pair
                for pair in candidate_pairs
                if pair[0] in mapped_candidate_ids and pair[1] in mapped_candidate_ids
            },
            historical_positive=historical_pairs,
            overlap=mapped_pairs & historical_pairs,
            note=(
                "Canonical undirected candidate neighbor pairs are compared only after both "
                "endpoints have unique exact normalized-name matches. Historical absence is "
                "unknown, never a negative or a precision denominator."
            ),
        ),
        output_sha256="0" * 64,
    )
    report = base.model_copy(
        update={"output_sha256": v3_terminal_historical_evaluation_sha256(base)}
    )
    verify_v3_terminal_historical_evaluation(report)
    return report


def write_v3_terminal_historical_evaluation(
    path: Path, receipt_path: Path, report: V3TerminalHistoricalEvaluation
) -> V3TerminalHistoricalEvaluationReceipt:
    """Write only a report and receipt, never a candidate or serving database."""
    verify_v3_terminal_historical_evaluation(report)
    _require_fresh_local_report_paths(path, receipt_path)
    payload = report.model_dump_json(indent=2).encode() + b"\n"
    _write_new_bytes(path, payload)
    artifact_sha256, artifact_byte_count = sha256_file(path)
    receipt = V3TerminalHistoricalEvaluationReceipt(
        artifact_sha256=artifact_sha256,
        artifact_byte_count=artifact_byte_count,
        logical_output_sha256=report.output_sha256,
    )
    _write_new_bytes(receipt_path, receipt.model_dump_json(indent=2).encode() + b"\n")
    return receipt


def verify_v3_terminal_historical_evaluation_receipt(
    path: Path,
    receipt: V3TerminalHistoricalEvaluationReceipt,
    report: V3TerminalHistoricalEvaluation,
) -> None:
    """Verify terminal-report bytes and receipt fields without reopening inputs."""
    verify_v3_terminal_historical_evaluation(report)
    artifact_sha256, artifact_byte_count = sha256_file(path)
    if (artifact_sha256, artifact_byte_count, report.output_sha256) != (
        receipt.artifact_sha256,
        receipt.artifact_byte_count,
        receipt.logical_output_sha256,
    ):
        raise V3TerminalHistoricalEvaluationError("terminal evaluation receipt does not replay")


def _load_fixed_v3_candidate(
    inputs: V3TerminalHistoricalEvaluationInputs,
) -> tuple[PublicModelArtifact, CandidatePublicProjectionV3Report, Path]:
    try:
        receipt = CandidatePublicProjectionV3Report.model_validate_json(inputs.receipt.read_bytes())
        model = PublicModelArtifact.model_validate_json(inputs.model.read_bytes())
    except (OSError, ValueError) as error:
        raise V3TerminalHistoricalEvaluationError("invalid v3 model or receipt") from error
    model_sha256, model_bytes = sha256_file(inputs.model)
    receipt_sha256, _ = sha256_file(inputs.receipt)
    database_sha256, _ = sha256_file(inputs.serving_database)
    if model_sha256 != receipt.model_file_sha256 or model_bytes != receipt.model_byte_size:
        raise V3TerminalHistoricalEvaluationError("v3 model bytes do not match receipt")
    if database_sha256 != receipt.serving_database_sha256:
        raise V3TerminalHistoricalEvaluationError("v3 serving database bytes do not match receipt")
    _verify_pinned_v3_custody(model_sha256, receipt_sha256, database_sha256, receipt)
    if public_model_output_sha256(model) != model.output_sha256:
        raise V3TerminalHistoricalEvaluationError("v3 model logical hash does not replay")
    if model.output_sha256 != receipt.model_logical_sha256 or not receipt.gate.passed:
        raise V3TerminalHistoricalEvaluationError("v3 receipt does not bind a passing fixed model")
    expected_receipt_hash = sha256_hex(
        canonical_json(receipt.model_dump(mode="json", exclude={"receipt_logical_sha256"}))
    )
    if expected_receipt_hash != receipt.receipt_logical_sha256:
        raise V3TerminalHistoricalEvaluationError("v3 receipt logical hash does not replay")
    _verify_readonly_serving_database(inputs.serving_database, receipt, model)
    _verify_construction_isolation(model)
    return model, receipt, inputs.serving_database


def _verify_readonly_serving_database(
    path: Path, receipt: CandidatePublicProjectionV3Report, model: PublicModelArtifact
) -> None:
    try:
        uri = f"file:{path.resolve()}?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True)) as database:
            integrity = database.execute("PRAGMA integrity_check").fetchone()
            foreign_keys = tuple(database.execute("PRAGMA foreign_key_check"))
            schema = database.execute("PRAGMA user_version").fetchone()
            published = database.execute(
                "SELECT output_sha256 FROM public_model_runs WHERE output_sha256 = ?",
                (model.output_sha256,),
            ).fetchone()
    except sqlite3.Error as error:
        raise V3TerminalHistoricalEvaluationError("cannot read v3 serving database") from error
    if integrity is None or integrity[0] != "ok" or foreign_keys:
        raise V3TerminalHistoricalEvaluationError("v3 serving database integrity does not replay")
    if schema is None or int(schema[0]) != receipt.serving_database_schema_version:
        raise V3TerminalHistoricalEvaluationError(
            "v3 serving database schema does not match receipt"
        )
    if published is None:
        raise V3TerminalHistoricalEvaluationError("v3 serving database lacks the fixed model")


def _verify_pinned_v3_custody(
    model_sha256: str,
    receipt_sha256: str,
    database_sha256: str,
    receipt: CandidatePublicProjectionV3Report,
) -> None:
    """Bind this terminal adapter to the one reviewed local v3 custody chain."""
    if (
        model_sha256 != _V3_MODEL_FILE_SHA256
        or receipt_sha256 != _V3_RECEIPT_FILE_SHA256
        or database_sha256 != _V3_SERVING_DATABASE_SHA256
    ):
        raise V3TerminalHistoricalEvaluationError("v3 candidate files do not match pinned custody")
    if (
        receipt.manifest_sha256 != _V3_MANIFEST_SHA256
        or receipt.candidate_sha256 != _V3_CANDIDATE_SHA256
        or receipt.historical_candidate_binding_sha256 != _V3_HISTORICAL_BINDING_SHA256
        or receipt.source_artifact_set_sha256 != _V3_SOURCE_ARTIFACT_SET_SHA256
    ):
        raise V3TerminalHistoricalEvaluationError("v3 receipt does not match pinned custody")


def _verify_construction_isolation(model: PublicModelArtifact) -> None:
    """Reject a v3 model that embeds an Every Noise historical reference token.

    This is a model-boundary check, not a claim that an absent token alone can
    prove how upstream sources were collected. The v3 receipt's source-artifact
    attestation remains the primary construction custody check.
    """
    forbidden_prefixes = ("enao-legacy:", "historical:", "every-noise:")
    values = tuple(_strings(model.model_dump(mode="json")))
    if any(value.casefold().startswith(forbidden_prefixes) for value in values):
        raise V3TerminalHistoricalEvaluationError(
            "v3 model contains a historical construction reference"
        )


def _load_historical(path: Path) -> tuple[HistoricalSignalArtifact, FileBinding]:
    historical_sha256, _ = sha256_file(path)
    if historical_sha256 != _HISTORICAL_SIGNAL_FILE_SHA256:
        raise V3TerminalHistoricalEvaluationError(
            "historical signal does not match pinned evaluation-only reference"
        )
    try:
        historical = HistoricalSignalArtifact.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise V3TerminalHistoricalEvaluationError("invalid historical signal reference") from error
    return historical, _binding(
        "held_out_historical_signal",
        path,
        sha256_hex(canonical_json(historical.model_dump(mode="json"))),
    )


def _exact_name_mapping(
    model: PublicModelArtifact, historical: HistoricalSignalArtifact
) -> tuple[dict[str, str], ExactNameCoverage]:
    candidate_by_name: dict[str, list[str]] = {}
    for genre in model.genres:
        candidate_by_name.setdefault(_name_key(genre.name), []).append(genre.genre_id)
    historical_by_name: dict[str, list[str]] = {}
    for node in historical.nodes:
        historical_by_name.setdefault(_name_key(node.name), []).append(node.genre_id)
    mapping: dict[str, str] = {}
    ambiguous = 0
    historical_ids = {node.genre_id for node in historical.nodes}
    exact_ids = 0
    for genre in model.genres:
        key = _name_key(genre.name)
        candidates = candidate_by_name[key]
        matches = historical_by_name.get(key, [])
        if len(candidates) == 1 and len(matches) == 1:
            mapping[genre.genre_id] = matches[0]
            exact_ids += genre.genre_id in historical_ids
        elif candidates or matches:
            ambiguous += 1
    return mapping, ExactNameCoverage(
        candidate_genre_count=len(model.genres),
        historical_genre_count=len(historical.nodes),
        exact_identifier_match_count=exact_ids,
        unique_exact_name_match_count=len(mapping),
        ambiguous_name_abstention_count=ambiguous,
        candidate_abstention_count=len(model.genres) - len(mapping),
        historical_abstention_count=len(historical.nodes) - len(mapping),
    )


def _positive_overlap[T](
    *,
    candidate_positive: set[T],
    mapped_candidate_positive: set[T],
    historical_positive: set[T],
    overlap: set[T],
    note: str,
) -> PositiveOverlap:
    recall = len(overlap) / len(historical_positive) if historical_positive else None
    return PositiveOverlap(
        candidate_positive_count=len(candidate_positive),
        mapped_candidate_positive_count=len(mapped_candidate_positive),
        historical_positive_count=len(historical_positive),
        overlap_count=len(overlap),
        historical_observed_positive_coverage=recall,
        denominator_note=note,
    )


def _binding(role: str, path: Path, logical_sha256: Sha256) -> FileBinding:
    digest, size = sha256_file(path)
    return FileBinding(
        role=role,
        bytes_sha256=digest,
        byte_count=size,
        logical_sha256=logical_sha256,
    )


def _canonical_pair(left: str, right: str) -> tuple[str, str]:
    return (left, right) if left < right else (right, left)


def _name_key(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _strings(value: object) -> tuple[str, ...]:
    """Return every serialized model string for the no-historical-token check."""
    if isinstance(value, str):
        return (value,)
    if isinstance(value, dict):
        return tuple(item for child in value.values() for item in _strings(child))
    if isinstance(value, list):
        return tuple(item for child in value for item in _strings(child))
    return ()


def _require_fresh_local_report_paths(report_path: Path, receipt_path: Path) -> None:
    """Permit fresh, non-symlinked report files only under /tmp or project .cache."""
    if report_path.absolute() == receipt_path.absolute():
        raise V3TerminalHistoricalEvaluationError("terminal report and receipt paths must differ")
    allowed_roots = (_TMP_ROOT, (Path.cwd() / ".cache").resolve())
    for path in (report_path, receipt_path):
        absolute = path.absolute()
        if path.exists() or path.is_symlink():
            raise V3TerminalHistoricalEvaluationError("terminal report output must be fresh")
        if not absolute.parent.is_dir() or any(
            ancestor.is_symlink() for ancestor in _existing_ancestors(absolute.parent)
        ):
            raise V3TerminalHistoricalEvaluationError(
                "terminal report parent must be an existing non-symlink directory"
            )
        if not any(_is_relative_to(absolute.resolve(), root) for root in allowed_roots):
            raise V3TerminalHistoricalEvaluationError(
                "terminal report output must be under /tmp or project .cache"
            )


def _existing_ancestors(path: Path) -> tuple[Path, ...]:
    """Return existing ancestors for the output-parent symlink guard."""
    result: list[Path] = []
    current = path
    while current.exists():
        result.append(current)
        if current.parent == current:
            break
        current = current.parent
    return tuple(result)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _write_new_bytes(path: Path, payload: bytes) -> None:
    """Atomically publish one fresh report file without replacing an existing path."""
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path, follow_symlinks=False)
    except FileExistsError as error:
        raise V3TerminalHistoricalEvaluationError(
            "terminal report output already exists"
        ) from error
    finally:
        temporary.unlink(missing_ok=True)
