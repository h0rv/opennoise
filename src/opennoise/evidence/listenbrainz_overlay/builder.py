"""Build, verify, and persist strictly separate ListenBrainz evidence sidecars."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final
from uuid import UUID, uuid4

import ijson

from opennoise.common import (
    canonical_json,
    connect_readonly,
    connect_readwrite,
    sha256_file,
    write_atomic_bytes,
)
from opennoise.evidence.graph_projection import (
    EvidenceGraphProjectionArtifact,
    verify_evidence_graph_projection,
)
from opennoise.ingest.listenbrainz.propagation import (
    ListenBrainzPropagationReceipt,
    ListenBrainzPropagationSettings,
    PropagationCandidate,
    PropagationCoverage,
)

from .contracts import (
    _CERTIFICATE,
    CertifiedCoListenOverlaySources,
    CertifiedDerivedReviewOverlaySources,
    CoListenCoverage,
    CoListenOverlayArtifact,
    CoListenOverlayInputs,
    CoListenOverlaySources,
    DerivedReviewOverlayArtifact,
    DerivedReviewOverlayInputs,
    DerivedReviewOverlaySources,
    ListenBrainzOverlayError,
    ReviewCandidateCoverage,
    SidecarInput,
    colisten_overlay_sha256,
    derived_review_overlay_sha256,
    verify_colisten_overlay,
    verify_derived_review_overlay,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_ARTIST_PREFIX: Final = "musicbrainz:artist:"
_SHA256_LENGTH: Final = 64


@dataclass(frozen=True, slots=True)
class _ReviewStreamStats:
    """Complete candidate-stream counts retained outside the output sidecar schema."""

    source_candidate_count: int
    invalid_identifier_count: int
    candidate_artist_count: int
    candidate_seed_count: int


def build_derived_review_overlay(
    inputs: DerivedReviewOverlayInputs,
) -> DerivedReviewOverlayArtifact:
    """Build a review-only candidate sidecar without modifying the evidence graph."""
    if inputs.output_database.exists():
        raise ListenBrainzOverlayError("derived-review output database already exists")
    graph_inputs, graph_receipt = _load_graph(inputs.graph_database, inputs.graph_receipt)
    propagation_inputs, propagation_output_sha256, propagation_coverage = _load_propagation(
        inputs.propagation_artifact, inputs.propagation_receipt
    )
    inputs.output_database.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_path(inputs.output_database)
    invalid_identifier_count = 0
    source_candidate_count = 0
    candidate_artists: set[str] = set()
    candidate_seeds: set[str] = set()
    try:
        with closing(connect_readwrite(temporary)) as database, database:
            _review_schema(database)
            _insert_inputs(database, (*graph_inputs, *propagation_inputs))
            for candidate in _stream_candidates(inputs.propagation_artifact):
                source_candidate_count += 1
                parsed = _parse_candidate(candidate)
                if parsed is None:
                    invalid_identifier_count += 1
                    continue
                artist_source_id, artist_mbid, legacy_seed_id, stable_seed_id, paths_json = parsed
                candidate_artists.add(artist_mbid)
                candidate_seeds.add(stable_seed_id)
                try:
                    database.execute(
                        """INSERT INTO raw_candidate(
                               artist_source_id, artist_mbid, legacy_seed_id, stable_seed_id,
                               score, genre_rank, paths_json
                           ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            artist_source_id,
                            artist_mbid,
                            legacy_seed_id,
                            stable_seed_id,
                            candidate.score,
                            candidate.genre_rank,
                            paths_json,
                        ),
                    )
                except sqlite3.IntegrityError as error:
                    raise ListenBrainzOverlayError(
                        "propagation artifact repeats an artist/seed candidate"
                    ) from error
            stream_stats = _ReviewStreamStats(
                source_candidate_count=source_candidate_count,
                invalid_identifier_count=invalid_identifier_count,
                candidate_artist_count=len(candidate_artists),
                candidate_seed_count=len(candidate_seeds),
            )
            coverage = _materialize_review_candidates(
                database,
                inputs.graph_database,
                propagation_output_sha256,
                stream_stats,
            )
            if (
                coverage.source_candidate_count != propagation_coverage.candidate_count
                or coverage.candidate_artist_count != propagation_coverage.candidate_artist_count
                or coverage.candidate_seed_count != propagation_coverage.candidate_genre_count
            ):
                raise ListenBrainzOverlayError(
                    "propagation coverage does not replay its candidate stream"
                )
            _verify_sqlite(database, "derived-review overlay")
        database_sha256, database_bytes = sha256_file(temporary)
        with closing(connect_readonly(temporary)) as database:
            _verify_sqlite(database, "derived-review overlay")
            _verify_review_counts(database, coverage)
        artifact = DerivedReviewOverlayArtifact(
            graph_receipt_output_sha256=graph_receipt.output_sha256,
            propagation_output_sha256=propagation_output_sha256,
            inputs=(*graph_inputs, *propagation_inputs),
            database_sha256=database_sha256,
            database_bytes=database_bytes,
            coverage=coverage,
            output_sha256="0" * 64,
        )
        artifact = artifact.model_copy(
            update={"output_sha256": derived_review_overlay_sha256(artifact)}
        )
        verify_derived_review_overlay(artifact)
        temporary.replace(inputs.output_database)
        return artifact
    finally:
        temporary.unlink(missing_ok=True)


