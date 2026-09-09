"""Reconcile the retained seed universe across public genre identities.

The seed name is a vocabulary, not a primary key.  ``source_item_id`` is the
only join key in this module.  Public taxonomy identities and MusicBrainz
identities remain separate facets, while lexical anchors and ambiguous
candidates remain review material.  A disposition is emitted for every seed
so downstream graph builders never have to silently drop an unresolved name.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, NamedTuple

from pydantic import Field, model_validator

from musix.models import FrozenModel
from musix.models.modeling import (
    DirectMembershipEvidence,
    GenreIdentity,
    PublicArtifact,
    PublicModelInput,
)
from musix.storage import ObjectKey
from musix.taxonomy.genre_seed_universe import SeedInput, normalize_label

if TYPE_CHECKING:
    from musix.evidence.reconstruction import GenreArtistEdge, ReconstructionInputs
    from musix.musicbrainz_coverage import CoverageReport
    from musix.storage import ObjectStore, ObjectWrite
    from musix.taxonomy.genre_seed_taxonomy import (
        GenreSeedPublicTaxonomyArtifact,
        PublicTaxonomyNode,
        SeedTaxonomyInference,
    )
    from musix.taxonomy.genre_seed_universe import SeedName

_REVISION: Final = "seed-reconciliation-v3"
_BRIDGE_REVISION: Final = "reconstruction-seed-bridge-v2"
_SHA256_PATTERN: Final[str] = r"^[0-9a-f]{64}$"
_PUBLIC_EVIDENCE_MAX: Final = 500

type ReconciliationDisposition = Literal[
    "reconciled",
    "public_only",
    "musicbrainz_only",
    "review_only",
    "ambiguous",
    "unresolved",
]
type IdentityNamespace = Literal[
    "wikidata_genre_qid", "musicbrainz_genre_id", "musicbrainz_tag_name"
]
type IdentityMatchKind = Literal[
    "canonical", "alias", "explicit_bridge", "lexical_exact", "lexical_normalized"
]
type BridgeFacet = Literal["musicbrainz_genre", "musicbrainz_tag"]
type IdentityKey = tuple[IdentityNamespace, str]


class MusicBrainzGenreIdentity(FrozenModel):
    """One explicit seed-to-MusicBrainz genre bridge row.

    This row is supplied by a separately audited bridge or a local research
    run.  The reconciler never guesses a MusicBrainz UUID from a display name.
    """

    source_item_id: str = Field(min_length=1, max_length=200)
    namespace: Literal["musicbrainz_genre_id", "musicbrainz_tag_name"] = "musicbrainz_genre_id"
    identifier: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=500)
    match_kind: IdentityMatchKind = "explicit_bridge"
    evidence_refs: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _require_nonempty_evidence_refs(self) -> MusicBrainzGenreIdentity:
        if any(not ref for ref in self.evidence_refs):
            raise ValueError("MusicBrainz evidence references must be non-empty")
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("MusicBrainz evidence references must be unique")
        return self


class MusicBrainzIdentityInput(FrozenModel):
    """Hash-bound optional MusicBrainz identity input."""

    revision: Literal["musicbrainz-seed-identities-v1"] = "musicbrainz-seed-identities-v1"
    source_artifact_sha256: str = Field(pattern=_SHA256_PATTERN)
    coverage_report_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    rows: tuple[MusicBrainzGenreIdentity, ...] = ()
    input_sha256: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def _verify_input_hash(self) -> MusicBrainzIdentityInput:
        identity_claims = tuple(
            (row.source_item_id, row.namespace, row.identifier) for row in self.rows
        )
        if len(identity_claims) != len(set(identity_claims)):
            raise ValueError("MusicBrainz identity rows must not repeat one seed identity claim")
        if (
            _mb_input_hash(self.source_artifact_sha256, self.rows, self.coverage_report_sha256)
            != self.input_sha256
        ):
            raise ValueError("MusicBrainz identity input hash does not match its rows")
        return self


class ReconciledIdentity(FrozenModel):
    """A retained identity facet attached to one stable seed ID."""

    namespace: IdentityNamespace
    identifier: str = Field(min_length=1, max_length=300)
    name: str = Field(min_length=1, max_length=500)
    match_kind: IdentityMatchKind
    evidence_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _require_unique_evidence_refs(self) -> ReconciledIdentity:
        if any(not ref for ref in self.evidence_refs):
            raise ValueError("reconciled identity evidence references must be non-empty")
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("reconciled identity evidence references must be unique")
        return self


def _require_unique_identity_claims(
    identities: tuple[ReconciledIdentity, ...], *, label: str
) -> None:
    claims = tuple((identity.namespace, identity.identifier) for identity in identities)
    if len(claims) != len(set(claims)):
        raise ValueError(f"{label} identity claims must be unique per seed")


def _has_multiple_identity_targets_in_one_facet(
    public_identities: tuple[ReconciledIdentity, ...],
    musicbrainz_identities: tuple[ReconciledIdentity, ...],
) -> bool:
    musicbrainz_namespace_counts = {
        namespace: sum(identity.namespace == namespace for identity in musicbrainz_identities)
        for namespace in ("musicbrainz_genre_id", "musicbrainz_tag_name")
    }
    return len(public_identities) > 1 or any(
        count > 1 for count in musicbrainz_namespace_counts.values()
    )


class SeedReconciliationDisposition(FrozenModel):
    """One and only one state for one legacy seed."""

    source_item_id: str = Field(min_length=1, max_length=200)
    source_external_id: str = Field(min_length=1, max_length=300)
    seed_name: str = Field(min_length=1, max_length=500)
    normalized_name: str = Field(min_length=1, max_length=500)
    disposition: ReconciliationDisposition
    public_identities: tuple[ReconciledIdentity, ...] = ()
    musicbrainz_identities: tuple[ReconciledIdentity, ...] = ()
    review_identity_names: tuple[str, ...] = ()
    collision_source_item_ids: tuple[str, ...] = ()
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _enforce_state(self) -> SeedReconciliationDisposition:
        _require_unique_identity_claims(self.public_identities, label="public")
        _require_unique_identity_claims(self.musicbrainz_identities, label="MusicBrainz")
        if self.source_item_id in self.collision_source_item_ids:
            raise ValueError("collision IDs cannot contain the disposition's own source ID")
        if len(self.collision_source_item_ids) != len(set(self.collision_source_item_ids)):
            raise ValueError("collision source IDs must be unique")
        if self.disposition == "reconciled" and not (
            self.public_identities and self.musicbrainz_identities
        ):
            raise ValueError("reconciled seeds require both identity facets")
        if self.disposition == "public_only" and not self.public_identities:
            raise ValueError("public-only seeds require a public identity")
        if self.disposition == "musicbrainz_only" and not self.musicbrainz_identities:
            raise ValueError("MusicBrainz-only seeds require a MusicBrainz identity")
        if self.disposition == "review_only" and not self.review_identity_names:
            raise ValueError("review-only seeds require retained review candidates")
        if self.disposition in {"ambiguous", "unresolved"} and self.reason is None:
            raise ValueError("ambiguous and unresolved seeds require a reason")
        if self.disposition != "ambiguous" and _has_multiple_identity_targets_in_one_facet(
            self.public_identities, self.musicbrainz_identities
        ):
            raise ValueError("multiple identity targets within one facet require ambiguity")
        return self


class SeedReconciliationCoverage(FrozenModel):
    """Counts that partition the complete seed universe."""

    seed_count: int = Field(ge=1)
    reconciled_count: int = Field(ge=0)
    public_only_count: int = Field(ge=0)
    musicbrainz_only_count: int = Field(ge=0)
    review_only_count: int = Field(ge=0)
    ambiguous_count: int = Field(ge=0)
    unresolved_count: int = Field(ge=0)
    public_identity_count: int = Field(ge=0)
    musicbrainz_identity_count: int = Field(ge=0)
    musicbrainz_genre_identity_count: int = Field(ge=0)
    musicbrainz_tag_identity_count: int = Field(ge=0)
    collision_seed_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _partition(self) -> SeedReconciliationCoverage:
        total = sum(
            (
                self.reconciled_count,
                self.public_only_count,
                self.musicbrainz_only_count,
                self.review_only_count,
                self.ambiguous_count,
                self.unresolved_count,
            )
        )
        if total != self.seed_count:
            raise ValueError("reconciliation dispositions must account for every seed exactly once")
        if (
            self.musicbrainz_genre_identity_count + self.musicbrainz_tag_identity_count
            != self.musicbrainz_identity_count
        ):
            raise ValueError("MusicBrainz facet counts must sum to the total identity count")
        return self


class SeedReconciliationArtifact(FrozenModel):
    """Content-addressed all-seed reconciliation artifact."""

    revision: Literal["seed-reconciliation-v3"] = _REVISION
    seed_input_sha256: str = Field(pattern=_SHA256_PATTERN)
    seed_source_id: str = Field(min_length=1)
    seed_source_content_sha256: str = Field(pattern=_SHA256_PATTERN)
    seed_identity_sha256: str = Field(pattern=_SHA256_PATTERN)
    taxonomy_artifact_sha256: str = Field(pattern=_SHA256_PATTERN)
    musicbrainz_input_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    input_sha256: str = Field(pattern=_SHA256_PATTERN)
    seed_count: int = Field(ge=1)
    dispositions: tuple[SeedReconciliationDisposition, ...] = Field(min_length=1)
    coverage: SeedReconciliationCoverage
    review_candidates_promoted_to_identity: Literal[0] = 0
    output_sha256: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def _complete_and_safe(self) -> SeedReconciliationArtifact:
        ids = tuple(item.source_item_id for item in self.dispositions)
        if len(ids) != len(set(ids)):
            raise ValueError("reconciliation dispositions must have unique source item IDs")
        if self.seed_count != len(ids) or self.coverage.seed_count != self.seed_count:
            raise ValueError("reconciliation counts must match disposition rows")
        if self.seed_identity_sha256 != _seed_identity_hash_from_dispositions(self.dispositions):
            raise ValueError("reconciliation seed identity hash does not match dispositions")
        if self.coverage.collision_seed_count != sum(
            bool(item.collision_source_item_ids) for item in self.dispositions
        ):
            raise ValueError("collision coverage does not match disposition rows")
        return self


class SeedReconciliationPublicationReceipt(FrozenModel):
    """Typed publication receipt for local or future remote object stores."""

    artifact_sha256: str = Field(pattern=_SHA256_PATTERN)
    artifact_byte_size: int = Field(ge=1)
    object_key: str = Field(min_length=1)
    logical_output_sha256: str = Field(pattern=_SHA256_PATTERN)


class ReconstructionSeedBridgeDisposition(FrozenModel):
    """Per-seed accounting for the reconstruction identity boundary."""

    source_item_id: str = Field(min_length=1, max_length=200)
    seed_name: str = Field(min_length=1, max_length=500)
    reconciliation_disposition: ReconciliationDisposition
    accepted_edge_count: int = Field(ge=0)
    rejected_edge_count: int = Field(ge=0)
    rejection_reasons: tuple[str, ...] = Field(default=(), max_length=16)


class ReconstructionSeedBridgeReport(FrozenModel):
    """Audit the stable-ID conversion without hiding rejected identity rows."""

    revision: Literal["reconstruction-seed-bridge-v2"] = _BRIDGE_REVISION
    reconciliation_output_sha256: str = Field(pattern=_SHA256_PATTERN)
    membership_artifact_sha256: str = Field(pattern=_SHA256_PATTERN)
    input_sha256: str = Field(pattern=_SHA256_PATTERN)
    accepted_edge_count: int = Field(ge=0)
    rejected_edge_count: int = Field(ge=0)
    accepted_genre_count: int = Field(ge=0)
    accepted_artist_count: int = Field(ge=0)
    unattributed_rejected_edge_count: int = Field(ge=0)
    rejected_edge_refs: tuple[str, ...] = ()
    dispositions: tuple[ReconstructionSeedBridgeDisposition, ...] = Field(min_length=1)
    output_sha256: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def _verify_counts_and_hash(self) -> ReconstructionSeedBridgeReport:
        accounted = (
            sum(item.accepted_edge_count + item.rejected_edge_count for item in self.dispositions)
            + self.unattributed_rejected_edge_count
        )
        if self.accepted_edge_count + self.rejected_edge_count != accounted:
            raise ValueError("bridge edge counts do not match per-seed dispositions")
        if self.rejected_edge_count != len(self.rejected_edge_refs):
            raise ValueError("bridge rejected edge count does not match rejected references")
        actual = _sha256(self.model_dump(mode="json", exclude={"output_sha256"}))
        if self.output_sha256 not in {"0" * 64, actual}:
            raise ValueError("reconstruction seed bridge output hash does not match its content")
        return self


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _seed_hash(seed: SeedInput) -> str:
    return _sha256(seed.model_dump(mode="json"))


def _seed_identity_hash(seed: SeedInput) -> str:
    """Hash the canonical stable seed join universe independent of wrappers.

    ``SeedInput.artifact_sha256`` is the H2 name projection and ``_seed_hash``
    seals the complete producer wrapper.  This third hash binds only the stable
    IDs, external IDs, and names that downstream evidence joins actually use.
    """
    return _sha256(
        [
            {
                "source_item_id": item.source_item_id,
                "source_external_id": item.source_external_id,
                "name": item.name,
            }
            for item in sorted(seed.names, key=lambda item: item.source_item_id)
        ]
    )


def _seed_identity_hash_from_dispositions(
    dispositions: tuple[SeedReconciliationDisposition, ...],
) -> str:
    return _sha256(
        [
            {
                "source_item_id": item.source_item_id,
                "source_external_id": item.source_external_id,
                "name": item.seed_name,
            }
            for item in sorted(dispositions, key=lambda item: item.source_item_id)
        ]
    )


def _mb_input_hash(
    source_artifact_sha256: str,
    rows: tuple[MusicBrainzGenreIdentity, ...],
    coverage_report_sha256: str | None = None,
) -> str:
    return _sha256(
        {
            "revision": "musicbrainz-seed-identities-v1",
            "source_artifact_sha256": source_artifact_sha256,
            "coverage_report_sha256": coverage_report_sha256,
            "rows": [row.model_dump(mode="json") for row in rows],
        }
    )


def make_musicbrainz_identity_input(
    source_artifact_sha256: str,
    rows: tuple[MusicBrainzGenreIdentity, ...] = (),
    *,
    coverage_report_sha256: str | None = None,
) -> MusicBrainzIdentityInput:
    """Seal and hash a deterministic explicit MusicBrainz bridge."""
    ordered_rows = tuple(
        sorted(rows, key=lambda row: (row.source_item_id, row.namespace, row.identifier))
    )
    input_sha256 = _mb_input_hash(source_artifact_sha256, ordered_rows, coverage_report_sha256)
    return MusicBrainzIdentityInput(
        source_artifact_sha256=source_artifact_sha256,
        coverage_report_sha256=coverage_report_sha256,
        rows=ordered_rows,
        input_sha256=input_sha256,
    )


def musicbrainz_identity_input_from_coverage(
    coverage: CoverageReport,
    seed: SeedInput,
) -> MusicBrainzIdentityInput:
    """Resolve coverage names once, then emit source-item-ID keyed rows.

    Coverage reports currently expose match-level evidence counts rather than
    individual database row IDs.  The generated references therefore attest
    to the immutable report and match ordinal; they do not pretend to be row
    identifiers.  This is the one explicit lexical boundary: an exact raw
    seed name wins, and normalized matching is used only when it is unique.
    Downstream reconciliation and graph joins use ``source_item_id`` only. A
    match without positive evidence is abstained from this identity input.
    """
    seed_by_raw: dict[str, tuple[str, ...]] = defaultdict(tuple)
    grouped: dict[str, list[str]] = defaultdict(list)
    for item in seed.names:
        grouped[item.name].append(item.source_item_id)
    seed_by_raw = {name: tuple(source_ids) for name, source_ids in grouped.items()}
    grouped = defaultdict(list)
    for item in seed.names:
        grouped[normalize_label(item.name)].append(item.source_item_id)
    if any(len(source_ids) > 1 for source_ids in grouped.values()):
        raise ValueError("duplicate normalized seed names cannot be joined by name")
    seed_by_normalized = {name: tuple(source_ids) for name, source_ids in grouped.items()}
    seed_names = {item.source_item_id: item.name for item in seed.names}
    coverage_sha256 = _sha256(coverage.model_dump(mode="json"))
    rows: list[MusicBrainzGenreIdentity] = []
    for ordinal, match in enumerate(coverage.matches):
        exact_ids = seed_by_raw.get(match.seed_name, ())
        source_ids = exact_ids or seed_by_normalized.get(normalize_label(match.seed_name), ())
        if len(source_ids) != 1:
            raise ValueError(
                f"coverage match cannot be joined to exactly one seed: {match.seed_name!r}"
            )
        if match.positive_evidence_count <= 0:
            continue
        match_kind: Literal["lexical_exact", "lexical_normalized"] = (
            "lexical_exact" if exact_ids else "lexical_normalized"
        )
        namespace: Literal["musicbrainz_genre_id", "musicbrainz_tag_name"] = (
            "musicbrainz_genre_id" if match.facet == "genre" else "musicbrainz_tag_name"
        )
        rows.extend(
            MusicBrainzGenreIdentity(
                source_item_id=source_ids[0],
                namespace=namespace,
                identifier=identifier,
                name=seed_names[source_ids[0]],
                match_kind=match_kind,
                evidence_refs=(
                    f"musicbrainz:coverage:{coverage_sha256}:match:{ordinal}:{match.facet}:{identifier}",
                ),
            )
            for identifier in match.musicbrainz_genre_ids
        )
    return make_musicbrainz_identity_input(
        coverage_sha256,
        tuple(rows),
        coverage_report_sha256=coverage_sha256,
    )


def _reconstruction_identity_key(
    edge: GenreArtistEdge,
) -> tuple[str, str, BridgeFacet]:
    """Parse the source-owned MusicBrainz edge namespace and facet."""
    genre_id = str(edge.genre_id)
    prefix, separator, identifier = genre_id.partition(":")
    kind, separator, identifier = identifier.partition(":")
    if prefix != "musicbrainz" or not separator or not identifier:
        raise ValueError(f"reconstruction edge is not a MusicBrainz identity: {genre_id}")
    if kind == "genre":
        namespace, canonical_facet = "musicbrainz_genre_id", "musicbrainz_genre"
    elif kind == "tag":
        namespace, canonical_facet = "musicbrainz_tag_name", "musicbrainz_tag"
    else:
        raise ValueError(f"unsupported MusicBrainz edge facet: {genre_id}")
    edge_facet = {
        "genre": "musicbrainz_genre",
        "tag": "musicbrainz_tag",
        "musicbrainz_genre": "musicbrainz_genre",
        "musicbrainz_tag": "musicbrainz_tag",
    }.get(str(edge.facet))
    if edge_facet != canonical_facet:
        raise ValueError(f"MusicBrainz edge facet disagrees with its identity: {genre_id}")
    return namespace, identifier, canonical_facet


def _bounded_evidence_ref(prefix: str, refs: set[str]) -> str:
    """Preserve every edge reference in the single public evidence field."""
    reference = prefix + "|".join(sorted(refs))
    if len(reference) > _PUBLIC_EVIDENCE_MAX:
        raise ValueError("aggregated edge evidence exceeds the public evidence bound")
    return reference


class _BridgeAccumulation(NamedTuple):
    aggregates: dict[tuple[str, str, BridgeFacet], float]
    aggregate_refs: dict[tuple[str, str, BridgeFacet], set[str]]
    accepted_by_seed: dict[str, int]
    rejected_by_seed: dict[str, int]
    reasons_by_seed: dict[str, set[str]]
    rejected_edge_refs: tuple[str, ...]
    unattributed_rejected_edge_count: int


def _accumulate_reconstruction_edges(
    reconstruction: ReconstructionInputs,
    identity_index: dict[tuple[str, str], list[SeedReconciliationDisposition]],
    identity_facets: dict[tuple[str, str], set[str]],
) -> _BridgeAccumulation:
    aggregates: dict[tuple[str, str, BridgeFacet], float] = defaultdict(float)
    aggregate_refs: dict[tuple[str, str, BridgeFacet], set[str]] = defaultdict(set)
    accepted_by_seed: dict[str, int] = defaultdict(int)
    rejected_by_seed: dict[str, int] = defaultdict(int)
    reasons_by_seed: dict[str, set[str]] = defaultdict(set)
    rejected_edge_refs: list[str] = []
    unattributed_rejected_edge_count = 0
    for edge in reconstruction.membership_edges:
        namespace, identifier, facet = _reconstruction_identity_key(edge)
        key = (namespace, identifier)
        candidates = identity_index.get(key, [])
        reason: str | None = None
        row: SeedReconciliationDisposition | None = None
        if len(candidates) != 1:
            reason = "missing_identity" if not candidates else "duplicate_identity"
        elif facet not in identity_facets[key]:
            reason = "facet_mismatch"
        else:
            row = candidates[0]
            if row.disposition not in {"reconciled", "musicbrainz_only"}:
                reason = f"reconciliation_{row.disposition}"
        edge_ref = f"{edge.genre_id}|{edge.artist_id}"
        if reason is not None or row is None:
            rejected_edge_refs.append(f"{edge_ref}|{reason or 'rejected'}")
            if row is not None:
                rejected_by_seed[row.source_item_id] += 1
                reasons_by_seed[row.source_item_id].add(reason or "rejected")
            else:
                unattributed_rejected_edge_count += 1
            continue
        aggregate_key = (row.source_item_id, str(edge.artist_id), facet)
        aggregates[aggregate_key] += float(edge.weight)
        aggregate_refs[aggregate_key].update(str(ref) for ref in edge.evidence_refs)
        accepted_by_seed[row.source_item_id] += 1
    return _BridgeAccumulation(
        aggregates=aggregates,
        aggregate_refs=aggregate_refs,
        accepted_by_seed=accepted_by_seed,
        rejected_by_seed=rejected_by_seed,
        reasons_by_seed=reasons_by_seed,
        rejected_edge_refs=tuple(sorted(rejected_edge_refs)),
        unattributed_rejected_edge_count=unattributed_rejected_edge_count,
    )


def public_model_input_from_reconstruction_reconciliation(
    reconstruction: ReconstructionInputs,
    reconciliation: SeedReconciliationArtifact,
) -> tuple[PublicModelInput, ReconstructionSeedBridgeReport]:
    """Convert source edges to stable seed IDs and public model evidence.

    MusicBrainz IDs are accepted only when the verified reconciliation has one
    non-ambiguous ``reconciled`` or ``musicbrainz_only`` disposition for the
    exact identity and matching facet. Review, ambiguous, unresolved, and
    missing identities are retained in the report and excluded from model
    input. Duplicate artist/seed/facet observations are summed with a sorted
    union of evidence references.
    """
    verify_seed_reconciliation(reconciliation)
    seed_rows = {row.source_item_id: row for row in reconciliation.dispositions}
    identity_index: dict[tuple[str, str], list[SeedReconciliationDisposition]] = defaultdict(list)
    identity_facets: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in reconciliation.dispositions:
        for identity in row.musicbrainz_identities:
            key = (identity.namespace, identity.identifier)
            identity_index[key].append(row)
            identity_facets[key].add(
                "musicbrainz_genre"
                if identity.namespace == "musicbrainz_genre_id"
                else "musicbrainz_tag"
            )

    accumulation = _accumulate_reconstruction_edges(reconstruction, identity_index, identity_facets)
    aggregates = accumulation.aggregates
    aggregate_refs = accumulation.aggregate_refs
    accepted_by_seed = accumulation.accepted_by_seed
    rejected_by_seed = accumulation.rejected_by_seed
    reasons_by_seed = accumulation.reasons_by_seed

    report_rows = tuple(
        ReconstructionSeedBridgeDisposition(
            source_item_id=source_item_id,
            seed_name=row.seed_name,
            reconciliation_disposition=row.disposition,
            accepted_edge_count=accepted_by_seed[source_item_id],
            rejected_edge_count=rejected_by_seed[source_item_id],
            rejection_reasons=tuple(sorted(reasons_by_seed[source_item_id])),
        )
        for source_item_id, row in sorted(seed_rows.items())
    )
    ordered_rejected = accumulation.rejected_edge_refs
    input_sha256 = _sha256(
        {
            "reconciliation_output_sha256": reconciliation.output_sha256,
            "membership_artifact": reconstruction.membership_artifact.model_dump(mode="json"),
            "membership_edges": [
                edge.model_dump(mode="json") for edge in reconstruction.membership_edges
            ],
        }
    )
    preliminary_report = ReconstructionSeedBridgeReport(
        reconciliation_output_sha256=reconciliation.output_sha256,
        membership_artifact_sha256=reconstruction.membership_artifact.content_sha256,
        input_sha256=input_sha256,
        accepted_edge_count=sum(accepted_by_seed.values()),
        rejected_edge_count=len(ordered_rejected),
        accepted_genre_count=len({key[0] for key in aggregates}),
        accepted_artist_count=len({key[1] for key in aggregates}),
        unattributed_rejected_edge_count=accumulation.unattributed_rejected_edge_count,
        rejected_edge_refs=ordered_rejected,
        dispositions=report_rows,
        output_sha256="0" * 64,
    )
    report = preliminary_report.model_copy(
        update={
            "output_sha256": _sha256(
                preliminary_report.model_dump(mode="json", exclude={"output_sha256"})
            )
        }
    )
    if not aggregates:
        raise ValueError("reconstruction contains no accepted stable MusicBrainz identities")

    genre_ids = {key[0] for key in aggregates}
    disposition_by_id = {item.source_item_id: item for item in reconciliation.dispositions}
    genres = tuple(
        GenreIdentity(
            genre_id=source_item_id,
            name=disposition_by_id[source_item_id].seed_name,
            evidence_refs=tuple(
                sorted(
                    {
                        ref
                        for identity in disposition_by_id[source_item_id].musicbrainz_identities
                        for ref in identity.evidence_refs
                    }
                    | {f"seed-reconciliation:{reconciliation.output_sha256}:{source_item_id}"}
                )
            ),
        )
        for source_item_id in sorted(genre_ids)
    )
    memberships = tuple(
        DirectMembershipEvidence(
            artist_id=artist_id,
            genre_id=source_item_id,
            facet=facet,
            value=weight,
            evidence_ref=_bounded_evidence_ref(
                f"reconstruction:{reconstruction.membership_artifact.content_sha256}:",
                aggregate_refs[(source_item_id, artist_id, facet)],
            ),
        )
        for (source_item_id, artist_id, facet), weight in sorted(aggregates.items())
    )
    model_input = PublicModelInput(
        artifacts=(
            PublicArtifact(
                source="musicbrainz",
                snapshot=reconstruction.membership_artifact.revision,
                artifact_key=reconstruction.membership_artifact.artifact_key,
                content_sha256=reconstruction.membership_artifact.content_sha256,
                export_allowed=False,
            ),
        ),
        genres=genres,
        direct_memberships=memberships,
    )
    return model_input, report


def _taxonomy_hash(taxonomy: GenreSeedPublicTaxonomyArtifact) -> str:
    """Verify and return the taxonomy artifact's claimed logical hash."""
    payload = taxonomy.model_dump(mode="json", exclude={"output_sha256"})
    actual = _sha256(payload)
    if actual != taxonomy.output_sha256:
        raise ValueError("taxonomy artifact output hash does not match its content")
    return taxonomy.output_sha256


