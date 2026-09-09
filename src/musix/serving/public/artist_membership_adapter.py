"""Adapt certified SQLite evidence into the narrow public-membership input.

The adapter is deliberately separate from graph construction.  It reads only
direct source claims with an explicit export permission and, when requested,
already-aggregated ListenBrainz pair rows.  It never reads audio, recordings,
historical artist memberships, or a model output.
"""
# The SQL strings interpolate only placeholder counts; every value remains a
# sqlite bound parameter. Ruff's heuristic cannot see that construction.
# ruff: noqa: S608

from __future__ import annotations

import hashlib
import sqlite3
from collections import defaultdict
from contextlib import closing
from typing import TYPE_CHECKING, Literal

from pydantic import Field, model_validator

from musix.models.modeling import (
    ArtistPairEvidence,
    DirectMembershipEvidence,
    GenreIdentity,
    PublicArtifact,
    PublicModelInput,
)
from musix.serving.public.artist_membership import (
    ApprovedPublicMembershipInput,
    PublicArtistMembershipSourcePolicy,
    StrictFrozenModel,
    _sha256,
)

if TYPE_CHECKING:
    from pathlib import Path

from musix.types import Sha256  # noqa: TC001


def _file_sha256(path: Path) -> Sha256:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class CertifiedPublicDirectSelector(StrictFrozenModel):
    """One direct source/facet and the rights license required for its rows."""

    source: Literal["wikidata", "musicbrainz"]
    facet: Literal["wikidata_p136", "musicbrainz_tag"]
    source_key_prefix: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.:-]+$")
    method_key: str = Field(min_length=1)
    required_license: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_declared_mapping(self) -> CertifiedPublicDirectSelector:
        """Reject a selector whose source family does not match its facet."""
        expected = {
            "wikidata": ("wikidata_p136", "wikidata_p136"),
            "musicbrainz": ("musicbrainz_tag", "musicbrainz_artist_tag"),
        }
        if expected[self.source] != (self.facet, self.method_key):
            raise ValueError("direct selector source, facet, and method key are inconsistent")
        return self


class CertifiedPublicMembershipAdapterPolicy(StrictFrozenModel):
    """Bound the only SQLite rows that may reach the public candidate."""

    revision: Literal["certified-public-membership-adapter-v1"] = (
        "certified-public-membership-adapter-v1"
    )
    direct_selectors: tuple[CertifiedPublicDirectSelector, ...] = (
        CertifiedPublicDirectSelector(
            source="wikidata",
            facet="wikidata_p136",
            source_key_prefix="wikidata_phase3_artists_",
            method_key="wikidata_p136",
            required_license="CC0-1.0",
        ),
    )
    require_public_domain: Literal[True] = True
    include_aggregate_candidates: bool = False
    aggregate_source_key_prefix: str = Field(
        default="listenbrainz_", min_length=1, pattern=r"^[A-Za-z0-9_.:-]+$"
    )
    minimum_distinct_users_per_window: int = Field(default=5, ge=1, le=100_000)
    maximum_direct_rows: int = Field(default=1_000_000, ge=1, le=1_000_000)
    maximum_aggregate_pairs: int = Field(default=5_000_000, ge=1, le=5_000_000)

    @model_validator(mode="after")
    def require_unique_selectors(self) -> CertifiedPublicMembershipAdapterPolicy:
        """Keep each source/facet/license choice explicit and independently rights-bound."""
        if not self.direct_selectors:
            raise ValueError("adapter must declare at least one direct selector")
        keys = tuple(
            (item.source, item.facet, item.source_key_prefix) for item in self.direct_selectors
        )
        if len(keys) != len(set(keys)):
            raise ValueError("adapter direct selectors must be unique")
        if self.require_public_domain and any(
            item.required_license != "CC0-1.0" for item in self.direct_selectors
        ):
            raise ValueError("public-domain adapter selectors require CC0-1.0")
        return self

    @property
    def effective_direct_sources(self) -> tuple[Literal["wikidata", "musicbrainz"], ...]:
        """Return source families in selector order."""
        return tuple(item.source for item in self.direct_selectors)

    @property
    def effective_direct_facets(self) -> tuple[Literal["wikidata_p136", "musicbrainz_tag"], ...]:
        """Return direct facets in selector order."""
        return tuple(item.facet for item in self.direct_selectors)

    @property
    def effective_direct_prefixes(self) -> tuple[str, ...]:
        """Return source-key prefixes in selector order."""
        return tuple(item.source_key_prefix for item in self.direct_selectors)

    @property
    def effective_direct_methods(self) -> tuple[str, ...]:
        """Return evidence method keys in selector order."""
        return tuple(item.method_key for item in self.direct_selectors)