def build_colisten_overlay(inputs: CoListenOverlayInputs) -> CoListenOverlayArtifact:
    """Build a canonical-undirected aggregate co-listen sidecar from qualified SQLite."""
    if inputs.output_database.exists():
        raise ListenBrainzOverlayError("co-listen output database already exists")
    graph_inputs, graph_receipt = _load_graph(inputs.graph_database, inputs.graph_receipt)
    qualified_input = _load_qualified_listenbrainz(
        inputs.qualified_listenbrainz_database, inputs.expected_qualified_database_sha256
    )
    inputs.output_database.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_path(inputs.output_database)
    try:
        with closing(connect_readwrite(temporary)) as database, database:
            _colisten_schema(database)
            _insert_inputs(database, (*graph_inputs, qualified_input))
            coverage = _materialize_colistens(
                database,
                inputs.graph_database,
                inputs.qualified_listenbrainz_database,
                qualified_input.byte_sha256,
                inputs.privacy.minimum_distinct_user_count,
            )
            _verify_sqlite(database, "co-listen overlay")
        database_sha256, database_bytes = sha256_file(temporary)
        with closing(connect_readonly(temporary)) as database:
            _verify_sqlite(database, "co-listen overlay")
            _verify_colisten_counts(database, coverage)
        artifact = CoListenOverlayArtifact(
            graph_receipt_output_sha256=graph_receipt.output_sha256,
            inputs=(*graph_inputs, qualified_input),
            privacy=inputs.privacy,
            database_sha256=database_sha256,
            database_bytes=database_bytes,
            coverage=coverage,
            output_sha256="0" * 64,
        )
        artifact = artifact.model_copy(update={"output_sha256": colisten_overlay_sha256(artifact)})
        verify_colisten_overlay(artifact)
        temporary.replace(inputs.output_database)
        return artifact
    finally:
        temporary.unlink(missing_ok=True)


def write_derived_review_overlay(path: Path, artifact: DerivedReviewOverlayArtifact) -> None:
    """Atomically write a replay-verified derived-review receipt."""
    verify_derived_review_overlay(artifact)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic_bytes(path, canonical_json(artifact.model_dump(mode="json")) + b"\n")


def write_colisten_overlay(path: Path, artifact: CoListenOverlayArtifact) -> None:
    """Atomically write a replay-verified co-listen receipt."""
    verify_colisten_overlay(artifact)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic_bytes(path, canonical_json(artifact.model_dump(mode="json")) + b"\n")


def load_derived_review_overlay(path: Path) -> DerivedReviewOverlayArtifact:
    """Parse and self-verify a serialized derived-review receipt."""
    try:
        artifact = DerivedReviewOverlayArtifact.model_validate_json(path.read_bytes())
        verify_derived_review_overlay(artifact)
    except (OSError, ValueError) as error:
        raise ListenBrainzOverlayError("derived-review receipt is invalid") from error
    return artifact


