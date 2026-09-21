"""Read-only, local-only bridge from the Phase 3 v3 model to canonical map seeds.

This module deliberately produces an in-memory audit object, not a layout,
static payload, artist projection, or public-model mutation.  A source genre
is admitted only through one explicit, non-ambiguous Wikidata identity in the
sealed all-seed reconciliation artifact.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from contextlib import closing
from pathlib import Path  # noqa: TC003
from typing import Literal

from pydantic import Field, model_validator

from opennoise.ml.public_graph import public_model_output_sha256
from opennoise.ml.semantic_layout.contracts import (
    SemanticLayoutArtifact,
    verify_semantic_map_layout,
)
from opennoise.models import FrozenModel
from opennoise.models.modeling import PublicModelArtifact
from opennoise.pipeline.candidate_public_projection import CandidatePublicProjectionV3Report
from opennoise.types import Sha256  # noqa: TC001

_REVISION = "phase3-v3-local-map-overlay-v1"
_SEED_COUNT = 6_291
_V3_RECEIPT_FILE_SHA256 = "3bd6adb0d213a4e95ed06e78426f47e85b7ac20e3e0b662de7ee1097140008af"
_V3_MODEL_FILE_SHA256 = "c430b9948b863404827dd346fed6324a38b650ab2a827608078fc145b79fd1ba"
_V3_SERVING_DATABASE_SHA256 = "1fca548fa214aae999f7b2462fd2ebf3e265a7f5195a3d6d76b5393f06bd8df9"
_V3_MANIFEST_SHA256 = "795992807586432e2b285e2ddca9a24a00a16e9fc83b6c382a3e914539333232"
_V3_CANDIDATE_SHA256 = "327bbf377cb9ad8a1ed48821718979606622175f255ece5958d674146aba6763"
_V3_BINDING_SHA256 = "ddaf45593ad78a6c6535691bf499c003d86e36227dd1bceb3e97e60dfae9d6a6"
_V3_SOURCE_SET_SHA256 = "5faa89fb81d69de534b985fb15b4d35cd3402191e4048569540a95778ac34f0a"
_RECONCILIATION_LOGICAL_SHA256 = "ba2bba15c8fb1e5188dbd8c3406bba0a5064742de0d25e9be024cee49ebcd3f0"
_CANONICAL_LAYOUT_LOGICAL_SHA256 = (
    "469f207021157031e88853be1b9f2d1eb63af8f0fcfc9c504e19e7584fd0cc38"
)


class V3MapOverlayError(ValueError):
    """The requested local bridge is incomplete, altered, or unsafe."""


class V3MapOverlayInputs(FrozenModel):
    """Immutable paths for the three read-only bridge boundaries."""

    v3_receipt: Path
    v3_model: Path
    v3_serving_database: Path
    reconciliation: Path
    canonical_layout: Path


class V3OverlaySeedLink(FrozenModel):
    """One v3 source genre joined to one existing canonical seed identity."""

    source_genre_ref: str = Field(pattern=r"^wikidata:genre:Q[1-9][0-9]*$")
    seed_id: str = Field(min_length=1)
    reconciliation_disposition: Literal["reconciled", "public_only"]
    positioned: bool


class _ReconciliationIdentity(FrozenModel):
    """The explicit public identity fields needed for this one bridge."""

    namespace: Literal["wikidata_genre_qid", "musicbrainz_genre_id", "musicbrainz_tag_name"]
    identifier: str = Field(min_length=1)


class _ReconciliationDisposition(FrozenModel):
    """One legacy seed's sealed public identity facet."""

    source_item_id: str = Field(min_length=1)
    disposition: Literal[
        "reconciled", "public_only", "musicbrainz_only", "review_only", "ambiguous", "unresolved"
    ]
    public_identities: tuple[_ReconciliationIdentity, ...] = ()


class _V1SeedReconciliation(FrozenModel):
    """The retained v1 reconciliation shape, parsed without upgrading it."""

    revision: Literal["seed-reconciliation-v1"]
    seed_count: Literal[6291]
    dispositions: tuple[_ReconciliationDisposition, ...]
    output_sha256: Sha256

    @model_validator(mode="after")
    def require_complete_seed_rows(self) -> _V1SeedReconciliation:
        """Keep the sealed reconciliation's all-seed identity boundary intact."""
        seed_ids = {row.source_item_id for row in self.dispositions}
        if len(seed_ids) != len(self.dispositions) or len(seed_ids) != _SEED_COUNT:
            raise ValueError("reconciliation must have one row for every canonical seed")
        return self


