PRAGMA foreign_keys = ON;

BEGIN IMMEDIATE;

CREATE TABLE genre_music_qualification_observations (
    id INTEGER PRIMARY KEY,
    genre_id INTEGER NOT NULL REFERENCES genres(id) ON DELETE RESTRICT,
    root_qid TEXT NOT NULL,
    path_depth INTEGER NOT NULL CHECK (path_depth = 1),
    path_spec TEXT NOT NULL,
    exclusion_profile TEXT NOT NULL,
    statement_id TEXT NOT NULL,
    statement_rank TEXT NOT NULL CHECK (statement_rank IN ('normal', 'preferred')),
    observed_at TEXT NOT NULL,
    provenance_id INTEGER NOT NULL REFERENCES provenance_records(id) ON DELETE RESTRICT,
    policy_id INTEGER NOT NULL REFERENCES rights_policies(id) ON DELETE RESTRICT,
    record_fingerprint TEXT NOT NULL UNIQUE,
    CHECK (root_qid = 'Q188451'),
    CHECK (path_spec = 'P31'),
    CHECK (exclusion_profile = 'P279:nondeprecated:Q25379'),
    CHECK (length(statement_id) > 0),
    CHECK (length(record_fingerprint) = 64
           AND record_fingerprint = lower(record_fingerprint)
           AND record_fingerprint NOT GLOB '*[^0-9a-f]*')
) STRICT;

CREATE INDEX genre_music_qualification_genre_idx
    ON genre_music_qualification_observations(genre_id, path_depth);

CREATE TRIGGER genre_music_qualification_requires_provenance_policy
BEFORE INSERT ON genre_music_qualification_observations
FOR EACH ROW
WHEN NEW.policy_id IS NOT (
    SELECT policy_id FROM provenance_records WHERE id = NEW.provenance_id
)
BEGIN
    SELECT RAISE(ABORT, 'music genre qualification policy must match provenance');
END;

CREATE TRIGGER genre_music_qualification_is_append_only
BEFORE UPDATE ON genre_music_qualification_observations
BEGIN SELECT RAISE(ABORT, 'music genre qualifications are append-only'); END;

CREATE TRIGGER genre_music_qualification_cannot_be_deleted
BEFORE DELETE ON genre_music_qualification_observations
BEGIN SELECT RAISE(ABORT, 'music genre qualifications are append-only'); END;

CREATE VIEW modelable_music_genres AS
SELECT DISTINCT observation.genre_id
FROM genre_music_qualification_observations AS observation
JOIN provenance_records AS provenance ON provenance.id = observation.provenance_id
JOIN active_rights_policy_permissions AS permission
  ON permission.policy_id = observation.policy_id
 AND permission.use_kind = 'embed'
 AND permission.decision = 'allow'
WHERE NOT EXISTS (
    SELECT 1 FROM active_suppressions AS suppression
    WHERE suppression.use_kind IN ('all', 'embed') AND (
        (suppression.target_kind = 'entity'
         AND suppression.target_ref = CAST(observation.genre_id AS TEXT))
        OR (suppression.target_kind = 'provenance'
            AND suppression.target_ref = CAST(observation.provenance_id AS TEXT))
        OR (suppression.target_kind = 'source'
            AND suppression.target_ref = CAST(provenance.source_id AS TEXT))
    )
);

PRAGMA user_version = 10;

COMMIT;