def load_colisten_overlay(path: Path) -> CoListenOverlayArtifact:
    """Parse and self-verify a serialized co-listen receipt."""
    try:
        artifact = CoListenOverlayArtifact.model_validate_json(path.read_bytes())
        verify_colisten_overlay(artifact)
    except (OSError, ValueError) as error:
        raise ListenBrainzOverlayError("co-listen receipt is invalid") from error
    return artifact


def certify_derived_review_overlay_sources(
    sources: DerivedReviewOverlaySources,
) -> CertifiedDerivedReviewOverlaySources:
    """Issue a wrapper only after receipt, bytes, schema, and counts verify."""
    verify_derived_review_overlay_sources(sources)
    return CertifiedDerivedReviewOverlaySources(sources, _CERTIFICATE)


def certify_colisten_overlay_sources(
    sources: CoListenOverlaySources,
) -> CertifiedCoListenOverlaySources:
    """Issue a wrapper only after receipt, bytes, schema, and counts verify."""
    verify_colisten_overlay_sources(sources)
    return CertifiedCoListenOverlaySources(sources, _CERTIFICATE)


def verify_derived_review_overlay_sources(sources: DerivedReviewOverlaySources) -> None:
    """Verify an immutable derived-review sidecar before any query is served."""
    verify_derived_review_overlay(sources.artifact)
    _verify_database_bytes(
        sources.database, sources.artifact.database_sha256, sources.artifact.database_bytes
    )
    with closing(connect_readonly(sources.database)) as database:
        _verify_sqlite(database, "derived-review overlay")
        _verify_review_counts(database, sources.artifact.coverage)


def verify_colisten_overlay_sources(sources: CoListenOverlaySources) -> None:
    """Verify an immutable aggregate co-listen sidecar before any query is served."""
    verify_colisten_overlay(sources.artifact)
    _verify_database_bytes(
        sources.database, sources.artifact.database_sha256, sources.artifact.database_bytes
    )
    with closing(connect_readonly(sources.database)) as database:
        _verify_sqlite(database, "co-listen overlay")
        _verify_colisten_counts(database, sources.artifact.coverage)


def _load_graph(
    database_path: Path, receipt_path: Path
) -> tuple[tuple[SidecarInput, SidecarInput], EvidenceGraphProjectionArtifact]:
    try:
        receipt = EvidenceGraphProjectionArtifact.model_validate_json(receipt_path.read_bytes())
        verify_evidence_graph_projection(receipt)
    except (OSError, ValueError) as error:
        raise ListenBrainzOverlayError("evidence graph receipt is invalid") from error
    graph_sha256, graph_bytes = sha256_file(database_path)
    if (graph_sha256, graph_bytes) != (receipt.database_sha256, receipt.database_bytes):
        raise ListenBrainzOverlayError("evidence graph database does not match its receipt")
    _verify_graph_schema(database_path)
    receipt_sha256, receipt_bytes = sha256_file(receipt_path)
    return (
        (
            SidecarInput(
                role="evidence_graph_database",
                locator=database_path.name,
                byte_sha256=graph_sha256,
                byte_count=graph_bytes,
                logical_sha256=receipt.database_sha256,
            ),
            SidecarInput(
                role="evidence_graph_receipt",
                locator=receipt_path.name,
                byte_sha256=receipt_sha256,
                byte_count=receipt_bytes,
                logical_sha256=receipt.output_sha256,
            ),
        ),
        receipt,
    )


