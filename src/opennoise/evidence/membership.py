"""Build explainable artist-to-genre memberships from preserved source evidence."""

import json
import math
import sqlite3
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from typing import Literal

from pydantic import Field, FiniteFloat, JsonValue, TypeAdapter, field_validator, model_validator

from opennoise.common import sha256_hex
from opennoise.models import FrozenModel
from opennoise.sources.musicbrainz import ArtistGenreRelationship
from opennoise.types import Sha256  # Pydantic resolves this Annotated alias at runtime.

type EvidenceKind = Literal["direct_source_claim", "release_group_propagation"]
type MembershipMethod = Literal["direct_evidence", "release_propagation"]
type SimilarityMetric = Literal["weighted_jaccard", "weighted_cosine"]

MEMBERSHIP_METHOD_ADAPTER: TypeAdapter[MembershipMethod] = TypeAdapter(MembershipMethod)


def _canonical_json(value: JsonValue) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


@contextmanager
def _savepoint(connection: sqlite3.Connection, name: str) -> Iterator[None]:
    connection.execute(f"SAVEPOINT {name}")
    try:
        yield
    except Exception:
        connection.execute(f"ROLLBACK TO {name}")
        connection.execute(f"RELEASE {name}")
        raise
    connection.execute(f"RELEASE {name}")


class ArtistGenreEvidence(FrozenModel):
    """Represent one immutable claim or explicit derivation about an artist and genre."""

    artist_id: int = Field(gt=0)
    genre_id: int = Field(gt=0)
    evidence_kind: EvidenceKind
    evidence_value: FiniteFloat = Field(ge=0.0)
    source_key: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    source_album_evidence_id: int | None = Field(default=None, gt=0)
    source_credit_provenance_id: int | None = Field(default=None, gt=0)
    source_credit_definition_provenance_id: int | None = Field(default=None, gt=0)
    method_key: str = Field(min_length=1)
    method_version: str = Field(min_length=1)
    parameter_manifest: dict[str, JsonValue]
    observed_at: datetime
    provenance_id: int = Field(gt=0)
    policy_id: int = Field(gt=0)

    @model_validator(mode="after")
    def require_origin_for_propagation(self) -> "ArtistGenreEvidence":
        """Require a source album only for propagated evidence."""
        propagated = self.evidence_kind == "release_group_propagation"
        has_album = self.source_album_evidence_id is not None
        has_credit = self.source_credit_provenance_id is not None
        if propagated is not (has_album and has_credit):
            raise ValueError("release propagation requires album and credit provenance")
        if not propagated and self.source_credit_definition_provenance_id is not None:
            raise ValueError("direct evidence cannot identify credit provenance")
        return self

    def fingerprint(self) -> Sha256:
        """Hash the entire normalized claim so repeated ingestion is idempotent."""
        return sha256_hex(_canonical_json(self.model_dump(mode="json")).encode())


class DirectArtistGenreProjection(FrozenModel):
    """Resolve one MusicBrainz relationship to local IDs and provenance."""

    artist_id: int = Field(gt=0)
    genre_id: int = Field(gt=0)
    source_record_id: str = Field(min_length=1)
    source_key: Literal["musicbrainz"] = "musicbrainz"
    observed_at: datetime
    provenance_id: int = Field(gt=0)
    policy_id: int = Field(gt=0)
    missing_weight_value: FiniteFloat = Field(ge=0.0)


def evidence_from_musicbrainz(
    relationship: ArtistGenreRelationship,
    projection: DirectArtistGenreProjection,
) -> ArtistGenreEvidence:
    """Project a resolved MusicBrainz artist genre claim without fuzzy matching."""
    evidence_value = (
        float(relationship.weight)
        if relationship.weight is not None
        else projection.missing_weight_value
    )
    return ArtistGenreEvidence(
        artist_id=projection.artist_id,
        genre_id=projection.genre_id,
        evidence_kind="direct_source_claim",
        evidence_value=evidence_value,
        source_key=projection.source_key,
        source_record_id=projection.source_record_id,
        method_key="direct_musicbrainz_artist_genre",
        method_version="1",
        parameter_manifest={
            "missing_weight_value": projection.missing_weight_value,
            "source_weight_semantics": "musicbrainz_vote_count",
        },
        observed_at=projection.observed_at,
        provenance_id=projection.provenance_id,
        policy_id=projection.policy_id,
    )