class CertifiedPublicSourceBinding(StrictFrozenModel):
    """One immutable source snapshot and the policy that allowed its export."""

    source_key: str = Field(min_length=1, max_length=200)
    license_name: str = Field(min_length=1, max_length=200)
    policy_key: str = Field(min_length=1, max_length=500)
    policy_version: int = Field(ge=1)
    classification: Literal["public_domain"]
    local_only: Literal[False] = False
    snapshot_ref: str = Field(min_length=1, max_length=500)
    manifest_sha256: Sha256
    artifact_ref: str = Field(min_length=1, max_length=500)
    artifact_sha256: Sha256
    row_count: int = Field(ge=1)


class CertifiedPublicMembershipAdapterReceipt(StrictFrozenModel):
    """Replay receipt binding the DB bytes, export policies, and adapted rows."""

    revision: Literal["certified-public-membership-adapter-receipt-v1"] = (
        "certified-public-membership-adapter-receipt-v1"
    )
    database_file_sha256: Sha256
    adapter_policy_sha256: Sha256
    row_export_policy_sha256: Sha256
    direct_source_bindings: tuple[CertifiedPublicSourceBinding, ...] = Field(min_length=1)
    aggregate_source_bindings: tuple[CertifiedPublicSourceBinding, ...] = ()
    direct_row_count: int = Field(ge=1)
    aggregate_pair_count: int = Field(ge=0)
    approved_input_sha256: Sha256
    output_sha256: Sha256
    aggregate_run_ref: str | None = None
    aggregate_window_seconds: int | None = Field(default=None, gt=0)
    aggregate_minimum_distinct_users: int | None = Field(default=None, gt=0)
    aggregate_listens_seen: int | None = Field(default=None, ge=0)
    aggregate_distinct_artists: int | None = Field(default=None, ge=0)
    aggregate_user_windows: int | None = Field(default=None, ge=0)
    aggregate_candidate_pairs: int | None = Field(default=None, ge=0)
    aggregate_emitted_pairs: int | None = Field(default=None, ge=0)
    aggregate_quarantined_records: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_recomputed_output_hash(self) -> CertifiedPublicMembershipAdapterReceipt:
        """Reject receipts whose canonical payload was changed after adaptation."""
        payload = self.model_dump(mode="json", exclude={"output_sha256"})
        if _sha256(payload) != self.output_sha256:
            raise ValueError("adapter receipt output hash does not match adapted input")
        return self


class CertifiedPublicMembershipAdaptation(StrictFrozenModel):
    """The strict construction input and its independently verifiable receipt."""

    approved_input: ApprovedPublicMembershipInput
    receipt: CertifiedPublicMembershipAdapterReceipt

    @model_validator(mode="after")
    def require_cross_bound_hashes(self) -> CertifiedPublicMembershipAdaptation:
        """Require the approved input and receipt to bind the same immutable rows."""
        if self.approved_input.input_file_sha256 != self.receipt.database_file_sha256:
            raise ValueError("approved input must bind the exact certified database file")
        if self.approved_input.row_export_policy_sha256 != self.receipt.row_export_policy_sha256:
            raise ValueError("approved input must bind the receipt export-policy hash")
        if self.approved_input.public_model_input_sha256 != self.receipt.approved_input_sha256:
            raise ValueError("approved input hash must match adapter receipt")
        return self


