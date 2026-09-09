"""Publish a verified public model artifact into the serving catalog."""

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from pydantic import Field

from musix.db import Database
from musix.serving.metadata.metadata_links import metadata_url
from musix.ml.public_graph import public_model_output_sha256
from musix.models import FrozenModel
from musix.models.modeling import LayoutLens, PublicModelArtifact
from musix.types import Sha256, SourceId

MODEL_KEY = "public-graph"
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
LAYOUT_SCALE = 1_000.0
_QID = re.compile(r"^Q[1-9][0-9]*$")
_MBID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class PublicModelPublishError(RuntimeError):
    """Report an artifact, identity, or policy that cannot be published safely."""


def resolve_public_policy_id(database_path: Path, source_key: SourceId) -> int:
    """Resolve one sealed public manifest policy by its exact source identity."""
    with closing(
        sqlite3.connect(f"file:{database_path.resolve()}?mode=ro", uri=True)
    ) as connection:
        row = connection.execute(
            """SELECT source.default_policy_id, source.acquisition_kind,
                      policy.policy_key, policy.classification, policy.local_only
               FROM data_sources AS source
               JOIN rights_policies AS policy ON policy.id = source.default_policy_id
               JOIN rights_policy_seals AS seal ON seal.policy_id = policy.id
               WHERE source.source_key = ?""",
            (source_key,),
        ).fetchone()
    if row is None:
        raise PublicModelPublishError(f"no sealed policy for public source {source_key!r}")
    policy_id, acquisition_kind, policy_key, classification, local_only = row
    expected_policy = re.fullmatch(
        rf"manifest:{re.escape(source_key)}:[0-9a-f]{{64}}", str(policy_key)
    )
    if (
        acquisition_kind not in {"public_download", "public_api"}
        or classification not in {"public_domain", "open_license"}
        or int(local_only) != 0
        or expected_policy is None
    ):
        raise PublicModelPublishError(
            f"source {source_key!r} does not own an eligible public manifest policy"
        )
    return int(policy_id)


class PublishedLensSummary(FrozenModel):
    """Report one layout lens selected by a public model publish."""

    layout_key: str
    layout_revision: int = Field(gt=0)
    coordinate_genres: int = Field(ge=0)


class PublicModelPublishSummary(FrozenModel):
    """Report the exact serving projections selected by one publish operation."""

    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    layouts: tuple[PublishedLensSummary, ...] = Field(min_length=4, max_length=4)
    representative_items: int = Field(ge=0)
    profile_memberships: int = Field(ge=0)
    neighbor_rows: int = Field(ge=0)
    duplicate: bool


class PublicModelExplainabilitySummary(FrozenModel):
    """Report persisted explanation rows for one already-published logical model."""

    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_memberships: int = Field(ge=0)
    neighbor_rows: int = Field(ge=0)


class LoadedPublicModel(FrozenModel):
    """Carry one bounded parse together with its exact file identity."""

    artifact: PublicModelArtifact
    artifact_sha256: Sha256
    byte_size: int = Field(gt=0)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def load_public_model(path: Path) -> LoadedPublicModel:
    """Parse one bounded JSON artifact and verify its stable logical hash."""
    with path.open("rb") as stream:
        payload = stream.read(MAX_ARTIFACT_BYTES + 1)
    if len(payload) > MAX_ARTIFACT_BYTES:
        raise PublicModelPublishError(
            f"public model artifact exceeds the {MAX_ARTIFACT_BYTES} byte limit"
        )
    if not payload:
        raise PublicModelPublishError("public model artifact is empty")
    artifact = PublicModelArtifact.model_validate_json(payload)
    calculated = public_model_output_sha256(artifact)
    if calculated != artifact.output_sha256:
        raise PublicModelPublishError("public model logical output hash does not match payload")
    if not artifact.export_allowed:
        raise PublicModelPublishError("public serving requires an exportable model artifact")
    return LoadedPublicModel(
        artifact=artifact,
        artifact_sha256=hashlib.sha256(payload).hexdigest(),
        byte_size=len(payload),
    )