def _load_propagation(
    artifact_path: Path, receipt_path: Path
) -> tuple[tuple[SidecarInput, SidecarInput], str, PropagationCoverage]:
    try:
        receipt = ListenBrainzPropagationReceipt.model_validate_json(receipt_path.read_bytes())
    except (OSError, ValueError) as error:
        raise ListenBrainzOverlayError("ListenBrainz propagation receipt is invalid") from error
    artifact_sha256, artifact_bytes = sha256_file(artifact_path)
    if (
        artifact_sha256 != receipt.artifact_sha256
        or receipt.artifact.sha256 != artifact_sha256
        or artifact_bytes != receipt.artifact.byte_size
    ):
        raise ListenBrainzOverlayError("propagation artifact does not match its receipt")
    if receipt.content_policy != "metadata_only_no_audio_or_historical_membership":
        raise ListenBrainzOverlayError("propagation receipt has an unsafe content policy")
    semantics = _single_root_value(artifact_path, "membership_semantics")
    output_sha256 = _single_root_value(artifact_path, "output_sha256")
    try:
        coverage = PropagationCoverage.model_validate(
            _single_root_object(artifact_path, "coverage")
        )
        settings = ListenBrainzPropagationSettings.model_validate(
            _single_root_object(artifact_path, "settings")
        )
    except ValueError as error:
        raise ListenBrainzOverlayError("propagation artifact has invalid typed fields") from error
    if semantics != "derived_review_evidence_not_factual_membership":
        raise ListenBrainzOverlayError("propagation artifact is not review-only evidence")
    if output_sha256 != receipt.logical_output_sha256:
        raise ListenBrainzOverlayError("propagation logical hash does not match its receipt")
    if settings.historical_input_used_for_construction or settings.audio_used_for_construction:
        raise ListenBrainzOverlayError("propagation artifact has unsafe construction inputs")
    receipt_sha256, receipt_bytes = sha256_file(receipt_path)
    return (
        (
            SidecarInput(
                role="listenbrainz_propagation_artifact",
                locator=artifact_path.name,
                byte_sha256=artifact_sha256,
                byte_count=artifact_bytes,
                logical_sha256=receipt.logical_output_sha256,
            ),
            SidecarInput(
                role="listenbrainz_propagation_receipt",
                locator=receipt_path.name,
                byte_sha256=receipt_sha256,
                byte_count=receipt_bytes,
                logical_sha256=receipt.logical_output_sha256,
            ),
        ),
        output_sha256,
        coverage,
    )


def _load_qualified_listenbrainz(path: Path, expected_sha256: str) -> SidecarInput:
    if len(expected_sha256) != _SHA256_LENGTH or any(
        char not in "0123456789abcdef" for char in expected_sha256
    ):
        raise ListenBrainzOverlayError("qualified ListenBrainz SHA-256 is malformed")
    actual_sha256, bytes_count = sha256_file(path)
    if actual_sha256 != expected_sha256:
        raise ListenBrainzOverlayError(
            "qualified ListenBrainz database does not match expected SHA-256"
        )
    with closing(connect_readonly(path)) as database:
        _verify_sqlite(database, "qualified ListenBrainz database")
        columns = {
            str(row[1]) for row in database.execute("PRAGMA table_info(artist_co_listen_evidence)")
        }
    required = {
        "left_artist_source_id",
        "right_artist_source_id",
        "window_start",
        "window_end",
        "distinct_user_count",
        "evidence_fingerprint",
    }
    if not required <= columns:
        raise ListenBrainzOverlayError("qualified ListenBrainz database schema is incompatible")
    with closing(connect_readonly(path)) as database:
        invalid = int(
            database.execute(
                """SELECT count(*) FROM artist_co_listen_evidence
                   WHERE window_start < 0 OR window_end <= window_start
                      OR distinct_user_count <= 0
                      OR length(evidence_fingerprint) != 64
                      OR evidence_fingerprint != lower(evidence_fingerprint)
                      OR evidence_fingerprint GLOB '*[^0-9a-f]*'"""
            ).fetchone()[0]
        )
        duplicate_fingerprints = int(
            database.execute(
                """SELECT count(*) - count(DISTINCT evidence_fingerprint)
                   FROM artist_co_listen_evidence"""
            ).fetchone()[0]
        )
    if invalid or duplicate_fingerprints:
        raise ListenBrainzOverlayError("qualified ListenBrainz aggregate rows are incompatible")
    return SidecarInput(
        role="qualified_listenbrainz_database",
        locator=path.name,
        byte_sha256=actual_sha256,
        byte_count=bytes_count,
        logical_sha256=actual_sha256,
    )


def _stream_candidates(path: Path) -> Iterator[PropagationCandidate]:
    with path.open("rb") as stream:
        for raw in ijson.items(stream, "candidates.item", use_float=True):
            try:
                yield PropagationCandidate.model_validate_json(canonical_json(raw))
            except ValueError as error:
                raise ListenBrainzOverlayError("propagation candidate is invalid") from error


