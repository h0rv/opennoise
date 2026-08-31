"""Store direct album genre evidence and publish transparent ranking baselines."""

import hashlib
import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, FiniteFloat, JsonValue, TypeAdapter, model_validator

from musix.adapters.musicbrainz import AlbumGenreEvidenceRecord as MusicBrainzEvidence
from musix.adapters.wikidata import AlbumGenreEvidenceRecord as WikidataEvidence
from musix.evidence import (
    AlbumGenreRankingArtifact,
    AlbumGenreRankingItem,
    DirectGenreEvidence,
    RankingComponent,
)
from musix.models import FrozenModel

type Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
type DirectEvidenceKind = Literal[
    "musicbrainz_release_group_genre",
    "musicbrainz_release_genre",
    "wikidata_p136",
]
type InferredEvidenceKind = Literal[
    "track_coverage",
    "artist_inference",
    "listener_inference",
]
type EvidenceKind = DirectEvidenceKind | InferredEvidenceKind
type EvidenceLevel = Literal["release_group", "release"]

DIRECT_EVIDENCE_KINDS: frozenset[str] = frozenset(
    {
        "musicbrainz_release_group_genre",
        "musicbrainz_release_genre",
        "wikidata_p136",
    }
)
DIRECT_SOURCE_FAMILIES: frozenset[str] = frozenset({"musicbrainz", "wikidata"})


@contextmanager
def _ranking_savepoint(connection: sqlite3.Connection) -> Iterator[None]:
    """Keep a multirow publication atomic inside a caller-owned transaction."""
    connection.execute("SAVEPOINT publish_album_genre_ranking")
    try:
        yield
    except Exception:
        connection.execute("ROLLBACK TO publish_album_genre_ranking")
        connection.execute("RELEASE publish_album_genre_ranking")
        raise
    connection.execute("RELEASE publish_album_genre_ranking")


class MembershipObservation(FrozenModel):
    """Represent one append-only source claim about an album and genre."""

    release_group_id: int = Field(gt=0)
    genre_id: int = Field(gt=0)
    source_release_id: int | None = Field(default=None, gt=0)
    evidence_kind: EvidenceKind
    evidence_level: EvidenceLevel
    source_family: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    source_genre_name: str = Field(min_length=1)
    source_count: int | None = Field(default=None, ge=0)
    source_total: int | None = Field(default=None, ge=0)
    method_key: str = Field(min_length=1)
    method_version: str = Field(min_length=1)
    observed_at: datetime
    provenance_id: int = Field(gt=0)
    policy_id: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_source_level(self) -> "MembershipObservation":
        """Keep edition evidence separate from release group evidence."""
        has_release = self.source_release_id is not None
        if (self.evidence_level == "release") is not has_release:
            raise ValueError("release evidence requires source_release_id")
        if (
            self.source_count is not None
            and self.source_total is not None
            and self.source_count > self.source_total
        ):
            raise ValueError("source_count cannot exceed source_total")
        expected_family = {
            "musicbrainz_release_group_genre": "musicbrainz",
            "musicbrainz_release_genre": "musicbrainz",
            "wikidata_p136": "wikidata",
        }.get(self.evidence_kind)
        if expected_family is not None and self.source_family != expected_family:
            raise ValueError("direct evidence kind must match its source family")
        return self

    def fingerprint(self) -> Sha256:
        """Hash the normalized observation for idempotent insertion."""
        payload = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return hashlib.sha256(payload).hexdigest()


class EvidenceFacetsStrategy(FrozenModel):
    """Rank by unweighted direct evidence counts and expose each facet."""

    strategy: Literal["evidence_facets"] = "evidence_facets"
    version: Literal["1"] = "1"
    minimum_direct_source_families: int = Field(default=1, gt=0)


class ComponentWeight(FrozenModel):
    """Record one user-selected transparent ranking weight."""

    component_key: str = Field(min_length=1)
    weight: FiniteFloat = Field(gt=0.0)


class TransparentWeightedStrategy(FrozenModel):
    """Describe a user-selected weighted rank without choosing its weights."""

    strategy: Literal["transparent_weighted"] = "transparent_weighted"
    version: Literal["1"] = "1"
    weights: tuple[ComponentWeight, ...] = Field(min_length=1)
    minimum_direct_source_families: int = Field(default=1, gt=0)

    @model_validator(mode="after")
    def require_distinct_components(self) -> "TransparentWeightedStrategy":
        """Reject a component whose weight is listed more than once."""
        keys = [weight.component_key.casefold() for weight in self.weights]
        if len(keys) != len(set(keys)):
            raise ValueError("weighted components must be unique")
        return self