def verify_certified_public_membership_receipt(
    approved_input: ApprovedPublicMembershipInput,
    receipt: CertifiedPublicMembershipAdapterReceipt,
    database_path: Path,
    adapter_policy: CertifiedPublicMembershipAdapterPolicy,
) -> None:
    """Verify a build's approved rows are exactly from the supplied adapter run."""
    derived = adapt_certified_public_membership_input(database_path, adapter_policy)
    if approved_input != derived.approved_input or receipt != derived.receipt:
        raise ValueError("approved input and adapter receipt do not reproduce database rows")
    if _file_sha256(database_path) != receipt.database_file_sha256:
        raise ValueError("adapter receipt database hash does not match the supplied database")
    if approved_input.input_file_sha256 != receipt.database_file_sha256:
        raise ValueError("approved input database hash does not match adapter receipt")
    if approved_input.public_model_input_sha256 != receipt.approved_input_sha256:
        raise ValueError("approved input model hash does not match adapter receipt")
    if approved_input.row_export_policy_sha256 != receipt.row_export_policy_sha256:
        raise ValueError("approved input policy hash does not match adapter receipt")
    if approved_input.declared_direct_row_count != receipt.direct_row_count:
        raise ValueError("approved direct row count does not match adapter receipt")
    if approved_input.declared_aggregate_row_count != receipt.aggregate_pair_count:
        raise ValueError("approved aggregate row count does not match adapter receipt")
    if _sha256(adapter_policy.model_dump(mode="json")) != receipt.adapter_policy_sha256:
        raise ValueError("adapter policy hash does not match adapter receipt")


def _source_family_for_key(
    source_key: str, policy: CertifiedPublicMembershipAdapterPolicy
) -> Literal["wikidata", "musicbrainz"]:
    """Map a selected source key through the declared policy union."""
    for selector in policy.direct_selectors:
        if source_key.startswith(selector.source_key_prefix):
            return selector.source
    raise ValueError("source key is outside the declared direct source union")


def _direct_source_bindings(
    connection: sqlite3.Connection,
    source_counts: dict[str, int],
    policy: CertifiedPublicMembershipAdapterPolicy,
) -> tuple[CertifiedPublicSourceBinding, ...]:
    """Bind each selected direct row to its own provenance policy and artifact."""
    if not source_counts:
        return ()
    source_placeholders = ",".join("?" for _ in source_counts)
    rows = connection.execute(
        f"""
        SELECT DISTINCT ds.source_key, ds.license_name, rp.policy_key, rp.policy_version,
               rp.classification, rp.local_only, ss.snapshot_ref, ss.manifest_sha256,
               sa.artifact_ref, sa.sha256
          FROM artist_genre_evidence AS evidence
          JOIN provenance_records AS provenance ON provenance.id = evidence.provenance_id
          JOIN data_sources AS ds
            ON ds.id = provenance.source_id AND ds.source_key = evidence.source_key
          JOIN rights_policies AS rp ON rp.id = provenance.policy_id
          JOIN source_snapshots AS ss
            ON ss.source_id = provenance.source_id AND ss.snapshot_ref = provenance.snapshot_ref
          JOIN source_artifacts AS sa
            ON sa.snapshot_id = ss.id AND sa.sha256 = provenance.artifact_sha256
         WHERE evidence.evidence_kind = 'direct_source_claim'
           AND ds.source_key IN ({source_placeholders})
           AND evidence.policy_id = provenance.policy_id
           AND sa.policy_id = provenance.policy_id
           AND rp.classification = 'public_domain' AND rp.local_only = 0
           AND rp.policy_key IS NOT NULL
           AND EXISTS (
               SELECT 1 FROM active_rights_policy_permissions AS permission
                WHERE permission.policy_id = provenance.policy_id
                  AND permission.use_kind = 'export' AND permission.decision = 'allow'
           )
         ORDER BY ds.source_key, sa.artifact_ref
        """,
        tuple(source_counts),
    ).fetchall()
    if {str(row["source_key"]) for row in rows} != set(source_counts):
        raise ValueError("direct evidence source lacks exact provenance-bound artifact")
    if len(rows) != len(source_counts):
        raise ValueError("each direct source must resolve to exactly one provenance-bound artifact")
    bindings: list[CertifiedPublicSourceBinding] = []
    for row in rows:
        source_key = str(row["source_key"])
        try:
            selector = next(
                selector
                for selector in policy.direct_selectors
                if source_key.startswith(selector.source_key_prefix)
            )
        except StopIteration as error:
            raise ValueError("direct provenance source is outside adapter policy") from error
        if str(row["license_name"]) != selector.required_license:
            raise ValueError("direct provenance artifact uses an unapproved selector license")
        bindings.append(
            CertifiedPublicSourceBinding(
                source_key=source_key,
                license_name=str(row["license_name"]),
                policy_key=str(row["policy_key"]),
                policy_version=int(row["policy_version"]),
                classification="public_domain",
                snapshot_ref=str(row["snapshot_ref"]),
                manifest_sha256=str(row["manifest_sha256"]),
                artifact_ref=str(row["artifact_ref"]),
                artifact_sha256=str(row["sha256"]),
                row_count=source_counts[source_key],
            )
        )
    return tuple(bindings)


