PRAGMA foreign_keys = ON;

BEGIN IMMEDIATE;

DROP VIEW displayable_recording_genre_memberships;
DROP VIEW normalizable_recording_genre_memberships;

ALTER TABLE recording_genre_membership_observations
RENAME TO recording_genre_membership_observations_v6;

DROP INDEX recording_genre_membership_pair_idx;
DROP TRIGGER recording_genre_membership_requires_provenance_policy;
DROP TRIGGER recording_genre_membership_is_append_only;
DROP TRIGGER recording_genre_membership_cannot_be_deleted;

CREATE TABLE recording_genre_membership_observations (
    id INTEGER PRIMARY KEY,
    recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE RESTRICT,
    genre_id INTEGER NOT NULL REFERENCES genres(id) ON DELETE RESTRICT,
    evidence_kind TEXT NOT NULL CHECK (evidence_kind IN (
        'musicbrainz_recording_genre', 'wikidata_p136'
    )),
    source_family TEXT NOT NULL CHECK (source_family IN ('musicbrainz', 'wikidata')),
    source_record_id TEXT NOT NULL,
    source_genre_name TEXT NOT NULL,
    source_count INTEGER CHECK (source_count IS NULL OR source_count >= 0),
    method_key TEXT NOT NULL,
    method_version TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    provenance_id INTEGER NOT NULL REFERENCES provenance_records(id) ON DELETE RESTRICT,
    policy_id INTEGER NOT NULL REFERENCES rights_policies(id) ON DELETE RESTRICT,
    record_fingerprint TEXT NOT NULL UNIQUE,
    CHECK (length(trim(source_record_id)) > 0),
    CHECK (length(trim(source_genre_name)) > 0),
    CHECK (length(trim(method_key)) > 0),
    CHECK (length(trim(method_version)) > 0),
    CHECK (
        (evidence_kind = 'musicbrainz_recording_genre'
         AND source_family = 'musicbrainz')
        OR (evidence_kind = 'wikidata_p136'
            AND source_family = 'wikidata')
    ),
    CHECK (
        length(record_fingerprint) = 64
        AND record_fingerprint = lower(record_fingerprint)
        AND record_fingerprint NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

INSERT INTO recording_genre_membership_observations
SELECT * FROM recording_genre_membership_observations_v6;

DROP TABLE recording_genre_membership_observations_v6;

CREATE INDEX recording_genre_membership_pair_idx
    ON recording_genre_membership_observations(genre_id, recording_id);

CREATE TRIGGER recording_genre_membership_requires_provenance_policy
BEFORE INSERT ON recording_genre_membership_observations
FOR EACH ROW
WHEN NEW.policy_id IS NOT (
    SELECT policy_id FROM provenance_records WHERE id = NEW.provenance_id
)
BEGIN
    SELECT RAISE(ABORT, 'recording genre evidence policy must match provenance');
END;

CREATE TRIGGER recording_genre_membership_is_append_only
BEFORE UPDATE ON recording_genre_membership_observations
BEGIN
    SELECT RAISE(ABORT, 'recording genre observations are append-only');
END;

CREATE TRIGGER recording_genre_membership_cannot_be_deleted
BEFORE DELETE ON recording_genre_membership_observations
BEGIN
    SELECT RAISE(ABORT, 'recording genre observations are append-only');
END;

CREATE VIEW normalizable_recording_genre_memberships AS
SELECT observation.*
FROM recording_genre_membership_observations AS observation
JOIN provenance_records AS provenance ON provenance.id = observation.provenance_id
JOIN data_sources AS source ON source.id = provenance.source_id
JOIN active_rights_policy_permissions AS permission
  ON permission.policy_id = observation.policy_id
 AND permission.use_kind = 'normalize'
 AND permission.decision = 'allow'
WHERE NOT EXISTS (
    SELECT 1 FROM active_suppressions AS suppression
    WHERE suppression.use_kind IN ('all', 'normalize') AND (
        (suppression.target_kind = 'entity' AND suppression.target_ref IN (
            CAST(observation.recording_id AS TEXT), CAST(observation.genre_id AS TEXT)
        ))
        OR (suppression.target_kind = 'provenance'
            AND suppression.target_ref = CAST(observation.provenance_id AS TEXT))
        OR (suppression.target_kind = 'source'
            AND suppression.target_ref = CAST(source.id AS TEXT))
    )
);

CREATE VIEW displayable_recording_genre_memberships AS
SELECT observation.*
FROM recording_genre_membership_observations AS observation
JOIN provenance_records AS provenance ON provenance.id = observation.provenance_id
JOIN data_sources AS source ON source.id = provenance.source_id
JOIN active_rights_policy_permissions AS permission
  ON permission.policy_id = observation.policy_id
 AND permission.use_kind = 'display'
 AND permission.decision = 'allow'
WHERE NOT EXISTS (
    SELECT 1 FROM active_suppressions AS suppression
    WHERE suppression.use_kind IN ('all', 'display') AND (
        (suppression.target_kind = 'entity' AND suppression.target_ref IN (
            CAST(observation.recording_id AS TEXT), CAST(observation.genre_id AS TEXT)
        ))
        OR (suppression.target_kind = 'provenance'
            AND suppression.target_ref = CAST(observation.provenance_id AS TEXT))
        OR (suppression.target_kind = 'source'
            AND suppression.target_ref = CAST(source.id AS TEXT))
    )
);

PRAGMA user_version = 9;

COMMIT;
