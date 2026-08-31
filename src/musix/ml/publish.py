"""Publish a verified public model artifact into the serving catalog."""

import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pydantic import Field

from musix.db import Database
from musix.metadata_links import metadata_url
from musix.ml.public_graph import public_model_output_sha256
from musix.models import FrozenModel
from musix.models.modeling import PublicModelArtifact

MODEL_KEY = "public-graph"
DEFAULT_LAYOUT_KEY = "public"
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
LAYOUT_SCALE = 1_000.0
_QID = re.compile(r"^Q[1-9][0-9]*$")
_MBID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class PublicModelPublishError(RuntimeError):
    """Report an artifact, identity, or policy that cannot be published safely."""


class PublicModelPublishSummary(FrozenModel):
    """Report the exact serving projection selected by one publish operation."""

    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    layout_key: str
    layout_revision: int = Field(gt=0)
    coordinate_genres: int = Field(ge=0)
    representative_items: int = Field(ge=0)
    duplicate: bool


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def load_public_model(path: Path) -> PublicModelArtifact:
    """Parse one bounded JSON artifact and verify its stable logical hash."""
    size = path.stat().st_size
    if size > MAX_ARTIFACT_BYTES:
        raise PublicModelPublishError(
            f"public model artifact is {size} bytes; limit is {MAX_ARTIFACT_BYTES}"
        )
    artifact = PublicModelArtifact.model_validate_json(path.read_bytes())
    calculated = public_model_output_sha256(artifact)
    if calculated != artifact.output_sha256:
        raise PublicModelPublishError("public model logical output hash does not match payload")
    if not artifact.export_allowed:
        raise PublicModelPublishError("public serving requires an exportable model artifact")
    return artifact


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
) -> tuple[int, bool]:
    existing = connection.execute(
        "SELECT id, policy_id FROM public_model_runs WHERE output_sha256 = ?",
        (artifact.output_sha256,),
    ).fetchone()
    if existing is not None:
        if int(existing[1]) != policy_id:
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
            output_sha256, export_allowed, policy_id, published_at)
           VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)""",
        (
            MODEL_KEY,
            int(revision_row[0]),
            artifact.revision,
            artifact.input_sha256,
            artifact.settings_sha256,
            artifact.output_sha256,
            policy_id,
            _now(),
        ),
    )
    if cursor.lastrowid is None:
        raise RuntimeError("public model insert returned no row ID")
    return cursor.lastrowid, False


def _layout_run(
    connection: sqlite3.Connection,
    artifact: PublicModelArtifact,
    policy_id: int,
    layout_key: str,
    genre_ids: dict[str, int],
) -> tuple[int, int]:
    existing = connection.execute(
        """SELECT id, revision FROM layout_runs
           WHERE layout_key = ? AND algorithm_key = 'public_graph_spectral'
             AND input_fingerprint = ?""",
        (layout_key, artifact.output_sha256),
    ).fetchone()
    if existing is not None:
        return int(existing[0]), int(existing[1])
    revision_row = connection.execute(
        "SELECT coalesce(max(revision), 0) + 1 FROM layout_runs WHERE layout_key = ?",
        (layout_key,),
    ).fetchone()
    if revision_row is None:
        raise RuntimeError("layout revision query returned no row")
    revision = int(revision_row[0])
    parameters = json.dumps(
        {
            "coordinate_scale": LAYOUT_SCALE,
            "semantic_axes": False,
            "source_model_output_sha256": artifact.output_sha256,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    cursor = connection.execute(
        """INSERT INTO layout_runs
           (layout_key, revision, algorithm_key, algorithm_revision, parameters_json,
            input_fingerprint, status, policy_id, completed_at)
           VALUES (?, ?, 'public_graph_spectral', ?, ?, ?, 'complete', ?, ?)""",
        (
            layout_key,
            revision,
            artifact.revision,
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
            for item in artifact.coordinates
        ),
    )
    return run_id, revision


def publish_public_model(
    database_path: Path,
    artifact_path: Path,
    *,
    policy_id: int,
    layout_key: str = DEFAULT_LAYOUT_KEY,
) -> PublicModelPublishSummary:
    """Verify and atomically select one public model for map and detail serving."""
    artifact = load_public_model(artifact_path)
    database = Database(database_path)
    database.initialize()
    with database.connect() as connection, connection:
        _policy_allows_public_serving(connection, policy_id)
        genre_ids = {
            genre.genre_id: _resolve_genre(connection, genre.genre_id) for genre in artifact.genres
        }
        model_run_id, duplicate = _model_run(connection, artifact, policy_id)
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
        layout_run_id, layout_revision = _layout_run(
            connection,
            artifact,
            policy_id,
            layout_key,
            genre_ids,
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
                   selected_at = excluded.selected_at""",
            (MODEL_KEY, model_run_id),
        )
        connection.execute(
            """INSERT INTO current_layouts (layout_key, layout_run_id)
               VALUES (?, ?)
               ON CONFLICT(layout_key) DO UPDATE SET
                   layout_run_id = excluded.layout_run_id,
                   selected_at = excluded.selected_at""",
            (layout_key, layout_run_id),
        )
    return PublicModelPublishSummary(
        output_sha256=artifact.output_sha256,
        layout_key=layout_key,
        layout_revision=layout_revision,
        coordinate_genres=len(artifact.coordinates),
        representative_items=len(artifact.representatives),
        duplicate=duplicate,
    )