def _parse_candidate(
    candidate: PropagationCandidate,
) -> tuple[str, str, str, str, str] | None:
    if not (
        candidate.artist_id.startswith(_ARTIST_PREFIX) and candidate.genre_id.startswith("legacy:")
    ):
        return None
    artist_mbid = candidate.artist_id.removeprefix(_ARTIST_PREFIX)
    stable_seed_id = candidate.genre_id.removeprefix("legacy:")
    try:
        if str(UUID(artist_mbid)) != artist_mbid:
            return None
    except ValueError:
        return None
    if not stable_seed_id.startswith("item"):
        return None
    paths_json = canonical_json([item.model_dump(mode="json") for item in candidate.paths]).decode()
    return candidate.artist_id, artist_mbid, candidate.genre_id, stable_seed_id, paths_json


def _single_root_value(path: Path, prefix: str) -> str:
    with path.open("rb") as stream:
        values = ijson.items(stream, prefix, use_float=True)
        try:
            value = next(values)
        except StopIteration as error:
            raise ListenBrainzOverlayError(f"propagation artifact lacks {prefix}") from error
        if next(values, None) is not None or not isinstance(value, str):
            raise ListenBrainzOverlayError(f"propagation artifact has invalid {prefix}")
        return value


def _single_root_object(path: Path, prefix: str) -> object:
    with path.open("rb") as stream:
        values = ijson.items(stream, prefix, use_float=True)
        try:
            value = next(values)
        except StopIteration as error:
            raise ListenBrainzOverlayError(f"propagation artifact lacks {prefix}") from error
        if next(values, None) is not None:
            raise ListenBrainzOverlayError(f"propagation artifact repeats {prefix}")
    return value


def _temporary_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.{uuid4().hex}.partial")


def _insert_inputs(database: sqlite3.Connection, inputs: tuple[SidecarInput, ...]) -> None:
    database.executemany(
        """INSERT INTO artifact_input(role, locator, byte_sha256, byte_count, logical_sha256)
           VALUES (?, ?, ?, ?, ?)""",
        (
            (item.role, item.locator, item.byte_sha256, item.byte_count, item.logical_sha256)
            for item in inputs
        ),
    )


def _attach_readonly(database: sqlite3.Connection, alias: str, path: Path) -> None:
    database.execute(f"ATTACH DATABASE ? AS {alias}", (f"file:{path.resolve()}?mode=ro&immutable=1",))


def _materialize_review_candidates(
    database: sqlite3.Connection,
    graph_path: Path,
    propagation_output_sha256: str,
    stats: _ReviewStreamStats,
) -> ReviewCandidateCoverage:
    _attach_readonly(database, "graph_source", graph_path)
    valid_count = int(database.execute("SELECT count(*) FROM raw_candidate").fetchone()[0])
    database.execute(
        """INSERT INTO review_candidate(
               artist_mbid, artist_source_id, stable_seed_id, legacy_seed_id, score, genre_rank,
               paths_json, propagation_provenance_ref
           )
           SELECT raw.artist_mbid, raw.artist_source_id, raw.stable_seed_id, raw.legacy_seed_id,
                  raw.score, raw.genre_rank, raw.paths_json,
                  ? || ':' || raw.artist_source_id || ':' || raw.legacy_seed_id
             FROM raw_candidate AS raw
             JOIN graph_source.identity AS artist
               ON artist.namespace = 'musicbrainz_artist' AND artist.identifier = raw.artist_mbid
             JOIN graph_source.identity AS seed
               ON seed.namespace = 'stable_seed' AND seed.identifier = raw.stable_seed_id
            ORDER BY raw.stable_seed_id, raw.genre_rank, raw.artist_mbid""",
        (f"listenbrainz-propagation:{propagation_output_sha256}",),
    )
    retained_count = int(database.execute("SELECT count(*) FROM review_candidate").fetchone()[0])
    missing_seed_count = int(
        database.execute(
            """SELECT count(*) FROM raw_candidate AS raw
               LEFT JOIN graph_source.identity AS seed
                 ON seed.namespace = 'stable_seed' AND seed.identifier = raw.stable_seed_id
               WHERE seed.identifier IS NULL"""
        ).fetchone()[0]
    )
    missing_artist_count = int(
        database.execute(
            """SELECT count(*) FROM raw_candidate AS raw
               JOIN graph_source.identity AS seed
                 ON seed.namespace = 'stable_seed' AND seed.identifier = raw.stable_seed_id
               LEFT JOIN graph_source.identity AS artist
                 ON artist.namespace = 'musicbrainz_artist' AND artist.identifier = raw.artist_mbid
               WHERE artist.identifier IS NULL"""
        ).fetchone()[0]
    )
    if valid_count + stats.invalid_identifier_count != stats.source_candidate_count:
        raise ListenBrainzOverlayError("review source candidate count does not replay")
    return ReviewCandidateCoverage(
        source_candidate_count=stats.source_candidate_count,
        retained_candidate_count=retained_count,
        abstained_artist_not_in_graph_count=missing_artist_count,
        rejected_stable_seed_not_in_graph_count=missing_seed_count,
        rejected_invalid_identifier_count=stats.invalid_identifier_count,
        candidate_artist_count=stats.candidate_artist_count,
        candidate_seed_count=stats.candidate_seed_count,
    )


