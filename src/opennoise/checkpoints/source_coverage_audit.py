# ruff: noqa: E501
"""Build a receipt-bound audit of source coverage without promoting evidence.

The audit is deliberately an accounting artifact.  In particular, it keeps
direct observations, the multi-channel graph union, and the pair-split train
matrix in different typed fields.  They answer different questions and must
not be used as interchangeable membership coverage denominators.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, model_validator

from opennoise.common import (
    canonical_json,
    connect_readonly,
    sha256_file,
    sha256_hex,
    write_atomic_bytes,
)
from opennoise.evidence.frontier import (
    AllSeedEvidenceFrontierArtifact,
    verify_all_seed_evidence_frontier,
)
from opennoise.evidence.graph_projection import (
    EvidenceGraphProjectionArtifact,
    verify_evidence_graph_projection,
)
from opennoise.ingest.musicbrainz.release_group_evidence import (
    ReleaseGroupEvidenceArtifact,
    verify_release_group_evidence,
)
from opennoise.ml.full_graph_signal import FullGraphSignalArtifact, verify_full_graph_signal
from opennoise.models import FrozenModel
from opennoise.serving.local.musicbrainz_artist_metadata import (
    ArtistMetadataArtifact,
    verify_artist_metadata_artifact,
)

if TYPE_CHECKING:
    from pathlib import Path

_SEED_COUNT: Final = 6_291
_SHA: Final = r"^[0-9a-f]{64}$"
_MEMBERSHIP_COUNT_COLUMNS: Final = 3
_GRAPH_RECEIPT_ROLES: Final = frozenset(
    {
        "sealed_frontier_v5",
        "musicbrainz_database",
        "musicbrainz_artifact",
        "reviewed_alias_context",
        "wikidata_factual_hierarchy",
        "direct_peer",
        "support_peer",
        "filtered_support_peer",
    }
)


class SourceCoverageAuditError(ValueError):
    """The source-coverage audit could not verify its sealed inputs."""


class ArtifactBinding(FrozenModel):
    """One hash-bound artifact, with verification scope stated by its container."""

    role: str = Field(min_length=1)
    path: str = Field(min_length=1)
    byte_sha256: str = Field(pattern=_SHA)
    byte_count: int = Field(gt=0)
    logical_sha256: str = Field(pattern=_SHA)


class MembershipCoverage(FrozenModel):
    """Counts with an explicit semantic boundary, never an implied fact label."""

    scope: Literal[
        "release_direct_anchor",
        "graph_direct_claim",
        "graph_multi_channel_union",
        "pair_split_train_matrix",
    ]
    seed_count: int = Field(ge=0, le=_SEED_COUNT)
    artist_count: int = Field(ge=0)
    pair_count: int = Field(ge=0)
    heldout_pair_count: int | None = Field(default=None, ge=0)
    claim_count: int | None = Field(default=None, ge=0)
    evidence_kinds: tuple[str, ...] = Field(min_length=1)
    definition: str = Field(min_length=1)

    @model_validator(mode="after")
    def _scope_has_the_right_terminology(self) -> MembershipCoverage:
        if self.scope == "release_direct_anchor":
            if (
                self.claim_count is not None
                or self.heldout_pair_count is not None
                or self.evidence_kinds != ("artist_direct",)
            ):
                raise ValueError("release direct anchors must not be presented as graph claims")
        elif self.scope == "graph_direct_claim":
            if (
                self.claim_count is None
                or self.heldout_pair_count is not None
                or self.evidence_kinds != ("artist_direct",)
            ):
                raise ValueError("graph direct scope requires only artist_direct claims")
        elif self.scope == "graph_multi_channel_union":
            if (
                self.claim_count is not None
                or self.heldout_pair_count is not None
                or self.evidence_kinds
                != (
                    "artist_direct",
                    "release_group_support",
                    "reviewed_alias_context",
                )
            ):
                raise ValueError("graph union must name all and only admitted membership channels")
        elif self.scope == "pair_split_train_matrix" and (
            self.claim_count is not None
            or self.heldout_pair_count is None
            or "pair_split" not in self.definition
        ):
            raise ValueError("matrix coverage must explicitly name pair-split scope")
        return self


class ArtifactCoverage(FrozenModel):
    """A repository inventory row, not necessarily an audit-rehashed artifact."""

    adapter: str = Field(min_length=1)
    artifact_role: str = Field(min_length=1)
    state: Literal["sealed", "implemented_no_sealed_input", "evaluation_only"]
    verification_scope: Literal[
        "audit_rehashed",
        "receipt_declared",
        "repository_documented_only",
    ]
    signals: tuple[
        Literal[
            "identity",
            "artist_membership",
            "releases",
            "tags",
            "co_listen",
            "hierarchy",
            "external_links",
        ],
        ...,
    ] = Field(min_length=1)
    boundary: str = Field(min_length=1)


class EnrichmentOpportunity(FrozenModel):
    """A repository-documented hypothesis, never a verified coverage forecast."""

    rank: int = Field(ge=1)
    source: str = Field(min_length=1)
    status: Literal[
        "repository_documented_unverified",
        "implemented_missing_input",
        "not_implemented",
    ]
    expected_seed_artist_coverage: str = Field(min_length=1)
    acquisition_cost: Literal["low", "medium", "high"]
    reproducibility: Literal["high", "medium", "low"]
    label_precision: Literal["direct", "contextual_review_only", "unknown"]
    recommendation: str = Field(min_length=1)


class SourceCoverageAudit(FrozenModel):
    """Immutable source inventory and scope-safe checkpoint accounting."""

    revision: Literal["source-coverage-audit-v1"] = "source-coverage-audit-v1"
    stable_seed_count: Literal[6291] = _SEED_COUNT
    rehashed_inputs: tuple[ArtifactBinding, ...] = Field(min_length=5, max_length=5)
    receipt_declared_graph_inputs: tuple[ArtifactBinding, ...] = Field(min_length=8, max_length=8)
    direct_observed_frontier_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    musicbrainz_direct_frontier_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    wikidata_only_direct_frontier_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    memberships: tuple[MembershipCoverage, ...] = Field(min_length=4, max_length=4)
    artifact_inventory: tuple[ArtifactCoverage, ...] = Field(min_length=1)
    enrichment_ranking: tuple[EnrichmentOpportunity, ...] = Field(min_length=1)
    output_sha256: str = Field(pattern=_SHA)

    @model_validator(mode="after")
    def _prevent_scope_conflation(self) -> SourceCoverageAudit:  # noqa: C901
        if {item.role for item in self.receipt_declared_graph_inputs} != _GRAPH_RECEIPT_ROLES:
            raise ValueError("audit must preserve every declared evidence-graph input role")
        scopes = {coverage.scope: coverage for coverage in self.memberships}
        required = {
            "release_direct_anchor",
            "graph_direct_claim",
            "graph_multi_channel_union",
            "pair_split_train_matrix",
        }
        if set(scopes) != required:
            raise ValueError("audit must retain all distinct direct, union, and matrix scopes")
        release_direct = scopes["release_direct_anchor"]
        graph_direct = scopes["graph_direct_claim"]
        graph_union = scopes["graph_multi_channel_union"]
        train_matrix = scopes["pair_split_train_matrix"]
        if graph_direct.seed_count != release_direct.seed_count:
            raise ValueError("direct graph and release anchor seed scopes no longer agree")
        if (
            graph_direct.seed_count > graph_union.seed_count
            or graph_direct.artist_count > graph_union.artist_count
        ):
            raise ValueError("direct graph coverage cannot exceed the multi-channel union")
        if (
            train_matrix.seed_count > graph_union.seed_count
            or train_matrix.artist_count != graph_union.artist_count
        ):
            raise ValueError("pair-split matrix cannot be labeled as broader than graph union")
        if self.musicbrainz_direct_frontier_seed_count != graph_direct.seed_count:
            raise ValueError(
                "MusicBrainz frontier direct coverage must match graph direct seed scope"
            )
        if self.direct_observed_frontier_seed_count != (
            self.musicbrainz_direct_frontier_seed_count
            + self.wikidata_only_direct_frontier_seed_count
        ):
            raise ValueError(
                "frontier direct coverage must partition MusicBrainz and Wikidata-only seeds"
            )
        heldout_pairs = train_matrix.heldout_pair_count
        if heldout_pairs is None:
            raise ValueError("pair-split matrix must declare held-out pairs")
        if train_matrix.pair_count + heldout_pairs != graph_union.pair_count:
            raise ValueError("pair split must partition complete graph-union pairs")
        if tuple(item.rank for item in self.enrichment_ranking) != tuple(
            range(1, len(self.enrichment_ranking) + 1)
        ):
            raise ValueError("enrichment ranking must be contiguous and deterministic")
        return self


@dataclass(frozen=True, slots=True)
class SourceCoverageAuditInputs:
    """The current small receipts plus the graph database used for aggregate checks."""

    root: Path
    graph_database: Path
    graph_receipt: Path
    full_graph: Path
    release_group_evidence: Path
    artist_metadata: Path
    frontier: Path


def source_coverage_audit_sha256(audit: SourceCoverageAudit) -> str:
    """Return the canonical logical checksum excluding the self hash."""
    return sha256_hex(canonical_json(audit.model_dump(mode="json", exclude={"output_sha256"})))


def verify_source_coverage_audit(audit: SourceCoverageAudit) -> None:
    """Reject an edited audit or a scope-invalid accounting statement."""
    if audit.output_sha256 != source_coverage_audit_sha256(audit):
        raise SourceCoverageAuditError("source coverage audit hash does not replay")


def build_source_coverage_audit(inputs: SourceCoverageAuditInputs) -> SourceCoverageAudit:
    """Verify current receipts and write no model, membership, or source data."""
    root = inputs.root.resolve()
    graph = _load_graph_receipt(inputs.graph_receipt)
    _verify_graph_database(inputs.graph_database, graph)
    full = _load_full_graph(inputs.full_graph)
    release = _load_release_group(inputs.release_group_evidence)
    metadata = _load_metadata(inputs.artist_metadata)
    frontier = _load_frontier(inputs.frontier)
    _verify_cross_artifact_lineage(graph, full, release, metadata, frontier)
    (
        membership_claims,
        direct_claims,
        direct_artists,
        direct_seeds,
        union_pairs,
        union_artists,
        union_seeds,
    ) = _graph_membership_counts(inputs.graph_database)
    if direct_seeds != release.coverage.direct_anchor_genre_count:
        raise SourceCoverageAuditError(
            "graph direct seed count does not match release direct anchors"
        )
    if (union_pairs, union_artists, union_seeds) != (
        full.pair_split.unique_pair_count,
        full.pair_split.artist_count,
        2_570,
    ):
        raise SourceCoverageAuditError("full graph pair split does not match complete graph union")
    if full.pair_split.claims_streamed != membership_claims:
        raise SourceCoverageAuditError("full graph claims streamed do not match membership claims")
    if graph.claim_count < membership_claims:
        raise SourceCoverageAuditError(
            "graph receipt has fewer claims than its membership predicate"
        )
    if metadata.target_artist_count != union_artists:
        raise SourceCoverageAuditError(
            "release-credit metadata targets do not match graph artist union"
        )
    bindings = (
        _binding("evidence_graph_receipt", inputs.graph_receipt, root, graph.output_sha256),
        _binding("full_graph_signal", inputs.full_graph, root, full.output_sha256),
        _binding(
            "release_group_evidence", inputs.release_group_evidence, root, release.output_sha256
        ),
        _binding("artist_metadata", inputs.artist_metadata, root, metadata.output_sha256),
        _binding("sealed_frontier_v5", inputs.frontier, root, frontier.output_sha256),
    )
    base = SourceCoverageAudit(
        rehashed_inputs=bindings,
        receipt_declared_graph_inputs=tuple(
            ArtifactBinding(
                role=item.role,
                path=item.path,
                byte_sha256=item.byte_sha256,
                byte_count=item.byte_count,
                logical_sha256=item.logical_sha256,
            )
            for item in graph.inputs
        ),
        direct_observed_frontier_seed_count=frontier.coverage.direct_observed_seed_count,
        musicbrainz_direct_frontier_seed_count=frontier.coverage.observed_musicbrainz_seed_count,
        wikidata_only_direct_frontier_seed_count=(
            frontier.coverage.observed_wikidata_only_seed_count
        ),
        memberships=(
            MembershipCoverage(
                scope="release_direct_anchor",
                seed_count=release.coverage.direct_anchor_genre_count,
                artist_count=0,
                pair_count=release.coverage.direct_anchor_membership_count,
                evidence_kinds=("artist_direct",),
                definition="MusicBrainz release-group artifact direct-anchor pairs; it does not carry graph claim or artist-union accounting.",
            ),
            MembershipCoverage(
                scope="graph_direct_claim",
                seed_count=direct_seeds,
                artist_count=direct_artists,
                pair_count=0,
                claim_count=direct_claims,
                evidence_kinds=("artist_direct",),
                definition="Current evidence-graph artist_direct claims and their distinct endpoints; direct observations only.",
            ),
            MembershipCoverage(
                scope="graph_multi_channel_union",
                seed_count=union_seeds,
                artist_count=union_artists,
                pair_count=union_pairs,
                evidence_kinds=("artist_direct", "release_group_support", "reviewed_alias_context"),
                definition="Distinct artist--seed pairs across all admitted graph membership channels; support and review context are not direct facts.",
            ),
            MembershipCoverage(
                scope="pair_split_train_matrix",
                seed_count=full.pair_split.observed_seed_count,
                artist_count=full.pair_split.artist_count,
                pair_count=full.pair_split.train_pair_count,
                heldout_pair_count=full.pair_split.heldout_pair_count,
                evidence_kinds=("artist_direct", "release_group_support", "reviewed_alias_context"),
                definition="Active seed columns in the full-graph training matrix after pair_split; held-out pairs are excluded from this matrix.",
            ),
        ),
        artifact_inventory=_INVENTORY,
        enrichment_ranking=_RANKING,
        output_sha256="0" * 64,
    )
    audit = base.model_copy(update={"output_sha256": source_coverage_audit_sha256(base)})
    verify_source_coverage_audit(audit)
    return audit


def write_source_coverage_audit(path: Path, audit: SourceCoverageAudit) -> None:
    """Atomically persist a verified deterministic audit JSON document."""
    verify_source_coverage_audit(audit)
    write_atomic_bytes(path, canonical_json(audit.model_dump(mode="json")) + b"\n")


def _binding(role: str, path: Path, root: Path, logical: str) -> ArtifactBinding:
    digest, size = sha256_file(path)
    try:
        locator = str(path.resolve().relative_to(root))
    except ValueError as error:
        raise SourceCoverageAuditError("audit inputs must be under root") from error
    return ArtifactBinding(
        role=role,
        path=locator,
        byte_sha256=digest,
        byte_count=size,
        logical_sha256=logical,
    )


def _load_graph_receipt(path: Path) -> EvidenceGraphProjectionArtifact:
    try:
        artifact = EvidenceGraphProjectionArtifact.model_validate_json(path.read_bytes())
        verify_evidence_graph_projection(artifact)
    except (OSError, ValueError) as error:
        raise SourceCoverageAuditError("invalid graph receipt") from error
    return artifact


def _load_full_graph(path: Path) -> FullGraphSignalArtifact:
    try:
        artifact = FullGraphSignalArtifact.model_validate_json(path.read_bytes())
        verify_full_graph_signal(artifact)
    except (OSError, ValueError) as error:
        raise SourceCoverageAuditError("invalid full graph signal") from error
    return artifact


def _load_release_group(path: Path) -> ReleaseGroupEvidenceArtifact:
    try:
        artifact = ReleaseGroupEvidenceArtifact.model_validate_json(path.read_bytes())
        verify_release_group_evidence(artifact)
    except (OSError, ValueError) as error:
        raise SourceCoverageAuditError("invalid release-group evidence") from error
    return artifact


def _load_metadata(path: Path) -> ArtistMetadataArtifact:
    try:
        artifact = ArtistMetadataArtifact.model_validate_json(path.read_bytes())
        verify_artist_metadata_artifact(artifact)
    except (OSError, ValueError) as error:
        raise SourceCoverageAuditError("invalid artist metadata receipt") from error
    return artifact


def _load_frontier(path: Path) -> AllSeedEvidenceFrontierArtifact:
    try:
        artifact = AllSeedEvidenceFrontierArtifact.model_validate_json(path.read_bytes())
        verify_all_seed_evidence_frontier(artifact)
    except (OSError, ValueError) as error:
        raise SourceCoverageAuditError("invalid sealed frontier") from error
    return artifact


def _verify_graph_database(path: Path, receipt: EvidenceGraphProjectionArtifact) -> None:
    digest, size = sha256_file(path)
    if (digest, size) != (receipt.database_sha256, receipt.database_bytes):
        raise SourceCoverageAuditError("graph database bytes do not match graph receipt")


def _verify_cross_artifact_lineage(
    graph: EvidenceGraphProjectionArtifact,
    full: FullGraphSignalArtifact,
    release: ReleaseGroupEvidenceArtifact,
    metadata: ArtistMetadataArtifact,
    frontier: AllSeedEvidenceFrontierArtifact,
) -> None:
    graph_inputs = {item.role: item.logical_sha256 for item in graph.inputs}
    if graph_inputs.get("sealed_frontier_v5") != frontier.output_sha256:
        raise SourceCoverageAuditError("graph receipt does not bind the supplied sealed frontier")
    if graph_inputs.get("musicbrainz_artifact") != release.output_sha256:
        raise SourceCoverageAuditError("graph receipt does not bind the supplied release evidence")
    if full.graph_receipt_output_sha256 != graph.output_sha256:
        raise SourceCoverageAuditError("full graph signal does not bind the supplied graph receipt")
    if metadata.evidence_output_sha256 != release.output_sha256:
        raise SourceCoverageAuditError(
            "metadata receipt does not bind the supplied release evidence"
        )


def _graph_membership_counts(path: Path) -> tuple[int, int, int, int, int, int, int]:
    with closing(connect_readonly(path)) as database:
        membership = database.execute(
            "SELECT count(*) FROM claim WHERE predicate = 'artist_membership'"
        ).fetchone()
        direct = database.execute(
            """SELECT count(*), count(DISTINCT subject_identifier), count(DISTINCT object_identifier)
            FROM claim WHERE predicate = 'artist_membership' AND evidence_kind = 'artist_direct'"""
        ).fetchone()
        union = database.execute(
            """SELECT count(*), count(DISTINCT subject_identifier), count(DISTINCT object_identifier)
            FROM (SELECT DISTINCT subject_identifier, object_identifier FROM claim
                  WHERE predicate = 'artist_membership')"""
        ).fetchone()
    if (
        membership is None
        or direct is None
        or union is None
        or len(membership) != 1
        or len(direct) != _MEMBERSHIP_COUNT_COLUMNS
        or len(union) != _MEMBERSHIP_COUNT_COLUMNS
    ):
        raise SourceCoverageAuditError("could not aggregate graph membership coverage")
    return (
        int(membership[0]),
        int(direct[0]),
        int(direct[1]),
        int(direct[2]),
        int(union[0]),
        int(union[1]),
        int(union[2]),
    )


_INVENTORY: Final[tuple[ArtifactCoverage, ...]] = (
    ArtifactCoverage(
        adapter="Wikidata resolver and taxonomy relation expansion",
        artifact_role="sealed_frontier_v5",
        state="sealed",
        verification_scope="receipt_declared",
        signals=("identity", "artist_membership", "releases", "hierarchy", "external_links"),
        boundary="Public QID/P136/P279 source rows remain separately provenance-bound; only accepted hierarchy edges are factual.",
    ),
    ArtifactCoverage(
        adapter="MusicBrainz artist/tag seed-target extraction",
        artifact_role="musicbrainz_seed_targets",
        state="sealed",
        verification_scope="repository_documented_only",
        signals=("artist_membership", "tags"),
        boundary="Exact normalized matches are direct anchors; contextual tag rows are not factual memberships.",
    ),
    ArtifactCoverage(
        adapter="MusicBrainz release-group evidence",
        artifact_role="release_group_evidence",
        state="sealed",
        verification_scope="receipt_declared",
        signals=("artist_membership", "releases", "tags"),
        boundary="Release-group labels are credited-artist support, never artist-direct facts.",
    ),
    ArtifactCoverage(
        adapter="MusicBrainz release-credit metadata",
        artifact_role="artist_metadata",
        state="sealed",
        verification_scope="audit_rehashed",
        signals=("identity", "releases", "external_links"),
        boundary="Exact MusicBrainz ID/name metadata is local research only and contains no membership label.",
    ),
    ArtifactCoverage(
        adapter="Reviewed MusicBrainz alias context",
        artifact_role="evidence_graph_input",
        state="sealed",
        verification_scope="receipt_declared",
        signals=("artist_membership", "tags"),
        boundary="Reviewed alias context remains its own evidence kind; it is not a direct source row.",
    ),
    ArtifactCoverage(
        adapter="ListenBrainz qualified aggregate and co-listen overlays",
        artifact_role="listenbrainz_overlay",
        state="sealed",
        verification_scope="repository_documented_only",
        signals=("co_listen",),
        boundary="Privacy-floor aggregates are receipt-bound; no artist-level ListenBrainz similarity is materialized in the full graph.",
    ),
    ArtifactCoverage(
        adapter="Last.fm reverse-tag adapter",
        artifact_role="lastfm_reverse_tag",
        state="implemented_no_sealed_input",
        verification_scope="repository_documented_only",
        signals=("artist_membership", "tags"),
        boundary="No response cache or evidence receipt exists; exact-ID corroboration would still be review-only.",
    ),
    ArtifactCoverage(
        adapter="MSD/Last.fm offline adapter",
        artifact_role="msd_lastfm",
        state="implemented_no_sealed_input",
        verification_scope="repository_documented_only",
        signals=("artist_membership", "tags", "co_listen"),
        boundary="Required SQLite inputs and verified cache receipt are absent.",
    ),
    ArtifactCoverage(
        adapter="MusicBrainz-to-Spotify bridge",
        artifact_role="spotify_bridge",
        state="evaluation_only",
        verification_scope="repository_documented_only",
        signals=("external_links",),
        boundary="Historical compatibility evaluation only; it is forbidden from open-model construction.",
    ),
)

_RANKING: Final[tuple[EnrichmentOpportunity, ...]] = (
    EnrichmentOpportunity(
        rank=1,
        source="Existing MusicBrainz contextual artist-tag matrix",
        status="repository_documented_unverified",
        expected_seed_artist_coverage="Measured inventory: 212,696 contextual rows over 88,328 artists; exact new-seed/artist lift is unmeasured. Its maximum seed ceiling is the 3,914 labels outside the 2,377 direct-anchor set.",
        acquisition_cost="low",
        reproducibility="high",
        label_precision="contextual_review_only",
        recommendation="First run a receipt-bound, held-out exact-label calibration and report candidate lift by seed before any review queue or membership use.",
    ),
    EnrichmentOpportunity(
        rank=2,
        source="MSD/Last.fm offline exact-ID adapter",
        status="implemented_missing_input",
        expected_seed_artist_coverage="Unknown until the three required SQLite inputs and receipt are supplied; potentially broad but no retained count supports a forecast.",
        acquisition_cost="medium",
        reproducibility="medium",
        label_precision="contextual_review_only",
        recommendation="Acquire only with source custody and evaluate exact artist-ID joins separately from tag-label normalization.",
    ),
    EnrichmentOpportunity(
        rank=3,
        source="Last.fm reverse-tag API adapter",
        status="implemented_missing_input",
        expected_seed_artist_coverage="Unknown; no API response cache, query receipt, or measured candidate count is present.",
        acquisition_cost="medium",
        reproducibility="low",
        label_precision="contextual_review_only",
        recommendation="Do not prioritize ahead of sealed MusicBrainz evidence; require approved key, manifest, cached responses, and exact corroboration.",
    ),
    EnrichmentOpportunity(
        rank=4,
        source="Broader Wikidata artist P136 querying",
        status="repository_documented_unverified",
        expected_seed_artist_coverage="Observed marginal seed lift in the current reconciliation is one Wikidata-only direct seed, so expansion is not evidenced as a high-yield seed strategy.",
        acquisition_cost="low",
        reproducibility="high",
        label_precision="direct",
        recommendation="Use only for targeted factual backfill after measuring new QID and artist yield; do not describe it as the primary expansion path.",
    ),
    EnrichmentOpportunity(
        rank=5,
        source="Discogs",
        status="not_implemented",
        expected_seed_artist_coverage="Unknown; no adapter, receipt, or repository measurement is present.",
        acquisition_cost="high",
        reproducibility="low",
        label_precision="unknown",
        recommendation="Defer until licensing, acquisition, canonical artist-ID joins, and provenance policy are specified.",
    ),
)