def _aggregate_source_bindings(
    connection: sqlite3.Connection, source_counts: dict[str, int], run_id: int | None
) -> tuple[CertifiedPublicSourceBinding, ...]:
    """Bind aggregate rows to the exact completed run artifact policy."""
    if not source_counts or run_id is None:
        return ()
    rows = connection.execute(
        """
        SELECT DISTINCT ds.source_key, ds.license_name, rp.policy_key, rp.policy_version,
               rp.classification, rp.local_only, ss.snapshot_ref, ss.manifest_sha256,
               sa.artifact_ref, sa.sha256
          FROM artist_co_listen_runs AS run
          JOIN source_artifacts AS sa ON sa.id = run.artifact_id
          JOIN source_snapshots AS ss ON ss.id = sa.snapshot_id
          JOIN ingest_attempts AS attempt
            ON attempt.id = run.ingest_attempt_id
           AND attempt.snapshot_id = ss.id AND attempt.policy_id = sa.policy_id
          JOIN data_sources AS ds ON ds.id = ss.source_id
          JOIN rights_policies AS rp ON rp.id = sa.policy_id
          JOIN active_rights_policy_permissions AS permission
            ON permission.policy_id = sa.policy_id
           AND permission.use_kind = 'export' AND permission.decision = 'allow'
         WHERE run.emitted_pairs > 0
           AND run.id = ?
           AND rp.classification = 'public_domain' AND rp.local_only = 0
         ORDER BY ds.source_key, sa.artifact_ref
        """,
        (run_id,),
    ).fetchall()
    if {str(row["source_key"]) for row in rows} != set(source_counts) or len(rows) != len(
        source_counts
    ):
        raise ValueError("aggregate evidence source lacks one exact exportable run artifact")
    return tuple(
        CertifiedPublicSourceBinding(
            source_key=str(row["source_key"]),
            license_name=str(row["license_name"]),
            policy_key=str(row["policy_key"]),
            policy_version=int(row["policy_version"]),
            classification="public_domain",
            snapshot_ref=str(row["snapshot_ref"]),
            manifest_sha256=str(row["manifest_sha256"]),
            artifact_ref=str(row["artifact_ref"]),
            artifact_sha256=str(row["sha256"]),
            row_count=source_counts[str(row["source_key"])],
        )
        for row in rows
    )