def _materialize_colistens(
    database: sqlite3.Connection,
    graph_path: Path,
    qualified_path: Path,
    qualified_sha256: str,
    privacy_threshold: int,
) -> CoListenCoverage:
    _attach_readonly(database, "graph_source", graph_path)
    _attach_readonly(database, "listenbrainz_source", qualified_path)
    database.create_function("is_canonical_uuid", 1, _is_canonical_uuid, deterministic=True)
    source_rows = int(
        database.execute(
            "SELECT count(*) FROM listenbrainz_source.artist_co_listen_evidence"
        ).fetchone()[0]
    )
    noncanonical = int(
        database.execute(
            """SELECT count(*) FROM listenbrainz_source.artist_co_listen_evidence AS row
               WHERE NOT (
                   row.left_artist_source_id GLOB
                       'musicbrainz:artist:????????-????-????-????-????????????'
                   AND row.right_artist_source_id GLOB
                       'musicbrainz:artist:????????-????-????-????-????????????'
                   AND row.left_artist_source_id < row.right_artist_source_id
                   AND is_canonical_uuid(substr(row.left_artist_source_id, 20)) = 1
                   AND is_canonical_uuid(substr(row.right_artist_source_id, 20)) = 1
               )"""
        ).fetchone()[0]
    )
    below_threshold = int(
        database.execute(
            """SELECT count(*) FROM listenbrainz_source.artist_co_listen_evidence AS row
                WHERE row.left_artist_source_id GLOB
                          'musicbrainz:artist:????????-????-????-????-????????????'
                  AND row.right_artist_source_id GLOB
                          'musicbrainz:artist:????????-????-????-????-????????????'
                  AND row.left_artist_source_id < row.right_artist_source_id
                  AND is_canonical_uuid(substr(row.left_artist_source_id, 20)) = 1
                  AND is_canonical_uuid(substr(row.right_artist_source_id, 20)) = 1
                  AND row.distinct_user_count < ?""",
            (privacy_threshold,),
        ).fetchone()[0]
    )
    outside_graph = int(
        database.execute(
            """SELECT count(*) FROM listenbrainz_source.artist_co_listen_evidence AS row
                LEFT JOIN graph_source.identity AS left_artist
                  ON left_artist.namespace = 'musicbrainz_artist'
                 AND left_artist.identifier = substr(row.left_artist_source_id, 20)
                LEFT JOIN graph_source.identity AS right_artist
                  ON right_artist.namespace = 'musicbrainz_artist'
                 AND right_artist.identifier = substr(row.right_artist_source_id, 20)
               WHERE row.left_artist_source_id GLOB
                         'musicbrainz:artist:????????-????-????-????-????????????'
                 AND row.right_artist_source_id GLOB
                         'musicbrainz:artist:????????-????-????-????-????????????'
                 AND row.left_artist_source_id < row.right_artist_source_id
                 AND is_canonical_uuid(substr(row.left_artist_source_id, 20)) = 1
                 AND is_canonical_uuid(substr(row.right_artist_source_id, 20)) = 1
                 AND row.distinct_user_count >= ?
                 AND (left_artist.identifier IS NULL OR right_artist.identifier IS NULL)""",
            (privacy_threshold,),
        ).fetchone()[0]
    )
    database.execute(
        """INSERT INTO colisten_relation(
                left_artist_mbid, right_artist_mbid, window_start, window_end,
                distinct_user_count, evidence_fingerprint, source_binding, source_provenance_ref
            )
            SELECT substr(row.left_artist_source_id, 20), substr(row.right_artist_source_id, 20),
                   row.window_start, row.window_end, row.distinct_user_count,
                   row.evidence_fingerprint, ?,
                   'listenbrainz:aggregate:' || row.evidence_fingerprint
              FROM listenbrainz_source.artist_co_listen_evidence AS row
              JOIN graph_source.identity AS left_artist
                ON left_artist.namespace = 'musicbrainz_artist'
               AND left_artist.identifier = substr(row.left_artist_source_id, 20)
              JOIN graph_source.identity AS right_artist
                ON right_artist.namespace = 'musicbrainz_artist'
               AND right_artist.identifier = substr(row.right_artist_source_id, 20)
             WHERE row.left_artist_source_id GLOB
                       'musicbrainz:artist:????????-????-????-????-????????????'
               AND row.right_artist_source_id GLOB
                       'musicbrainz:artist:????????-????-????-????-????????????'
               AND row.left_artist_source_id < row.right_artist_source_id
               AND is_canonical_uuid(substr(row.left_artist_source_id, 20)) = 1
               AND is_canonical_uuid(substr(row.right_artist_source_id, 20)) = 1
               AND row.distinct_user_count >= ?
             ORDER BY row.left_artist_source_id, row.right_artist_source_id,
                      row.window_start, row.evidence_fingerprint""",
        (
            f"listenbrainz-qualified:{qualified_sha256}",
            privacy_threshold,
        ),
    )
    retained = int(database.execute("SELECT count(*) FROM colisten_relation").fetchone()[0])
    return CoListenCoverage(
        source_row_count=source_rows,
        retained_relation_count=retained,
        abstained_endpoint_not_in_graph_count=outside_graph,
        rejected_below_privacy_threshold_count=below_threshold,
        rejected_noncanonical_endpoint_count=noncanonical,
        retained_artist_count=int(
            database.execute(
                """SELECT count(*) FROM (
                       SELECT left_artist_mbid AS artist_mbid FROM colisten_relation
                       UNION
                       SELECT right_artist_mbid AS artist_mbid FROM colisten_relation
                   )"""
            ).fetchone()[0]
        ),
    )


