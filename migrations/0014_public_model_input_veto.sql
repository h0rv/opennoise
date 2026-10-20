PRAGMA foreign_keys = ON;

BEGIN IMMEDIATE;

-- Preserve run/ledger/output rows and existing output permission/event rules.
DROP VIEW servable_public_model_runs;

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
     AND suppression.use_kind IN ('all', 'display', 'export', 'embed')
    WHERE input.model_run_id = run.id
)
-- The recorded ledger is source-batch provenance, not exact claim lineage.
-- Resolve active references by primary key, then require an exact canonical
-- namespace/positive-ID round trip. Malformed references never bind a row.
AND NOT EXISTS (
    SELECT 1 FROM active_suppressions AS suppression
    JOIN artist_genre_evidence AS evidence
      ON evidence.id = CAST(substr(suppression.target_ref, 23) AS INTEGER)
     AND evidence.id > 0
     AND suppression.target_ref = 'artist_genre_evidence:' || CAST(evidence.id AS TEXT)
    JOIN public_model_input_provenance AS input ON input.provenance_id = evidence.provenance_id
    WHERE input.model_run_id = run.id AND suppression.target_kind = 'claim'
      AND suppression.use_kind IN ('all', 'embed')
)
AND NOT EXISTS (
    SELECT 1 FROM active_suppressions AS suppression
    JOIN entity_claims AS claim
      ON claim.id = CAST(substr(suppression.target_ref, 15) AS INTEGER)
     AND claim.id > 0
     AND suppression.target_ref = 'entity_claims:' || CAST(claim.id AS TEXT)
    JOIN public_model_input_provenance AS input ON input.provenance_id = claim.provenance_id
    WHERE input.model_run_id = run.id AND suppression.target_kind = 'claim'
      AND suppression.use_kind IN ('all', 'embed')
);

PRAGMA user_version = 14;

COMMIT;
