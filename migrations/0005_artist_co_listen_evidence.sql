PRAGMA foreign_keys = ON;

BEGIN IMMEDIATE;

-- ListenBrainz listener identifiers are deliberately absent. The adapter emits
-- only fixed-window artist-pair aggregates after counting each user once.
CREATE TABLE artist_co_listen_runs (
    id INTEGER PRIMARY KEY,
    run_ref TEXT NOT NULL UNIQUE,
    ingest_attempt_id INTEGER NOT NULL UNIQUE
        REFERENCES ingest_attempts(id) ON DELETE RESTRICT,
    artifact_id INTEGER NOT NULL REFERENCES source_artifacts(id) ON DELETE RESTRICT,
    adapter_key TEXT NOT NULL,
    adapter_version TEXT NOT NULL,
    adapter_build_sha256 TEXT NOT NULL,
    aggregation_version TEXT NOT NULL,
    configuration_sha256 TEXT NOT NULL,
    window_seconds INTEGER NOT NULL CHECK (window_seconds > 0),
    minimum_distinct_users INTEGER NOT NULL CHECK (minimum_distinct_users > 0),
    listens_seen INTEGER NOT NULL CHECK (listens_seen >= 0),
    listens_with_artist_mbid INTEGER NOT NULL CHECK (listens_with_artist_mbid >= 0),
    distinct_artists INTEGER NOT NULL CHECK (distinct_artists >= 0),
    user_windows INTEGER NOT NULL CHECK (user_windows >= 0),
    candidate_pairs INTEGER NOT NULL CHECK (candidate_pairs >= 0),
    emitted_pairs INTEGER NOT NULL CHECK (emitted_pairs >= 0),
    quarantined_records INTEGER NOT NULL CHECK (quarantined_records >= 0),
    minimum_listened_at INTEGER CHECK (minimum_listened_at IS NULL OR minimum_listened_at >= 0),
    maximum_listened_at INTEGER CHECK (maximum_listened_at IS NULL OR maximum_listened_at >= 0),
    elapsed_ms INTEGER NOT NULL CHECK (elapsed_ms >= 0),
    peak_rss_bytes INTEGER NOT NULL CHECK (peak_rss_bytes >= 0),
    completed_at TEXT NOT NULL,
    CHECK (length(trim(run_ref)) > 0),
    CHECK (length(trim(adapter_key)) > 0),
    CHECK (length(trim(adapter_version)) > 0),
    CHECK (length(trim(aggregation_version)) > 0),
    CHECK (listens_with_artist_mbid <= listens_seen),
    CHECK (emitted_pairs <= candidate_pairs),
    CHECK (
        (minimum_listened_at IS NULL AND maximum_listened_at IS NULL)
        OR (minimum_listened_at IS NOT NULL AND maximum_listened_at IS NOT NULL
            AND minimum_listened_at <= maximum_listened_at)
    ),
    CHECK (
        length(adapter_build_sha256) = 64
        AND adapter_build_sha256 = lower(adapter_build_sha256)
        AND adapter_build_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    CHECK (
        length(configuration_sha256) = 64
        AND configuration_sha256 = lower(configuration_sha256)
        AND configuration_sha256 NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE TRIGGER artist_co_listen_runs_require_matching_artifact
BEFORE INSERT ON artist_co_listen_runs
FOR EACH ROW WHEN NOT EXISTS (
    SELECT 1
    FROM ingest_attempts AS attempt
    JOIN source_artifacts AS artifact ON artifact.id = NEW.artifact_id
    WHERE attempt.id = NEW.ingest_attempt_id
      AND attempt.snapshot_id = artifact.snapshot_id
)
BEGIN
    SELECT RAISE(ABORT, 'co-listen run artifact must belong to its ingest attempt');
END;

CREATE TRIGGER artist_co_listen_runs_require_normalize_permission
BEFORE INSERT ON artist_co_listen_runs
FOR EACH ROW WHEN NOT EXISTS (
    SELECT 1
    FROM source_artifacts AS artifact
    JOIN active_rights_policy_permissions AS permission
      ON permission.policy_id = artifact.policy_id
     AND permission.use_kind = 'normalize'
     AND permission.decision = 'allow'
    WHERE artifact.id = NEW.artifact_id
)
BEGIN
    SELECT RAISE(ABORT, 'co-listen run requires normalization permission');
END;

CREATE TRIGGER artist_co_listen_runs_are_append_only
BEFORE UPDATE ON artist_co_listen_runs
BEGIN SELECT RAISE(ABORT, 'co-listen runs are append-only'); END;

CREATE TRIGGER artist_co_listen_runs_cannot_be_deleted
BEFORE DELETE ON artist_co_listen_runs
BEGIN SELECT RAISE(ABORT, 'co-listen runs are append-only'); END;

CREATE TABLE artist_co_listen_evidence (
    id INTEGER PRIMARY KEY,
    ingest_attempt_id INTEGER NOT NULL
        REFERENCES ingest_attempts(id) ON DELETE RESTRICT,
    staged_record_id INTEGER NOT NULL UNIQUE
        REFERENCES staged_records(id) ON DELETE RESTRICT,
    left_artist_source_id TEXT NOT NULL,
    right_artist_source_id TEXT NOT NULL,
    window_start INTEGER NOT NULL CHECK (window_start >= 0),
    window_end INTEGER NOT NULL CHECK (window_end > window_start),
    distinct_user_count INTEGER NOT NULL CHECK (distinct_user_count > 0),
    evidence_fingerprint TEXT NOT NULL UNIQUE,
    UNIQUE (ingest_attempt_id, left_artist_source_id, right_artist_source_id, window_start),
    CHECK (left_artist_source_id GLOB 'musicbrainz:artist:????????-????-????-????-????????????'),
    CHECK (right_artist_source_id GLOB 'musicbrainz:artist:????????-????-????-????-????????????'),
    CHECK (left_artist_source_id < right_artist_source_id),
    CHECK (
        length(evidence_fingerprint) = 64
        AND evidence_fingerprint = lower(evidence_fingerprint)
        AND evidence_fingerprint NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE INDEX artist_co_listen_evidence_left_idx
    ON artist_co_listen_evidence(left_artist_source_id, window_start);
CREATE INDEX artist_co_listen_evidence_right_idx
    ON artist_co_listen_evidence(right_artist_source_id, window_start);

CREATE TRIGGER artist_co_listen_runs_require_complete_evidence
BEFORE INSERT ON artist_co_listen_runs
FOR EACH ROW WHEN
    NEW.emitted_pairs IS NOT (
        SELECT count(*) FROM artist_co_listen_evidence
        WHERE ingest_attempt_id = NEW.ingest_attempt_id
    )
    OR EXISTS (
        SELECT 1 FROM artist_co_listen_evidence
        WHERE ingest_attempt_id = NEW.ingest_attempt_id
          AND (
              distinct_user_count < NEW.minimum_distinct_users
              OR window_end - window_start <> NEW.window_seconds
          )
    )
BEGIN
    SELECT RAISE(ABORT, 'co-listen run does not match its complete evidence set');
END;

CREATE TRIGGER artist_co_listen_evidence_requires_accepted_record
BEFORE INSERT ON artist_co_listen_evidence
FOR EACH ROW WHEN NOT EXISTS (
    SELECT 1
    FROM staged_records AS record
    WHERE record.id = NEW.staged_record_id
      AND record.ingest_attempt_id = NEW.ingest_attempt_id
      AND record.parse_status = 'accepted'
)
BEGIN
    SELECT RAISE(ABORT, 'co-listen evidence requires an accepted aggregate record');
END;

CREATE TRIGGER artist_co_listen_evidence_are_append_only
BEFORE UPDATE ON artist_co_listen_evidence
BEGIN SELECT RAISE(ABORT, 'co-listen evidence is append-only'); END;

CREATE TRIGGER artist_co_listen_evidence_cannot_be_deleted
BEFORE DELETE ON artist_co_listen_evidence
BEGIN SELECT RAISE(ABORT, 'co-listen evidence is append-only'); END;

CREATE VIEW normalizable_artist_co_listen_evidence AS
SELECT evidence.*
FROM artist_co_listen_evidence AS evidence
JOIN artist_co_listen_runs AS run ON run.ingest_attempt_id = evidence.ingest_attempt_id
JOIN source_artifacts AS artifact ON artifact.id = run.artifact_id
JOIN active_rights_policy_permissions AS permission
  ON permission.policy_id = artifact.policy_id
 AND permission.use_kind = 'normalize'
 AND permission.decision = 'allow';

PRAGMA user_version = 5;

COMMIT;