def _validate_shared_seed(seed: SeedInput, taxonomy: GenreSeedPublicTaxonomyArtifact) -> None:
    expected = {item.source_item_id: item for item in seed.names}
    actual = {item.source_item_id: item for item in taxonomy.seed_input.names}
    if set(expected) != set(actual):
        raise ValueError("taxonomy and seed inputs do not contain the same source item IDs")
    for source_item_id, item in expected.items():
        other = actual[source_item_id]
        if item.source_external_id != other.source_external_id or item.name != other.name:
            raise ValueError(f"taxonomy seed identity mismatch for source_item_id {source_item_id}")
    inference_ids = tuple(item.source_item_id for item in taxonomy.inferences)
    if set(inference_ids) != set(expected):
        raise ValueError("taxonomy inferences must contain exactly the seed source item IDs")
    if len(inference_ids) != len(set(inference_ids)):
        raise ValueError("taxonomy inferences must contain one row per source item ID")


def _public_identities(
    status: str,
    exact_candidates: tuple[PublicTaxonomyNode, ...],
) -> tuple[ReconciledIdentity, ...]:
    if status not in {"canonical_exact", "canonical_alias", "ambiguous_exact"}:
        return ()
    identities: list[ReconciledIdentity] = []
    for candidate in exact_candidates:
        # Candidate is a typed Pydantic model from GenreSeedPublicTaxonomyArtifact.
        catalog_id = candidate.catalog_id
        name = candidate.name
        match_kind: IdentityMatchKind = (
            "canonical" if candidate.match_kind == "canonical" else "alias"
        )
        identities.append(
            ReconciledIdentity(
                namespace="wikidata_genre_qid",
                identifier=catalog_id,
                name=name,
                match_kind=match_kind,
            )
        )
    return tuple(sorted(identities, key=lambda item: item.identifier))