class V3MapOverlayCoverage(FrozenModel):
    """Complete accounting for v3 source genres and canonical map coverage."""

    v3_genre_count: int = Field(ge=0)
    reconciliation_candidate_genre_count: int = Field(ge=0)
    unique_candidate_genre_count: int = Field(ge=0)
    unique_non_ambiguous_genre_count: int = Field(ge=0)
    positioned_link_count: int = Field(ge=0)
    canonical_seed_count: Literal[6291] = _SEED_COUNT
    canonical_placed_count: int = Field(ge=0)
    canonical_unplaced_count: int = Field(ge=0)

    @model_validator(mode="after")
    def require_monotonic_bridge_counts(self) -> V3MapOverlayCoverage:
        """Require bridge stages and canonical coverage to be internally consistent."""
        if not (
            self.positioned_link_count
            <= self.unique_non_ambiguous_genre_count
            <= self.unique_candidate_genre_count
            <= self.reconciliation_candidate_genre_count
            <= self.v3_genre_count
        ):
            raise ValueError("v3 bridge coverage counts are inconsistent")
        if self.canonical_placed_count + self.canonical_unplaced_count != _SEED_COUNT:
            raise ValueError("canonical bridge coverage must preserve all 6291 seeds")
        return self


class V3MapOverlayAudit(FrozenModel):
    """Non-exportable result of checking the bounded v3-to-seed bridge."""

    revision: Literal["phase3-v3-local-map-overlay-v1"] = _REVISION
    publication_scope: Literal["local_research_only"] = "local_research_only"
    export_allowed: Literal[False] = False
    static_output_written: Literal[False] = False
    artist_integration_included: Literal[False] = False
    v3_receipt_file_sha256: Sha256
    v3_receipt_logical_sha256: Sha256
    v3_model_file_sha256: Sha256
    v3_serving_database_sha256: Sha256
    reconciliation_file_sha256: Sha256
    reconciliation_logical_sha256: Sha256
    canonical_layout_file_sha256: Sha256
    canonical_layout_logical_sha256: Sha256
    links: tuple[V3OverlaySeedLink, ...]
    coverage: V3MapOverlayCoverage


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _load_receipt(path: Path) -> CandidatePublicProjectionV3Report:
    if _file_sha256(path) != _V3_RECEIPT_FILE_SHA256:
        raise V3MapOverlayError("v3 projection receipt file hash is not the pinned local receipt")
    try:
        receipt = CandidatePublicProjectionV3Report.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise V3MapOverlayError("v3 projection receipt is invalid") from error
    logical = _canonical_sha256(receipt.model_dump(mode="json", exclude={"receipt_logical_sha256"}))
    if receipt.receipt_logical_sha256 != logical:
        raise V3MapOverlayError("v3 projection receipt logical hash does not replay")
    if not receipt.gate.passed:
        raise V3MapOverlayError("v3 projection model gate did not pass")
    if (
        receipt.manifest_sha256,
        receipt.candidate_sha256,
        receipt.historical_candidate_binding_sha256,
        receipt.source_artifact_set_sha256,
    ) != (_V3_MANIFEST_SHA256, _V3_CANDIDATE_SHA256, _V3_BINDING_SHA256, _V3_SOURCE_SET_SHA256):
        raise V3MapOverlayError("v3 receipt is outside the pinned local custody boundary")
    return receipt


def _load_model(path: Path, receipt: CandidatePublicProjectionV3Report) -> None:
    if (
        _file_sha256(path) != _V3_MODEL_FILE_SHA256
        or receipt.model_file_sha256 != _V3_MODEL_FILE_SHA256
    ):
        raise V3MapOverlayError("v3 model file hash does not match its receipt")
    try:
        model = PublicModelArtifact.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise V3MapOverlayError("v3 model identity is invalid") from error
    if (model.input_sha256, model.settings_sha256, model.output_sha256) != (
        receipt.model_input_sha256,
        receipt.model_settings_sha256,
        receipt.model_logical_sha256,
    ):
        raise V3MapOverlayError("v3 model logical identities do not match its receipt")
    if public_model_output_sha256(model) != model.output_sha256:
        raise V3MapOverlayError("v3 model logical hash does not replay")


def _v3_genre_refs(path: Path, receipt: CandidatePublicProjectionV3Report) -> tuple[str, ...]:
    if (
        _file_sha256(path) != _V3_SERVING_DATABASE_SHA256
        or receipt.serving_database_sha256 != _V3_SERVING_DATABASE_SHA256
    ):
        raise V3MapOverlayError("v3 serving database hash does not match its receipt")
    try:
        with closing(sqlite3.connect(f"file:{path.resolve()}?mode=ro&immutable=1", uri=True)) as db:
            integrity = db.execute("PRAGMA integrity_check").fetchone()
            foreign_keys = tuple(db.execute("PRAGMA foreign_key_check"))
            version = db.execute("PRAGMA user_version").fetchone()
            rows = tuple(
                str(row[0])
                for row in db.execute(
                    "SELECT source_genre_ref FROM public_genre_names ORDER BY source_genre_ref"
                )
            )
    except sqlite3.Error as error:
        raise V3MapOverlayError(
            "v3 serving database cannot supply public genre references"
        ) from error
    if (
        integrity != ("ok",)
        or foreign_keys
        or version != (receipt.serving_database_schema_version,)
    ):
        raise V3MapOverlayError(
            "v3 serving database integrity or schema does not match its receipt"
        )
    if len(rows) != receipt.gate.genre_count or len(rows) != len(set(rows)):
        raise V3MapOverlayError("v3 serving genre references do not match receipt coverage")
    if any(not ref.startswith("wikidata:genre:Q") for ref in rows):
        raise V3MapOverlayError(
            "v3 serving genre reference is outside the explicit Wikidata boundary"
        )
    return rows