def _direct_rows(
    connection: sqlite3.Connection, policy: CertifiedPublicMembershipAdapterPolicy
) -> tuple[tuple[DirectMembershipEvidence, ...], tuple[GenreIdentity, ...], dict[str, int]]:
    """Read only direct, export-authorized artist/genre claims from certified tables."""
    selector_clauses = " OR ".join(
        "(evidence.source_key GLOB ? AND evidence.method_key = ? AND source.license_name = ?)"
        for _ in policy.direct_selectors
    )
    rows = connection.execute(
        f"""
        WITH musicbrainz_identifiers AS (
            SELECT identifier.entity_id, MIN(identifier.normalized_value) AS value
              FROM entity_identifiers AS identifier
              JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
             WHERE type.type_key = 'musicbrainz_artist_id'
             GROUP BY identifier.entity_id
        ), wikidata_artist_identifiers AS (
            SELECT identifier.entity_id, MIN(identifier.normalized_value) AS value
              FROM entity_identifiers AS identifier
              JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
             WHERE type.type_key = 'wikidata_artist_qid'
             GROUP BY identifier.entity_id
        ), wikidata_genre_identifiers AS (
            SELECT identifier.entity_id, MIN(identifier.normalized_value) AS value
              FROM entity_identifiers AS identifier
              JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
             WHERE type.type_key = 'wikidata_genre_qid'
             GROUP BY identifier.entity_id
        ), musicbrainz_tag_identifiers AS (
            SELECT identifier.entity_id, MIN(identifier.normalized_value) AS value
              FROM entity_identifiers AS identifier
              JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
             WHERE type.type_key = 'musicbrainz_tag_name'
             GROUP BY identifier.entity_id
        )
        SELECT evidence.id, evidence.artist_id, evidence.genre_id, evidence.evidence_value,
               evidence.source_key, evidence.source_record_id, evidence.record_fingerprint,
               genre.name AS genre_name, artist_mbid.value AS artist_mbid,
               artist_qid.value AS artist_qid, genre_qid.value AS genre_qid,
               tag_identity.value AS tag_identity
          FROM artist_genre_evidence AS evidence
          JOIN data_sources AS source ON source.source_key = evidence.source_key
          JOIN rights_policies AS policy ON policy.id = evidence.policy_id
          JOIN genres AS genre ON genre.id = evidence.genre_id
          LEFT JOIN musicbrainz_identifiers AS artist_mbid
            ON artist_mbid.entity_id = evidence.artist_id
          LEFT JOIN wikidata_artist_identifiers AS artist_qid
            ON artist_qid.entity_id = evidence.artist_id
          LEFT JOIN wikidata_genre_identifiers AS genre_qid
            ON genre_qid.entity_id = evidence.genre_id
          LEFT JOIN musicbrainz_tag_identifiers AS tag_identity
            ON tag_identity.entity_id = evidence.genre_id
         WHERE evidence.evidence_kind = 'direct_source_claim'
           AND ({selector_clauses})
           AND policy.classification = 'public_domain'
           AND policy.local_only = 0
           AND EXISTS (
               SELECT 1 FROM active_rights_policy_permissions AS permission
                WHERE permission.policy_id = evidence.policy_id
                  AND permission.use_kind = 'export'
                  AND permission.decision = 'allow'
           )
         ORDER BY evidence.id
        """,
        (
            *(
                value
                for selector in policy.direct_selectors
                for value in (
                    f"{selector.source_key_prefix}*",
                    selector.method_key,
                    selector.required_license,
                )
            ),
        ),
    ).fetchall()
    if not rows:
        raise ValueError("no direct export-authorized evidence rows matched adapter policy")
    if len(rows) > policy.maximum_direct_rows:
        raise ValueError("direct evidence rows exceed adapter bound")
    memberships: list[DirectMembershipEvidence] = []
    genre_rows: dict[str, GenreIdentity] = {}
    source_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        source_key = str(row["source_key"])
        try:
            selector = next(
                selector
                for selector in policy.direct_selectors
                if source_key.startswith(selector.source_key_prefix)
            )
        except StopIteration as error:
            raise ValueError("direct evidence source is outside adapter policy") from error
        facet = selector.facet
        if facet == "musicbrainz_tag":
            artist_identifier = row["artist_mbid"]
            genre_identifier = row["tag_identity"]
            artist_prefix = "musicbrainz:artist:"
            genre_prefix = "musicbrainz:tag:"
            evidence_prefix = "musicbrainz:artist:tag"
        else:
            artist_identifier = row["artist_qid"] or row["artist_mbid"]
            genre_identifier = row["genre_qid"]
            artist_prefix = "wikidata:artist:" if row["artist_qid"] else "musicbrainz:artist:"
            genre_prefix = "wikidata:genre:"
            evidence_prefix = "wikidata:p136"
        if artist_identifier is None or genre_identifier is None:
            raise ValueError("direct evidence lacks a stable public artist or genre identifier")
        artist_id = f"{artist_prefix}{artist_identifier}"
        genre_id = f"{genre_prefix}{genre_identifier}"
        evidence_ref = (
            f"{evidence_prefix}:{source_key}:{row['source_record_id']}:{row['record_fingerprint']}"
        )
        memberships.append(
            DirectMembershipEvidence(
                artist_id=artist_id,
                genre_id=genre_id,
                facet=facet,
                value=float(row["evidence_value"]),
                evidence_ref=evidence_ref,
            )
        )
        genre_rows[genre_id] = GenreIdentity(
            genre_id=genre_id,
            name=str(row["genre_name"]),
            evidence_refs=(f"{evidence_prefix}:{genre_identifier}",),
        )
        source_counts[source_key] += 1
    return (
        tuple(memberships),
        tuple(genre_rows[key] for key in sorted(genre_rows)),
        dict(source_counts),
    )