def _musicbrainz_identity_conflicts(
    rows: tuple[MusicBrainzGenreIdentity, ...],
) -> dict[str, tuple[IdentityKey, ...]]:
    """Return stable seeds that one exact MusicBrainz identity would target twice.

    Genre UUIDs and tag names are separate source facets, so their agreement
    is corroboration for one seed.  A repeated target *within* either facet is
    different: that source identity cannot simultaneously designate two stable
    seeds and must remain reviewable as ambiguity.
    """
    seed_ids_by_identity: dict[IdentityKey, set[str]] = defaultdict(set)
    for row in rows:
        seed_ids_by_identity[(row.namespace, row.identifier)].add(row.source_item_id)
    conflict_keys = tuple(
        (identity, seed_ids)
        for identity, seed_ids in seed_ids_by_identity.items()
        if len(seed_ids) > 1
    )
    conflicts_by_seed: dict[str, list[IdentityKey]] = defaultdict(list)
    for identity, seed_ids in conflict_keys:
        for source_item_id in seed_ids:
            conflicts_by_seed[source_item_id].append(identity)
    return {
        source_item_id: tuple(sorted(identity_keys))
        for source_item_id, identity_keys in conflicts_by_seed.items()
    }


def _has_multiple_musicbrainz_targets_in_one_facet(
    rows: tuple[MusicBrainzGenreIdentity, ...],
) -> bool:
    """Distinguish same-facet candidate conflicts from cross-facet agreement."""
    namespace_counts = {
        namespace: sum(row.namespace == namespace for row in rows)
        for namespace in ("musicbrainz_genre_id", "musicbrainz_tag_name")
    }
    return any(count > 1 for count in namespace_counts.values())


