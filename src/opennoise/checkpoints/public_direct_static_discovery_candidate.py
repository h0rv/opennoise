"""Project a pinned direct bridge into a local static-discovery review candidate.

The projection is deliberately separate from the serving exporter.  In
particular, a reconciliation-backed presentation binding is not represented as
the exporter's exact-label binding, and this module never writes an asset.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from contextlib import closing
from pathlib import Path  # noqa: TC003
from typing import Final, Literal

from pydantic import Field, model_validator

from opennoise.checkpoints.public_direct_bridge_candidate import (
    CandidateInputs,
    DirectBridgeRow,
    build_public_direct_bridge_candidate,
    candidate_sha256,
)
from opennoise.common import canonical_json, sha256_hex
from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001

_REVISION: Final = "public-direct-static-discovery-review-candidate-v1"


class PublicDirectStaticDiscoveryCandidateError(ValueError):
    """The pinned local static-discovery review projection is invalid."""


class ReviewEvidence(FrozenModel):
    """One exact direct source claim retained for human review."""

    evidence_id: int = Field(gt=0)
    source_key: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    method_key: Literal["wikidata_p136"]
    method_version: Literal["1"]
    provenance_id: int = Field(gt=0)


class ReviewMembership(FrozenModel):
    """One artist/genre presentation proposal with source-bound observations."""

    node_id: str = Field(pattern=r"^item[1-9][0-9]*$")
    catalog_genre_id: int = Field(gt=0)
    catalog_genre_name: str = Field(min_length=1)
    source_genre_ref: str = Field(pattern=r"^wikidata:genre:Q[1-9][0-9]*$")
    reconciliation_disposition: Literal["reconciled", "public_only"]
    binding: Literal["one_to_one_reconciled_wikidata_genre"]
    artist_catalog_id: int = Field(gt=0)
    artist_id: str = Field(
        pattern=(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    )
    artist_name: str = Field(min_length=1)
    evidence: tuple[ReviewEvidence, ...] = Field(min_length=1)


class ReviewGenre(FrozenModel):
    """One positioned map node with only direct source-observed artists."""

    node_id: str = Field(pattern=r"^item[1-9][0-9]*$")
    catalog_genre_id: int = Field(gt=0)
    catalog_genre_name: str = Field(min_length=1)
    source_genre_ref: str = Field(pattern=r"^wikidata:genre:Q[1-9][0-9]*$")
    reconciliation_disposition: Literal["reconciled", "public_only"]
    binding: Literal["one_to_one_reconciled_wikidata_genre"]
    artist_ids: tuple[str, ...] = Field(min_length=1)


class ReviewCoverage(FrozenModel):
    """Replayable accounting for this candidate only, never an export delta."""

    positioned_genre_count: int = Field(ge=0)
    membership_count: int = Field(ge=0)
    direct_observation_count: int = Field(ge=0)
    artist_count: int = Field(ge=0)
    net_new_artist_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _bounds(self) -> ReviewCoverage:
        if self.net_new_artist_count > self.artist_count:
            raise ValueError("net-new artists exceed candidate artists")
        return self


class PublicDirectStaticDiscoveryReviewCandidate(FrozenModel):
    """A review-only, static-discovery-shaped projection of the public bridge."""

    revision: Literal["public-direct-static-discovery-review-candidate-v1"] = _REVISION
    publication_scope: Literal["local_review_candidate_only"] = "local_review_candidate_only"
    static_output_written: Literal[False] = False
    promotion_performed: Literal[False] = False
    existing_static_discovery_modified: Literal[False] = False
    historical_inputs_used: Literal[False] = False
    compatible_static_discovery_revision: Literal["static-direct-discovery-v1"] = (
        "static-direct-discovery-v1"
    )
    public_direct_bridge_output_sha256: Sha256
    public_database_sha256: Sha256
    static_discovery_sha256: Sha256
    memberships: tuple[ReviewMembership, ...]
    genres: tuple[ReviewGenre, ...]
    coverage: ReviewCoverage
    output_sha256: Sha256


def review_candidate_sha256(candidate: PublicDirectStaticDiscoveryReviewCandidate) -> Sha256:
    """Hash the review candidate independently of its self-hash field."""
    return sha256_hex(canonical_json(candidate.model_dump(mode="json", exclude={"output_sha256"})))


def build_public_direct_static_discovery_review_candidate(
    inputs: CandidateInputs,
) -> PublicDirectStaticDiscoveryReviewCandidate:
    """Return a source-complete, local-only review projection of the pinned bridge."""
    bridge = build_public_direct_bridge_candidate(inputs)
    observations = _review_observations(inputs.public_database, bridge.rows)
    memberships = _memberships(bridge.rows, observations)
    genres = _genres(memberships)
    coverage = ReviewCoverage(
        positioned_genre_count=len(genres),
        membership_count=len(memberships),
        direct_observation_count=sum(len(membership.evidence) for membership in memberships),
        artist_count=len({membership.artist_id for membership in memberships}),
        net_new_artist_count=bridge.coverage.net_new_artist_count,
    )
    if coverage.model_dump() != {
        "positioned_genre_count": 84,
        "membership_count": 862,
        "direct_observation_count": 959,
        "artist_count": 536,
        "net_new_artist_count": 118,
    }:
        raise PublicDirectStaticDiscoveryCandidateError(
            f"pinned static-discovery review coverage drifted: {coverage.model_dump()}"
        )
    base = PublicDirectStaticDiscoveryReviewCandidate(
        public_direct_bridge_output_sha256=candidate_sha256(bridge),
        public_database_sha256=bridge.public_database_sha256,
        static_discovery_sha256=bridge.static_discovery_sha256,
        memberships=memberships,
        genres=genres,
        coverage=coverage,
        output_sha256="0" * 64,
    )
    return base.model_copy(update={"output_sha256": review_candidate_sha256(base)})


class _ReviewObservation(FrozenModel):
    """One database row parsed before joining it to a pinned bridge row."""

    evidence_id: int = Field(gt=0)
    artist_catalog_id: int = Field(gt=0)
    catalog_genre_id: int = Field(gt=0)
    catalog_genre_name: str = Field(min_length=1)
    artist_name: str = Field(min_length=1)
    source_key: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    method_key: Literal["wikidata_p136"]
    method_version: Literal["1"]
    provenance_id: int = Field(gt=0)


def _review_observations(
    database_path: Path, rows: tuple[DirectBridgeRow, ...]
) -> dict[int, _ReviewObservation]:
    evidence_ids = tuple(row.evidence_id for row in rows)
    if len(set(evidence_ids)) != len(evidence_ids):
        raise PublicDirectStaticDiscoveryCandidateError("pinned bridge repeats an evidence ID")
    if not evidence_ids:
        raise PublicDirectStaticDiscoveryCandidateError("pinned bridge has no reviewable rows")
    placeholders = ",".join("?" for _ in evidence_ids)
    try:
        with closing(
            sqlite3.connect(f"file:{database_path.resolve()}?mode=ro&immutable=1", uri=True)
        ) as database:
            database.row_factory = sqlite3.Row
            source_rows = database.execute(
                f"""WITH preferred_artist_names AS (
                        SELECT entity_id, name FROM (
                            SELECT name.entity_id, name.name,
                                   row_number() OVER (
                                       PARTITION BY name.entity_id
                                   ORDER BY (name.language_tag = 'en') DESC,
                                            name.is_preferred DESC,
                                            (name.language_tag = 'und') DESC,
                                            name.id
                                   ) AS row_number
                            FROM displayable_entity_names AS name
                            JOIN artists AS artist ON artist.id = name.entity_id
                        ) WHERE row_number = 1
                    )
                    SELECT evidence.id, evidence.artist_id, evidence.genre_id,
                           genre.name AS genre_name, artist_name.name AS artist_name,
                           evidence.source_key, evidence.source_record_id,
                           evidence.method_key, evidence.method_version, evidence.provenance_id
                    FROM displayable_artist_genre_evidence AS evidence
                    JOIN genres AS genre ON genre.id = evidence.genre_id
                    JOIN preferred_artist_names AS artist_name
                      ON artist_name.entity_id = evidence.artist_id
                    WHERE evidence.id IN ({placeholders})
                      AND evidence.method_key = 'wikidata_p136'
                      AND evidence.method_version = '1'
                    ORDER BY evidence.id""",  # noqa: S608 - pinned integer IDs only.
                evidence_ids,
            ).fetchall()
    except sqlite3.Error as error:
        raise PublicDirectStaticDiscoveryCandidateError(
            "public database cannot replay review observations"
        ) from error
    observations = {
        observation.evidence_id: observation
        for observation in (_review_observation_from_row(row) for row in source_rows)
    }
    if set(observations) != set(evidence_ids):
        raise PublicDirectStaticDiscoveryCandidateError(
            "public database cannot replay every pinned bridge evidence ID"
        )
    return observations


def _review_observation_from_row(row: sqlite3.Row) -> _ReviewObservation:
    """Parse one SQLite result before it enters the review candidate."""
    method_key, method_version = _parse_p136_method(
        str(row["method_key"]), str(row["method_version"])
    )
    return _ReviewObservation(
        evidence_id=int(row["id"]),
        artist_catalog_id=int(row["artist_id"]),
        catalog_genre_id=int(row["genre_id"]),
        catalog_genre_name=str(row["genre_name"]),
        artist_name=str(row["artist_name"]),
        source_key=str(row["source_key"]),
        source_record_id=str(row["source_record_id"]),
        method_key=method_key,
        method_version=method_version,
        provenance_id=int(row["provenance_id"]),
    )


def _parse_p136_method(
    method_key: str, method_version: str
) -> tuple[Literal["wikidata_p136"], Literal["1"]]:
    """Parse the only source method this bridge is allowed to project."""
    if method_key != "wikidata_p136" or method_version != "1":
        raise PublicDirectStaticDiscoveryCandidateError(
            "review observation is not an exact Wikidata P136 claim"
        )
    return "wikidata_p136", "1"


def _memberships(
    rows: tuple[DirectBridgeRow, ...], observations: dict[int, _ReviewObservation]
) -> tuple[ReviewMembership, ...]:
    grouped: dict[tuple[int, int], list[tuple[DirectBridgeRow, _ReviewObservation]]] = defaultdict(
        list
    )
    for row in rows:
        observation = observations[row.evidence_id]
        if (
            observation.artist_catalog_id != row.artist_catalog_id
            or observation.catalog_genre_id != row.catalog_genre_id
            or observation.source_key != row.source_key
            or observation.source_record_id != row.source_record_id
        ):
            raise PublicDirectStaticDiscoveryCandidateError(
                "public database observation does not match pinned bridge claim"
            )
        grouped[(row.artist_catalog_id, row.catalog_genre_id)].append((row, observation))
    memberships = []
    for (artist_id, genre_id), items in sorted(grouped.items()):
        bridge_identities = {
            (
                row.seed_id,
                row.source_genre_ref,
                row.reconciliation_disposition,
                row.artist_musicbrainz_id,
            )
            for row, _ in items
        }
        observation_identities = {
            (observation.catalog_genre_name, observation.artist_name) for _, observation in items
        }
        if len(bridge_identities) != 1 or len(observation_identities) != 1:
            raise PublicDirectStaticDiscoveryCandidateError(
                "grouped bridge rows do not share one presentation identity"
            )
        node_id, source_genre_ref, reconciliation_disposition, musicbrainz_artist_id = next(
            iter(bridge_identities)
        )
        catalog_genre_name, artist_name = next(iter(observation_identities))
        memberships.append(
            ReviewMembership(
                node_id=node_id,
                catalog_genre_id=genre_id,
                catalog_genre_name=catalog_genre_name,
                source_genre_ref=source_genre_ref,
                reconciliation_disposition=reconciliation_disposition,
                binding="one_to_one_reconciled_wikidata_genre",
                artist_catalog_id=artist_id,
                artist_id=musicbrainz_artist_id,
                artist_name=artist_name,
                evidence=tuple(
                    ReviewEvidence(
                        evidence_id=source.evidence_id,
                        source_key=source.source_key,
                        source_record_id=source.source_record_id,
                        method_key=source.method_key,
                        method_version=source.method_version,
                        provenance_id=source.provenance_id,
                    )
                    for _, source in items
                ),
            )
        )
    return tuple(memberships)


def _genres(memberships: tuple[ReviewMembership, ...]) -> tuple[ReviewGenre, ...]:
    grouped: dict[int, list[ReviewMembership]] = defaultdict(list)
    for membership in memberships:
        grouped[membership.catalog_genre_id].append(membership)
    genres = []
    for catalog_genre_id, items in sorted(grouped.items()):
        presentation_identities = {
            (
                item.node_id,
                item.source_genre_ref,
                item.reconciliation_disposition,
                item.catalog_genre_name,
                item.binding,
            )
            for item in items
        }
        if len(presentation_identities) != 1:
            raise PublicDirectStaticDiscoveryCandidateError(
                "grouped genre memberships do not share one presentation identity"
            )
        node_id, source_genre_ref, reconciliation_disposition, catalog_genre_name, binding = next(
            iter(presentation_identities)
        )
        genres.append(
            ReviewGenre(
                node_id=node_id,
                catalog_genre_id=catalog_genre_id,
                catalog_genre_name=catalog_genre_name,
                source_genre_ref=source_genre_ref,
                reconciliation_disposition=reconciliation_disposition,
                binding=binding,
                artist_ids=tuple(sorted({item.artist_id for item in items})),
            )
        )
    return tuple(genres)