def _aggregate_pairs(
    connection: sqlite3.Connection, policy: CertifiedPublicMembershipAdapterPolicy
) -> tuple[tuple[ArtistPairEvidence, ...], dict[str, int], sqlite3.Row | None]:
    """Optionally reduce exportable raw window rows to privacy-safe pair aggregates."""
    if not policy.include_aggregate_candidates:
        return (), {}, None
    run_rows = connection.execute(
        """
        SELECT run.*, source.source_key
          FROM artist_co_listen_runs AS run
          JOIN source_artifacts AS artifact ON artifact.id = run.artifact_id
          JOIN source_snapshots AS snapshot ON snapshot.id = artifact.snapshot_id
          JOIN data_sources AS source ON source.id = snapshot.source_id
          JOIN rights_policies AS rights ON rights.id = artifact.policy_id
         WHERE source.source_key GLOB ?
           AND rights.classification = 'public_domain' AND rights.local_only = 0
           AND artifact.policy_id = (
               SELECT policy_id FROM ingest_attempts WHERE id = run.ingest_attempt_id
           )
         ORDER BY run.id
        """,
        (f"{policy.aggregate_source_key_prefix}*",),
    ).fetchall()
    if len(run_rows) != 1:
        raise ValueError("aggregate adapter requires exactly one completed public run")
    run = run_rows[0]
    if not isinstance(run, sqlite3.Row):
        raise TypeError("aggregate run query returned an invalid row")
    if int(run["minimum_distinct_users"]) < policy.minimum_distinct_users_per_window:
        raise ValueError("aggregate run privacy threshold is below adapter policy")
    rows = connection.execute(
        """
        SELECT evidence.left_artist_source_id, evidence.right_artist_source_id,
               SUM(evidence.distinct_user_count) AS listener_day_support,
               COUNT(*) AS supporting_windows,
               GROUP_CONCAT(evidence.evidence_fingerprint, '|') AS fingerprints,
               source.source_key
          FROM artist_co_listen_evidence AS evidence
          JOIN artist_co_listen_runs AS run ON run.ingest_attempt_id = evidence.ingest_attempt_id
          JOIN source_artifacts AS artifact ON artifact.id = run.artifact_id
          JOIN source_snapshots AS snapshot ON snapshot.id = artifact.snapshot_id
          JOIN data_sources AS source ON source.id = snapshot.source_id
          JOIN rights_policies AS policy ON policy.id = artifact.policy_id
         WHERE source.source_key GLOB ?
           AND policy.classification = 'public_domain'
           AND policy.local_only = 0
           AND evidence.distinct_user_count >= ?
           AND run.id = ?
           AND EXISTS (
               SELECT 1 FROM active_rights_policy_permissions AS permission
                WHERE permission.policy_id = artifact.policy_id
                  AND permission.use_kind = 'export'
                  AND permission.decision = 'allow'
           )
         GROUP BY evidence.left_artist_source_id, evidence.right_artist_source_id, source.source_key
         ORDER BY evidence.left_artist_source_id, evidence.right_artist_source_id, source.source_key
        """,
        (
            f"{policy.aggregate_source_key_prefix}*",
            policy.minimum_distinct_users_per_window,
            run["id"],
        ),
    ).fetchall()
    if len(rows) > policy.maximum_aggregate_pairs:
        raise ValueError("aggregate pair rows exceed adapter bound")
    pairs: list[ArtistPairEvidence] = []
    source_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        left = str(row["left_artist_source_id"])
        right = str(row["right_artist_source_id"])
        if left == right:
            continue
        left, right = sorted((left, right))
        fingerprints = tuple(sorted(set(str(row["fingerprints"]).split("|"))))
        pairs.append(
            ArtistPairEvidence(
                left_artist_id=left,
                right_artist_id=right,
                listener_day_support=int(row["listener_day_support"]),
                supporting_windows=int(row["supporting_windows"]),
                evidence_refs=tuple(
                    f"listenbrainz:aggregate:{row['source_key']}:{fingerprint}"
                    for fingerprint in fingerprints
                ),
            )
        )
        source_counts[str(row["source_key"])] += 1
    # ``emitted_pairs`` counts privacy-safe window observations in the sealed
    # run.  The adapter intentionally re-aggregates those rows by artist pair,
    # so the normalized PublicModelInput pair count may be smaller.
    return tuple(pairs), dict(source_counts), run