def _load_reconciliation(path: Path) -> _V1SeedReconciliation:
    try:
        payload = path.read_bytes()
        raw = json.loads(payload)
        reconciliation = _V1SeedReconciliation.model_validate_json(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise V3MapOverlayError("seed reconciliation artifact is invalid") from error
    if not isinstance(raw, dict):
        raise V3MapOverlayError("seed reconciliation artifact must be a JSON object")
    expected = _canonical_sha256(
        {key: value for key, value in raw.items() if key != "output_sha256"}
    )
    if reconciliation.output_sha256 != expected:
        raise V3MapOverlayError("seed reconciliation logical hash does not replay")
    if reconciliation.output_sha256 != _RECONCILIATION_LOGICAL_SHA256:
        raise V3MapOverlayError("seed reconciliation is not the pinned bridge input")
    if reconciliation.seed_count != _SEED_COUNT:
        raise V3MapOverlayError("seed reconciliation does not cover the canonical seed universe")
    return reconciliation


def _load_canonical_inventory(path: Path) -> SemanticLayoutArtifact:
    try:
        inventory = SemanticLayoutArtifact.model_validate_json(path.read_bytes())
        verify_semantic_map_layout(inventory)
    except (OSError, ValueError) as error:
        raise V3MapOverlayError("canonical layout inventory is invalid") from error
    else:
        if inventory.output_sha256 != _CANONICAL_LAYOUT_LOGICAL_SHA256:
            raise V3MapOverlayError("canonical layout is not the pinned v3 layout")
        return inventory


def build_local_v3_map_overlay_audit(inputs: V3MapOverlayInputs) -> V3MapOverlayAudit:
    """Verify read-only local inputs and return only explicit seed links.

    This intentionally does not read artist profiles, historical artifacts,
    or any static-export destination. It reads only canonical seed IDs and
    placed/unplaced membership, never their coordinate values.
    """
    receipt = _load_receipt(inputs.v3_receipt)
    _load_model(inputs.v3_model, receipt)
    genre_refs = _v3_genre_refs(inputs.v3_serving_database, receipt)
    reconciliation = _load_reconciliation(inputs.reconciliation)
    canonical = _load_canonical_inventory(inputs.canonical_layout)
    canonical_seed_ids = {
        *(row.seed_id for row in canonical.coordinates),
        *(row.seed_id for row in canonical.unplaced),
    }
    reconciliation_seed_ids = {
        disposition.source_item_id for disposition in reconciliation.dispositions
    }
    if canonical_seed_ids != reconciliation_seed_ids:
        raise V3MapOverlayError(
            "canonical layout and reconciliation do not share the same 6291 seed identities"
        )

    candidates: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for disposition in reconciliation.dispositions:
        for identity in disposition.public_identities:
            if identity.namespace == "wikidata_genre_qid":
                candidates[identity.identifier].append(
                    (disposition.source_item_id, disposition.disposition)
                )
    positioned_ids = {row.seed_id for row in canonical.coordinates}
    candidate_count = sum(ref in candidates for ref in genre_refs)
    unique = {ref: rows[0] for ref in genre_refs if len(rows := candidates.get(ref, ())) == 1}
    safe: dict[str, tuple[str, Literal["reconciled", "public_only"]]] = {}
    for ref, (seed_id, disposition) in unique.items():
        if disposition == "reconciled":
            safe[ref] = (seed_id, "reconciled")
        elif disposition == "public_only":
            safe[ref] = (seed_id, "public_only")
    links = tuple(
        V3OverlaySeedLink(
            source_genre_ref=ref,
            seed_id=seed_id,
            reconciliation_disposition=disposition,
            positioned=seed_id in positioned_ids,
        )
        for ref, (seed_id, disposition) in sorted(safe.items())
    )
    return V3MapOverlayAudit(
        v3_receipt_file_sha256=_file_sha256(inputs.v3_receipt),
        v3_receipt_logical_sha256=receipt.receipt_logical_sha256,
        v3_model_file_sha256=receipt.model_file_sha256,
        v3_serving_database_sha256=receipt.serving_database_sha256,
        reconciliation_file_sha256=_file_sha256(inputs.reconciliation),
        reconciliation_logical_sha256=reconciliation.output_sha256,
        canonical_layout_file_sha256=_file_sha256(inputs.canonical_layout),
        canonical_layout_logical_sha256=canonical.output_sha256,
        links=links,
        coverage=V3MapOverlayCoverage(
            v3_genre_count=len(genre_refs),
            reconciliation_candidate_genre_count=candidate_count,
            unique_candidate_genre_count=len(unique),
            unique_non_ambiguous_genre_count=len(safe),
            positioned_link_count=sum(link.positioned for link in links),
            canonical_placed_count=len(canonical.coordinates),
            canonical_unplaced_count=len(canonical.unplaced),
        ),
    )
