# ruff: noqa: B008, D107, E501, FURB192, PLR0913, PLR2004, RUF005, S608, TC003, TRY301, UP031
"""Build bounded, explainable representative catalog candidates.

This module ranks release groups only.  A concrete release and its ordered
media/tracks may improve the *metadata completeness* component, but are never
treated as audio, popularity, quality, listener, or playability evidence.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, ValidationError, model_validator

from opennoise.models import FrozenModel
from opennoise.policy import require_metadata_file
from opennoise.storage import ObjectKey, ObjectStore, ObjectWrite

type Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
DIRECT_KINDS = frozenset(
    {"musicbrainz_release_group_genre", "musicbrainz_release_genre", "wikidata_p136"}
)
MAX_DIRECT_SOURCE_FAMILIES = 2
ARTIFACT_BYTES_LIMIT = 8 * 1024 * 1024
METHOD_KEY = "transparent_weighted"
METHOD_VERSION = "representative-candidates-v1"


class RepresentativeCatalogRankingError(RuntimeError):
    """Report a rejected candidate build or replay."""


class CandidateWeights(FrozenModel):
    """Declare the fixed, evidence-only score composition."""

    direct_evidence: float = Field(default=0.45, gt=0.0, le=1.0)
    source_diversity: float = Field(default=0.20, gt=0.0, le=1.0)
    artist_membership: float = Field(default=0.20, ge=0.0, le=1.0)
    metadata_completeness: float = Field(default=0.15, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def sums_to_one(self) -> CandidateWeights:
        """Prevent a hidden score scale change."""
        if (
            abs(
                self.direct_evidence
                + self.source_diversity
                + self.artist_membership
                + self.metadata_completeness
                - 1.0
            )
            > 1e-12
        ):
            raise ValueError("candidate score weights must sum to 1")
        return self


class RepresentativeCatalogRankingConfig(FrozenModel):
    """Bound and version every choice affecting candidate selection."""

    method_key: Literal["transparent_weighted"] = METHOD_KEY
    method_version: Literal["representative-candidates-v1"] = METHOD_VERSION
    weights: CandidateWeights = CandidateWeights()
    minimum_direct_source_families: int = Field(default=1, ge=1, le=2)
    max_genres: int = Field(default=100, ge=1, le=1_000)
    max_candidates_per_genre: int = Field(default=20, ge=1, le=100)
    eligibility_rule: Literal["direct_album_genre_evidence_required"] = (
        "direct_album_genre_evidence_required"
    )
    metadata_boundary: Literal["metadata_only_no_audio_or_audience_data"] = (
        "metadata_only_no_audio_or_audience_data"
    )


class ScoreComponent(FrozenModel):
    """Persist one transparent score input and its fixed weighted contribution."""

    component_key: Literal[
        "direct_evidence",
        "source_diversity",
        "artist_membership_strength",
        "release_track_metadata_completeness",
    ]
    raw_value: float = Field(ge=0.0)
    normalized_value: float = Field(ge=0.0, le=1.0)
    weight: float = Field(ge=0.0, le=1.0)
    contribution: float = Field(ge=0.0, le=1.0)
    evidence_refs: tuple[str, ...] = ()


class CandidateReleaseMetadata(FrozenModel):
    """Record the deterministic display-release choice when metadata exists."""

    release_id: int = Field(gt=0)
    media_count: int = Field(ge=0)
    track_count: int = Field(ge=0)
    declared_track_count: int | None = Field(default=None, ge=0)
    is_official: bool


class RepresentativeCandidate(FrozenModel):
    """One evidence-based release-group candidate, never a quality claim."""

    genre_id: int = Field(gt=0)
    release_group_id: int = Field(gt=0)
    rank: int = Field(gt=0)
    score: float = Field(ge=0.0, le=1.0)
    direct_observation_count: int = Field(gt=0)
    direct_source_family_count: int = Field(gt=0)
    artist_membership_strength: float = Field(ge=0.0, le=1.0)
    representative_release: CandidateReleaseMetadata | None = None
    components: tuple[ScoreComponent, ...]
    direct_evidence_refs: tuple[str, ...] = Field(min_length=1)
    artist_membership_refs: tuple[str, ...] = ()
    explanation: str = Field(min_length=1)
    classification: Literal["representative_candidate"] = "representative_candidate"
    missing_features: tuple[str, ...] = (
        "audio",
        "streams",
        "listeners",
        "popularity",
        "quality",
        "audience_consensus",
    )


class GenreCandidateResult(FrozenModel):
    """Store either bounded candidates or an explicit evidence abstention."""

    genre_id: int = Field(gt=0)
    run_ref: str = Field(min_length=1)
    candidates: tuple[RepresentativeCandidate, ...] = ()
    abstention_reason: (
        Literal["no_direct_album_genre_evidence", "insufficient_direct_source_diversity"] | None
    ) = None

    @model_validator(mode="after")
    def candidates_or_abstention(self) -> GenreCandidateResult:
        """Never silently turn absent evidence into an empty ranking."""
        if bool(self.candidates) == (self.abstention_reason is not None):
            raise ValueError("a genre result must contain candidates or exactly one abstention")
        if self.candidates and tuple(candidate.rank for candidate in self.candidates) != tuple(
            range(1, len(self.candidates) + 1)
        ):
            raise ValueError("candidate ranks must be contiguous")
        return self


class RepresentativeCatalogRankingGate(FrozenModel):
    """State the output-boundary checks without claiming candidate quality."""

    passed: bool
    selected_genres: int = Field(ge=0)
    ranked_genres: int = Field(ge=0)
    abstained_genres: int = Field(ge=0)
    candidates: int = Field(ge=0)
    limits: RepresentativeCatalogRankingConfig
    policy_statement: Literal["metadata_evidence_only_not_popularity_or_quality"] = (
        "metadata_evidence_only_not_popularity_or_quality"
    )


class RepresentativeCatalogRankingArtifact(FrozenModel):
    """A canonical public-safe projection of persisted candidate results."""

    revision: Literal["representative-catalog-ranking-v1"] = "representative-catalog-ranking-v1"
    run_ref: str = Field(min_length=1)
    generated_at: datetime
    policy_id: int = Field(gt=0)
    config: RepresentativeCatalogRankingConfig
    config_sha256: Sha256
    input_fingerprint: Sha256
    results: tuple[GenreCandidateResult, ...]
    gate: RepresentativeCatalogRankingGate
    content_policy: Literal["metadata_only_no_audio_or_audience_data"] = (
        "metadata_only_no_audio_or_audience_data"
    )


class RepresentativeCatalogRankingPublication(FrozenModel):
    """Receipt for immutable object-store publication."""

    artifact: ObjectWrite
    candidate_count: int = Field(ge=0)
    abstention_count: int = Field(ge=0)
    gate: RepresentativeCatalogRankingGate


class RepresentativeCatalogRankingReport(FrozenModel):
    """Small CLI-facing report that binds the output to its exact bytes."""

    artifact_sha256: Sha256
    artifact_byte_size: int = Field(gt=0, le=ARTIFACT_BYTES_LIMIT)
    publication: RepresentativeCatalogRankingPublication
    replayed: bool


class _DirectEvidence(FrozenModel):
    observation_id: int = Field(gt=0)
    release_group_id: int = Field(gt=0)
    source_family: str = Field(min_length=1)

    @property
    def reference(self) -> str:
        return f"album_genre_membership:{self.observation_id}"


class _ArtistMembership(FrozenModel):
    artist_id: int = Field(gt=0)
    score: float = Field(ge=0.0)
    source_count: int = Field(gt=0)

    @property
    def reference(self) -> str:
        return f"artist_genre_membership:{self.artist_id}"


class _ReleaseCompleteness(FrozenModel):
    release_id: int = Field(gt=0)
    media_count: int = Field(ge=0)
    track_count: int = Field(ge=0)
    declared_track_count: int | None = Field(default=None, ge=0)
    is_official: bool

    @property
    def normalized(self) -> float:
        """Score only presence and internally complete retained metadata."""
        if self.media_count == 0:
            return 0.25
        if self.track_count == 0:
            return 0.50
        if self.declared_track_count is not None and self.track_count < self.declared_track_count:
            return 0.75
        return 1.0


def _canonical_bytes(value: FrozenModel) -> bytes:
    return json.dumps(
        value.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _config_sha(config: RepresentativeCatalogRankingConfig) -> Sha256:
    return _sha256(_canonical_bytes(config))


@contextmanager
def _savepoint(connection: sqlite3.Connection) -> Iterator[None]:
    connection.execute("SAVEPOINT representative_catalog_ranking")
    try:
        yield
    except Exception:
        connection.execute("ROLLBACK TO representative_catalog_ranking")
        connection.execute("RELEASE representative_catalog_ranking")
        raise
    connection.execute("RELEASE representative_catalog_ranking")


class RepresentativeCatalogRankingRepository:
    """Read safe catalog evidence and populate the existing immutable album ranking tables."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def build(
        self,
        *,
        run_ref: str,
        genre_ids: Iterable[int] = (),
        config: RepresentativeCatalogRankingConfig = RepresentativeCatalogRankingConfig(),
        policy_id: int,
        generated_at: datetime,
    ) -> tuple[RepresentativeCatalogRankingArtifact, bool]:
        """Build and persist a bounded replayable projection in one savepoint."""
        selected_genres = self._selected_genres(genre_ids, max_genres=config.max_genres)
        config_sha = _config_sha(config)
        inputs = self._input_rows(selected_genres)
        fingerprint = _sha256(
            json.dumps(inputs, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
        )
        results = tuple(
            self._genre_result(genre_id, f"{run_ref}:genre:{genre_id}", config)
            for genre_id in selected_genres
        )
        gate = RepresentativeCatalogRankingGate(
            passed=True,
            selected_genres=len(results),
            ranked_genres=sum(bool(result.candidates) for result in results),
            abstained_genres=sum(result.abstention_reason is not None for result in results),
            candidates=sum(len(result.candidates) for result in results),
            limits=config,
        )
        artifact = RepresentativeCatalogRankingArtifact(
            run_ref=run_ref,
            generated_at=generated_at,
            policy_id=policy_id,
            config=config,
            config_sha256=config_sha,
            input_fingerprint=fingerprint,
            results=results,
            gate=gate,
        )
        with _savepoint(self._connection):
            existing = self._existing_results(results, config_sha, fingerprint, policy_id)
            if existing:
                return artifact, True
            self._insert_results(artifact)
        return artifact, False

    def _selected_genres(self, requested: Iterable[int], *, max_genres: int) -> tuple[int, ...]:
        explicit = tuple(sorted(set(requested)))
        if any(genre_id <= 0 for genre_id in explicit):
            raise RepresentativeCatalogRankingError("genre identifiers must be positive")
        if explicit:
            if len(explicit) > max_genres:
                raise RepresentativeCatalogRankingError("requested genres exceed max_genres")
            return explicit
        rows = self._connection.execute(
            """
            SELECT DISTINCT genre_id FROM displayable_album_genre_memberships
            WHERE evidence_kind IN (?, ?, ?)
            ORDER BY genre_id LIMIT ?
            """,
            tuple(sorted(DIRECT_KINDS)) + (max_genres,),
        ).fetchall()
        return tuple(int(row[0]) for row in rows)

    def _input_rows(self, genres: tuple[int, ...]) -> dict[str, object]:
        return {
            "genres": genres,
            "direct": [
                tuple(row)
                for row in self._connection.execute(
                    """SELECT id, genre_id, release_group_id, evidence_kind, source_family
                    FROM displayable_album_genre_memberships
                    WHERE genre_id IN (%s) AND evidence_kind IN (?, ?, ?)
                    ORDER BY genre_id, release_group_id, source_family, id"""
                    % ",".join("?" for _ in genres),
                    genres + tuple(sorted(DIRECT_KINDS)),
                ).fetchall()
            ]
            if genres
            else [],
            "artist_memberships": [
                tuple(row)
                for row in self._connection.execute(
                    """SELECT membership.genre_id, credit.entity_id, membership.artist_id,
                              membership.score, membership.source_count
                    FROM displayable_artist_genre_memberships AS membership
                    JOIN artist_credit_members AS member ON member.artist_id = membership.artist_id
                    JOIN entity_artist_credits AS credit ON credit.artist_credit_id = member.artist_credit_id
                    WHERE credit.entity_id IN (SELECT id FROM release_groups)
                      AND membership.genre_id IN (%s)
                    ORDER BY membership.genre_id, credit.entity_id, membership.artist_id"""
                    % ",".join("?" for _ in genres),
                    genres,
                ).fetchall()
            ]
            if genres
            else [],
        }

    def _genre_result(
        self, genre_id: int, run_ref: str, config: RepresentativeCatalogRankingConfig
    ) -> GenreCandidateResult:
        direct_by_group: dict[int, list[_DirectEvidence]] = defaultdict(list)
        rows = self._connection.execute(
            """SELECT id, release_group_id, source_family
            FROM displayable_album_genre_memberships
            WHERE genre_id = ? AND evidence_kind IN (?, ?, ?)
            ORDER BY release_group_id, source_family COLLATE NOCASE, id""",
            (genre_id, *sorted(DIRECT_KINDS)),
        ).fetchall()
        for row in rows:
            evidence = _DirectEvidence(
                observation_id=int(row[0]), release_group_id=int(row[1]), source_family=str(row[2])
            )
            direct_by_group[evidence.release_group_id].append(evidence)
        if not direct_by_group:
            return GenreCandidateResult(
                genre_id=genre_id,
                run_ref=run_ref,
                abstention_reason="no_direct_album_genre_evidence",
            )
        eligible = {
            group_id: evidence
            for group_id, evidence in direct_by_group.items()
            if len({item.source_family for item in evidence})
            >= config.minimum_direct_source_families
        }
        if not eligible:
            return GenreCandidateResult(
                genre_id=genre_id,
                run_ref=run_ref,
                abstention_reason="insufficient_direct_source_diversity",
            )
        artist = self._artist_memberships(genre_id, tuple(eligible))
        releases = self._release_completeness(tuple(eligible))
        candidates = [
            self._candidate(
                genre_id=genre_id,
                release_group_id=group_id,
                direct=evidence,
                artist=artist.get(group_id, ()),
                release=releases.get(group_id),
                config=config,
            )
            for group_id, evidence in eligible.items()
        ]
        candidates.sort(
            key=lambda candidate: (
                -candidate.score,
                -candidate.direct_source_family_count,
                -candidate.direct_observation_count,
                -candidate.artist_membership_strength,
                -(candidate.representative_release is not None),
                candidate.release_group_id,
            )
        )
        return GenreCandidateResult(
            genre_id=genre_id,
            run_ref=run_ref,
            candidates=tuple(
                candidate.model_copy(update={"rank": rank})
                for rank, candidate in enumerate(
                    candidates[: config.max_candidates_per_genre], start=1
                )
            ),
        )

    def _artist_memberships(
        self, genre_id: int, groups: tuple[int, ...]
    ) -> dict[int, tuple[_ArtistMembership, ...]]:
        if not groups:
            return {}
        rows = self._connection.execute(
            """SELECT credit.entity_id, membership.artist_id, membership.score, membership.source_count
            FROM displayable_artist_genre_memberships AS membership
            JOIN artist_credit_members AS member ON member.artist_id = membership.artist_id
            JOIN entity_artist_credits AS credit ON credit.artist_credit_id = member.artist_credit_id
            WHERE membership.genre_id = ? AND credit.entity_id IN (%s)
            GROUP BY credit.entity_id, membership.artist_id
            ORDER BY credit.entity_id, membership.artist_id"""
            % ",".join("?" for _ in groups),
            (genre_id, *groups),
        ).fetchall()
        result: dict[int, list[_ArtistMembership]] = defaultdict(list)
        for row in rows:
            result[int(row[0])].append(
                _ArtistMembership(
                    artist_id=int(row[1]), score=float(row[2]), source_count=int(row[3])
                )
            )
        return {group_id: tuple(items) for group_id, items in result.items()}

    def _release_completeness(self, groups: tuple[int, ...]) -> dict[int, _ReleaseCompleteness]:
        if not groups:
            return {}
        rows = self._connection.execute(
            """SELECT release.release_group_id, release.id, release.status,
                      count(DISTINCT medium.id), count(DISTINCT track.id),
                      sum(medium.track_count)
            FROM releases AS release
            LEFT JOIN media AS medium ON medium.release_id = release.id
            LEFT JOIN tracks AS track ON track.medium_id = medium.id
            WHERE release.release_group_id IN (%s)
            GROUP BY release.release_group_id, release.id, release.status
            ORDER BY release.release_group_id, release.id"""
            % ",".join("?" for _ in groups),
            groups,
        ).fetchall()
        by_group: dict[int, list[_ReleaseCompleteness]] = defaultdict(list)
        for row in rows:
            by_group[int(row[0])].append(
                _ReleaseCompleteness(
                    release_id=int(row[1]),
                    is_official=str(row[2] or "").casefold() == "official",
                    media_count=int(row[3]),
                    track_count=int(row[4]),
                    declared_track_count=int(row[5]) if row[5] is not None else None,
                )
            )
        return {
            group_id: sorted(
                values,
                key=lambda item: (-item.normalized, -item.is_official, item.release_id),
            )[0]
            for group_id, values in by_group.items()
        }

    @staticmethod
    def _candidate(
        *,
        genre_id: int,
        release_group_id: int,
        direct: list[_DirectEvidence],
        artist: tuple[_ArtistMembership, ...],
        release: _ReleaseCompleteness | None,
        config: RepresentativeCatalogRankingConfig,
    ) -> RepresentativeCandidate:
        families = tuple(sorted({item.source_family for item in direct}, key=str.casefold))
        direct_refs = tuple(item.reference for item in direct)
        artist_strength = min(max((item.score for item in artist), default=0.0), 1.0)
        artist_refs = tuple(item.reference for item in artist)
        completeness = release.normalized if release is not None else 0.0
        specs = (
            (
                "direct_evidence",
                float(len(direct)),
                1.0,
                config.weights.direct_evidence,
                direct_refs,
            ),
            (
                "source_diversity",
                float(len(families)),
                min(float(len(families)) / MAX_DIRECT_SOURCE_FAMILIES, 1.0),
                config.weights.source_diversity,
                direct_refs,
            ),
            (
                "artist_membership_strength",
                artist_strength,
                artist_strength,
                config.weights.artist_membership,
                artist_refs,
            ),
            (
                "release_track_metadata_completeness",
                completeness,
                completeness,
                config.weights.metadata_completeness,
                (),
            ),
        )
        components = tuple(
            ScoreComponent(
                component_key=key,
                raw_value=raw,
                normalized_value=normalized,
                weight=weight,
                contribution=normalized * weight,
                evidence_refs=references,
            )
            for key, raw, normalized, weight, references in specs
        )
        display_release = (
            CandidateReleaseMetadata(
                release_id=release.release_id,
                media_count=release.media_count,
                track_count=release.track_count,
                declared_track_count=release.declared_track_count,
                is_official=release.is_official,
            )
            if release is not None
            else None
        )
        return RepresentativeCandidate(
            genre_id=genre_id,
            release_group_id=release_group_id,
            rank=1,
            score=sum(component.contribution for component in components),
            direct_observation_count=len(direct),
            direct_source_family_count=len(families),
            artist_membership_strength=artist_strength,
            representative_release=display_release,
            components=components,
            direct_evidence_refs=direct_refs,
            artist_membership_refs=artist_refs,
            explanation=(
                "Representative candidate selected from direct album-genre evidence; artist "
                "membership is an explicit inferred component only. Metadata completeness reflects "
                "retained release/media/track rows when present, not popularity, quality, audio, "
                "streams, listeners, or audience consensus."
            ),
        )

    def _existing_results(
        self,
        results: tuple[GenreCandidateResult, ...],
        config_sha: str,
        fingerprint: str,
        policy_id: int,
    ) -> bool:
        if not results:
            return False
        rows = self._connection.execute(
            "SELECT run_ref, config_sha256, input_fingerprint, policy_id FROM album_genre_ranking_runs "
            "WHERE run_ref IN (%s)" % ",".join("?" for _ in results),
            tuple(result.run_ref for result in results),
        ).fetchall()
        if not rows:
            return False
        if len(rows) != len(results) or any(
            (str(row[1]), str(row[2]), int(row[3])) != (config_sha, fingerprint, policy_id)
            for row in rows
        ):
            raise RepresentativeCatalogRankingError(
                "run_ref already exists with different candidate inputs or configuration"
            )
        return True

    def _insert_results(self, artifact: RepresentativeCatalogRankingArtifact) -> None:
        for result in artifact.results:
            revision = int(
                self._connection.execute(
                    "SELECT coalesce(max(revision), 0) + 1 FROM album_genre_ranking_runs "
                    "WHERE genre_id = ? AND strategy_key = ?",
                    (result.genre_id, METHOD_KEY),
                ).fetchone()[0]
            )
            cursor = self._connection.execute(
                """INSERT INTO album_genre_ranking_runs (
                    run_ref, genre_id, strategy_key, strategy_version, revision, config_json,
                    config_sha256, input_fingerprint, eligibility_rule, policy_id, generated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    result.run_ref,
                    result.genre_id,
                    METHOD_KEY,
                    METHOD_VERSION,
                    revision,
                    _canonical_bytes(artifact.config).decode(),
                    artifact.config_sha256,
                    artifact.input_fingerprint,
                    artifact.config.eligibility_rule,
                    artifact.policy_id,
                    artifact.generated_at.isoformat(),
                ),
            )
            if cursor.lastrowid is None:
                raise RepresentativeCatalogRankingError("ranking run insert returned no ID")
            for candidate in result.candidates:
                self._connection.execute(
                    """INSERT INTO album_genre_ranking_items (
                        run_id, release_group_id, representative_release_id, rank, score,
                        membership_confidence, evidence_coverage, components_json, explanation_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        cursor.lastrowid,
                        candidate.release_group_id,
                        candidate.representative_release.release_id
                        if candidate.representative_release is not None
                        else None,
                        candidate.rank,
                        candidate.score,
                        1.0,
                        candidate.direct_source_family_count / MAX_DIRECT_SOURCE_FAMILIES,
                        json.dumps(
                            [item.model_dump(mode="json") for item in candidate.components],
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        json.dumps(
                            {
                                "classification": candidate.classification,
                                "explanation": candidate.explanation,
                                "missing_features": candidate.missing_features,
                                "artist_membership_refs": candidate.artist_membership_refs,
                            },
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                    ),
                )
                self._connection.executemany(
                    """INSERT INTO album_genre_ranking_item_evidence
                    (run_id, release_group_id, membership_observation_id) VALUES (?, ?, ?)""",
                    (
                        (cursor.lastrowid, candidate.release_group_id, int(ref.rsplit(":", 1)[1]))
                        for ref in candidate.direct_evidence_refs
                    ),
                )


def write_representative_catalog_ranking(
    artifact: RepresentativeCatalogRankingArtifact, output: Path
) -> tuple[str, int]:
    """Write canonical bounded JSON before optional immutable publication."""
    payload = _canonical_bytes(artifact)
    if len(payload) > ARTIFACT_BYTES_LIMIT:
        raise RepresentativeCatalogRankingError("candidate artifact exceeds 8 MiB")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    require_metadata_file(output)
    return _sha256(payload), len(payload)


def publish_representative_catalog_ranking(
    output: Path, store: ObjectStore
) -> RepresentativeCatalogRankingPublication:
    """Publish exactly the verified artifact bytes through the ObjectStore boundary."""
    try:
        payload = output.read_bytes()
        if not payload or len(payload) > ARTIFACT_BYTES_LIMIT:
            raise ValueError("artifact size is invalid")
        require_metadata_file(output)
        artifact = RepresentativeCatalogRankingArtifact.model_validate_json(payload)
    except (OSError, ValidationError, ValueError) as error:
        raise RepresentativeCatalogRankingError(
            "candidate artifact is invalid or unsafe"
        ) from error
    digest = _sha256(payload)
    stored = store.push(output, ObjectKey(value=f"representative-candidates/sha256/{digest}.json"))
    if (stored.sha256, stored.byte_size) != (digest, len(payload)):
        raise RepresentativeCatalogRankingError("object store changed candidate artifact")
    return RepresentativeCatalogRankingPublication(
        artifact=stored,
        candidate_count=artifact.gate.candidates,
        abstention_count=artifact.gate.abstained_genres,
        gate=artifact.gate,
    )