def _build_disposition(
    seed_item: SeedName,
    inference: SeedTaxonomyInference,
    mb_rows: tuple[MusicBrainzGenreIdentity, ...],
    collision_ids: tuple[str, ...],
    musicbrainz_identity_conflicts: tuple[IdentityKey, ...],
) -> SeedReconciliationDisposition:
    """Build one typed row after stable-ID joins have been validated."""
    public = _public_identities(inference.status, inference.exact_candidates)
    mb = tuple(
        ReconciledIdentity(
            namespace=row.namespace,
            identifier=row.identifier,
            name=row.name,
            match_kind=row.match_kind,
            evidence_refs=row.evidence_refs,
        )
        for row in mb_rows
    )
    review_names: list[str] = []
    if inference.status == "anchored_compositional" and inference.anchor is not None:
        review_names.append(inference.anchor.name)
    if inference.status == "ambiguous_compositional":
        review_names.append(inference.abstention_reason or "ambiguous compositional candidate")
    if inference.status == "ambiguous_exact" or len(public) > 1:
        disposition: ReconciliationDisposition = "ambiguous"
        reason = "multiple public identity candidates remain unresolved"
    elif _has_multiple_musicbrainz_targets_in_one_facet(mb_rows):
        disposition, reason = "ambiguous", "multiple MusicBrainz facet targets remain unresolved"
    elif musicbrainz_identity_conflicts:
        disposition, reason = "ambiguous", "MusicBrainz identity targets multiple stable seeds"
    elif public and mb:
        disposition, reason = "reconciled", None
    elif public:
        disposition, reason = "public_only", None
    elif mb:
        disposition, reason = "musicbrainz_only", None
    elif review_names:
        disposition, reason = "review_only", "public taxonomy candidate is review-only"
    else:
        disposition, reason = "unresolved", inference.abstention_reason or "no identity evidence"
    return SeedReconciliationDisposition(
        source_item_id=seed_item.source_item_id,
        source_external_id=seed_item.source_external_id,
        seed_name=seed_item.name,
        normalized_name=normalize_label(seed_item.name),
        disposition=disposition,
        public_identities=public,
        musicbrainz_identities=mb,
        review_identity_names=tuple(review_names),
        collision_source_item_ids=collision_ids,
        reason=reason,
    )