def _input_provenance(
    connection: sqlite3.Connection,
    artifact: PublicModelArtifact,
) -> tuple[tuple[int, int], ...]:
    """Resolve every declared input by exact source key and content hash."""
    result: list[tuple[int, int]] = []
    for source_artifact in artifact.artifacts:
        source_key, separator, declared_hash = source_artifact.artifact_key.rpartition(":")
        if separator != ":" or declared_hash != source_artifact.content_sha256 or not source_key:
            raise PublicModelPublishError("public input artifact key must end in its exact SHA256")
        rows = connection.execute(
            """SELECT DISTINCT provenance.id, artifact.id
               FROM provenance_records AS provenance
               JOIN data_sources AS source ON source.id = provenance.source_id
               JOIN source_snapshots AS snapshot ON snapshot.source_id = source.id
                AND snapshot.snapshot_ref = provenance.snapshot_ref
               JOIN source_artifacts AS artifact
                 ON artifact.snapshot_id = snapshot.id
                AND artifact.sha256 = provenance.artifact_sha256
               JOIN active_rights_policy_permissions AS provenance_export
                 ON provenance_export.policy_id = provenance.policy_id
                AND provenance_export.use_kind = 'export'
                AND provenance_export.decision = 'allow'
               JOIN active_rights_policy_permissions AS artifact_export
                 ON artifact_export.policy_id = artifact.policy_id
                AND artifact_export.use_kind = 'export'
                AND artifact_export.decision = 'allow'
               WHERE source.source_key = ?
                 AND snapshot.snapshot_ref = ?
                 AND provenance.artifact_sha256 = ?
               ORDER BY provenance.id, artifact.id""",
            (source_key, source_artifact.snapshot, source_artifact.content_sha256),
        ).fetchall()
        if not rows:
            raise PublicModelPublishError(
                f"public input has no exact exportable provenance: {source_artifact.artifact_key}"
            )
        result.extend((int(row[0]), int(row[1])) for row in rows)
    return tuple(dict.fromkeys(result))


def _derived_output(
    connection: sqlite3.Connection,
    loaded: LoadedPublicModel,
    policy_id: int,
    provenance: tuple[tuple[int, int], ...],
) -> int:
    artifact = loaded.artifact
    existing = connection.execute(
        """SELECT id, content_sha256, policy_id FROM derived_outputs
           WHERE output_kind = 'public_model' AND output_ref = ?""",
        (artifact.output_sha256,),
    ).fetchone()
    if existing is not None:
        if str(existing[1]) != loaded.artifact_sha256 or int(existing[2]) != policy_id:
            raise PublicModelPublishError("existing public model derived output does not match")
        output_id = int(existing[0])
    else:
        cursor = connection.execute(
            """INSERT INTO derived_outputs
               (output_kind, output_ref, content_sha256, policy_id, created_at)
               VALUES ('public_model', ?, ?, ?, ?)""",
            (artifact.output_sha256, loaded.artifact_sha256, policy_id, _now()),
        )
        if cursor.lastrowid is None:
            raise RuntimeError("derived output insert returned no row ID")
        output_id = cursor.lastrowid
        connection.execute(
            """INSERT INTO derived_output_events
               (derived_output_id, event_kind, event_at, reason)
               VALUES (?, 'created', ?, 'verified public model publication')""",
            (output_id, _now()),
        )
    connection.executemany(
        """INSERT OR IGNORE INTO derivation_edges
           (parent_kind, parent_ref, child_output_id) VALUES ('provenance', ?, ?)""",
        ((str(provenance_id), output_id) for provenance_id, _artifact_id in provenance),
    )
    return output_id


def _genre_reference(value: str) -> tuple[str, str]:
    try:
        namespace, kind, identifier = value.split(":", maxsplit=2)
    except ValueError as error:
        raise PublicModelPublishError(f"invalid genre reference: {value}") from error
    if kind != "genre":
        raise PublicModelPublishError(f"model genre reference has kind {kind}: {value}")
    if namespace == "wikidata" and _QID.fullmatch(identifier):
        return namespace, identifier
    if namespace == "musicbrainz" and _MBID.fullmatch(identifier):
        return namespace, identifier
    raise PublicModelPublishError(f"unsupported genre reference: {value}")


def _resolve_genre(
    connection: sqlite3.Connection,
    source_ref: str,
) -> int:
    namespace, identifier = _genre_reference(source_ref)
    rows = connection.execute(
        """SELECT DISTINCT identifier.entity_id
           FROM entity_identifiers AS identifier
           JOIN catalog_entities AS entity ON entity.id = identifier.entity_id
           WHERE entity.entity_kind = 'genre'
             AND identifier.namespace = ? AND identifier.normalized_value = ?
           ORDER BY identifier.entity_id
           LIMIT 2""",
        (namespace, identifier),
    ).fetchall()
    if len(rows) != 1:
        raise PublicModelPublishError(
            f"genre reference must resolve exactly once: {source_ref} resolved {len(rows)} times"
        )
    return int(rows[0][0])