class StoredEvidence(FrozenModel):
    """Identify one newly inserted or previously stored evidence record."""

    evidence_id: int = Field(gt=0)
    record_fingerprint: Sha256
    reused: bool


class ReleasePropagationManifest(FrozenModel):
    """Make the deliberately simple album-to-primary-artist rule inspectable."""

    method: Literal["release_propagation"] = "release_propagation"
    version: Literal["1"] = "1"
    credit_kind: str = Field(default="primary", min_length=1)
    allocation: Literal["full_value_to_each_credited_artist"] = "full_value_to_each_credited_artist"
    missing_source_count_value: FiniteFloat = Field(ge=0.0)
    max_input_evidence: int = Field(default=100_000, gt=0, le=10_000_000)


class MaterializationManifest(FrozenModel):
    """Configure a bounded evidence-only membership run."""

    method: MembershipMethod
    version: Literal["1"] = "1"
    included_evidence_kinds: tuple[EvidenceKind, ...] = Field(min_length=1)
    included_source_keys: tuple[str, ...] = Field(min_length=1)
    aggregation: Literal["sum_preserved_values"] = "sum_preserved_values"
    max_input_evidence: int = Field(default=100_000, gt=0, le=10_000_000)
    max_output_items: int = Field(default=100_000, gt=0, le=10_000_000)

    @model_validator(mode="after")
    def require_unique_filters(self) -> "MaterializationManifest":
        """Reject duplicate or blank selectors before they enter SQL."""
        if len(self.included_evidence_kinds) != len(set(self.included_evidence_kinds)):
            raise ValueError("included evidence kinds must be unique")
        keys = tuple(key.strip() for key in self.included_source_keys)
        if keys != self.included_source_keys:
            raise ValueError("included source keys must not contain surrounding whitespace")
        if any(not key for key in keys) or len(keys) != len(set(keys)):
            raise ValueError("included source keys must be nonblank and unique")
        if self.method == "direct_evidence" and self.included_evidence_kinds != (
            "direct_source_claim",
        ):
            raise ValueError("direct_evidence runs accept only direct_source_claim")
        if self.method == "release_propagation" and self.included_evidence_kinds != (
            "release_group_propagation",
        ):
            raise ValueError("release_propagation runs accept only propagated evidence")
        return self


class MembershipRunRequest(FrozenModel):
    """Name and date one immutable membership materialization."""

    run_ref: str = Field(min_length=1)
    revision: int = Field(gt=0)
    manifest: MaterializationManifest
    policy_id: int = Field(gt=0)
    generated_at: datetime


class MembershipItem(FrozenModel):
    """Expose one membership with its unscaled score and evidence facets."""

    artist_id: int = Field(gt=0)
    genre_id: int = Field(gt=0)
    score: FiniteFloat = Field(ge=0.0)
    evidence_count: int = Field(gt=0)
    source_count: int = Field(gt=0)
    evidence_ids: tuple[int, ...] = Field(min_length=1)


class MembershipArtifact(FrozenModel):
    """Return a fully identified immutable membership run."""

    run_id: int = Field(gt=0)
    run_ref: str
    method: MembershipMethod
    revision: int = Field(gt=0)
    parameter_manifest_sha256: Sha256
    input_fingerprint: Sha256
    items: tuple[MembershipItem, ...]
    reused: bool


class FeatureValue(FrozenModel):
    """Store one nonnegative sparse representation component."""

    key: str = Field(min_length=1)
    value: FiniteFloat = Field(ge=0.0)


class RepresentationVector(FrozenModel):
    """Represent an entity as explicit, unscaled sparse nonnegative features."""

    entity_ref: str = Field(min_length=1)
    components: tuple[FeatureValue, ...]

    @model_validator(mode="after")
    def require_unique_components(self) -> "RepresentationVector":
        """Reject ambiguous duplicate feature keys."""
        keys = tuple(component.key for component in self.components)
        if len(keys) != len(set(keys)):
            raise ValueError("representation component keys must be unique")
        return self


