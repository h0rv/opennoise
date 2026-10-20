PRAGMA foreign_keys = ON;

BEGIN IMMEDIATE;

-- Preserve the existing view contract and all stored facts. Missing custody
-- inventory is not a new display denial; matching registered custody can veto.
DROP VIEW displayable_artist_genre_evidence;

CREATE VIEW displayable_artist_genre_evidence AS
SELECT evidence.*
FROM artist_genre_evidence AS evidence
JOIN provenance_records AS provenance ON provenance.id = evidence.provenance_id
JOIN active_rights_policy_permissions AS permission
  ON permission.policy_id = evidence.policy_id
 AND permission.use_kind = 'display' AND permission.decision = 'allow'
WHERE NOT EXISTS (
    SELECT 1 FROM active_suppressions AS suppression
    WHERE suppression.use_kind IN ('all', 'display') AND (
        (suppression.target_kind = 'entity' AND suppression.target_ref IN (
            CAST(evidence.artist_id AS TEXT), CAST(evidence.genre_id AS TEXT)
        ))
        OR (suppression.target_kind = 'provenance'
            AND suppression.target_ref = CAST(evidence.provenance_id AS TEXT))
        OR (suppression.target_kind = 'source'
            AND suppression.target_ref = CAST(provenance.source_id AS TEXT))
    )
)
AND (
    evidence.source_credit_provenance_id IS NULL OR (
        EXISTS (
            SELECT 1 FROM provenance_records AS credit_provenance
            JOIN active_rights_policy_permissions AS credit_permission
              ON credit_permission.policy_id = credit_provenance.policy_id
             AND credit_permission.use_kind = 'display'
             AND credit_permission.decision = 'allow'
            WHERE credit_provenance.id = evidence.source_credit_provenance_id
        )
        AND NOT EXISTS (
            SELECT 1 FROM active_suppressions AS suppression
            JOIN provenance_records AS credit_provenance
              ON credit_provenance.id = evidence.source_credit_provenance_id
            WHERE suppression.use_kind IN ('all', 'display') AND (
                (suppression.target_kind = 'provenance'
                 AND suppression.target_ref = CAST(credit_provenance.id AS TEXT))
                OR (suppression.target_kind = 'source'
                    AND suppression.target_ref = CAST(credit_provenance.source_id AS TEXT))
            )
        )
    )
)
AND (
    evidence.source_credit_definition_provenance_id IS NULL OR (
        EXISTS (
            SELECT 1 FROM provenance_records AS credit_definition
            JOIN active_rights_policy_permissions AS definition_permission
              ON definition_permission.policy_id = credit_definition.policy_id
             AND definition_permission.use_kind = 'display'
             AND definition_permission.decision = 'allow'
            WHERE credit_definition.id = evidence.source_credit_definition_provenance_id
        )
        AND NOT EXISTS (
            SELECT 1 FROM active_suppressions AS suppression
            JOIN provenance_records AS credit_definition
              ON credit_definition.id = evidence.source_credit_definition_provenance_id
            WHERE suppression.use_kind IN ('all', 'display') AND (
                (suppression.target_kind = 'provenance'
                 AND suppression.target_ref = CAST(credit_definition.id AS TEXT))
                OR (suppression.target_kind = 'source'
                    AND suppression.target_ref = CAST(credit_definition.source_id AS TEXT))
            )
        )
    )
)
AND (
    evidence.source_album_evidence_id IS NULL OR EXISTS (
        SELECT 1 FROM displayable_album_genre_memberships AS album
        WHERE album.id = evidence.source_album_evidence_id
    )
)
-- Only direct source claims gain these gates. Existing propagation remains unchanged.
AND (
    evidence.evidence_kind != 'direct_source_claim' OR (
        NOT EXISTS (
            SELECT 1 FROM source_snapshots AS snapshot
            LEFT JOIN source_artifacts AS artifact
              ON artifact.snapshot_id = snapshot.id
             AND artifact.sha256 = provenance.artifact_sha256
             AND artifact.policy_id = provenance.policy_id
            JOIN active_suppressions AS suppression
              ON suppression.use_kind IN ('all', 'display')
            WHERE snapshot.source_id = provenance.source_id
              AND snapshot.snapshot_ref = provenance.snapshot_ref
              AND snapshot.policy_id = provenance.policy_id
              AND (
                  (suppression.target_kind = 'snapshot'
                   AND suppression.target_ref = CAST(snapshot.id AS TEXT))
                  OR (suppression.target_kind = 'artifact'
                      AND suppression.target_ref = CAST(artifact.id AS TEXT))
              )
        )
        AND NOT EXISTS (
            SELECT 1 FROM active_suppressions AS suppression
            WHERE suppression.use_kind IN ('all', 'display')
              AND suppression.target_kind = 'claim'
              AND suppression.target_ref = 'artist_genre_evidence:' || CAST(evidence.id AS TEXT)
        )
        AND NOT EXISTS (
            SELECT 1 FROM entity_claims AS claim
            JOIN active_suppressions AS suppression
              ON suppression.target_kind = 'claim'
             AND suppression.target_ref = 'entity_claims:' || CAST(claim.id AS TEXT)
             AND suppression.use_kind IN ('all', 'display')
            WHERE claim.entity_id = evidence.artist_id
              AND claim.provenance_id = evidence.provenance_id
              AND claim.policy_id = evidence.policy_id
              AND claim.claim_key = 'genre' AND claim.claim_type = 'wikidata_relation'
              AND json_extract(claim.normalized_value_json, '$.target.namespace') = 'wikidata'
              AND EXISTS (
                  SELECT 1 FROM entity_identifiers AS identifier
                  JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
                  WHERE identifier.entity_id = evidence.genre_id
                    AND identifier.namespace = 'wikidata'
                    AND type.type_key IN ('wikidata_genre_qid', 'wikidata_qid')
                    AND identifier.normalized_value = json_extract(
                        claim.normalized_value_json, '$.target.value')
              )
        )
    )
);