def _disposition_counts(
    dispositions: tuple[SeedReconciliationDisposition, ...],
) -> dict[ReconciliationDisposition, int]:
    statuses: tuple[ReconciliationDisposition, ...] = (
        "reconciled",
        "public_only",
        "musicbrainz_only",
        "review_only",
        "ambiguous",
        "unresolved",
    )
    return {status: sum(item.disposition == status for item in dispositions) for status in statuses}


def build_seed_reconciliation(
    seed: SeedInput,
    taxonomy: GenreSeedPublicTaxonomyArtifact,
    musicbrainz: MusicBrainzIdentityInput | None = None,
) -> SeedReconciliationArtifact:
    """Build one disposition for every seed using explicit stable-ID joins."""
    _validate_shared_seed(seed, taxonomy)
    taxonomy_hash = _taxonomy_hash(taxonomy)
    if musicbrainz is not None:
        expected_hash = _mb_input_hash(
            musicbrainz.source_artifact_sha256,
            musicbrainz.rows,
            musicbrainz.coverage_report_sha256,
        )
        if expected_hash != musicbrainz.input_sha256:
            raise ValueError("MusicBrainz identity input hash does not match its rows")
    seed_by_id = {item.source_item_id: item for item in seed.names}
    mb_by_seed: dict[str, list[MusicBrainzGenreIdentity]] = defaultdict(list)
    if musicbrainz is not None:
        for row in musicbrainz.rows:
            if row.source_item_id not in seed_by_id:
                raise ValueError(
                    f"MusicBrainz identity is outside the seed universe: {row.source_item_id}"
                )
            mb_by_seed[row.source_item_id].append(row)
    musicbrainz_conflicts_by_seed = _musicbrainz_identity_conflicts(
        musicbrainz.rows if musicbrainz is not None else ()
    )
    normalized_name_groups: dict[str, list[str]] = defaultdict(list)
    for item in seed.names:
        normalized_name_groups[normalize_label(item.name)].append(item.source_item_id)
    taxonomy_by_id = {item.source_item_id: item for item in taxonomy.inferences}
    dispositions: list[SeedReconciliationDisposition] = []
    for seed_item in seed.names:
        inference = taxonomy_by_id[seed_item.source_item_id]
        mb_rows = tuple(
            sorted(
                mb_by_seed[seed_item.source_item_id],
                key=lambda row: (row.namespace, row.identifier),
            )
        )
        collision_ids = tuple(
            sorted(
                item_id
                for item_id in normalized_name_groups[normalize_label(seed_item.name)]
                if item_id != seed_item.source_item_id
            )
        )
        dispositions.append(
            _build_disposition(
                seed_item,
                inference,
                mb_rows,
                collision_ids,
                musicbrainz_conflicts_by_seed.get(seed_item.source_item_id, ()),
            )
        )
    disposition_tuple = tuple(dispositions)
    counts = _disposition_counts(disposition_tuple)
    input_sha256 = _sha256(
        {
            "revision": _REVISION,
            "seed_input_sha256": _seed_hash(seed),
            "seed_source_id": seed.source_id,
            "seed_source_content_sha256": seed.source_content_sha256,
            "seed_identity_sha256": _seed_identity_hash(seed),
            "taxonomy_artifact_sha256": taxonomy_hash,
            "musicbrainz_input_sha256": musicbrainz.input_sha256 if musicbrainz else None,
        }
    )
    coverage = SeedReconciliationCoverage(
        seed_count=len(disposition_tuple),
        reconciled_count=counts["reconciled"],
        public_only_count=counts["public_only"],
        musicbrainz_only_count=counts["musicbrainz_only"],
        review_only_count=counts["review_only"],
        ambiguous_count=counts["ambiguous"],
        unresolved_count=counts["unresolved"],
        public_identity_count=sum(len(item.public_identities) for item in disposition_tuple),
        musicbrainz_identity_count=sum(
            len(item.musicbrainz_identities) for item in disposition_tuple
        ),
        musicbrainz_genre_identity_count=sum(
            sum(
                identity.namespace == "musicbrainz_genre_id"
                for identity in item.musicbrainz_identities
            )
            for item in disposition_tuple
        ),
        musicbrainz_tag_identity_count=sum(
            sum(
                identity.namespace == "musicbrainz_tag_name"
                for identity in item.musicbrainz_identities
            )
            for item in disposition_tuple
        ),
        collision_seed_count=sum(
            bool(item.collision_source_item_ids) for item in disposition_tuple
        ),
    )
    preliminary = SeedReconciliationArtifact(
        seed_input_sha256=_seed_hash(seed),
        seed_source_id=seed.source_id,
        seed_source_content_sha256=seed.source_content_sha256,
        seed_identity_sha256=_seed_identity_hash(seed),
        taxonomy_artifact_sha256=taxonomy_hash,
        musicbrainz_input_sha256=musicbrainz.input_sha256 if musicbrainz else None,
        input_sha256=input_sha256,
        seed_count=len(disposition_tuple),
        dispositions=disposition_tuple,
        coverage=coverage,
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(
        update={
            "output_sha256": _sha256(preliminary.model_dump(mode="json", exclude={"output_sha256"}))
        }
    )


def verify_seed_reconciliation(artifact: SeedReconciliationArtifact) -> None:
    """Fail closed if a serialized artifact was modified or mis-partitioned."""
    if artifact.seed_identity_sha256 != _seed_identity_hash_from_dispositions(
        artifact.dispositions
    ):
        raise ValueError(
            "seed reconciliation stable seed identity hash does not match dispositions"
        )
    actual = _sha256(artifact.model_dump(mode="json", exclude={"output_sha256"}))
    if actual != artifact.output_sha256:
        raise ValueError("seed reconciliation output hash does not match its content")
    if artifact.coverage.seed_count != artifact.seed_count:
        raise ValueError("seed reconciliation coverage count does not match artifact")


def load_seed_reconciliation(path: Path) -> SeedReconciliationArtifact:
    """Parse and verify one persisted reconciliation artifact."""
    artifact = SeedReconciliationArtifact.model_validate_json(path.read_bytes())
    verify_seed_reconciliation(artifact)
    return artifact


def write_seed_reconciliation(artifact: SeedReconciliationArtifact, path: Path) -> str:
    """Write deterministic JSON after verifying its logical hash."""
    verify_seed_reconciliation(artifact)
    payload = (artifact.model_dump_json(indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw_temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return hashlib.sha256(payload).hexdigest()


def publish_seed_reconciliation(
    artifact: SeedReconciliationArtifact, *, output_path: Path, store: ObjectStore
) -> tuple[SeedReconciliationPublicationReceipt, ObjectWrite]:
    """Publish one immutable artifact through the configured ObjectStore."""
    artifact_sha256 = write_seed_reconciliation(artifact, output_path)
    payload_size = output_path.stat().st_size
    key = ObjectKey(value=f"seed-reconciliation/{artifact.output_sha256}/{artifact_sha256}.json")
    write = store.push(output_path, key)
    if write.sha256 != artifact_sha256 or write.byte_size != payload_size:
        raise ValueError("object store write does not match seed reconciliation")
    return (
        SeedReconciliationPublicationReceipt(
            artifact_sha256=artifact_sha256,
            artifact_byte_size=payload_size,
            object_key=key.value,
            logical_output_sha256=artifact.output_sha256,
        ),
        write,
    )
