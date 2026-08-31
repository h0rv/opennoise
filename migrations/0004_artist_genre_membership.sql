PRAGMA foreign_keys = ON;

BEGIN IMMEDIATE;

CREATE TABLE artist_genre_evidence (
    id INTEGER PRIMARY KEY,
    artist_id INTEGER NOT NULL REFERENCES artists(id) ON DELETE RESTRICT,
    genre_id INTEGER NOT NULL REFERENCES genres(id) ON DELETE RESTRICT,
    evidence_kind TEXT NOT NULL CHECK (evidence_kind IN (
        'direct_source_claim', 'release_group_propagation'
    )),
    evidence_value REAL NOT NULL CHECK (
        evidence_value = evidence_value
        AND evidence_value >= 0.0
        AND abs(evidence_value) <= 1.7976931348623157e308
    ),
    source_key TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    source_album_evidence_id INTEGER
        REFERENCES album_genre_membership_observations(id) ON DELETE RESTRICT,
    source_credit_provenance_id INTEGER
        REFERENCES provenance_records(id) ON DELETE RESTRICT,
    source_credit_definition_provenance_id INTEGER
        REFERENCES provenance_records(id) ON DELETE RESTRICT,
    method_key TEXT NOT NULL,
    method_version TEXT NOT NULL,
    parameter_manifest_json TEXT NOT NULL
        CHECK (json_valid(parameter_manifest_json)
               AND json_type(parameter_manifest_json) = 'object'),
    observed_at TEXT NOT NULL,
    provenance_id INTEGER NOT NULL REFERENCES provenance_records(id) ON DELETE RESTRICT,
    policy_id INTEGER NOT NULL REFERENCES rights_policies(id) ON DELETE RESTRICT,
    record_fingerprint TEXT NOT NULL UNIQUE,
    CHECK (length(trim(source_key)) > 0),
    CHECK (length(trim(source_record_id)) > 0),
    CHECK (length(trim(method_key)) > 0),
    CHECK (length(trim(method_version)) > 0),
    CHECK (
        (evidence_kind = 'release_group_propagation'
         AND source_album_evidence_id IS NOT NULL
         AND source_credit_provenance_id IS NOT NULL)
        OR (evidence_kind = 'direct_source_claim'
            AND source_album_evidence_id IS NULL
            AND source_credit_provenance_id IS NULL
            AND source_credit_definition_provenance_id IS NULL)
    ),
    CHECK (
        length(record_fingerprint) = 64
        AND record_fingerprint = lower(record_fingerprint)
        AND record_fingerprint NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE INDEX artist_genre_evidence_pair_idx
    ON artist_genre_evidence(genre_id, artist_id, evidence_kind, source_key);
CREATE INDEX artist_genre_evidence_provenance_idx
    ON artist_genre_evidence(provenance_id);

CREATE TRIGGER artist_genre_evidence_requires_matching_policy
BEFORE INSERT ON artist_genre_evidence
FOR EACH ROW
WHEN NEW.policy_id IS NOT (
    SELECT policy_id FROM provenance_records WHERE id = NEW.provenance_id
)
BEGIN
    SELECT RAISE(ABORT, 'artist genre evidence policy must match provenance policy');
END;

CREATE TRIGGER artist_genre_evidence_requires_matching_source
BEFORE INSERT ON artist_genre_evidence
FOR EACH ROW
WHEN NEW.source_key IS NOT (
    SELECT source.source_key
    FROM provenance_records AS provenance
    JOIN data_sources AS source ON source.id = provenance.source_id
    WHERE provenance.id = NEW.provenance_id
)
BEGIN
    SELECT RAISE(ABORT, 'artist genre evidence source must match provenance source');
END;

CREATE TRIGGER artist_genre_evidence_propagation_matches_album
BEFORE INSERT ON artist_genre_evidence
FOR EACH ROW
WHEN NEW.source_album_evidence_id IS NOT NULL AND NOT EXISTS (
    SELECT 1
    FROM album_genre_membership_observations AS album
    JOIN entity_artist_credits AS link ON link.entity_id = album.release_group_id
    JOIN artist_credits AS credit ON credit.id = link.artist_credit_id
    JOIN artist_credit_members AS member ON member.artist_credit_id = link.artist_credit_id
    WHERE album.id = NEW.source_album_evidence_id
      AND album.genre_id = NEW.genre_id
      AND album.provenance_id = NEW.provenance_id
      AND link.provenance_id = NEW.source_credit_provenance_id
      AND credit.provenance_id IS NEW.source_credit_definition_provenance_id
      AND member.artist_id = NEW.artist_id
)
BEGIN
    SELECT RAISE(ABORT, 'propagated evidence must match its album genre and artist credit');
END;

CREATE TRIGGER artist_genre_evidence_is_append_only
BEFORE UPDATE ON artist_genre_evidence
BEGIN SELECT RAISE(ABORT, 'artist genre evidence is append-only'); END;

CREATE TRIGGER artist_genre_evidence_cannot_be_deleted
BEFORE DELETE ON artist_genre_evidence
BEGIN SELECT RAISE(ABORT, 'artist genre evidence is append-only'); END;

CREATE TABLE artist_genre_membership_runs (
    id INTEGER PRIMARY KEY,
    run_ref TEXT NOT NULL UNIQUE,
    method_key TEXT NOT NULL CHECK (method_key IN (
        'direct_evidence', 'release_propagation'
    )),
    method_version TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    parameter_manifest_json TEXT NOT NULL
        CHECK (json_valid(parameter_manifest_json)
               AND json_type(parameter_manifest_json) = 'object'),
    parameter_manifest_sha256 TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL,
    input_evidence_count INTEGER NOT NULL CHECK (input_evidence_count >= 0),
    output_item_limit INTEGER NOT NULL CHECK (output_item_limit > 0),
    policy_id INTEGER NOT NULL REFERENCES rights_policies(id) ON DELETE RESTRICT,
    generated_at TEXT NOT NULL,
    UNIQUE (method_key, revision),
    CHECK (length(trim(run_ref)) > 0),
    CHECK (length(trim(method_version)) > 0),
    CHECK (
        length(parameter_manifest_sha256) = 64
        AND parameter_manifest_sha256 = lower(parameter_manifest_sha256)
        AND parameter_manifest_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    CHECK (
        length(input_fingerprint) = 64
        AND input_fingerprint = lower(input_fingerprint)
        AND input_fingerprint NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE TRIGGER artist_genre_membership_runs_require_normalize_permission
BEFORE INSERT ON artist_genre_membership_runs
FOR EACH ROW WHEN NOT EXISTS (
    SELECT 1 FROM active_rights_policy_permissions
    WHERE policy_id = NEW.policy_id
      AND use_kind = 'normalize'
      AND decision = 'allow'
)
BEGIN
    SELECT RAISE(ABORT, 'artist genre membership requires normalization permission');
END;

CREATE TRIGGER artist_genre_membership_runs_are_append_only
BEFORE UPDATE ON artist_genre_membership_runs
BEGIN SELECT RAISE(ABORT, 'artist genre membership runs are append-only'); END;

CREATE TRIGGER artist_genre_membership_runs_cannot_be_deleted
BEFORE DELETE ON artist_genre_membership_runs
BEGIN SELECT RAISE(ABORT, 'artist genre membership runs are append-only'); END;

CREATE TABLE artist_genre_membership_items (
    run_id INTEGER NOT NULL REFERENCES artist_genre_membership_runs(id) ON DELETE RESTRICT,
    artist_id INTEGER NOT NULL REFERENCES artists(id) ON DELETE RESTRICT,
    genre_id INTEGER NOT NULL REFERENCES genres(id) ON DELETE RESTRICT,
    score REAL NOT NULL CHECK (
        score = score AND score >= 0.0 AND abs(score) <= 1.7976931348623157e308
    ),
    evidence_count INTEGER NOT NULL CHECK (evidence_count > 0),
    source_count INTEGER NOT NULL CHECK (source_count > 0),
    explanation_json TEXT NOT NULL
        CHECK (json_valid(explanation_json) AND json_type(explanation_json) = 'object'),
    PRIMARY KEY (run_id, artist_id, genre_id)
) STRICT;

CREATE TABLE artist_genre_membership_item_evidence (
    run_id INTEGER NOT NULL,
    artist_id INTEGER NOT NULL,
    genre_id INTEGER NOT NULL,
    evidence_id INTEGER NOT NULL REFERENCES artist_genre_evidence(id) ON DELETE RESTRICT,
    PRIMARY KEY (run_id, artist_id, genre_id, evidence_id),
    FOREIGN KEY (run_id, artist_id, genre_id)
        REFERENCES artist_genre_membership_items(run_id, artist_id, genre_id)
        ON DELETE RESTRICT
) STRICT;

CREATE TRIGGER artist_genre_membership_item_evidence_matches_item
BEFORE INSERT ON artist_genre_membership_item_evidence
FOR EACH ROW WHEN NOT EXISTS (
    SELECT 1 FROM artist_genre_evidence AS evidence
    WHERE evidence.id = NEW.evidence_id
      AND evidence.artist_id = NEW.artist_id
      AND evidence.genre_id = NEW.genre_id
)
BEGIN
    SELECT RAISE(ABORT, 'membership evidence must match its artist and genre');
END;

CREATE TRIGGER artist_genre_membership_items_are_append_only
BEFORE UPDATE ON artist_genre_membership_items
BEGIN SELECT RAISE(ABORT, 'artist genre membership items are append-only'); END;

CREATE TRIGGER artist_genre_membership_items_cannot_be_deleted
BEFORE DELETE ON artist_genre_membership_items
BEGIN SELECT RAISE(ABORT, 'artist genre membership items are append-only'); END;

CREATE TRIGGER artist_genre_membership_item_evidence_is_append_only
BEFORE UPDATE ON artist_genre_membership_item_evidence
BEGIN SELECT RAISE(ABORT, 'artist genre membership evidence links are append-only'); END;

CREATE TRIGGER artist_genre_membership_item_evidence_cannot_be_deleted
BEFORE DELETE ON artist_genre_membership_item_evidence
BEGIN SELECT RAISE(ABORT, 'artist genre membership evidence links are append-only'); END;

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
);

CREATE VIEW normalizable_album_genre_memberships AS
SELECT observation.*
FROM album_genre_membership_observations AS observation
JOIN provenance_records AS provenance ON provenance.id = observation.provenance_id
JOIN active_rights_policy_permissions AS permission
  ON permission.policy_id = observation.policy_id
 AND permission.use_kind = 'normalize' AND permission.decision = 'allow'
WHERE NOT EXISTS (
    SELECT 1 FROM active_suppressions AS suppression
    WHERE suppression.use_kind IN ('all', 'normalize') AND (
        (suppression.target_kind = 'entity' AND suppression.target_ref IN (
            CAST(observation.release_group_id AS TEXT),
            CAST(observation.genre_id AS TEXT),
            coalesce(CAST(observation.source_release_id AS TEXT), '')
        ))
        OR (suppression.target_kind = 'provenance'
            AND suppression.target_ref = CAST(observation.provenance_id AS TEXT))
        OR (suppression.target_kind = 'source'
            AND suppression.target_ref = CAST(provenance.source_id AS TEXT))
    )
);

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
);

CREATE VIEW displayable_artist_genre_memberships AS
WITH latest_runs AS (
    SELECT method_key, max(revision) AS revision
    FROM artist_genre_membership_runs
    GROUP BY method_key
)
SELECT run.run_ref, run.method_key, run.method_version, run.revision,
       run.parameter_manifest_sha256, run.input_fingerprint,
       item.artist_id, item.genre_id, item.score, item.evidence_count,
       item.source_count, item.explanation_json, run.generated_at
FROM latest_runs AS latest
JOIN artist_genre_membership_runs AS run
  ON run.method_key = latest.method_key AND run.revision = latest.revision
JOIN active_rights_policy_permissions AS permission
  ON permission.policy_id = run.policy_id
 AND permission.use_kind = 'display' AND permission.decision = 'allow'
JOIN artist_genre_membership_items AS item ON item.run_id = run.id
WHERE EXISTS (
    SELECT 1 FROM artist_genre_membership_item_evidence AS link
    JOIN displayable_artist_genre_evidence AS evidence ON evidence.id = link.evidence_id
    WHERE link.run_id = item.run_id
      AND link.artist_id = item.artist_id AND link.genre_id = item.genre_id
)
AND NOT EXISTS (
    SELECT 1 FROM artist_genre_membership_item_evidence AS link
    WHERE link.run_id = item.run_id
      AND link.artist_id = item.artist_id AND link.genre_id = item.genre_id
      AND NOT EXISTS (
          SELECT 1 FROM displayable_artist_genre_evidence AS evidence
          WHERE evidence.id = link.evidence_id
      )
);

PRAGMA user_version = 4;

COMMIT;
