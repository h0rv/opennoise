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
from pathlib import Path
from typing import Literal, NamedTuple

from pydantic import Field, model_validator

from opennoise.models.modeling import (
    ArtistPairEvidence,
    DirectMembershipEvidence,
    GenreIdentity,
    PublicArtifact,
    PublicModelInput,
)
from opennoise.serving.public.artist_membership import (
    ApprovedPublicMembershipInput,
    PublicArtistMembershipSourcePolicy,
    StrictFrozenModel,
    _sha256,
)
from opennoise.serving.public.membership_export_eligibility import ExportEligibility
from opennoise.types import Sha256  # noqa: TC001


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


class CertifiedPublicMetadataSelector(StrictFrozenModel):
    """Declare an additional supported source family for eligible ID/name observations."""

    source: Literal["wikidata", "musicbrainz"]
    source_key_prefix: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.:-]+$")
    required_license: Literal["CC0-1.0"] = "CC0-1.0"


class CertifiedPublicMembershipAdapterPolicy(StrictFrozenModel):
    """Bound the only SQLite rows that may reach the public candidate."""

    revision: Literal["certified-public-membership-adapter-v2"] = (
        "certified-public-membership-adapter-v2"
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
    metadata_selectors: tuple[CertifiedPublicMetadataSelector, ...] = ()
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
        if not {item.source for item in self.metadata_selectors} <= {
            item.source for item in self.direct_selectors
        }:
            raise ValueError("metadata sources must belong to declared direct source families")
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
        return tuple(dict.fromkeys(item.source for item in self.direct_selectors))

    @property
    def effective_direct_facets(self) -> tuple[Literal["wikidata_p136", "musicbrainz_tag"], ...]:
        """Return direct facets in selector order."""
        return tuple(dict.fromkeys(item.facet for item in self.direct_selectors))

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


class CertifiedPublicMetadataBinding(StrictFrozenModel):
    """Bind an emitted identity or name to its own exact eligible observation."""

    entity_id: int = Field(gt=0)
    field: str = Field(min_length=1)
    value: str = Field(min_length=1)
    provenance_id: int = Field(gt=0)
    source_family: Literal["wikidata", "musicbrainz"]
    source_binding: CertifiedPublicSourceBinding


class CertifiedPublicMembershipAdapterReceipt(StrictFrozenModel):
    """Replay receipt binding the DB bytes, export policies, and adapted rows."""

    revision: Literal["certified-public-membership-adapter-receipt-v2"] = (
        "certified-public-membership-adapter-receipt-v2"
    )
    database_file_sha256: Sha256
    adapter_policy_sha256: Sha256
    row_export_policy_sha256: Sha256
    direct_source_bindings: tuple[CertifiedPublicSourceBinding, ...] = Field(min_length=1)
    aggregate_source_bindings: tuple[CertifiedPublicSourceBinding, ...] = ()
    metadata_bindings: tuple[CertifiedPublicMetadataBinding, ...] = Field(min_length=1)
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
        row_policy = {
            "claims": [
                item.model_dump(mode="json")
                for item in (*self.direct_source_bindings, *self.aggregate_source_bindings)
            ],
            "metadata": [item.model_dump(mode="json") for item in self.metadata_bindings],
        }
        if _sha256(row_policy) != self.row_export_policy_sha256:
            raise ValueError("adapter receipt metadata/export-policy binding is incomplete")
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


def _binding(chain: dict[str, object], count: int = 1) -> CertifiedPublicSourceBinding:
    return CertifiedPublicSourceBinding.model_validate(
        {
            key: chain[key]
            for key in (
                "source_key",
                "license_name",
                "policy_key",
                "policy_version",
                "classification",
                "local_only",
                "snapshot_ref",
                "manifest_sha256",
                "artifact_ref",
                "artifact_sha256",
            )
        }
        | {"row_count": count}
    )


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
           AND ds.license_name='CC0-1.0' AND ss.policy_id=sa.policy_id
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


class _DirectIdentities(NamedTuple):
    artist: tuple[str, tuple[dict[str, object], ...]] | None
    genre: tuple[str, tuple[dict[str, object], ...]] | None
    artist_field: str
    genre_field: str
    artist_prefix: str
    genre_prefix: str
    evidence_prefix: str


def _row_identities(
    eligibility: ExportEligibility, row: sqlite3.Row, facet: str
) -> _DirectIdentities:
    artist_id, genre_id = int(row["artist_id"]), int(row["genre_id"])
    # Validate all eligible known IDs, including one not preferred for this facet.
    qid = eligibility.identifier(artist_id, "wikidata_artist_qid", "wikidata")
    mbid = eligibility.identifier(artist_id, "musicbrainz_artist_id", "musicbrainz")
    genre = eligibility.identifier(genre_id, "wikidata_genre_qid", "wikidata")
    tag = eligibility.identifier(genre_id, "musicbrainz_tag_name", "musicbrainz_tag")
    if eligibility.evidence_blocked(row, genre[0] if genre else None):
        return _DirectIdentities(None, None, "", "", "", "", "")
    if facet == "musicbrainz_tag":
        return _DirectIdentities(
            mbid,
            tag,
            "musicbrainz_artist_id",
            "musicbrainz_tag_name",
            "musicbrainz:artist:",
            "musicbrainz:tag:",
            "musicbrainz:artist:tag",
        )
    return _DirectIdentities(
        qid or mbid,
        genre,
        "wikidata_artist_qid" if qid else "musicbrainz_artist_id",
        "wikidata_genre_qid",
        "wikidata:artist:" if qid else "musicbrainz:artist:",
        "wikidata:genre:",
        "wikidata:p136",
    )


def _metadata_binding(
    entity_id: int, field: str, value: str, chain: dict[str, object]
) -> CertifiedPublicMetadataBinding:
    return CertifiedPublicMetadataBinding.model_validate(
        {
            "entity_id": entity_id,
            "field": field,
            "value": value,
            "provenance_id": chain["provenance_id"],
            "source_family": chain["source_family"],
            "source_binding": _binding(chain),
        }
    )


def _claim_chain(eligibility: ExportEligibility, row: sqlite3.Row) -> dict[str, object] | None:
    if any(eligibility.blocked("entity", int(row[key])) for key in ("artist_id", "genre_id")):
        return None
    chain = eligibility.chain(int(row["provenance_id"]))
    if chain is not None and (
        chain["source_key"] != row["source_key"] or chain["policy_id"] != row["policy_id"]
    ):
        raise ValueError("direct evidence provenance/source policy mismatch")
    return chain


def _direct_rows(
    connection: sqlite3.Connection,
    policy: CertifiedPublicMembershipAdapterPolicy,
    eligibility: ExportEligibility,
) -> tuple[
    tuple[DirectMembershipEvidence, ...],
    tuple[GenreIdentity, ...],
    tuple[CertifiedPublicSourceBinding, ...],
    tuple[CertifiedPublicMetadataBinding, ...],
]:
    """Select claims and every emitted metadata observation with independent custody."""
    selector_clauses = " OR ".join(
        "(e.source_key GLOB ? AND e.method_key=? AND s.license_name=?)"
        for _ in policy.direct_selectors
    )
    rows = connection.execute(
        f"""SELECT e.* FROM artist_genre_evidence e
            JOIN data_sources s ON s.source_key=e.source_key
            JOIN catalog_entities artist ON artist.id=e.artist_id AND artist.entity_kind='artist'
            JOIN artists artist_subtype ON artist_subtype.id=artist.id
            JOIN catalog_entities genre ON genre.id=e.genre_id AND genre.entity_kind='genre'
            JOIN genres genre_subtype ON genre_subtype.id=genre.id
            WHERE e.evidence_kind='direct_source_claim' AND ({selector_clauses})
            ORDER BY e.id""",
        tuple(
            value
            for selector in policy.direct_selectors
            for value in (
                f"{selector.source_key_prefix}*",
                selector.method_key,
                selector.required_license,
            )
        ),
    ).fetchall()
    if len(rows) > policy.maximum_direct_rows:
        raise ValueError("direct evidence rows exceed adapter bound")
    memberships: list[DirectMembershipEvidence] = []
    genres: dict[str, GenreIdentity] = {}
    bindings: dict[str, tuple[CertifiedPublicSourceBinding, int]] = {}
    metadata: dict[str, CertifiedPublicMetadataBinding] = {}

    for row in rows:
        artist_id, genre_id = int(row["artist_id"]), int(row["genre_id"])
        chain = _claim_chain(eligibility, row)
        if chain is None:
            continue
        selector = next(
            item
            for item in policy.direct_selectors
            if row["source_key"].startswith(item.source_key_prefix)
        )
        a, g, artist_field, genre_field, artist_prefix, genre_prefix, evidence_prefix = (
            _row_identities(eligibility, row, selector.facet)
        )
        if a is None or g is None:
            continue
        public_artist, public_genre = artist_prefix + a[0], genre_prefix + g[0]
        for entity_id, field, observed in (
            (artist_id, artist_field, a),
            (genre_id, genre_field, g),
        ):
            for observation in observed[1]:
                item = _metadata_binding(entity_id, field, observed[0], observation)
                metadata[_sha256(item.model_dump(mode="json"))] = item
        name = eligibility.name(genre_id)
        # An authorized identity string is an explicit identity label, not a catalog name.
        label = name[0] if name else g[0]
        if name:
            item = _metadata_binding(genre_id, "name", name[0], name[1])
            metadata[_sha256(item.model_dump(mode="json"))] = item
        genres[public_genre] = GenreIdentity(
            genre_id=public_genre,
            name=label,
            evidence_refs=(f"{evidence_prefix}:{g[0]}",),
        )
        memberships.append(
            DirectMembershipEvidence(
                artist_id=public_artist,
                genre_id=public_genre,
                facet=selector.facet,
                value=float(row["evidence_value"]),
                evidence_ref=f"{evidence_prefix}:{row['source_key']}:{row['source_record_id']}:"
                f"{row['record_fingerprint']}",
            )
        )
        binding = _binding(chain)
        key = _sha256(binding.model_dump(mode="json"))
        prior = bindings.get(key)
        bindings[key] = (binding, 1 if prior is None else prior[1] + 1)
    if not memberships:
        raise ValueError("no direct export-authorized evidence rows matched adapter policy")
    return (
        tuple(memberships),
        tuple(genres[key] for key in sorted(genres)),
        tuple(
            item.model_copy(update={"row_count": count})
            for _, (item, count) in sorted(bindings.items())
        ),
        tuple(metadata[key] for key in sorted(metadata)),
    )


def _aggregate_pairs(
    connection: sqlite3.Connection,
    policy: CertifiedPublicMembershipAdapterPolicy,
    eligibility: ExportEligibility,
) -> tuple[tuple[ArtistPairEvidence, ...], dict[str, int], sqlite3.Row | None]:
    """Optionally reduce exportable raw window rows to privacy-safe pair aggregates."""
    if not policy.include_aggregate_candidates:
        return (), {}, None
    run_rows = connection.execute(
        """
        SELECT run.*, source.source_key, source.id AS source_id, snapshot.id AS snapshot_id
          FROM artist_co_listen_runs AS run
          JOIN source_artifacts AS artifact ON artifact.id = run.artifact_id
          JOIN source_snapshots AS snapshot ON snapshot.id = artifact.snapshot_id
          JOIN data_sources AS source ON source.id = snapshot.source_id
          JOIN rights_policies AS rights ON rights.id = artifact.policy_id
         WHERE source.source_key GLOB ?
           AND rights.classification = 'public_domain' AND rights.local_only = 0
           AND source.license_name='CC0-1.0' AND snapshot.policy_id=artifact.policy_id
           AND EXISTS(SELECT 1 FROM active_rights_policy_permissions permission
               WHERE permission.policy_id=artifact.policy_id AND permission.use_kind='export'
                 AND permission.decision='allow')
           AND artifact.policy_id = (
               SELECT policy_id FROM ingest_attempts WHERE id = run.ingest_attempt_id
           )
         ORDER BY run.id
        """,
        (f"{policy.aggregate_source_key_prefix}*",),
    ).fetchall()
    run_rows = [
        row
        for row in run_rows
        if not any(
            eligibility.blocked(kind, int(row[key]))
            for kind, key in (
                ("source", "source_id"),
                ("snapshot", "snapshot_id"),
                ("artifact", "artifact_id"),
            )
        )
    ]
    if not run_rows:
        return (), {}, None
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
    database_path = database_path.resolve()
    if any(Path(str(database_path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError("certified database must be checkpointed without SQLite sidecars")
    database_sha = _file_sha256(database_path)
    with closing(
        sqlite3.connect(database_path.as_uri() + "?mode=ro&immutable=1", uri=True)
    ) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        eligibility = ExportEligibility(
            connection,
            tuple(
                (item.source_key_prefix, item.source)
                for item in (*policy.direct_selectors, *policy.metadata_selectors)
            ),
        )
        direct, genres, direct_bindings, metadata = _direct_rows(connection, policy, eligibility)
        pairs, aggregate_counts, aggregate_run = _aggregate_pairs(connection, policy, eligibility)
        aggregate_bindings = _aggregate_source_bindings(
            connection, aggregate_counts, aggregate_run["id"] if aggregate_run is not None else None
        )
    if _file_sha256(database_path) != database_sha:
        raise ValueError("certified database changed while adapting; replay is not safe")
    row_policy_sha = _sha256(
        {
            "claims": [
                item.model_dump(mode="json") for item in (*direct_bindings, *aggregate_bindings)
            ],
            "metadata": [item.model_dump(mode="json") for item in metadata],
        }
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
    artifacts += tuple(
        PublicArtifact(
            source=item.source_family,
            snapshot=item.source_binding.snapshot_ref,
            artifact_key=item.source_binding.artifact_ref,
            content_sha256=item.source_binding.artifact_sha256,
            export_allowed=True,
        )
        for item in metadata
    )
    artifacts = tuple({item.model_dump_json(): item for item in artifacts}.values())
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
        "revision": "certified-public-membership-adapter-receipt-v2",
        "database_file_sha256": database_sha,
        "adapter_policy_sha256": _sha256(policy.model_dump(mode="json")),
        "row_export_policy_sha256": row_policy_sha,
        "direct_source_bindings": tuple(item.model_dump(mode="json") for item in direct_bindings),
        "aggregate_source_bindings": tuple(
            item.model_dump(mode="json") for item in aggregate_bindings
        ),
        "metadata_bindings": tuple(item.model_dump(mode="json") for item in metadata),
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