def _review_schema(database: sqlite3.Connection) -> None:
    database.executescript(
        """PRAGMA journal_mode=OFF;
PRAGMA synchronous=OFF;
PRAGMA temp_store=MEMORY;
PRAGMA foreign_keys=ON;
CREATE TABLE artifact_input(
role TEXT PRIMARY KEY NOT NULL, locator TEXT NOT NULL, byte_sha256 TEXT NOT NULL,
byte_count INTEGER NOT NULL, logical_sha256 TEXT NOT NULL) WITHOUT ROWID;
CREATE TABLE raw_candidate(
artist_source_id TEXT NOT NULL, artist_mbid TEXT NOT NULL, legacy_seed_id TEXT NOT NULL,
stable_seed_id TEXT NOT NULL, score REAL NOT NULL CHECK(score > 0 AND score <= 1),
genre_rank INTEGER NOT NULL CHECK(genre_rank >= 1), paths_json TEXT NOT NULL,
PRIMARY KEY(artist_source_id, legacy_seed_id)) WITHOUT ROWID;
CREATE TABLE review_candidate(
artist_mbid TEXT NOT NULL, artist_source_id TEXT NOT NULL, stable_seed_id TEXT NOT NULL,
legacy_seed_id TEXT NOT NULL, score REAL NOT NULL CHECK(score > 0 AND score <= 1),
genre_rank INTEGER NOT NULL CHECK(genre_rank >= 1), paths_json TEXT NOT NULL,
propagation_provenance_ref TEXT NOT NULL,
PRIMARY KEY(artist_mbid, stable_seed_id)) WITHOUT ROWID;
CREATE INDEX review_candidate_seed_rank
ON review_candidate(stable_seed_id, genre_rank, artist_mbid);
CREATE INDEX review_candidate_artist_seed ON review_candidate(artist_mbid, stable_seed_id);
"""
    )