def _policy_allows_public_serving(connection: sqlite3.Connection, policy_id: int) -> None:
    permissions = {
        str(row[0]): str(row[1])
        for row in connection.execute(
            """SELECT use_kind, decision FROM active_rights_policy_permissions
               WHERE policy_id = ? AND use_kind IN ('display', 'export')""",
            (policy_id,),
        )
    }
    if permissions != {"display": "allow", "export": "allow"}:
        raise PublicModelPublishError(f"policy {policy_id} must actively allow display and export")


def _model_run(
    connection: sqlite3.Connection,
    artifact: PublicModelArtifact,
    policy_id: int,
    artifact_sha256: Sha256,
    derived_output_id: int,
) -> tuple[int, bool]:
    existing = connection.execute(
        """SELECT id, policy_id, artifact_sha256, derived_output_id
           FROM public_model_runs WHERE output_sha256 = ?""",
        (artifact.output_sha256,),
    ).fetchone()
    if existing is not None:
        if (
            int(existing[1]) != policy_id
            or str(existing[2]) != artifact_sha256
            or int(existing[3]) != derived_output_id
        ):
            raise PublicModelPublishError(
                "an existing model output cannot be republished under a different policy"
            )
        return int(existing[0]), True
    revision_row = connection.execute(
        "SELECT coalesce(max(revision), 0) + 1 FROM public_model_runs WHERE model_key = ?",
        (MODEL_KEY,),
    ).fetchone()
    if revision_row is None:
        raise RuntimeError("public model revision query returned no row")
    cursor = connection.execute(
        """INSERT INTO public_model_runs
           (model_key, revision, model_revision, input_sha256, settings_sha256,
            output_sha256, artifact_sha256, export_allowed, policy_id,
            derived_output_id, published_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
        (
            MODEL_KEY,
            int(revision_row[0]),
            artifact.revision,
            artifact.input_sha256,
            artifact.settings_sha256,
            artifact.output_sha256,
            artifact_sha256,
            policy_id,
            derived_output_id,
            _now(),
        ),
    )
    if cursor.lastrowid is None:
        raise RuntimeError("public model insert returned no row ID")
    return cursor.lastrowid, False


def _layout_run(
    connection: sqlite3.Connection,
    artifact: PublicModelArtifact,
    lens: LayoutLens,
    policy_id: int,
    genre_ids: dict[str, int],
) -> tuple[int, int]:
    algorithm_key = f"public_graph_{lens.method}"
    parameters = json.dumps(
        {
            "coordinate_scale": LAYOUT_SCALE,
            "semantic_axes": False,
            "source_model_output_sha256": artifact.output_sha256,
            "lens_input_sha256": lens.input_sha256,
            "lens_output_sha256": lens.output_sha256,
            "input_kind": lens.input_kind,
            "metric": lens.metric,
            "seed": lens.seed,
            "quality": lens.quality.model_dump(mode="json"),
            "stability": lens.stability.model_dump(mode="json"),
            "community": lens.community.model_dump(mode="json")
            if lens.community is not None
            else None,
            "resources": lens.resources.model_dump(mode="json"),
            "unplaced": [item.model_dump(mode="json") for item in lens.unplaced],
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    existing = connection.execute(
        """SELECT id, revision, algorithm_revision, parameters_json, policy_id
           FROM layout_runs
           WHERE layout_key = ? AND algorithm_key = ?
             AND input_fingerprint = ?""",
        (lens.layout_key, algorithm_key, artifact.output_sha256),
    ).fetchone()
    if existing is not None:
        if (
            str(existing[2]) != lens.method_version
            or str(existing[3]) != parameters
            or int(existing[4]) != policy_id
        ):
            raise PublicModelPublishError("existing public layout run does not match artifact")
        return int(existing[0]), int(existing[1])
    revision_row = connection.execute(
        "SELECT coalesce(max(revision), 0) + 1 FROM layout_runs WHERE layout_key = ?",
        (lens.layout_key,),
    ).fetchone()
    if revision_row is None:
        raise RuntimeError("layout revision query returned no row")
    revision = int(revision_row[0])
    cursor = connection.execute(
        """INSERT INTO layout_runs
           (layout_key, revision, algorithm_key, algorithm_revision, parameters_json,
            input_fingerprint, status, policy_id, completed_at)
           VALUES (?, ?, ?, ?, ?, ?, 'complete', ?, ?)""",
        (
            lens.layout_key,
            revision,
            algorithm_key,
            lens.method_version,
            parameters,
            artifact.output_sha256,
            policy_id,
            _now(),
        ),
    )
    if cursor.lastrowid is None:
        raise RuntimeError("layout run insert returned no row ID")
    run_id = cursor.lastrowid
    direct_sizes = {
        profile.genre_id: len(profile.memberships)
        for profile in artifact.profiles
        if profile.profile_kind == "direct"
    }
    connection.executemany(
        """INSERT INTO layout_points
           (layout_run_id, entity_id, x, y, display_weight, metadata_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            (
                run_id,
                genre_ids[item.genre_id],
                float(item.x) * LAYOUT_SCALE,
                float(item.y) * LAYOUT_SCALE,
                float(direct_sizes.get(item.genre_id, 1)),
                json.dumps({"component": item.component}, separators=(",", ":")),
            )
            for item in lens.coordinates
        ),
    )
    return run_id, revision