class UserPairwiseStrategy(FrozenModel):
    """Describe a future ranking trained from explicit user comparisons."""

    strategy: Literal["user_pairwise"] = "user_pairwise"
    version: Literal["1"] = "1"
    judgment_set_ref: str = Field(min_length=1)
    minimum_comparisons: int = Field(gt=0)


type RankStrategy = Annotated[
    EvidenceFacetsStrategy | TransparentWeightedStrategy | UserPairwiseStrategy,
    Field(discriminator="strategy"),
]

RANK_STRATEGY_ADAPTER: TypeAdapter[RankStrategy] = TypeAdapter(RankStrategy)


def parse_rank_strategy(value: JsonValue) -> RankStrategy:
    """Parse one selected strategy at the configuration boundary."""
    return RANK_STRATEGY_ADAPTER.validate_json(json.dumps(value))


class EvidenceRankingRequest(FrozenModel):
    """Request one published unweighted evidence ranking."""

    run_ref: str = Field(min_length=1)
    genre_id: int = Field(gt=0)
    strategy: EvidenceFacetsStrategy
    input_fingerprint: Sha256
    policy_id: int = Field(gt=0)
    generated_at: datetime


class StoredMembership(FrozenModel):
    """Return the durable identity of one inserted or reused observation."""

    observation_id: int = Field(gt=0)
    record_fingerprint: Sha256
    reused: bool


class MembershipProjection(FrozenModel):
    """Hold resolved local IDs and source provenance for adapter projection."""

    release_group_id: int = Field(gt=0)
    genre_id: int = Field(gt=0)
    source_release_id: int | None = Field(default=None, gt=0)
    observed_at: datetime
    provenance_id: int = Field(gt=0)
    policy_id: int = Field(gt=0)


def membership_from_musicbrainz(
    evidence: MusicBrainzEvidence,
    projection: MembershipProjection,
) -> MembershipObservation:
    """Project resolved MusicBrainz IDs into one local membership observation."""
    return MembershipObservation(
        release_group_id=projection.release_group_id,
        genre_id=projection.genre_id,
        source_release_id=projection.source_release_id,
        evidence_kind=(
            "musicbrainz_release_genre"
            if evidence.evidence_level == "release"
            else "musicbrainz_release_group_genre"
        ),
        evidence_level=evidence.evidence_level,
        source_family=evidence.source_family,
        source_record_id=evidence.source_record_id,
        source_genre_name=evidence.source_genre_name,
        source_count=evidence.source_count,
        method_key="direct_musicbrainz_genre",
        method_version="1",
        observed_at=projection.observed_at,
        provenance_id=projection.provenance_id,
        policy_id=projection.policy_id,
    )


def membership_from_wikidata(
    evidence: WikidataEvidence,
    projection: MembershipProjection,
    *,
    source_genre_name: str,
) -> MembershipObservation:
    """Project resolved Wikidata IDs into one local membership observation."""
    return MembershipObservation(
        release_group_id=projection.release_group_id,
        genre_id=projection.genre_id,
        source_release_id=projection.source_release_id,
        evidence_kind="wikidata_p136",
        evidence_level=evidence.evidence_level,
        source_family=evidence.source_family,
        source_record_id=evidence.source_record_id,
        source_genre_name=source_genre_name,
        method_key="direct_wikidata_p136",
        method_version="1",
        observed_at=projection.observed_at,
        provenance_id=projection.provenance_id,
        policy_id=projection.policy_id,
    )


class _EvidenceRow(FrozenModel):
    """Parse one policy-safe SQLite membership row used by the baseline."""

    observation_id: int
    release_group_id: int
    source_family: str
    source_genre_name: str
    source_count: int | None
    source_total: int | None
    observed_at: datetime
    provenance_id: int

    @property
    def evidence_ref(self) -> str:
        return f"album_genre_membership:{self.observation_id}"