DROP VIEW normalizable_artist_genre_evidence;

CREATE VIEW normalizable_artist_genre_evidence AS
SELECT evidence.*
FROM artist_genre_evidence AS evidence
JOIN provenance_records AS provenance ON provenance.id = evidence.provenance_id
JOIN active_rights_policy_permissions AS permission
  ON permission.policy_id = evidence.policy_id
 AND permission.use_kind = 'normalize' AND permission.decision = 'allow'
WHERE NOT EXISTS (
    SELECT 1 FROM active_suppressions AS suppression
    WHERE suppression.use_kind IN ('all', 'normalize') AND (
        (suppression.target_kind = 'entity' AND suppression.target_ref IN (
            CAST(evidence.artist_id AS TEXT), CAST(evidence.genre_id AS TEXT)
        ))
        OR (suppression.target_kind = 'provenance'
            AND suppression.target_ref = CAST(evidence.provenance_id AS TEXT))
        OR (suppression.target_kind = 'source'
            AND suppression.target_ref = CAST(provenance.source_id AS TEXT))
    )
)
AND (
    evidence.source_credit_provenance_id IS NULL OR (
        EXISTS (
            SELECT 1 FROM provenance_records AS credit_provenance
            JOIN active_rights_policy_permissions AS credit_permission
              ON credit_permission.policy_id = credit_provenance.policy_id
             AND credit_permission.use_kind = 'normalize'
             AND credit_permission.decision = 'allow'
            WHERE credit_provenance.id = evidence.source_credit_provenance_id
        )
        AND NOT EXISTS (
            SELECT 1 FROM active_suppressions AS suppression
            JOIN provenance_records AS credit_provenance
              ON credit_provenance.id = evidence.source_credit_provenance_id
            WHERE suppression.use_kind IN ('all', 'normalize') AND (
                (suppression.target_kind = 'provenance'
                 AND suppression.target_ref = CAST(credit_provenance.id AS TEXT))
                OR (suppression.target_kind = 'source'
                    AND suppression.target_ref = CAST(credit_provenance.source_id AS TEXT))
            )
        )
    )
)
AND (
    evidence.source_credit_definition_provenance_id IS NULL OR (
        EXISTS (
            SELECT 1 FROM provenance_records AS credit_definition
            JOIN active_rights_policy_permissions AS definition_permission
              ON definition_permission.policy_id = credit_definition.policy_id
             AND definition_permission.use_kind = 'normalize'
             AND definition_permission.decision = 'allow'
            WHERE credit_definition.id = evidence.source_credit_definition_provenance_id
        )
        AND NOT EXISTS (
            SELECT 1 FROM active_suppressions AS suppression
            JOIN provenance_records AS credit_definition
              ON credit_definition.id = evidence.source_credit_definition_provenance_id
            WHERE suppression.use_kind IN ('all', 'normalize') AND (
                (suppression.target_kind = 'provenance'
                 AND suppression.target_ref = CAST(credit_definition.id AS TEXT))
                OR (suppression.target_kind = 'source'
                    AND suppression.target_ref = CAST(credit_definition.source_id AS TEXT))
            )
        )
    )
)
AND (
    evidence.source_album_evidence_id IS NULL OR EXISTS (
        SELECT 1 FROM normalizable_album_genre_memberships AS album
        WHERE album.id = evidence.source_album_evidence_id
    )
)-- Only direct source claims gain these gates. Existing propagation remains unchanged.
AND (
    evidence.evidence_kind != 'direct_source_claim' OR (
        NOT EXISTS (
            SELECT 1 FROM source_snapshots AS snapshot
            LEFT JOIN source_artifacts AS artifact
              ON artifact.snapshot_id = snapshot.id
             AND artifact.sha256 = provenance.artifact_sha256
             AND artifact.policy_id = provenance.policy_id
            JOIN active_suppressions AS suppression
              ON suppression.use_kind IN ('all', 'normalize')
            WHERE snapshot.source_id = provenance.source_id
              AND snapshot.snapshot_ref = provenance.snapshot_ref
              AND snapshot.policy_id = provenance.policy_id
              AND (
                  (suppression.target_kind = 'snapshot'
                   AND suppression.target_ref = CAST(snapshot.id AS TEXT))
                  OR (suppression.target_kind = 'artifact'
                      AND suppression.target_ref = CAST(artifact.id AS TEXT))
              )
        )
        AND NOT EXISTS (
            SELECT 1 FROM active_suppressions AS suppression
            WHERE suppression.use_kind IN ('all', 'normalize')
              AND suppression.target_kind = 'claim'
              AND suppression.target_ref = 'artist_genre_evidence:' || CAST(evidence.id AS TEXT)
        )
        AND NOT EXISTS (
            SELECT 1 FROM entity_claims AS claim
            JOIN active_suppressions AS suppression
              ON suppression.target_kind = 'claim'
             AND suppression.target_ref = 'entity_claims:' || CAST(claim.id AS TEXT)
             AND suppression.use_kind IN ('all', 'normalize')
            WHERE claim.entity_id = evidence.artist_id
              AND claim.provenance_id = evidence.provenance_id
              AND claim.policy_id = evidence.policy_id
              AND claim.claim_key = 'genre' AND claim.claim_type = 'wikidata_relation'
              AND json_extract(claim.normalized_value_json, '$.target.namespace') = 'wikidata'
              AND EXISTS (
                  SELECT 1 FROM entity_identifiers AS identifier
                  JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
                  WHERE identifier.entity_id = evidence.genre_id
                    AND identifier.namespace = 'wikidata'
                    AND type.type_key IN ('wikidata_genre_qid', 'wikidata_qid')
                    AND identifier.normalized_value = json_extract(
                        claim.normalized_value_json, '$.target.value')
              )
        )
    )
);

PRAGMA user_version = 13;

COMMIT;