class FeatureWeight(FrozenModel):
    """Declare one caller-selected similarity feature weight."""

    key: str = Field(min_length=1)
    weight: FiniteFloat = Field(gt=0.0)


class SimilarityManifest(FrozenModel):
    """Require every weight and zero-vector behavior to be explicit."""

    metric: SimilarityMetric
    version: Literal["1"] = "1"
    feature_weights: tuple[FeatureWeight, ...] = Field(min_length=1)
    zero_vector_result: FiniteFloat = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def require_unique_weights(self) -> "SimilarityManifest":
        """Reject duplicate feature weights."""
        keys = tuple(weight.key for weight in self.feature_weights)
        if len(keys) != len(set(keys)):
            raise ValueError("similarity feature weights must be unique")
        return self


class SimilarityResult(FrozenModel):
    """Return a score with the exact parameter manifest that produced it."""

    left_ref: str
    right_ref: str
    score: FiniteFloat = Field(ge=0.0, le=1.0)
    manifest_sha256: Sha256
    contributing_features: tuple[str, ...]


def representation_similarity(
    left: RepresentationVector,
    right: RepresentationVector,
    manifest: SimilarityManifest,
) -> SimilarityResult:
    """Compute weighted Jaccard or cosine with no implicit feature weights."""
    left_values = {component.key: component.value for component in left.components}
    right_values = {component.key: component.value for component in right.components}
    feature_keys = set(left_values) | set(right_values)
    weights = {feature.key: feature.weight for feature in manifest.feature_weights}
    missing = feature_keys - set(weights)
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"manifest has no weights for features: {missing_list}")
    ordered = tuple(sorted(feature_keys))
    if manifest.metric == "weighted_jaccard":
        numerator = sum(
            weights[key] * min(left_values.get(key, 0.0), right_values.get(key, 0.0))
            for key in ordered
        )
        denominator = sum(
            weights[key] * max(left_values.get(key, 0.0), right_values.get(key, 0.0))
            for key in ordered
        )
    else:
        numerator = sum(
            weights[key] * left_values.get(key, 0.0) * right_values.get(key, 0.0) for key in ordered
        )
        left_norm = math.sqrt(sum(weights[key] * left_values.get(key, 0.0) ** 2 for key in ordered))
        right_norm = math.sqrt(
            sum(weights[key] * right_values.get(key, 0.0) ** 2 for key in ordered)
        )
        denominator = left_norm * right_norm
    score = manifest.zero_vector_result if denominator == 0.0 else numerator / denominator
    manifest_json = _canonical_json(manifest.model_dump(mode="json"))
    return SimilarityResult(
        left_ref=left.entity_ref,
        right_ref=right.entity_ref,
        score=score,
        manifest_sha256=sha256_hex(manifest_json.encode()),
        contributing_features=ordered,
    )


class EvaluationClaim(FrozenModel):
    """Name one known positive artist-to-genre claim."""

    artist_ref: str = Field(min_length=1)
    genre_ref: str = Field(min_length=1)

    @field_validator("artist_ref", "genre_ref")
    @classmethod
    def require_normalized_reference(cls, value: str) -> str:
        """Reject blank or padded identifiers instead of changing evaluation keys."""
        if not value.strip() or value != value.strip():
            raise ValueError("evaluation references must be nonblank and unpadded")
        return value