def adapt_certified_public_membership_input(
    database_path: Path, policy: CertifiedPublicMembershipAdapterPolicy
) -> CertifiedPublicMembershipAdaptation:
    """Convert one immutable certified database into a replayable approved input."""
    database_sha = _file_sha256(database_path)
    with closing(sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        direct, genres, direct_counts = _direct_rows(connection, policy)
        pairs, aggregate_counts, aggregate_run = _aggregate_pairs(connection, policy)
        direct_bindings = _direct_source_bindings(connection, direct_counts, policy)
        aggregate_bindings = _aggregate_source_bindings(
            connection, aggregate_counts, aggregate_run["id"] if aggregate_run is not None else None
        )
    if _file_sha256(database_path) != database_sha:
        raise ValueError("certified database changed while adapting; replay is not safe")
    row_policy_sha = _sha256(
        [item.model_dump(mode="json") for item in (*direct_bindings, *aggregate_bindings)]
    )
    artifacts = tuple(
        PublicArtifact(
            source=_source_family_for_key(item.source_key, policy),
            snapshot=item.snapshot_ref,
            artifact_key=item.artifact_ref,
            content_sha256=item.artifact_sha256,
            export_allowed=True,
        )
        for item in direct_bindings
    ) + tuple(
        PublicArtifact(
            source="listenbrainz",
            snapshot=item.snapshot_ref,
            artifact_key=item.artifact_ref,
            content_sha256=item.artifact_sha256,
            export_allowed=True,
        )
        for item in aggregate_bindings
    )
    public_model_input = PublicModelInput(
        artifacts=artifacts,
        genres=genres,
        direct_memberships=direct,
        artist_pairs=pairs,
    )
    public_input_sha = _sha256(public_model_input.model_dump(mode="json"))
    approved = ApprovedPublicMembershipInput(
        public_model_input=public_model_input,
        input_file_sha256=database_sha,
        public_model_input_sha256=public_input_sha,
        row_export_policy_sha256=row_policy_sha,
        aggregate_rows_export_allowed=bool(pairs),
        declared_direct_row_count=len(direct),
        declared_aggregate_row_count=len(pairs),
    )
    receipt_payload = {
        "revision": "certified-public-membership-adapter-receipt-v1",
        "database_file_sha256": database_sha,
        "adapter_policy_sha256": _sha256(policy.model_dump(mode="json")),
        "row_export_policy_sha256": row_policy_sha,
        "direct_source_bindings": tuple(item.model_dump(mode="json") for item in direct_bindings),
        "aggregate_source_bindings": tuple(
            item.model_dump(mode="json") for item in aggregate_bindings
        ),
        "direct_row_count": len(direct),
        "aggregate_pair_count": len(pairs),
        "approved_input_sha256": public_input_sha,
    }
    if aggregate_run is not None:
        receipt_payload.update(
            {
                "aggregate_run_ref": str(aggregate_run["run_ref"]),
                "aggregate_window_seconds": int(aggregate_run["window_seconds"]),
                "aggregate_minimum_distinct_users": int(aggregate_run["minimum_distinct_users"]),
                "aggregate_listens_seen": int(aggregate_run["listens_seen"]),
                "aggregate_distinct_artists": int(aggregate_run["distinct_artists"]),
                "aggregate_user_windows": int(aggregate_run["user_windows"]),
                "aggregate_candidate_pairs": int(aggregate_run["candidate_pairs"]),
                "aggregate_emitted_pairs": int(aggregate_run["emitted_pairs"]),
                "aggregate_quarantined_records": int(aggregate_run["quarantined_records"]),
            }
        )
    for optional_field in (
        "aggregate_run_ref",
        "aggregate_window_seconds",
        "aggregate_minimum_distinct_users",
        "aggregate_listens_seen",
        "aggregate_distinct_artists",
        "aggregate_user_windows",
        "aggregate_candidate_pairs",
        "aggregate_emitted_pairs",
        "aggregate_quarantined_records",
    ):
        receipt_payload.setdefault(optional_field, None)
    receipt = CertifiedPublicMembershipAdapterReceipt.model_validate(
        {**receipt_payload, "output_sha256": _sha256(receipt_payload)}
    )
    return CertifiedPublicMembershipAdaptation(approved_input=approved, receipt=receipt)


def source_policy_for_adapter(
    policy: CertifiedPublicMembershipAdapterPolicy,
) -> PublicArtistMembershipSourcePolicy:
    """Translate adapter permissions into the candidate's independently sealed policy."""
    return PublicArtistMembershipSourcePolicy(
        direct_source=policy.direct_selectors[0].source,
        direct_facet=policy.direct_selectors[0].facet,
        direct_sources=policy.effective_direct_sources,
        direct_facets=policy.effective_direct_facets,
        aggregate_co_listen_publicly_permitted=policy.include_aggregate_candidates,
        aggregate_co_listen_export_allowed=policy.include_aggregate_candidates,
        include_aggregate_candidates=policy.include_aggregate_candidates,
    )
