PRAGMA foreign_keys = ON;

BEGIN IMMEDIATE;

CREATE TABLE public_model_runs (
    id INTEGER PRIMARY KEY,
    model_key TEXT NOT NULL COLLATE NOCASE,
    revision INTEGER NOT NULL CHECK (revision > 0),
    model_revision TEXT NOT NULL,
    input_sha256 TEXT NOT NULL,
    settings_sha256 TEXT NOT NULL,
    output_sha256 TEXT NOT NULL UNIQUE,
    artifact_sha256 TEXT NOT NULL,
    export_allowed INTEGER NOT NULL CHECK (export_allowed = 1),
    policy_id INTEGER NOT NULL REFERENCES rights_policies(id) ON DELETE RESTRICT,
    derived_output_id INTEGER NOT NULL UNIQUE
        REFERENCES derived_outputs(id) ON DELETE RESTRICT,
    published_at TEXT NOT NULL,
    UNIQUE (model_key, revision),
    UNIQUE (id, model_key),
    CHECK (length(trim(model_key)) > 0),
    CHECK (length(trim(model_revision)) > 0),
    CHECK (
        length(input_sha256) = 64 AND input_sha256 = lower(input_sha256)
        AND input_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    CHECK (
        length(settings_sha256) = 64 AND settings_sha256 = lower(settings_sha256)
        AND settings_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    CHECK (
        length(output_sha256) = 64 AND output_sha256 = lower(output_sha256)
        AND output_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    CHECK (
        length(artifact_sha256) = 64 AND artifact_sha256 = lower(artifact_sha256)
        AND artifact_sha256 NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE TABLE public_model_input_provenance (
    model_run_id INTEGER NOT NULL REFERENCES public_model_runs(id) ON DELETE RESTRICT,
    provenance_id INTEGER NOT NULL REFERENCES provenance_records(id) ON DELETE RESTRICT,
    artifact_id INTEGER NOT NULL REFERENCES source_artifacts(id) ON DELETE RESTRICT,
    PRIMARY KEY (model_run_id, provenance_id, artifact_id)
) STRICT;

CREATE TABLE public_genre_representatives (
    model_run_id INTEGER NOT NULL REFERENCES public_model_runs(id) ON DELETE RESTRICT,
    genre_id INTEGER NOT NULL REFERENCES genres(id) ON DELETE RESTRICT,
    entity_kind TEXT NOT NULL CHECK (entity_kind IN ('artist', 'release_group', 'recording')),
    source_entity_ref TEXT NOT NULL,
    display_name TEXT NOT NULL,
    rank INTEGER NOT NULL CHECK (rank > 0),
    direct_evidence_value REAL NOT NULL CHECK (direct_evidence_value > 0.0),
    source_count INTEGER NOT NULL CHECK (source_count > 0),
    evidence_refs_json TEXT NOT NULL
        CHECK (json_valid(evidence_refs_json) AND json_type(evidence_refs_json) = 'array'),
    PRIMARY KEY (model_run_id, genre_id, entity_kind, rank),
    UNIQUE (model_run_id, genre_id, entity_kind, source_entity_ref),
    CHECK (length(trim(source_entity_ref)) > 0),
    CHECK (length(trim(display_name)) > 0)
) STRICT;

CREATE TABLE public_genre_names (
    model_run_id INTEGER NOT NULL REFERENCES public_model_runs(id) ON DELETE RESTRICT,
    genre_id INTEGER NOT NULL REFERENCES genres(id) ON DELETE RESTRICT,
    source_genre_ref TEXT NOT NULL,
    display_name TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL
        CHECK (json_valid(evidence_refs_json) AND json_type(evidence_refs_json) = 'array'),
    PRIMARY KEY (model_run_id, genre_id),
    UNIQUE (model_run_id, source_genre_ref),
    CHECK (length(trim(source_genre_ref)) > 0),
    CHECK (length(trim(display_name)) > 0)
) STRICT;

CREATE INDEX public_genre_representatives_genre_idx
    ON public_genre_representatives(genre_id, entity_kind, rank);

CREATE TABLE current_public_models (
    model_key TEXT PRIMARY KEY COLLATE NOCASE,
    model_run_id INTEGER NOT NULL,
    selected_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (model_run_id, model_key)
        REFERENCES public_model_runs(id, model_key) ON DELETE RESTRICT
) STRICT;

CREATE VIEW servable_public_model_runs AS
SELECT run.*
FROM public_model_runs AS run
JOIN active_rights_policy_permissions AS display_permission
  ON display_permission.policy_id = run.policy_id
 AND display_permission.use_kind = 'display'
 AND display_permission.decision = 'allow'
JOIN active_rights_policy_permissions AS export_permission
  ON export_permission.policy_id = run.policy_id
 AND export_permission.use_kind = 'export'
 AND export_permission.decision = 'allow'
WHERE NOT EXISTS (
    SELECT 1 FROM active_suppressions AS suppression
    WHERE suppression.target_kind = 'derived_output'
      AND suppression.target_ref = CAST(run.derived_output_id AS TEXT)
      AND suppression.use_kind IN ('all', 'display', 'export')
)
AND (
    SELECT event.event_kind
    FROM derived_output_events AS event
    WHERE event.derived_output_id = run.derived_output_id
    ORDER BY event.event_at DESC, event.id DESC
    LIMIT 1
) = 'created'
AND NOT EXISTS (
    SELECT 1
    FROM public_model_input_provenance AS input
    JOIN provenance_records AS provenance ON provenance.id = input.provenance_id
    JOIN source_artifacts AS artifact ON artifact.id = input.artifact_id
    JOIN active_suppressions AS suppression
      ON (
        (suppression.target_kind = 'provenance'
         AND suppression.target_ref = CAST(input.provenance_id AS TEXT))
        OR (suppression.target_kind = 'source'
            AND suppression.target_ref = CAST(provenance.source_id AS TEXT))
        OR (suppression.target_kind = 'artifact'
            AND suppression.target_ref = CAST(input.artifact_id AS TEXT))
        OR (suppression.target_kind = 'snapshot'
            AND suppression.target_ref = CAST(artifact.snapshot_id AS TEXT))
      )
     AND suppression.use_kind IN ('all', 'display', 'export')
    WHERE input.model_run_id = run.id
);

CREATE VIEW displayable_public_genre_representatives AS
SELECT representative.*
FROM current_public_models AS current
JOIN servable_public_model_runs AS run ON run.id = current.model_run_id
JOIN public_genre_representatives AS representative
  ON representative.model_run_id = run.id
WHERE NOT EXISTS (
    SELECT 1
    FROM active_suppressions AS suppression
    WHERE suppression.target_kind = 'entity'
      AND suppression.target_ref = CAST(representative.genre_id AS TEXT)
      AND suppression.use_kind IN ('all', 'display')
);

DROP VIEW displayable_map_points;

CREATE VIEW displayable_map_points AS
WITH ranked_names AS (
    SELECT name.entity_id, name.name,
           row_number() OVER (
               PARTITION BY name.entity_id
               ORDER BY (name.name_kind = 'primary') DESC, name.is_preferred DESC,
                        (name.language_tag = 'und') DESC, name.id
           ) AS rank
    FROM displayable_entity_names AS name
)
SELECT run.layout_key, run.revision AS layout_revision, point.entity_id,
       entity.entity_kind, coalesce(public_name.display_name, name.name) AS name,
       point.x, point.y, point.display_weight, point.color_hex, point.metadata_json
FROM current_layouts AS current
JOIN layout_runs AS run ON run.id = current.layout_run_id
JOIN active_rights_policy_permissions AS permission
  ON permission.policy_id = run.policy_id
 AND permission.use_kind = 'display' AND permission.decision = 'allow'
JOIN layout_points AS point ON point.layout_run_id = run.id
JOIN catalog_entities AS entity ON entity.id = point.entity_id
LEFT JOIN ranked_names AS name ON name.entity_id = point.entity_id AND name.rank = 1
LEFT JOIN servable_public_model_runs AS public_run
  ON public_run.output_sha256 = run.input_fingerprint
LEFT JOIN public_genre_names AS public_name
  ON public_name.model_run_id = public_run.id AND public_name.genre_id = point.entity_id
WHERE run.status = 'complete'
  AND (run.algorithm_key != 'public_graph_spectral' OR public_run.id IS NOT NULL)
  AND coalesce(name.name, public_name.display_name) IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM active_suppressions AS suppression
      WHERE suppression.target_kind = 'entity'
        AND suppression.target_ref = CAST(point.entity_id AS TEXT)
        AND suppression.use_kind IN ('all', 'display')
  );

CREATE TRIGGER public_model_runs_are_immutable
BEFORE UPDATE ON public_model_runs
BEGIN SELECT RAISE(ABORT, 'public model runs are immutable'); END;

CREATE TRIGGER public_model_runs_cannot_be_deleted
BEFORE DELETE ON public_model_runs
BEGIN SELECT RAISE(ABORT, 'public model runs are immutable'); END;

CREATE TRIGGER public_genre_representatives_are_immutable
BEFORE UPDATE ON public_genre_representatives
BEGIN SELECT RAISE(ABORT, 'public representatives are immutable'); END;

CREATE TRIGGER public_genre_representatives_cannot_be_deleted
BEFORE DELETE ON public_genre_representatives
BEGIN SELECT RAISE(ABORT, 'public representatives are immutable'); END;

CREATE TRIGGER public_genre_names_are_immutable
BEFORE UPDATE ON public_genre_names
BEGIN SELECT RAISE(ABORT, 'public genre names are immutable'); END;

CREATE TRIGGER public_genre_names_cannot_be_deleted
BEFORE DELETE ON public_genre_names
BEGIN SELECT RAISE(ABORT, 'public genre names are immutable'); END;

CREATE TRIGGER public_model_input_provenance_is_immutable
BEFORE UPDATE ON public_model_input_provenance
BEGIN SELECT RAISE(ABORT, 'public model inputs are immutable'); END;

CREATE TRIGGER public_model_input_provenance_cannot_be_deleted
BEFORE DELETE ON public_model_input_provenance
BEGIN SELECT RAISE(ABORT, 'public model inputs are immutable'); END;

PRAGMA user_version = 7;

COMMIT;
