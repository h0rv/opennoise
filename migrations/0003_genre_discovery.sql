PRAGMA foreign_keys = ON;

BEGIN IMMEDIATE;

CREATE TABLE historical_genre_artist_observations (
    id INTEGER PRIMARY KEY,
    genre_id INTEGER NOT NULL REFERENCES genres(id) ON DELETE RESTRICT,
    source_artist_id TEXT,
    source_artist_name TEXT NOT NULL,
    observation_role TEXT NOT NULL CHECK (observation_role IN (
        'representative', 'genre_page_member'
    )),
    source_local_rank INTEGER CHECK (source_local_rank IS NULL OR source_local_rank > 0),
    source_local_x REAL,
    source_local_y REAL,
    source_revision_date TEXT NOT NULL,
    source_artifact_sha256 TEXT NOT NULL,
    provenance_id INTEGER NOT NULL REFERENCES provenance_records(id) ON DELETE RESTRICT,
    policy_id INTEGER NOT NULL REFERENCES rights_policies(id) ON DELETE RESTRICT,
    record_fingerprint TEXT NOT NULL UNIQUE,
    CHECK (length(trim(source_artist_name)) > 0),
    CHECK (
        (source_local_x IS NULL AND source_local_y IS NULL)
        OR (source_local_x IS NOT NULL AND source_local_y IS NOT NULL)
    ),
    CHECK (
        length(source_artifact_sha256) = 64
        AND source_artifact_sha256 = lower(source_artifact_sha256)
        AND source_artifact_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    CHECK (
        length(record_fingerprint) = 64
        AND record_fingerprint = lower(record_fingerprint)
        AND record_fingerprint NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE INDEX historical_genre_artists_genre_idx
    ON historical_genre_artist_observations(genre_id, observation_role, source_local_rank);

CREATE TABLE historical_genre_track_observations (
    id INTEGER PRIMARY KEY,
    genre_id INTEGER NOT NULL REFERENCES genres(id) ON DELETE RESTRICT,
    artist_observation_id INTEGER
        REFERENCES historical_genre_artist_observations(id) ON DELETE RESTRICT,
    source_track_title TEXT NOT NULL,
    recording_provider TEXT NOT NULL CHECK (recording_provider IN ('spotify')),
    recording_source_id TEXT NOT NULL,
    safe_external_url TEXT,
    legacy_preview_state TEXT NOT NULL CHECK (legacy_preview_state IN (
        'absent', 'disabled_legacy'
    )),
    legacy_preview_url_sha256 TEXT,
    source_revision_date TEXT NOT NULL,
    source_artifact_sha256 TEXT NOT NULL,
    provenance_id INTEGER NOT NULL REFERENCES provenance_records(id) ON DELETE RESTRICT,
    policy_id INTEGER NOT NULL REFERENCES rights_policies(id) ON DELETE RESTRICT,
    record_fingerprint TEXT NOT NULL UNIQUE,
    CHECK (length(trim(source_track_title)) > 0),
    CHECK (
        length(recording_source_id) = 22
        AND recording_source_id NOT GLOB '*[^A-Za-z0-9]*'
    ),
    CHECK (
        safe_external_url IS NULL
        OR safe_external_url = 'https://open.spotify.com/track/' || recording_source_id
    ),
    CHECK (
        legacy_preview_url_sha256 IS NULL OR (
            length(legacy_preview_url_sha256) = 64
            AND legacy_preview_url_sha256 = lower(legacy_preview_url_sha256)
            AND legacy_preview_url_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    CHECK (
        length(source_artifact_sha256) = 64
        AND source_artifact_sha256 = lower(source_artifact_sha256)
        AND source_artifact_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    CHECK (
        length(record_fingerprint) = 64
        AND record_fingerprint = lower(record_fingerprint)
        AND record_fingerprint NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE INDEX historical_genre_tracks_genre_idx
    ON historical_genre_track_observations(genre_id);

CREATE TABLE historical_genre_relation_observations (
    id INTEGER PRIMARY KEY,
    genre_id INTEGER NOT NULL REFERENCES genres(id) ON DELETE RESTRICT,
    related_genre_id INTEGER REFERENCES genres(id) ON DELETE RESTRICT,
    source_related_genre_name TEXT NOT NULL,
    relation_method TEXT NOT NULL CHECK (relation_method IN (
        'artist_overlap', 'audio_similarity', 'historical_unspecified'
    )),
    source_local_rank INTEGER CHECK (source_local_rank IS NULL OR source_local_rank > 0),
    source_revision_date TEXT NOT NULL,
    source_artifact_sha256 TEXT NOT NULL,
    provenance_id INTEGER NOT NULL REFERENCES provenance_records(id) ON DELETE RESTRICT,
    policy_id INTEGER NOT NULL REFERENCES rights_policies(id) ON DELETE RESTRICT,
    record_fingerprint TEXT NOT NULL UNIQUE,
    CHECK (length(trim(source_related_genre_name)) > 0),
    CHECK (genre_id IS NOT related_genre_id),
    CHECK (
        length(source_artifact_sha256) = 64
        AND source_artifact_sha256 = lower(source_artifact_sha256)
        AND source_artifact_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    CHECK (
        length(record_fingerprint) = 64
        AND record_fingerprint = lower(record_fingerprint)
        AND record_fingerprint NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE INDEX historical_genre_relations_genre_idx
    ON historical_genre_relation_observations(genre_id, relation_method, source_local_rank);

CREATE TRIGGER historical_genre_artists_require_matching_policy
BEFORE INSERT ON historical_genre_artist_observations
FOR EACH ROW WHEN NEW.policy_id IS NOT (
    SELECT policy_id FROM provenance_records WHERE id = NEW.provenance_id
)
BEGIN
    SELECT RAISE(ABORT, 'historical artist policy must match provenance policy');
END;

CREATE TRIGGER historical_genre_tracks_require_matching_policy
BEFORE INSERT ON historical_genre_track_observations
FOR EACH ROW WHEN NEW.policy_id IS NOT (
    SELECT policy_id FROM provenance_records WHERE id = NEW.provenance_id
)
BEGIN
    SELECT RAISE(ABORT, 'historical track policy must match provenance policy');
END;

CREATE TRIGGER historical_genre_relations_require_matching_policy
BEFORE INSERT ON historical_genre_relation_observations
FOR EACH ROW WHEN NEW.policy_id IS NOT (
    SELECT policy_id FROM provenance_records WHERE id = NEW.provenance_id
)
BEGIN
    SELECT RAISE(ABORT, 'historical relation policy must match provenance policy');
END;

CREATE TRIGGER historical_genre_artists_are_append_only
BEFORE UPDATE ON historical_genre_artist_observations
BEGIN SELECT RAISE(ABORT, 'historical artist observations are append-only'); END;

CREATE TRIGGER historical_genre_artists_cannot_be_deleted
BEFORE DELETE ON historical_genre_artist_observations
BEGIN SELECT RAISE(ABORT, 'historical artist observations are append-only'); END;

CREATE TRIGGER historical_genre_tracks_are_append_only
BEFORE UPDATE ON historical_genre_track_observations
BEGIN SELECT RAISE(ABORT, 'historical track observations are append-only'); END;

CREATE TRIGGER historical_genre_tracks_cannot_be_deleted
BEFORE DELETE ON historical_genre_track_observations
BEGIN SELECT RAISE(ABORT, 'historical track observations are append-only'); END;

CREATE TRIGGER historical_genre_relations_are_append_only
BEFORE UPDATE ON historical_genre_relation_observations
BEGIN SELECT RAISE(ABORT, 'historical relation observations are append-only'); END;

CREATE TRIGGER historical_genre_relations_cannot_be_deleted
BEFORE DELETE ON historical_genre_relation_observations
BEGIN SELECT RAISE(ABORT, 'historical relation observations are append-only'); END;

CREATE VIEW displayable_historical_genre_artists AS
SELECT observation.*
FROM historical_genre_artist_observations AS observation
JOIN provenance_records AS provenance ON provenance.id = observation.provenance_id
JOIN active_rights_policy_permissions AS permission
  ON permission.policy_id = observation.policy_id
 AND permission.use_kind = 'display' AND permission.decision = 'allow'
WHERE NOT EXISTS (
    SELECT 1 FROM active_suppressions AS suppression
    WHERE suppression.use_kind IN ('all', 'display') AND (
        (suppression.target_kind = 'entity'
            AND suppression.target_ref = CAST(observation.genre_id AS TEXT))
        OR (suppression.target_kind = 'provenance'
            AND suppression.target_ref = CAST(observation.provenance_id AS TEXT))
        OR (suppression.target_kind = 'source'
            AND suppression.target_ref = CAST(provenance.source_id AS TEXT))
    )
);

CREATE VIEW displayable_historical_genre_tracks AS
SELECT observation.*
FROM historical_genre_track_observations AS observation
JOIN provenance_records AS provenance ON provenance.id = observation.provenance_id
JOIN active_rights_policy_permissions AS permission
  ON permission.policy_id = observation.policy_id
 AND permission.use_kind = 'display' AND permission.decision = 'allow'
WHERE NOT EXISTS (
    SELECT 1 FROM active_suppressions AS suppression
    WHERE suppression.use_kind IN ('all', 'display') AND (
        (suppression.target_kind = 'entity'
            AND suppression.target_ref = CAST(observation.genre_id AS TEXT))
        OR (suppression.target_kind = 'provenance'
            AND suppression.target_ref = CAST(observation.provenance_id AS TEXT))
        OR (suppression.target_kind = 'source'
            AND suppression.target_ref = CAST(provenance.source_id AS TEXT))
    )
);

CREATE VIEW displayable_historical_genre_relations AS
SELECT observation.*
FROM historical_genre_relation_observations AS observation
JOIN provenance_records AS provenance ON provenance.id = observation.provenance_id
JOIN active_rights_policy_permissions AS permission
  ON permission.policy_id = observation.policy_id
 AND permission.use_kind = 'display' AND permission.decision = 'allow'
WHERE NOT EXISTS (
    SELECT 1 FROM active_suppressions AS suppression
    WHERE suppression.use_kind IN ('all', 'display') AND (
        (suppression.target_kind = 'entity' AND suppression.target_ref IN (
            CAST(observation.genre_id AS TEXT),
            coalesce(CAST(observation.related_genre_id AS TEXT), '')
        ))
        OR (suppression.target_kind = 'provenance'
            AND suppression.target_ref = CAST(observation.provenance_id AS TEXT))
        OR (suppression.target_kind = 'source'
            AND suppression.target_ref = CAST(provenance.source_id AS TEXT))
    )
);

PRAGMA user_version = 3;

COMMIT;