def _link_layout(
    connection: sqlite3.Connection,
    model_run_id: int,
    layout_run_id: int,
    lens: LayoutLens,
) -> None:
    connection.execute(
        """INSERT OR IGNORE INTO public_model_layouts
           (model_run_id, lens_key, layout_run_id, lens_input_sha256,
            lens_output_sha256, is_default)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            model_run_id,
            lens.layout_key,
            layout_run_id,
            lens.input_sha256,
            lens.output_sha256,
            int(lens.is_default),
        ),
    )
    row = connection.execute(
        """SELECT layout_run_id, lens_input_sha256, lens_output_sha256, is_default
           FROM public_model_layouts WHERE model_run_id = ? AND lens_key = ?""",
        (model_run_id, lens.layout_key),
    ).fetchone()
    expected = (
        layout_run_id,
        lens.input_sha256,
        lens.output_sha256,
        int(lens.is_default),
    )
    if row is None or tuple(row) != expected:
        raise PublicModelPublishError("existing public model layout does not match artifact")


def _persist_explainability(
    connection: sqlite3.Connection,
    artifact: PublicModelArtifact,
    model_run_id: int,
    genre_ids: dict[str, int],
) -> PublicModelExplainabilitySummary:
    """Persist the logical model's profile components and ranked neighbors once."""
    connection.executemany(
        """INSERT OR IGNORE INTO public_genre_profile_memberships
           (model_run_id, genre_id, profile_kind, source_artist_ref, score,
            evidence_refs_json, components_json)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            (
                model_run_id,
                genre_ids[profile.genre_id],
                profile.profile_kind,
                membership.artist_id,
                float(membership.score),
                json.dumps(membership.evidence_refs, separators=(",", ":")),
                json.dumps(
                    [component.model_dump(mode="json") for component in membership.components],
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            )
            for profile in artifact.profiles
            for membership in profile.memberships
        ),
    )
    connection.executemany(
        """INSERT OR IGNORE INTO public_genre_neighbors
           (model_run_id, genre_id, neighbor_genre_id, profile_kind, metric,
            score, shared_artist_count, rank)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            (
                model_run_id,
                genre_ids[item.genre_id],
                genre_ids[item.neighbor_genre_id],
                item.profile_kind,
                item.metric,
                float(item.score),
                item.shared_artist_count,
                item.rank,
            )
            for item in artifact.neighbors
        ),
    )
    profile_memberships = connection.execute(
        "SELECT count(*) FROM public_genre_profile_memberships WHERE model_run_id = ?",
        (model_run_id,),
    ).fetchone()
    neighbor_rows = connection.execute(
        "SELECT count(*) FROM public_genre_neighbors WHERE model_run_id = ?",
        (model_run_id,),
    ).fetchone()
    if profile_memberships is None or neighbor_rows is None:
        raise RuntimeError("persisted public explanation counts could not be read")
    expected_profiles = sum(len(profile.memberships) for profile in artifact.profiles)
    if int(profile_memberships[0]) != expected_profiles or int(neighbor_rows[0]) != len(
        artifact.neighbors
    ):
        raise PublicModelPublishError("persisted public explanation rows do not match artifact")
    return PublicModelExplainabilitySummary(
        output_sha256=artifact.output_sha256,
        profile_memberships=int(profile_memberships[0]),
        neighbor_rows=int(neighbor_rows[0]),
    )


def project_public_model_explainability(
    database_path: Path,
    artifact_path: Path,
) -> PublicModelExplainabilitySummary:
    """Add serving projections to an existing model selected by its logical hash."""
    loaded = load_public_model(artifact_path)
    database = Database(database_path)
    database.initialize()
    with database.connect() as connection, connection:
        row = connection.execute(
            "SELECT id FROM public_model_runs WHERE output_sha256 = ?",
            (loaded.artifact.output_sha256,),
        ).fetchone()
        if row is None:
            raise PublicModelPublishError("public model output has not been published")
        genre_ids = {
            genre.genre_id: _resolve_genre(connection, genre.genre_id)
            for genre in loaded.artifact.genres
        }
        return _persist_explainability(
            connection,
            loaded.artifact,
            int(row[0]),
            genre_ids,
        )


