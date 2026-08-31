PRAGMA foreign_keys = ON;

BEGIN IMMEDIATE;

CREATE TABLE album_genre_membership_observations (
    id INTEGER PRIMARY KEY,
    release_group_id INTEGER NOT NULL REFERENCES release_groups(id) ON DELETE RESTRICT,
    genre_id INTEGER NOT NULL REFERENCES genres(id) ON DELETE RESTRICT,
    source_release_id INTEGER REFERENCES releases(id) ON DELETE RESTRICT,
    evidence_kind TEXT NOT NULL CHECK (evidence_kind IN (
        'musicbrainz_release_group_genre',
        'musicbrainz_release_genre',
        'wikidata_p136',
        'track_coverage',
        'artist_inference',
        'listener_inference'
    )),
    evidence_level TEXT NOT NULL CHECK (evidence_level IN ('release_group', 'release')),
    source_family TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    source_genre_name TEXT NOT NULL,
    source_count INTEGER CHECK (source_count IS NULL OR source_count >= 0),
    source_total INTEGER CHECK (source_total IS NULL OR source_total >= 0),
    method_key TEXT NOT NULL,
    method_version TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    provenance_id INTEGER NOT NULL REFERENCES provenance_records(id) ON DELETE RESTRICT,
    policy_id INTEGER NOT NULL REFERENCES rights_policies(id) ON DELETE RESTRICT,
    record_fingerprint TEXT NOT NULL UNIQUE,
    CHECK (length(trim(source_family)) > 0),
    CHECK (length(trim(source_record_id)) > 0),
    CHECK (length(trim(source_genre_name)) > 0),
    CHECK (length(trim(method_key)) > 0),
    CHECK (length(trim(method_version)) > 0),
    CHECK (
        (evidence_kind IN (
            'musicbrainz_release_group_genre', 'musicbrainz_release_genre'
        ) AND source_family = 'musicbrainz')
        OR (evidence_kind = 'wikidata_p136' AND source_family = 'wikidata')
        OR evidence_kind IN ('track_coverage', 'artist_inference', 'listener_inference')
    ),
    CHECK (
        (evidence_level = 'release' AND source_release_id IS NOT NULL)
        OR (evidence_level = 'release_group' AND source_release_id IS NULL)
    ),
    CHECK (source_total IS NULL OR source_count IS NULL OR source_count <= source_total),
    CHECK (
        length(record_fingerprint) = 64
        AND record_fingerprint = lower(record_fingerprint)
        AND record_fingerprint NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE INDEX album_genre_membership_pair_idx
    ON album_genre_membership_observations(genre_id, release_group_id, source_family);

CREATE TRIGGER album_genre_membership_requires_provenance_policy
BEFORE INSERT ON album_genre_membership_observations
FOR EACH ROW
WHEN NEW.policy_id IS NOT (
    SELECT policy_id FROM provenance_records WHERE id = NEW.provenance_id
)
BEGIN
    SELECT RAISE(ABORT, 'album genre evidence policy must match its provenance policy');
END;

CREATE TRIGGER album_genre_membership_requires_matching_release_group
BEFORE INSERT ON album_genre_membership_observations
FOR EACH ROW
WHEN NEW.source_release_id IS NOT NULL
 AND NEW.release_group_id IS NOT (
    SELECT release_group_id FROM releases WHERE id = NEW.source_release_id
 )
BEGIN
    SELECT RAISE(ABORT, 'album genre release evidence must name its release group');
END;

CREATE TRIGGER album_genre_membership_is_append_only
BEFORE UPDATE ON album_genre_membership_observations
BEGIN
    SELECT RAISE(ABORT, 'album genre membership observations are append-only');
END;

CREATE TRIGGER album_genre_membership_cannot_be_deleted
BEFORE DELETE ON album_genre_membership_observations
BEGIN
    SELECT RAISE(ABORT, 'album genre membership observations are append-only');
END;

CREATE TABLE album_genre_ranking_runs (
    id INTEGER PRIMARY KEY,
    run_ref TEXT NOT NULL UNIQUE,
    genre_id INTEGER NOT NULL REFERENCES genres(id) ON DELETE RESTRICT,
    strategy_key TEXT NOT NULL CHECK (strategy_key IN (
        'evidence_facets', 'transparent_weighted', 'user_pairwise'
    )),
    strategy_version TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    config_json TEXT NOT NULL
        CHECK (json_valid(config_json) AND json_type(config_json) = 'object'),
    config_sha256 TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL,
    eligibility_rule TEXT NOT NULL,
    policy_id INTEGER NOT NULL REFERENCES rights_policies(id) ON DELETE RESTRICT,
    generated_at TEXT NOT NULL,
    UNIQUE (genre_id, strategy_key, revision),
    CHECK (length(trim(run_ref)) > 0),
    CHECK (length(trim(strategy_version)) > 0),
    CHECK (length(trim(eligibility_rule)) > 0),
    CHECK (
        length(config_sha256) = 64 AND config_sha256 = lower(config_sha256)
        AND config_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    CHECK (
        length(input_fingerprint) = 64 AND input_fingerprint = lower(input_fingerprint)
        AND input_fingerprint NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE TRIGGER album_genre_ranking_runs_require_normalize_permission
BEFORE INSERT ON album_genre_ranking_runs
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1 FROM active_rights_policy_permissions
    WHERE policy_id = NEW.policy_id
      AND use_kind = 'normalize'
      AND decision = 'allow'
)
BEGIN
    SELECT RAISE(ABORT, 'album genre ranking storage requires normalization permission');
END;

CREATE TRIGGER album_genre_ranking_runs_are_append_only
BEFORE UPDATE ON album_genre_ranking_runs
BEGIN
    SELECT RAISE(ABORT, 'album genre ranking runs are append-only');
END;

CREATE TRIGGER album_genre_ranking_runs_cannot_be_deleted
BEFORE DELETE ON album_genre_ranking_runs
BEGIN
    SELECT RAISE(ABORT, 'album genre ranking runs are append-only');
END;

CREATE TABLE album_genre_ranking_items (
    run_id INTEGER NOT NULL REFERENCES album_genre_ranking_runs(id) ON DELETE RESTRICT,
    release_group_id INTEGER NOT NULL REFERENCES release_groups(id) ON DELETE RESTRICT,
    representative_release_id INTEGER REFERENCES releases(id) ON DELETE RESTRICT,
    rank INTEGER NOT NULL CHECK (rank > 0),
    score REAL,
    membership_confidence REAL NOT NULL
        CHECK (membership_confidence BETWEEN 0.0 AND 1.0),
    evidence_coverage REAL NOT NULL CHECK (evidence_coverage BETWEEN 0.0 AND 1.0),
    components_json TEXT NOT NULL
        CHECK (json_valid(components_json) AND json_type(components_json) = 'array'),
    explanation_json TEXT NOT NULL
        CHECK (json_valid(explanation_json) AND json_type(explanation_json) = 'object'),
    PRIMARY KEY (run_id, release_group_id),
    UNIQUE (run_id, rank)
) STRICT;

CREATE TRIGGER album_genre_ranking_items_require_matching_release_group
BEFORE INSERT ON album_genre_ranking_items
FOR EACH ROW
WHEN NEW.representative_release_id IS NOT NULL
 AND NEW.release_group_id IS NOT (
    SELECT release_group_id FROM releases WHERE id = NEW.representative_release_id
 )
BEGIN
    SELECT RAISE(ABORT, 'representative release must belong to the ranked release group');
END;

CREATE TRIGGER album_genre_ranking_items_are_append_only
BEFORE UPDATE ON album_genre_ranking_items
BEGIN
    SELECT RAISE(ABORT, 'album genre ranking items are append-only');
END;

CREATE TRIGGER album_genre_ranking_items_cannot_be_deleted
BEFORE DELETE ON album_genre_ranking_items
BEGIN
    SELECT RAISE(ABORT, 'album genre ranking items are append-only');
END;

CREATE TABLE album_genre_ranking_item_evidence (
    run_id INTEGER NOT NULL,
    release_group_id INTEGER NOT NULL,
    membership_observation_id INTEGER NOT NULL
        REFERENCES album_genre_membership_observations(id) ON DELETE RESTRICT,
    PRIMARY KEY (run_id, release_group_id, membership_observation_id),
    FOREIGN KEY (run_id, release_group_id)
        REFERENCES album_genre_ranking_items(run_id, release_group_id) ON DELETE RESTRICT
) STRICT;

CREATE TRIGGER album_genre_ranking_item_evidence_matches_item
BEFORE INSERT ON album_genre_ranking_item_evidence
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1
    FROM album_genre_ranking_runs AS run
    JOIN album_genre_membership_observations AS observation
      ON observation.id = NEW.membership_observation_id
    WHERE run.id = NEW.run_id
      AND run.genre_id = observation.genre_id
      AND NEW.release_group_id = observation.release_group_id
)
BEGIN
    SELECT RAISE(ABORT, 'ranking evidence must match the ranked genre and release group');
END;

CREATE TRIGGER album_genre_ranking_item_evidence_is_append_only
BEFORE UPDATE ON album_genre_ranking_item_evidence
BEGIN
    SELECT RAISE(ABORT, 'album genre ranking evidence links are append-only');
END;

CREATE TRIGGER album_genre_ranking_item_evidence_cannot_be_deleted
BEFORE DELETE ON album_genre_ranking_item_evidence
BEGIN
    SELECT RAISE(ABORT, 'album genre ranking evidence links are append-only');
END;

CREATE VIEW displayable_album_genre_memberships AS
SELECT observation.*
FROM album_genre_membership_observations AS observation
JOIN provenance_records AS provenance ON provenance.id = observation.provenance_id
JOIN data_sources AS source ON source.id = provenance.source_id
JOIN active_rights_policy_permissions AS permission
  ON permission.policy_id = observation.policy_id
 AND permission.use_kind = 'display'
 AND permission.decision = 'allow'
WHERE NOT EXISTS (
    SELECT 1 FROM active_suppressions AS suppression
    WHERE suppression.use_kind IN ('all', 'display')
      AND (
          (suppression.target_kind = 'entity' AND suppression.target_ref IN (
              CAST(observation.release_group_id AS TEXT),
              CAST(observation.genre_id AS TEXT),
              coalesce(CAST(observation.source_release_id AS TEXT), '')
          ))
          OR (suppression.target_kind = 'provenance'
              AND suppression.target_ref = CAST(observation.provenance_id AS TEXT))
          OR (suppression.target_kind = 'source'
              AND suppression.target_ref = CAST(source.id AS TEXT))
      )
);

CREATE VIEW displayable_album_genre_ranking_items AS
WITH latest_runs AS (
    SELECT genre_id, strategy_key, max(revision) AS revision
    FROM album_genre_ranking_runs
    GROUP BY genre_id, strategy_key
)
SELECT
    run.run_ref,
    run.genre_id,
    run.strategy_key,
    run.strategy_version,
    run.revision,
    item.release_group_id,
    item.representative_release_id,
    item.rank,
    item.score,
    item.membership_confidence,
    item.evidence_coverage,
    item.components_json,
    item.explanation_json,
    run.config_sha256,
    run.input_fingerprint,
    run.generated_at
FROM latest_runs AS latest
JOIN album_genre_ranking_runs AS run
  ON run.genre_id = latest.genre_id
 AND run.strategy_key = latest.strategy_key
 AND run.revision = latest.revision
JOIN active_rights_policy_permissions AS permission
  ON permission.policy_id = run.policy_id
 AND permission.use_kind = 'display'
 AND permission.decision = 'allow'
JOIN album_genre_ranking_items AS item ON item.run_id = run.id
WHERE NOT EXISTS (
    SELECT 1 FROM active_suppressions AS suppression
    WHERE suppression.target_kind = 'entity'
      AND suppression.target_ref IN (
          CAST(run.genre_id AS TEXT),
          CAST(item.release_group_id AS TEXT),
          coalesce(CAST(item.representative_release_id AS TEXT), '')
      )
      AND suppression.use_kind IN ('all', 'display')
)
AND EXISTS (
    SELECT 1
    FROM album_genre_ranking_item_evidence AS link
    JOIN displayable_album_genre_memberships AS observation
      ON observation.id = link.membership_observation_id
    WHERE link.run_id = item.run_id
      AND link.release_group_id = item.release_group_id
)
AND NOT EXISTS (
    SELECT 1
    FROM album_genre_ranking_item_evidence AS link
    WHERE link.run_id = item.run_id
      AND link.release_group_id = item.release_group_id
      AND NOT EXISTS (
          SELECT 1
          FROM displayable_album_genre_memberships AS observation
          WHERE observation.id = link.membership_observation_id
      )
);

PRAGMA user_version = 2;

COMMIT;