class EvaluationPrediction(EvaluationClaim):
    """Name one predicted claim and the source keys supporting it."""

    source_keys: tuple[str, ...] = Field(min_length=1)

    @field_validator("source_keys")
    @classmethod
    def require_normalized_source_keys(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Require fixed, unique source keys for coverage accounting."""
        if any(not key.strip() or key != key.strip() for key in value):
            raise ValueError("source keys must be nonblank and unpadded")
        if len(value) != len(set(value)):
            raise ValueError("source keys must be unique")
        return value


class MembershipEvaluation(FrozenModel):
    """Report absolute baseline quality, coverage, source coverage, and stability."""

    known_positive_prediction_fraction: FiniteFloat = Field(ge=0.0, le=1.0)
    known_positive_recall: FiniteFloat = Field(ge=0.0, le=1.0)
    coverage: FiniteFloat = Field(ge=0.0, le=1.0)
    source_coverage: FiniteFloat = Field(ge=0.0, le=1.0)
    stability: FiniteFloat = Field(ge=0.0, le=1.0)
    true_positive_count: int = Field(ge=0)
    predicted_count: int = Field(ge=0)
    known_claim_count: int = Field(ge=0)
    covered_artist_count: int = Field(ge=0)
    eligible_artist_count: int = Field(ge=0)
    observed_source_count: int = Field(ge=0)
    expected_source_count: int = Field(gt=0)


def evaluate_predictions(
    predictions: Sequence[EvaluationPrediction],
    known_claims: Sequence[EvaluationClaim],
    previous_predictions: Sequence[EvaluationPrediction],
    *,
    eligible_artist_refs: frozenset[str],
    expected_source_keys: frozenset[str],
) -> MembershipEvaluation:
    """Evaluate against fixed claims and declared denominators without relative scaling."""
    if not expected_source_keys or any(
        not key.strip() or key != key.strip() for key in expected_source_keys
    ):
        raise ValueError("expected_source_keys must contain nonblank, unpadded keys")
    predicted_pairs = {(item.artist_ref, item.genre_ref) for item in predictions}
    known_pairs = {(item.artist_ref, item.genre_ref) for item in known_claims}
    previous_pairs = {(item.artist_ref, item.genre_ref) for item in previous_predictions}
    true_positives = predicted_pairs & known_pairs
    covered_artists = {artist for artist, _genre in predicted_pairs} & eligible_artist_refs
    observed_sources = {
        key for prediction in predictions for key in prediction.source_keys
    } & expected_source_keys
    union = predicted_pairs | previous_pairs
    return MembershipEvaluation(
        known_positive_prediction_fraction=(
            len(true_positives) / len(predicted_pairs) if predicted_pairs else 0.0
        ),
        known_positive_recall=len(true_positives) / len(known_pairs) if known_pairs else 0.0,
        coverage=(
            len(covered_artists) / len(eligible_artist_refs) if eligible_artist_refs else 0.0
        ),
        source_coverage=len(observed_sources) / len(expected_source_keys),
        stability=len(predicted_pairs & previous_pairs) / len(union) if union else 1.0,
        true_positive_count=len(true_positives),
        predicted_count=len(predicted_pairs),
        known_claim_count=len(known_pairs),
        covered_artist_count=len(covered_artists),
        eligible_artist_count=len(eligible_artist_refs),
        observed_source_count=len(observed_sources),
        expected_source_count=len(expected_source_keys),
    )


class ArtistGenreRepository:
    """Persist evidence and bounded, immutable membership materializations."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Keep transaction ownership with the caller."""
        self._connection = connection

    def add_evidence(self, evidence: ArtistGenreEvidence) -> StoredEvidence:
        """Insert one complete claim once."""
        fingerprint = evidence.fingerprint()
        cursor = self._connection.execute(
            """
            INSERT INTO artist_genre_evidence (
                artist_id, genre_id, evidence_kind, evidence_value, source_key,
                source_record_id, source_album_evidence_id, source_credit_provenance_id,
                source_credit_definition_provenance_id,
                method_key, method_version,
                parameter_manifest_json, observed_at, provenance_id, policy_id,
                record_fingerprint
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(record_fingerprint) DO NOTHING
            """,
            (
                evidence.artist_id,
                evidence.genre_id,
                evidence.evidence_kind,
                evidence.evidence_value,
                evidence.source_key,
                evidence.source_record_id,
                evidence.source_album_evidence_id,
                evidence.source_credit_provenance_id,
                evidence.source_credit_definition_provenance_id,
                evidence.method_key,
                evidence.method_version,
                _canonical_json(evidence.parameter_manifest),
                evidence.observed_at.isoformat(),
                evidence.provenance_id,
                evidence.policy_id,
                fingerprint,
            ),
        )
        row = self._connection.execute(
            "SELECT id FROM artist_genre_evidence WHERE record_fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        if row is None:
            raise RuntimeError("artist genre evidence insert returned no identity")
        return StoredEvidence(
            evidence_id=int(row[0]), record_fingerprint=fingerprint, reused=cursor.rowcount == 0
        )

    def propagate_release_evidence(self, manifest: ReleasePropagationManifest) -> int:
        """Materialize eligible album claims onto explicitly credited primary artists."""
        rows = self._connection.execute(
            """
            SELECT album.id, album.genre_id, source.source_key, album.source_record_id,
                   album.source_count, album.observed_at, album.provenance_id, album.policy_id,
                   member.artist_id, link.provenance_id, credit.provenance_id
            FROM normalizable_album_genre_memberships AS album
            JOIN provenance_records AS provenance ON provenance.id = album.provenance_id
            JOIN data_sources AS source ON source.id = provenance.source_id
            JOIN entity_artist_credits AS link
              ON link.entity_id = album.release_group_id AND link.credit_kind = ?
            JOIN artist_credits AS credit ON credit.id = link.artist_credit_id
            JOIN artist_credit_members AS member
              ON member.artist_credit_id = link.artist_credit_id
            JOIN provenance_records AS link_provenance
              ON link_provenance.id = link.provenance_id
            JOIN active_rights_policy_permissions AS link_permission
              ON link_permission.policy_id = link_provenance.policy_id
             AND link_permission.use_kind = 'normalize'
             AND link_permission.decision = 'allow'
            LEFT JOIN provenance_records AS credit_provenance
              ON credit_provenance.id = credit.provenance_id
            LEFT JOIN active_rights_policy_permissions AS credit_permission
              ON credit_permission.policy_id = credit_provenance.policy_id
             AND credit_permission.use_kind = 'normalize'
             AND credit_permission.decision = 'allow'
            WHERE NOT EXISTS (
                SELECT 1 FROM active_suppressions AS suppression
                WHERE suppression.use_kind IN ('all', 'normalize') AND (
                    (suppression.target_kind = 'provenance'
                     AND suppression.target_ref = CAST(link.provenance_id AS TEXT))
                    OR (suppression.target_kind = 'source'
                        AND suppression.target_ref = CAST(link_provenance.source_id AS TEXT))
                )
            )
            AND (
                credit.provenance_id IS NULL OR (
                    credit_permission.policy_id IS NOT NULL
                    AND NOT EXISTS (
                        SELECT 1 FROM active_suppressions AS suppression
                        WHERE suppression.use_kind IN ('all', 'normalize') AND (
                            (suppression.target_kind = 'provenance'
                             AND suppression.target_ref = CAST(credit.provenance_id AS TEXT))
                            OR (suppression.target_kind = 'source'
                                AND suppression.target_ref = CAST(
                                    credit_provenance.source_id AS TEXT
                                ))
                        )
                    )
                )
            )
            ORDER BY album.id, member.artist_id
            LIMIT ?
            """,
            (manifest.credit_kind, manifest.max_input_evidence + 1),
        ).fetchall()
        if len(rows) > manifest.max_input_evidence:
            raise ValueError("release propagation exceeds max_input_evidence")
        inserted = 0
        manifest_value = manifest.model_dump(mode="json")
        with _savepoint(self._connection, "propagate_artist_genres"):
            for row in rows:
                stored = self.add_evidence(
                    ArtistGenreEvidence(
                        artist_id=int(row[8]),
                        genre_id=int(row[1]),
                        evidence_kind="release_group_propagation",
                        evidence_value=(
                            float(row[4])
                            if row[4] is not None
                            else manifest.missing_source_count_value
                        ),
                        source_key=str(row[2]),
                        source_record_id=f"album-genre-evidence:{int(row[0])}",
                        source_album_evidence_id=int(row[0]),
                        source_credit_provenance_id=int(row[9]),
                        source_credit_definition_provenance_id=(
                            int(row[10]) if row[10] is not None else None
                        ),
                        method_key="release_group_primary_artist_propagation",
                        method_version=manifest.version,
                        parameter_manifest=manifest_value,
                        observed_at=datetime.fromisoformat(str(row[5])),
                        provenance_id=int(row[6]),
                        policy_id=int(row[7]),
                    )
                )
                inserted += int(not stored.reused)
        return inserted

    def materialize(self, request: MembershipRunRequest) -> MembershipArtifact:
        """Aggregate a bounded eligible evidence set without hidden rescaling."""
        existing = self._connection.execute(
            "SELECT id FROM artist_genre_membership_runs WHERE run_ref = ?",
            (request.run_ref,),
        ).fetchone()
        manifest_json = _canonical_json(request.manifest.model_dump(mode="json"))
        manifest_sha256 = sha256_hex(manifest_json.encode())
        evidence_rows = self._eligible_evidence(request.manifest)
        input_fingerprint = self._input_fingerprint(
            request.manifest.method, manifest_sha256, evidence_rows
        )
        if existing is not None:
            return self._load_artifact(
                int(existing[0]),
                expected_request=request,
                expected_manifest_sha256=manifest_sha256,
                expected_input_fingerprint=input_fingerprint,
                reused=True,
            )
        grouped: dict[tuple[int, int], list[sqlite3.Row]] = defaultdict(list)
        for row in evidence_rows:
            grouped[(int(row[1]), int(row[2]))].append(row)
        if len(grouped) > request.manifest.max_output_items:
            raise ValueError("membership materialization exceeds max_output_items")
        with _savepoint(self._connection, "materialize_artist_genres"):
            cursor = self._connection.execute(
                """
                INSERT INTO artist_genre_membership_runs (
                    run_ref, method_key, method_version, revision,
                    parameter_manifest_json, parameter_manifest_sha256,
                    input_fingerprint, input_evidence_count, output_item_limit,
                    policy_id, generated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request.run_ref,
                    request.manifest.method,
                    request.manifest.version,
                    request.revision,
                    manifest_json,
                    manifest_sha256,
                    input_fingerprint,
                    len(evidence_rows),
                    request.manifest.max_output_items,
                    request.policy_id,
                    request.generated_at.isoformat(),
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("membership run insert returned no identity")
            run_id = cursor.lastrowid
            for (artist_id, genre_id), rows in sorted(grouped.items()):
                score = sum(float(row[4]) for row in rows)
                source_keys = sorted({str(row[5]) for row in rows})
                evidence_ids = tuple(sorted(int(row[0]) for row in rows))
                explanation: dict[str, JsonValue] = {
                    "aggregation": request.manifest.aggregation,
                    "evidence_ids": list(evidence_ids),
                    "preserved_values": [float(row[4]) for row in rows],
                    "source_keys": source_keys,
                }
                self._connection.execute(
                    """
                    INSERT INTO artist_genre_membership_items (
                        run_id, artist_id, genre_id, score, evidence_count,
                        source_count, explanation_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        artist_id,
                        genre_id,
                        score,
                        len(rows),
                        len(source_keys),
                        _canonical_json(explanation),
                    ),
                )
                self._connection.executemany(
                    """
                    INSERT INTO artist_genre_membership_item_evidence (
                        run_id, artist_id, genre_id, evidence_id
                    ) VALUES (?, ?, ?, ?)
                    """,
                    ((run_id, artist_id, genre_id, evidence_id) for evidence_id in evidence_ids),
                )
        return self._load_artifact(
            run_id,
            expected_request=request,
            expected_manifest_sha256=manifest_sha256,
            expected_input_fingerprint=input_fingerprint,
            reused=False,
        )

    def _eligible_evidence(self, manifest: MaterializationManifest) -> list[sqlite3.Row]:
        query = """
            SELECT evidence.id, evidence.artist_id, evidence.genre_id,
                   evidence.evidence_kind, evidence.evidence_value,
                   evidence.source_key, evidence.source_record_id,
                   evidence.source_album_evidence_id, evidence.method_key,
                   evidence.method_version, evidence.parameter_manifest_json,
                   evidence.observed_at, evidence.provenance_id, evidence.policy_id,
                   evidence.record_fingerprint, provenance.record_fingerprint
            FROM normalizable_artist_genre_evidence AS evidence
            JOIN provenance_records AS provenance ON provenance.id = evidence.provenance_id
            WHERE evidence.evidence_kind IN (SELECT value FROM json_each(?))
              AND evidence.source_key IN (SELECT value FROM json_each(?))
            ORDER BY evidence.record_fingerprint
            LIMIT ?
        """
        parameters = (
            _canonical_json(list(manifest.included_evidence_kinds)),
            _canonical_json(list(manifest.included_source_keys)),
            manifest.max_input_evidence + 1,
        )
        raw_rows = self._connection.execute(query, parameters).fetchall()
        rows: list[sqlite3.Row] = []
        for row in raw_rows:
            if not isinstance(row, sqlite3.Row):
                raise TypeError("ArtistGenreRepository requires sqlite3.Row row_factory")
            rows.append(row)
        if len(rows) > manifest.max_input_evidence:
            raise ValueError("membership materialization exceeds max_input_evidence")
        return rows

    @staticmethod
    def _input_fingerprint(
        method: MembershipMethod,
        manifest_sha256: Sha256,
        rows: Iterable[sqlite3.Row],
    ) -> Sha256:
        payload: dict[str, JsonValue] = {
            "method": method,
            "manifest_sha256": manifest_sha256,
            "evidence": [[row[index] for index in range(len(row))] for row in rows],
        }
        return sha256_hex(_canonical_json(payload).encode())

    def _load_artifact(
        self,
        run_id: int,
        *,
        expected_request: MembershipRunRequest,
        expected_manifest_sha256: Sha256,
        expected_input_fingerprint: Sha256,
        reused: bool,
    ) -> MembershipArtifact:
        run = self._connection.execute(
            """
            SELECT run_ref, method_key, revision, parameter_manifest_sha256,
                   input_fingerprint, policy_id, generated_at
            FROM artist_genre_membership_runs WHERE id = ?
            """,
            (run_id,),
        ).fetchone()
        if run is None:
            raise RuntimeError("membership run insert returned no identity")
        if str(run[3]) != expected_manifest_sha256 or str(run[4]) != expected_input_fingerprint:
            raise ValueError("run_ref already identifies different parameters or inputs")
        if (
            str(run[0]) != expected_request.run_ref
            or int(run[2]) != expected_request.revision
            or int(run[5]) != expected_request.policy_id
            or str(run[6]) != expected_request.generated_at.isoformat()
        ):
            raise ValueError("run_ref already identifies a different run request")
        rows = self._connection.execute(
            """
            SELECT item.artist_id, item.genre_id, item.score, item.evidence_count,
                   item.source_count, link.evidence_id
            FROM artist_genre_membership_items AS item
            JOIN artist_genre_membership_item_evidence AS link
              ON link.run_id = item.run_id AND link.artist_id = item.artist_id
             AND link.genre_id = item.genre_id
            WHERE item.run_id = ?
            ORDER BY item.artist_id, item.genre_id, link.evidence_id
            """,
            (run_id,),
        ).fetchall()
        grouped: dict[tuple[int, int, float, int, int], list[int]] = defaultdict(list)
        for row in rows:
            grouped[(int(row[0]), int(row[1]), float(row[2]), int(row[3]), int(row[4]))].append(
                int(row[5])
            )
        items = tuple(
            MembershipItem(
                artist_id=key[0],
                genre_id=key[1],
                score=key[2],
                evidence_count=key[3],
                source_count=key[4],
                evidence_ids=tuple(evidence_ids),
            )
            for key, evidence_ids in grouped.items()
        )
        return MembershipArtifact(
            run_id=run_id,
            run_ref=str(run[0]),
            method=MEMBERSHIP_METHOD_ADAPTER.validate_python(str(run[1]), strict=True),
            revision=int(run[2]),
            parameter_manifest_sha256=str(run[3]),
            input_fingerprint=str(run[4]),
            items=items,
            reused=reused,
        )