def _colisten_schema(database: sqlite3.Connection) -> None:
    database.executescript(
        """PRAGMA journal_mode=OFF;
PRAGMA synchronous=OFF;
PRAGMA temp_store=MEMORY;
PRAGMA foreign_keys=ON;
CREATE TABLE artifact_input(
role TEXT PRIMARY KEY NOT NULL, locator TEXT NOT NULL, byte_sha256 TEXT NOT NULL,
byte_count INTEGER NOT NULL, logical_sha256 TEXT NOT NULL) WITHOUT ROWID;
CREATE TABLE colisten_relation(
left_artist_mbid TEXT NOT NULL, right_artist_mbid TEXT NOT NULL,
window_start INTEGER NOT NULL CHECK(window_start >= 0),
window_end INTEGER NOT NULL CHECK(window_end > window_start),
distinct_user_count INTEGER NOT NULL CHECK(distinct_user_count > 0),
evidence_fingerprint TEXT PRIMARY KEY NOT NULL,
source_binding TEXT NOT NULL, source_provenance_ref TEXT NOT NULL,
CHECK(left_artist_mbid < right_artist_mbid)) WITHOUT ROWID;
CREATE INDEX colisten_relation_left ON colisten_relation(left_artist_mbid, window_start);
CREATE INDEX colisten_relation_right ON colisten_relation(right_artist_mbid, window_start);
"""
    )


def _verify_graph_schema(path: Path) -> None:
    with closing(connect_readonly(path)) as database:
        _verify_sqlite(database, "evidence graph")
        columns = {str(row[1]) for row in database.execute("PRAGMA table_info(identity)")}
    if not {"namespace", "identifier"} <= columns:
        raise ListenBrainzOverlayError("evidence graph schema is incompatible")


def _verify_sqlite(database: sqlite3.Connection, label: str) -> None:
    database.execute("PRAGMA query_only = ON")
    if database.execute("PRAGMA integrity_check").fetchone() != ("ok",):
        raise ListenBrainzOverlayError(f"{label} integrity check failed")
    if database.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ListenBrainzOverlayError(f"{label} foreign key check failed")


def _verify_database_bytes(path: Path, expected_sha256: str, expected_bytes: int) -> None:
    if sha256_file(path) != (expected_sha256, expected_bytes):
        raise ListenBrainzOverlayError("sidecar database does not match receipt")


def _is_canonical_uuid(value: object) -> int:
    if not isinstance(value, str):
        return 0
    try:
        return int(str(UUID(value)) == value)
    except ValueError:
        return 0


def _verify_review_counts(database: sqlite3.Connection, coverage: ReviewCandidateCoverage) -> None:
    row_count = int(database.execute("SELECT count(*) FROM review_candidate").fetchone()[0])
    if row_count != coverage.retained_candidate_count:
        raise ListenBrainzOverlayError("derived-review sidecar rows do not match receipt")
    schema = {str(row[1]) for row in database.execute("PRAGMA table_info(review_candidate)")}
    if (
        not {
            "artist_mbid",
            "stable_seed_id",
            "score",
            "paths_json",
            "propagation_provenance_ref",
        }
        <= schema
    ):
        raise ListenBrainzOverlayError("derived-review sidecar schema is incompatible")


def _verify_colisten_counts(database: sqlite3.Connection, coverage: CoListenCoverage) -> None:
    row_count = int(database.execute("SELECT count(*) FROM colisten_relation").fetchone()[0])
    if row_count != coverage.retained_relation_count:
        raise ListenBrainzOverlayError("co-listen sidecar rows do not match receipt")
    schema = {str(row[1]) for row in database.execute("PRAGMA table_info(colisten_relation)")}
    if (
        not {
            "left_artist_mbid",
            "right_artist_mbid",
            "window_start",
            "window_end",
            "distinct_user_count",
            "evidence_fingerprint",
            "source_binding",
        }
        <= schema
    ):
        raise ListenBrainzOverlayError("co-listen sidecar schema is incompatible")