def publish_public_model(
    database_path: Path,
    artifact_path: Path,
    *,
    policy_id: int,
) -> PublicModelPublishSummary:
    """Verify and atomically select one public model for map and detail serving."""
    loaded = load_public_model(artifact_path)
    artifact = loaded.artifact
    database = Database(database_path)
    database.initialize()
    with database.connect() as connection, connection:
        _policy_allows_public_serving(connection, policy_id)
        provenance = _input_provenance(connection, artifact)
        derived_output_id = _derived_output(connection, loaded, policy_id, provenance)
        genre_ids = {
            genre.genre_id: _resolve_genre(connection, genre.genre_id) for genre in artifact.genres
        }
        model_run_id, duplicate = _model_run(
            connection,
            artifact,
            policy_id,
            loaded.artifact_sha256,
            derived_output_id,
        )
        connection.executemany(
            """INSERT OR IGNORE INTO public_model_input_provenance
               (model_run_id, provenance_id, artifact_id) VALUES (?, ?, ?)""",
            (
                (model_run_id, provenance_id, source_artifact_id)
                for provenance_id, source_artifact_id in provenance
            ),
        )
        connection.executemany(
            """INSERT OR IGNORE INTO public_genre_names
               (model_run_id, genre_id, source_genre_ref, display_name, evidence_refs_json)
               VALUES (?, ?, ?, ?, ?)""",
            (
                (
                    model_run_id,
                    genre_ids[item.genre_id],
                    item.genre_id,
                    item.name,
                    json.dumps(item.evidence_refs, separators=(",", ":")),
                )
                for item in artifact.genres
            ),
        )
        explanation = _persist_explainability(connection, artifact, model_run_id, genre_ids)
        layout_summaries: list[PublishedLensSummary] = []
        layout_runs: list[tuple[str, int]] = []
        for lens in artifact.layouts:
            layout_run_id, layout_revision = _layout_run(
                connection,
                artifact,
                lens,
                policy_id,
                genre_ids,
            )
            _link_layout(connection, model_run_id, layout_run_id, lens)
            layout_runs.append((lens.layout_key, layout_run_id))
            layout_summaries.append(
                PublishedLensSummary(
                    layout_key=lens.layout_key,
                    layout_revision=layout_revision,
                    coordinate_genres=len(lens.coordinates),
                )
            )
        for item in artifact.representatives:
            if metadata_url(item.entity_kind, item.entity_id) is None:
                raise PublicModelPublishError(
                    f"unsupported representative reference: {item.entity_id}"
                )
        connection.executemany(
            """INSERT OR IGNORE INTO public_genre_representatives
               (model_run_id, genre_id, entity_kind, source_entity_ref, display_name,
                rank, direct_evidence_value, source_count, evidence_refs_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                (
                    model_run_id,
                    genre_ids[item.genre_id],
                    item.entity_kind,
                    item.entity_id,
                    item.name,
                    item.rank,
                    float(item.direct_evidence_value),
                    item.source_count,
                    json.dumps(item.evidence_refs, separators=(",", ":")),
                )
                for item in artifact.representatives
            ),
        )
        connection.execute(
            """INSERT INTO current_public_models (model_key, model_run_id)
               VALUES (?, ?)
               ON CONFLICT(model_key) DO UPDATE SET
                   model_run_id = excluded.model_run_id,
                   selected_at = excluded.selected_at
               WHERE current_public_models.model_run_id != excluded.model_run_id""",
            (MODEL_KEY, model_run_id),
        )
        connection.executemany(
            """INSERT INTO current_layouts (layout_key, layout_run_id)
               VALUES (?, ?)
               ON CONFLICT(layout_key) DO UPDATE SET
                   layout_run_id = excluded.layout_run_id,
                   selected_at = excluded.selected_at
               WHERE current_layouts.layout_run_id != excluded.layout_run_id""",
            layout_runs,
        )
    return PublicModelPublishSummary(
        output_sha256=artifact.output_sha256,
        layouts=tuple(layout_summaries),
        representative_items=len(artifact.representatives),
        profile_memberships=explanation.profile_memberships,
        neighbor_rows=explanation.neighbor_rows,
        duplicate=duplicate,
    )
