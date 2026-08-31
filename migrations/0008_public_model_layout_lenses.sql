PRAGMA foreign_keys = ON;

BEGIN IMMEDIATE;

CREATE TABLE public_model_layouts (
    model_run_id INTEGER NOT NULL REFERENCES public_model_runs(id) ON DELETE RESTRICT,
    lens_key TEXT NOT NULL COLLATE NOCASE,
    layout_run_id INTEGER NOT NULL UNIQUE REFERENCES layout_runs(id) ON DELETE RESTRICT,
    lens_input_sha256 TEXT NOT NULL,
    lens_output_sha256 TEXT NOT NULL,
    is_default INTEGER NOT NULL CHECK (is_default IN (0, 1)),
    PRIMARY KEY (model_run_id, lens_key),
    CHECK (length(trim(lens_key)) > 0),
    CHECK (
        length(lens_input_sha256) = 64
        AND lens_input_sha256 = lower(lens_input_sha256)
        AND lens_input_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    CHECK (
        length(lens_output_sha256) = 64
        AND lens_output_sha256 = lower(lens_output_sha256)
        AND lens_output_sha256 NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE UNIQUE INDEX public_model_layouts_one_default_idx
    ON public_model_layouts(model_run_id) WHERE is_default = 1;

CREATE TRIGGER public_model_layouts_are_immutable
BEFORE UPDATE ON public_model_layouts
BEGIN SELECT RAISE(ABORT, 'public model layouts are immutable'); END;

CREATE TRIGGER public_model_layouts_cannot_be_deleted
BEFORE DELETE ON public_model_layouts
BEGIN SELECT RAISE(ABORT, 'public model layouts are immutable'); END;

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
LEFT JOIN public_model_layouts AS public_layout ON public_layout.layout_run_id = run.id
LEFT JOIN current_public_models AS current_public
  ON current_public.model_key = 'public-graph'
 AND current_public.model_run_id = public_layout.model_run_id
LEFT JOIN servable_public_model_runs AS public_run
  ON public_run.id = current_public.model_run_id
LEFT JOIN public_genre_names AS public_name
  ON public_name.model_run_id = public_run.id AND public_name.genre_id = point.entity_id
WHERE run.status = 'complete'
  AND (run.algorithm_key NOT LIKE 'public_graph_%' OR public_run.id IS NOT NULL)
  AND coalesce(name.name, public_name.display_name) IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM active_suppressions AS suppression
      WHERE suppression.target_kind = 'entity'
        AND suppression.target_ref = CAST(point.entity_id AS TEXT)
        AND suppression.use_kind IN ('all', 'display')
  );

CREATE VIEW displayable_public_layout_unplaced AS
SELECT public_layout.model_run_id, public_layout.lens_key,
       name.genre_id, json_extract(reason.value, '$.reason') AS reason_key
FROM public_model_layouts AS public_layout
JOIN current_public_models AS current_public
  ON current_public.model_key = 'public-graph'
 AND current_public.model_run_id = public_layout.model_run_id
JOIN servable_public_model_runs AS public_run
  ON public_run.id = current_public.model_run_id
JOIN layout_runs AS layout ON layout.id = public_layout.layout_run_id
JOIN current_layouts AS current_layout
  ON current_layout.layout_key = public_layout.lens_key
 AND current_layout.layout_run_id = public_layout.layout_run_id
JOIN json_each(layout.parameters_json, '$.unplaced') AS reason
JOIN public_genre_names AS name
  ON name.model_run_id = public_run.id
 AND name.source_genre_ref = json_extract(reason.value, '$.genre_id')
WHERE json_type(reason.value, '$.genre_id') = 'text'
  AND json_type(reason.value, '$.reason') = 'text';

PRAGMA user_version = 8;

COMMIT;