class AlbumGenreRepository:
    """Apply direct SQLite operations through typed records."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Store a caller-owned connection so transactions remain explicit."""
        self._connection = connection

    def add_membership(self, observation: MembershipObservation) -> StoredMembership:
        """Insert one observation once and return its stable database identity."""
        fingerprint = observation.fingerprint()
        cursor = self._connection.execute(
            """
            INSERT INTO album_genre_membership_observations (
                release_group_id, genre_id, source_release_id, evidence_kind,
                evidence_level, source_family, source_record_id, source_genre_name,
                source_count, source_total, method_key, method_version, observed_at,
                provenance_id, policy_id, record_fingerprint
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(record_fingerprint) DO NOTHING
            """,
            (
                observation.release_group_id,
                observation.genre_id,
                observation.source_release_id,
                observation.evidence_kind,
                observation.evidence_level,
                observation.source_family,
                observation.source_record_id,
                observation.source_genre_name,
                observation.source_count,
                observation.source_total,
                observation.method_key,
                observation.method_version,
                observation.observed_at.isoformat(),
                observation.provenance_id,
                observation.policy_id,
                fingerprint,
            ),
        )
        row = self._connection.execute(
            """
            SELECT id FROM album_genre_membership_observations
            WHERE record_fingerprint = ?
            """,
            (fingerprint,),
        ).fetchone()
        if row is None:
            raise RuntimeError("album genre membership insert returned no row")
        return StoredMembership(
            observation_id=int(row[0]),
            record_fingerprint=fingerprint,
            reused=cursor.rowcount == 0,
        )

    def publish_evidence_baseline(
        self,
        request: EvidenceRankingRequest,
    ) -> AlbumGenreRankingArtifact:
        """Publish a stable rank based only on unweighted direct evidence counts."""
        with _ranking_savepoint(self._connection):
            return self._publish_evidence_baseline(request)

    def _publish_evidence_baseline(
        self,
        request: EvidenceRankingRequest,
    ) -> AlbumGenreRankingArtifact:
        """Write one evidence ranking within an active savepoint."""
        rows = self._direct_evidence_rows(request.genre_id)
        grouped: dict[int, list[_EvidenceRow]] = defaultdict(list)
        for row in rows:
            grouped[row.release_group_id].append(row)
        eligible = [
            (release_group_id, evidence)
            for release_group_id, evidence in grouped.items()
            if len({row.source_family for row in evidence})
            >= request.strategy.minimum_direct_source_families
        ]
        eligible.sort(
            key=lambda pair: (
                -len({row.source_family for row in pair[1]}),
                -len(pair[1]),
                pair[0],
            )
        )
        config_json = request.strategy.model_dump_json()
        config_sha256 = hashlib.sha256(config_json.encode()).hexdigest()
        revision = self._next_revision(request.genre_id, request.strategy.strategy)
        eligibility_rule = (
            "At least "
            f"{request.strategy.minimum_direct_source_families} independent direct source "
            "families"
        )
        run_id = self._insert_run(
            request=request,
            revision=revision,
            config_json=config_json,
            config_sha256=config_sha256,
            eligibility_rule=eligibility_rule,
        )
        items: list[AlbumGenreRankingItem] = []
        for rank, (release_group_id, evidence_rows) in enumerate(eligible, start=1):
            item = self._ranking_item(
                genre_id=request.genre_id,
                release_group_id=release_group_id,
                rank=rank,
                evidence_rows=evidence_rows,
            )
            self._insert_item(run_id, item)
            self._insert_evidence_links(run_id, item, evidence_rows)
            items.append(item)
        return AlbumGenreRankingArtifact(
            run_ref=request.run_ref,
            method_key=request.strategy.strategy,
            method_version=request.strategy.version,
            config_sha256=config_sha256,
            input_fingerprint=request.input_fingerprint,
            policy_id=request.policy_id,
            generated_at=request.generated_at,
            membership_threshold=float(request.strategy.minimum_direct_source_families),
            eligibility_rule=eligibility_rule,
            items=tuple(items),
        )

    def _direct_evidence_rows(self, genre_id: int) -> tuple[_EvidenceRow, ...]:
        rows = self._connection.execute(
            """
            SELECT id, release_group_id, source_family, source_genre_name,
                   source_count, source_total, observed_at, provenance_id
            FROM displayable_album_genre_memberships
            WHERE genre_id = ?
              AND evidence_kind IN (?, ?, ?)
            ORDER BY release_group_id, source_family COLLATE NOCASE, id
            """,
            (genre_id, *sorted(DIRECT_EVIDENCE_KINDS)),
        ).fetchall()
        return tuple(
            _EvidenceRow(
                observation_id=int(row[0]),
                release_group_id=int(row[1]),
                source_family=str(row[2]),
                source_genre_name=str(row[3]),
                source_count=int(row[4]) if row[4] is not None else None,
                source_total=int(row[5]) if row[5] is not None else None,
                observed_at=datetime.fromisoformat(str(row[6])),
                provenance_id=int(row[7]),
            )
            for row in rows
        )

    def _next_revision(self, genre_id: int, strategy_key: str) -> int:
        row = self._connection.execute(
            """
            SELECT coalesce(max(revision), 0) + 1
            FROM album_genre_ranking_runs
            WHERE genre_id = ? AND strategy_key = ?
            """,
            (genre_id, strategy_key),
        ).fetchone()
        if row is None:
            raise RuntimeError("album genre revision query returned no row")
        return int(row[0])

    def _insert_run(
        self,
        *,
        request: EvidenceRankingRequest,
        revision: int,
        config_json: str,
        config_sha256: Sha256,
        eligibility_rule: str,
    ) -> int:
        cursor = self._connection.execute(
            """
            INSERT INTO album_genre_ranking_runs (
                run_ref, genre_id, strategy_key, strategy_version, revision,
                config_json, config_sha256, input_fingerprint, eligibility_rule,
                policy_id, generated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request.run_ref,
                request.genre_id,
                request.strategy.strategy,
                request.strategy.version,
                revision,
                config_json,
                config_sha256,
                request.input_fingerprint,
                eligibility_rule,
                request.policy_id,
                request.generated_at.isoformat(),
            ),
        )
        if cursor.lastrowid is None:
            raise RuntimeError("album genre ranking run insert returned no row ID")
        return cursor.lastrowid

    @staticmethod
    def _ranking_item(
        *,
        genre_id: int,
        release_group_id: int,
        rank: int,
        evidence_rows: list[_EvidenceRow],
    ) -> AlbumGenreRankingItem:
        source_families = {row.source_family for row in evidence_rows}
        evidence_refs = tuple(row.evidence_ref for row in evidence_rows)
        family_count = len(source_families)
        components = (
            RankingComponent(
                component_key="direct_source_family_count",
                raw_value=float(family_count),
                transformed_value=float(family_count),
                transform_key="identity",
                transform_version="1",
                evidence_refs=evidence_refs,
            ),
            RankingComponent(
                component_key="direct_observation_count",
                raw_value=float(len(evidence_rows)),
                transformed_value=float(len(evidence_rows)),
                transform_key="identity",
                transform_version="1",
                evidence_refs=evidence_refs,
            ),
        )
        evidence = tuple(
            DirectGenreEvidence(
                evidence_ref=row.evidence_ref,
                provenance_id=row.provenance_id,
                source_key=row.source_family,
                observed_at=row.observed_at,
                source_genre_name=row.source_genre_name,
                source_count=row.source_count,
                source_total=row.source_total,
            )
            for row in evidence_rows
        )
        return AlbumGenreRankingItem(
            genre_id=genre_id,
            release_group_id=release_group_id,
            rank=rank,
            score=float(family_count),
            membership_confidence=1.0,
            evidence_coverage=family_count / len(DIRECT_SOURCE_FAMILIES),
            components=components,
            evidence=evidence,
            explanation=(
                f"{family_count} independent direct source families and "
                f"{len(evidence_rows)} direct observations. No weights were applied."
            ),
            missing_features=("audience", "consensus", "influence"),
        )

    def _insert_item(self, run_id: int, item: AlbumGenreRankingItem) -> None:
        components_json = json.dumps(
            [component.model_dump(mode="json") for component in item.components],
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        explanation_json = json.dumps(
            {
                "explanation": item.explanation,
                "missing_features": item.missing_features,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        self._connection.execute(
            """
            INSERT INTO album_genre_ranking_items (
                run_id, release_group_id, representative_release_id, rank, score,
                membership_confidence, evidence_coverage, components_json,
                explanation_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                item.release_group_id,
                item.edition.release_id if item.edition is not None else None,
                item.rank,
                item.score,
                item.membership_confidence,
                item.evidence_coverage,
                components_json,
                explanation_json,
            ),
        )

    def _insert_evidence_links(
        self,
        run_id: int,
        item: AlbumGenreRankingItem,
        evidence_rows: list[_EvidenceRow],
    ) -> None:
        self._connection.executemany(
            """
            INSERT INTO album_genre_ranking_item_evidence (
                run_id, release_group_id, membership_observation_id
            ) VALUES (?, ?, ?)
            """,
            ((run_id, item.release_group_id, row.observation_id) for row in evidence_rows),
        )
