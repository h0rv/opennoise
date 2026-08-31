PRAGMA foreign_keys = ON;

BEGIN IMMEDIATE;

-- Rights are versioned and deny by default. A missing permission is a denial.
CREATE TABLE rights_policies (
    id INTEGER PRIMARY KEY,
    policy_key TEXT NOT NULL COLLATE NOCASE,
    policy_version INTEGER NOT NULL CHECK (policy_version > 0),
    classification TEXT NOT NULL CHECK (classification IN (
        'public_domain', 'open_license', 'user_authorized_local',
        'restricted_research', 'proprietary', 'unknown'
    )),
    local_only INTEGER NOT NULL DEFAULT 0 CHECK (local_only IN (0, 1)),
    basis TEXT NOT NULL,
    reviewed_at TEXT,
    expires_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (policy_key, policy_version),
    CHECK (length(trim(policy_key)) > 0),
    CHECK (length(trim(basis)) > 0)
) STRICT;

CREATE TRIGGER rights_policies_are_immutable
BEFORE UPDATE ON rights_policies
BEGIN
    SELECT RAISE(ABORT, 'create a new rights policy version instead of changing a policy');
END;

CREATE TRIGGER rights_policies_cannot_be_deleted
BEFORE DELETE ON rights_policies
BEGIN
    SELECT RAISE(ABORT, 'rights policies are immutable');
END;

CREATE TABLE rights_policy_permissions (
    policy_id INTEGER NOT NULL REFERENCES rights_policies(id) ON DELETE CASCADE,
    use_kind TEXT NOT NULL CHECK (use_kind IN (
        'normalize', 'local_search', 'display', 'embed', 'train', 'export'
    )),
    decision TEXT NOT NULL CHECK (decision IN ('allow', 'deny', 'unknown')),
    reason TEXT NOT NULL,
    PRIMARY KEY (policy_id, use_kind),
    CHECK (length(trim(reason)) > 0)
) STRICT;

CREATE TABLE rights_policy_seals (
    policy_id INTEGER PRIMARY KEY REFERENCES rights_policies(id) ON DELETE RESTRICT,
    sealed_at TEXT NOT NULL
) STRICT;

CREATE TRIGGER rights_policy_permissions_reject_sealed_policy
BEFORE INSERT ON rights_policy_permissions
FOR EACH ROW
WHEN EXISTS (SELECT 1 FROM rights_policy_seals WHERE policy_id = NEW.policy_id)
BEGIN
    SELECT RAISE(ABORT, 'create a new rights policy version instead of adding a permission');
END;

CREATE TRIGGER rights_policy_permissions_reject_local_only_export
BEFORE INSERT ON rights_policy_permissions
FOR EACH ROW
WHEN NEW.use_kind = 'export'
 AND NEW.decision = 'allow'
 AND (SELECT local_only FROM rights_policies WHERE id = NEW.policy_id) = 1
BEGIN
    SELECT RAISE(ABORT, 'a local-only policy cannot allow export');
END;

CREATE TRIGGER rights_policy_seals_are_immutable
BEFORE UPDATE ON rights_policy_seals
BEGIN
    SELECT RAISE(ABORT, 'rights policy seals are immutable');
END;

CREATE TRIGGER rights_policy_seals_cannot_be_deleted
BEFORE DELETE ON rights_policy_seals
BEGIN
    SELECT RAISE(ABORT, 'rights policy seals are immutable');
END;

CREATE VIEW active_rights_policy_permissions AS
SELECT permission.policy_id, permission.use_kind, permission.decision, permission.reason
FROM rights_policy_permissions AS permission
JOIN rights_policy_seals AS seal ON seal.policy_id = permission.policy_id
JOIN rights_policies AS policy ON policy.id = permission.policy_id
WHERE policy.expires_at IS NULL
   OR policy.expires_at > strftime('%Y-%m-%dT%H:%M:%fZ', 'now');

CREATE TRIGGER rights_policy_permissions_are_immutable
BEFORE UPDATE ON rights_policy_permissions
BEGIN
    SELECT RAISE(ABORT, 'create a new rights policy version instead of changing a permission');
END;

CREATE TRIGGER rights_policy_permissions_cannot_be_deleted
BEFORE DELETE ON rights_policy_permissions
BEGIN
    SELECT RAISE(ABORT, 'rights policy permissions are immutable');
END;

CREATE TABLE data_sources (
    id INTEGER PRIMARY KEY,
    source_key TEXT NOT NULL COLLATE NOCASE UNIQUE,
    name TEXT NOT NULL,
    homepage_url TEXT,
    license_name TEXT,
    license_url TEXT,
    attribution_text TEXT,
    acquisition_kind TEXT NOT NULL DEFAULT 'public_download' CHECK (acquisition_kind IN (
        'user_supplied_local', 'public_download', 'public_api', 'generated'
    )),
    default_policy_id INTEGER NOT NULL REFERENCES rights_policies(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (length(trim(source_key)) > 0),
    CHECK (length(trim(name)) > 0)
) STRICT;

-- Raw source bytes and private paths stay outside SQLite. The database stores
-- exact hashes and content addressed vault keys.
CREATE TABLE provenance_records (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE RESTRICT,
    policy_id INTEGER NOT NULL REFERENCES rights_policies(id) ON DELETE RESTRICT,
    snapshot_ref TEXT NOT NULL,
    artifact_sha256 TEXT,
    record_fingerprint TEXT NOT NULL,
    parser_release_ref TEXT NOT NULL,
    ingest_attempt_ref TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (source_id, snapshot_ref, record_fingerprint, parser_release_ref),
    CHECK (length(trim(snapshot_ref)) > 0),
    CHECK (length(trim(parser_release_ref)) > 0),
    CHECK (length(trim(ingest_attempt_ref)) > 0),
    CHECK (
        artifact_sha256 IS NULL OR (
            length(artifact_sha256) = 64
            AND artifact_sha256 = lower(artifact_sha256)
            AND artifact_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    CHECK (
        length(record_fingerprint) = 64
        AND record_fingerprint = lower(record_fingerprint)
        AND record_fingerprint NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE TRIGGER provenance_requires_normalize_permission
BEFORE INSERT ON provenance_records
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1 FROM active_rights_policy_permissions
    WHERE policy_id = NEW.policy_id
      AND use_kind = 'normalize'
      AND decision = 'allow'
)
BEGIN
    SELECT RAISE(ABORT, 'normalization is not allowed by the rights policy');
END;

CREATE TRIGGER provenance_records_are_immutable
BEFORE UPDATE ON provenance_records
BEGIN
    SELECT RAISE(ABORT, 'provenance records are immutable');
END;

CREATE TABLE catalog_entities (
    id INTEGER PRIMARY KEY,
    entity_kind TEXT NOT NULL CHECK (entity_kind IN (
        'genre', 'artist', 'work', 'recording', 'release_group', 'release',
        'medium', 'track', 'label', 'instrument', 'descriptor', 'collection', 'asset'
    )),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, entity_kind)
) STRICT;

CREATE TRIGGER catalog_entity_kinds_are_immutable
BEFORE UPDATE OF entity_kind ON catalog_entities
FOR EACH ROW
WHEN NEW.entity_kind <> OLD.entity_kind
BEGIN
    SELECT RAISE(ABORT, 'catalog entity kinds are immutable');
END;

CREATE TABLE entity_provenance (
    entity_id INTEGER NOT NULL REFERENCES catalog_entities(id) ON DELETE RESTRICT,
    provenance_id INTEGER NOT NULL REFERENCES provenance_records(id) ON DELETE RESTRICT,
    field_set_json TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(field_set_json) AND json_type(field_set_json) = 'array'),
    is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0, 1)),
    PRIMARY KEY (entity_id, provenance_id)
) STRICT;

CREATE UNIQUE INDEX entity_provenance_one_primary_idx
    ON entity_provenance(entity_id) WHERE is_primary = 1;

CREATE INDEX entity_provenance_source_idx ON entity_provenance(provenance_id);

CREATE TABLE genres (
    id INTEGER PRIMARY KEY,
    entity_kind TEXT NOT NULL DEFAULT 'genre' CHECK (entity_kind = 'genre'),
    slug TEXT NOT NULL COLLATE NOCASE UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    FOREIGN KEY (id, entity_kind)
        REFERENCES catalog_entities(id, entity_kind) ON DELETE CASCADE,
    CHECK (length(trim(slug)) > 0),
    CHECK (length(trim(name)) > 0)
) STRICT;

CREATE TABLE artists (
    id INTEGER PRIMARY KEY,
    entity_kind TEXT NOT NULL DEFAULT 'artist' CHECK (entity_kind = 'artist'),
    artist_kind TEXT,
    disambiguation TEXT,
    begin_year INTEGER CHECK (begin_year IS NULL OR begin_year BETWEEN 1 AND 9999),
    end_year INTEGER CHECK (end_year IS NULL OR end_year BETWEEN 1 AND 9999),
    FOREIGN KEY (id, entity_kind)
        REFERENCES catalog_entities(id, entity_kind) ON DELETE CASCADE
) STRICT;

CREATE TABLE works (
    id INTEGER PRIMARY KEY,
    entity_kind TEXT NOT NULL DEFAULT 'work' CHECK (entity_kind = 'work'),
    work_kind TEXT,
    language_tag TEXT,
    FOREIGN KEY (id, entity_kind)
        REFERENCES catalog_entities(id, entity_kind) ON DELETE CASCADE
) STRICT;

CREATE TABLE recordings (
    id INTEGER PRIMARY KEY,
    entity_kind TEXT NOT NULL DEFAULT 'recording' CHECK (entity_kind = 'recording'),
    duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    is_video INTEGER NOT NULL DEFAULT 0 CHECK (is_video IN (0, 1)),
    disambiguation TEXT,
    FOREIGN KEY (id, entity_kind)
        REFERENCES catalog_entities(id, entity_kind) ON DELETE CASCADE
) STRICT;

CREATE TABLE recording_works (
    recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE RESTRICT,
    relation_kind TEXT NOT NULL DEFAULT 'performance',
    position INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0),
    provenance_id INTEGER NOT NULL REFERENCES provenance_records(id) ON DELETE RESTRICT,
    PRIMARY KEY (recording_id, work_id, relation_kind, provenance_id),
    CHECK (length(trim(relation_kind)) > 0)
) STRICT;

CREATE TABLE release_groups (
    id INTEGER PRIMARY KEY,
    entity_kind TEXT NOT NULL DEFAULT 'release_group' CHECK (entity_kind = 'release_group'),
    group_kind TEXT,
    secondary_kinds_json TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(secondary_kinds_json) AND json_type(secondary_kinds_json) = 'array'),
    FOREIGN KEY (id, entity_kind)
        REFERENCES catalog_entities(id, entity_kind) ON DELETE CASCADE
) STRICT;

CREATE TABLE releases (
    id INTEGER PRIMARY KEY,
    entity_kind TEXT NOT NULL DEFAULT 'release' CHECK (entity_kind = 'release'),
    release_group_id INTEGER NOT NULL REFERENCES release_groups(id) ON DELETE RESTRICT,
    status TEXT,
    packaging TEXT,
    edition_note TEXT,
    FOREIGN KEY (id, entity_kind)
        REFERENCES catalog_entities(id, entity_kind) ON DELETE CASCADE
) STRICT;

CREATE INDEX releases_group_idx ON releases(release_group_id);

CREATE TABLE media (
    id INTEGER PRIMARY KEY,
    entity_kind TEXT NOT NULL DEFAULT 'medium' CHECK (entity_kind = 'medium'),
    release_id INTEGER NOT NULL REFERENCES releases(id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position > 0),
    format TEXT,
    format_detail TEXT,
    track_count INTEGER CHECK (track_count IS NULL OR track_count >= 0),
    FOREIGN KEY (id, entity_kind)
        REFERENCES catalog_entities(id, entity_kind) ON DELETE CASCADE,
    UNIQUE (release_id, position)
) STRICT;

CREATE TABLE tracks (
    id INTEGER PRIMARY KEY,
    entity_kind TEXT NOT NULL DEFAULT 'track' CHECK (entity_kind = 'track'),
    medium_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    recording_id INTEGER REFERENCES recordings(id) ON DELETE RESTRICT,
    position INTEGER NOT NULL CHECK (position > 0),
    number_text TEXT NOT NULL,
    duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    FOREIGN KEY (id, entity_kind)
        REFERENCES catalog_entities(id, entity_kind) ON DELETE CASCADE,
    UNIQUE (medium_id, position),
    CHECK (length(trim(number_text)) > 0)
) STRICT;

CREATE INDEX tracks_recording_idx ON tracks(recording_id);

CREATE TABLE labels (
    id INTEGER PRIMARY KEY,
    entity_kind TEXT NOT NULL DEFAULT 'label' CHECK (entity_kind = 'label'),
    label_kind TEXT,
    disambiguation TEXT,
    FOREIGN KEY (id, entity_kind)
        REFERENCES catalog_entities(id, entity_kind) ON DELETE CASCADE
) STRICT;

CREATE TABLE release_labels (
    release_id INTEGER NOT NULL REFERENCES releases(id) ON DELETE CASCADE,
    label_id INTEGER NOT NULL REFERENCES labels(id) ON DELETE RESTRICT,
    catalog_number TEXT NOT NULL DEFAULT '',
    provenance_id INTEGER NOT NULL REFERENCES provenance_records(id) ON DELETE RESTRICT,
    PRIMARY KEY (release_id, label_id, catalog_number, provenance_id)
) STRICT;

CREATE TABLE instruments (
    id INTEGER PRIMARY KEY,
    entity_kind TEXT NOT NULL DEFAULT 'instrument' CHECK (entity_kind = 'instrument'),
    instrument_kind TEXT,
    description TEXT,
    FOREIGN KEY (id, entity_kind)
        REFERENCES catalog_entities(id, entity_kind) ON DELETE CASCADE
) STRICT;

CREATE TABLE artist_credits (
    id INTEGER PRIMARY KEY,
    credit_key TEXT NOT NULL UNIQUE,
    provenance_id INTEGER REFERENCES provenance_records(id) ON DELETE RESTRICT,
    CHECK (length(trim(credit_key)) > 0)
) STRICT;

CREATE TABLE artist_credit_members (
    artist_credit_id INTEGER NOT NULL REFERENCES artist_credits(id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position >= 0),
    artist_id INTEGER NOT NULL REFERENCES artists(id) ON DELETE RESTRICT,
    credited_name TEXT NOT NULL,
    join_phrase TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (artist_credit_id, position),
    CHECK (length(credited_name) > 0)
) STRICT;

CREATE TABLE entity_artist_credits (
    entity_id INTEGER NOT NULL REFERENCES catalog_entities(id) ON DELETE CASCADE,
    credit_kind TEXT NOT NULL,
    artist_credit_id INTEGER NOT NULL REFERENCES artist_credits(id) ON DELETE RESTRICT,
    provenance_id INTEGER NOT NULL REFERENCES provenance_records(id) ON DELETE RESTRICT,
    PRIMARY KEY (entity_id, credit_kind, artist_credit_id, provenance_id),
    CHECK (length(trim(credit_kind)) > 0)
) STRICT;

CREATE TABLE contributor_roles (
    id INTEGER PRIMARY KEY,
    role_key TEXT NOT NULL COLLATE NOCASE UNIQUE,
    name TEXT NOT NULL,
    CHECK (length(trim(role_key)) > 0),
    CHECK (length(trim(name)) > 0)
) STRICT;

CREATE TABLE contributions (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL REFERENCES catalog_entities(id) ON DELETE CASCADE,
    artist_id INTEGER NOT NULL REFERENCES artists(id) ON DELETE RESTRICT,
    role_id INTEGER NOT NULL REFERENCES contributor_roles(id) ON DELETE RESTRICT,
    instrument_id INTEGER REFERENCES instruments(id) ON DELETE RESTRICT,
    credited_name TEXT,
    position INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0),
    provenance_id INTEGER NOT NULL REFERENCES provenance_records(id) ON DELETE RESTRICT,
    UNIQUE (entity_id, artist_id, role_id, instrument_id, position, provenance_id)
) STRICT;

CREATE UNIQUE INDEX contributions_identity_idx
    ON contributions(
        entity_id, artist_id, role_id, ifnull(instrument_id, 0), position, provenance_id
    );

CREATE TABLE entity_names (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL REFERENCES catalog_entities(id) ON DELETE CASCADE,
    name_kind TEXT NOT NULL CHECK (name_kind IN (
        'primary', 'alias', 'transliteration', 'sort', 'credited'
    )),
    name TEXT NOT NULL,
    language_tag TEXT NOT NULL DEFAULT 'und',
    script_code TEXT CHECK (script_code IS NULL OR length(script_code) = 4),
    is_preferred INTEGER NOT NULL DEFAULT 0 CHECK (is_preferred IN (0, 1)),
    valid_from TEXT,
    valid_to TEXT,
    provenance_id INTEGER NOT NULL REFERENCES provenance_records(id) ON DELETE RESTRICT,
    fingerprint TEXT NOT NULL,
    UNIQUE (entity_id, fingerprint),
    CHECK (length(name) > 0),
    CHECK (length(trim(language_tag)) > 0),
    CHECK (
        length(fingerprint) = 64 AND fingerprint = lower(fingerprint)
        AND fingerprint NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE INDEX entity_names_lookup_idx ON entity_names(name COLLATE NOCASE, language_tag);

CREATE UNIQUE INDEX entity_names_one_preferred_kind_locale_idx
    ON entity_names(entity_id, name_kind, language_tag, ifnull(script_code, ''))
    WHERE is_preferred = 1;

CREATE TABLE identifier_types (
    id INTEGER PRIMARY KEY,
    type_key TEXT NOT NULL COLLATE NOCASE UNIQUE,
    name TEXT NOT NULL,
    normalization_note TEXT,
    CHECK (length(trim(type_key)) > 0),
    CHECK (length(trim(name)) > 0)
) STRICT;

CREATE TABLE entity_identifiers (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL REFERENCES catalog_entities(id) ON DELETE CASCADE,
    identifier_type_id INTEGER NOT NULL REFERENCES identifier_types(id) ON DELETE RESTRICT,
    namespace TEXT NOT NULL DEFAULT '',
    value TEXT NOT NULL,
    normalized_value TEXT NOT NULL,
    provenance_id INTEGER NOT NULL REFERENCES provenance_records(id) ON DELETE RESTRICT,
    valid_from TEXT,
    valid_to TEXT,
    UNIQUE (entity_id, identifier_type_id, namespace, normalized_value, provenance_id),
    CHECK (length(value) > 0),
    CHECK (length(normalized_value) > 0)
) STRICT;

CREATE INDEX entity_identifiers_lookup_idx
    ON entity_identifiers(identifier_type_id, namespace, normalized_value);

CREATE TABLE territories (
    id INTEGER PRIMARY KEY,
    territory_code TEXT NOT NULL COLLATE NOCASE UNIQUE,
    name TEXT NOT NULL,
    CHECK (length(trim(territory_code)) BETWEEN 2 AND 8),
    CHECK (length(trim(name)) > 0)
) STRICT;

CREATE TABLE release_events (
    id INTEGER PRIMARY KEY,
    release_id INTEGER NOT NULL REFERENCES releases(id) ON DELETE CASCADE,
    territory_id INTEGER NOT NULL REFERENCES territories(id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL DEFAULT 'release',
    date_year INTEGER NOT NULL CHECK (date_year BETWEEN 1 AND 9999),
    date_month INTEGER CHECK (date_month IS NULL OR date_month BETWEEN 1 AND 12),
    date_day INTEGER CHECK (date_day IS NULL OR date_day BETWEEN 1 AND 31),
    provenance_id INTEGER NOT NULL REFERENCES provenance_records(id) ON DELETE RESTRICT,
    UNIQUE (release_id, territory_id, event_kind, date_year, date_month, date_day, provenance_id),
    CHECK (date_day IS NULL OR date_month IS NOT NULL),
    CHECK (length(trim(event_kind)) > 0)
) STRICT;

CREATE UNIQUE INDEX release_events_identity_idx
    ON release_events(
        release_id, territory_id, event_kind, date_year,
        ifnull(date_month, 0), ifnull(date_day, 0), provenance_id
    );

CREATE TABLE storefronts (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE RESTRICT,
    storefront_key TEXT NOT NULL,
    name TEXT NOT NULL,
    UNIQUE (source_id, storefront_key),
    CHECK (length(trim(storefront_key)) > 0),
    CHECK (length(trim(name)) > 0)
) STRICT;

CREATE TABLE catalog_availability (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL REFERENCES catalog_entities(id) ON DELETE CASCADE,
    storefront_id INTEGER NOT NULL REFERENCES storefronts(id) ON DELETE RESTRICT,
    territory_id INTEGER NOT NULL REFERENCES territories(id) ON DELETE RESTRICT,
    availability TEXT NOT NULL CHECK (availability IN (
        'available', 'unavailable', 'preorder', 'unknown'
    )),
    restriction_reason TEXT,
    product_key TEXT NOT NULL DEFAULT '',
    delivery_variant TEXT NOT NULL DEFAULT '',
    is_playable INTEGER CHECK (is_playable IS NULL OR is_playable IN (0, 1)),
    valid_from TEXT,
    valid_to TEXT,
    observed_at TEXT NOT NULL,
    provenance_id INTEGER NOT NULL REFERENCES provenance_records(id) ON DELETE RESTRICT,
    UNIQUE (
        entity_id, storefront_id, territory_id, product_key,
        delivery_variant, observed_at, provenance_id
    )
) STRICT;

CREATE TRIGGER catalog_availability_requires_playable_entity
BEFORE INSERT ON catalog_availability
FOR EACH ROW
WHEN (SELECT entity_kind FROM catalog_entities WHERE id = NEW.entity_id)
    NOT IN ('recording', 'release', 'track')
BEGIN
    SELECT RAISE(ABORT, 'availability requires a recording, release, or track');
END;

CREATE TRIGGER catalog_availability_updates_require_playable_entity
BEFORE UPDATE ON catalog_availability
FOR EACH ROW
WHEN (SELECT entity_kind FROM catalog_entities WHERE id = NEW.entity_id)
    NOT IN ('recording', 'release', 'track')
BEGIN
    SELECT RAISE(ABORT, 'availability requires a recording, release, or track');
END;

CREATE TABLE catalog_equivalences (
    id INTEGER PRIMARY KEY,
    left_entity_id INTEGER NOT NULL REFERENCES catalog_entities(id) ON DELETE CASCADE,
    right_entity_id INTEGER NOT NULL REFERENCES catalog_entities(id) ON DELETE CASCADE,
    storefront_id INTEGER REFERENCES storefronts(id) ON DELETE RESTRICT,
    equivalence_kind TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('equivalent', 'different', 'uncertain')),
    provenance_id INTEGER NOT NULL REFERENCES provenance_records(id) ON DELETE RESTRICT,
    CHECK (left_entity_id < right_entity_id)
) STRICT;

CREATE UNIQUE INDEX catalog_equivalences_identity_idx
    ON catalog_equivalences(
        left_entity_id, right_entity_id, ifnull(storefront_id, 0),
        equivalence_kind, provenance_id
    );

CREATE TRIGGER catalog_equivalences_require_same_supported_kind
BEFORE INSERT ON catalog_equivalences
FOR EACH ROW
WHEN (SELECT entity_kind FROM catalog_entities WHERE id = NEW.left_entity_id)
        IS NOT (SELECT entity_kind FROM catalog_entities WHERE id = NEW.right_entity_id)
    OR (SELECT entity_kind FROM catalog_entities WHERE id = NEW.left_entity_id)
        NOT IN ('recording', 'release', 'track')
BEGIN
    SELECT RAISE(ABORT, 'equivalence requires two entities of the same playable kind');
END;

CREATE TRIGGER catalog_equivalence_updates_require_same_supported_kind
BEFORE UPDATE ON catalog_equivalences
FOR EACH ROW
WHEN (SELECT entity_kind FROM catalog_entities WHERE id = NEW.left_entity_id)
        IS NOT (SELECT entity_kind FROM catalog_entities WHERE id = NEW.right_entity_id)
    OR (SELECT entity_kind FROM catalog_entities WHERE id = NEW.left_entity_id)
        NOT IN ('recording', 'release', 'track')
BEGIN
    SELECT RAISE(ABORT, 'equivalence requires two entities of the same playable kind');
END;

CREATE TABLE descriptors (
    id INTEGER PRIMARY KEY,
    entity_kind TEXT NOT NULL DEFAULT 'descriptor' CHECK (entity_kind = 'descriptor'),
    descriptor_kind TEXT NOT NULL CHECK (descriptor_kind IN ('tag', 'mood', 'theme')),
    slug TEXT NOT NULL COLLATE NOCASE UNIQUE,
    FOREIGN KEY (id, entity_kind)
        REFERENCES catalog_entities(id, entity_kind) ON DELETE CASCADE
) STRICT;

CREATE TABLE descriptor_observations (
    id INTEGER PRIMARY KEY,
    subject_entity_id INTEGER NOT NULL REFERENCES catalog_entities(id) ON DELETE CASCADE,
    descriptor_entity_id INTEGER NOT NULL REFERENCES catalog_entities(id) ON DELETE RESTRICT,
    weight REAL,
    rank INTEGER CHECK (rank IS NULL OR rank > 0),
    observed_at TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    provenance_id INTEGER NOT NULL REFERENCES provenance_records(id) ON DELETE RESTRICT,
    fingerprint TEXT NOT NULL UNIQUE,
    CHECK (weight IS NULL OR (weight >= 0.0 AND weight <= 1.0)),
    CHECK (subject_entity_id <> descriptor_entity_id),
    CHECK (
        length(fingerprint) = 64 AND fingerprint = lower(fingerprint)
        AND fingerprint NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE TRIGGER descriptor_observations_require_descriptor_kind
BEFORE INSERT ON descriptor_observations
FOR EACH ROW
WHEN (SELECT entity_kind FROM catalog_entities WHERE id = NEW.descriptor_entity_id)
    NOT IN ('genre', 'descriptor')
BEGIN
    SELECT RAISE(ABORT, 'descriptor observations require a genre, tag, mood, or theme');
END;

CREATE TRIGGER descriptor_observation_updates_require_descriptor_kind
BEFORE UPDATE ON descriptor_observations
FOR EACH ROW
WHEN (SELECT entity_kind FROM catalog_entities WHERE id = NEW.descriptor_entity_id)
    NOT IN ('genre', 'descriptor')
BEGIN
    SELECT RAISE(ABORT, 'descriptor observations require a genre, tag, mood, or theme');
END;

CREATE TABLE metric_definitions (
    id INTEGER PRIMARY KEY,
    metric_key TEXT NOT NULL COLLATE NOCASE UNIQUE,
    name TEXT NOT NULL,
    value_kind TEXT NOT NULL CHECK (value_kind IN ('integer', 'real', 'text', 'json')),
    unit TEXT,
    scale_min REAL,
    scale_max REAL,
    CHECK (length(trim(metric_key)) > 0),
    CHECK (length(trim(name)) > 0),
    CHECK (scale_min IS NULL OR scale_max IS NULL OR scale_min <= scale_max)
) STRICT;

CREATE TABLE metric_observations (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL REFERENCES catalog_entities(id) ON DELETE CASCADE,
    metric_id INTEGER NOT NULL REFERENCES metric_definitions(id) ON DELETE RESTRICT,
    territory_id INTEGER REFERENCES territories(id) ON DELETE RESTRICT,
    integer_value INTEGER,
    real_value REAL,
    text_value TEXT,
    json_value TEXT CHECK (json_value IS NULL OR json_valid(json_value)),
    observed_at TEXT NOT NULL,
    valid_until TEXT,
    provenance_id INTEGER NOT NULL REFERENCES provenance_records(id) ON DELETE RESTRICT,
    fingerprint TEXT NOT NULL UNIQUE,
    CHECK (
        (integer_value IS NOT NULL) + (real_value IS NOT NULL)
        + (text_value IS NOT NULL) + (json_value IS NOT NULL) = 1
    ),
    CHECK (
        length(fingerprint) = 64 AND fingerprint = lower(fingerprint)
        AND fingerprint NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE TRIGGER metric_observations_require_declared_value_kind
BEFORE INSERT ON metric_observations
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1 FROM metric_definitions AS definition
    WHERE definition.id = NEW.metric_id
      AND (
          (definition.value_kind = 'integer' AND NEW.integer_value IS NOT NULL)
          OR (definition.value_kind = 'real' AND NEW.real_value IS NOT NULL)
          OR (definition.value_kind = 'text' AND NEW.text_value IS NOT NULL)
          OR (definition.value_kind = 'json' AND NEW.json_value IS NOT NULL)
      )
      AND (
          definition.scale_min IS NULL
          OR coalesce(NEW.integer_value, NEW.real_value) >= definition.scale_min
      )
      AND (
          definition.scale_max IS NULL
          OR coalesce(NEW.integer_value, NEW.real_value) <= definition.scale_max
      )
)
BEGIN
    SELECT RAISE(ABORT, 'metric value does not match its definition');
END;

CREATE TRIGGER metric_observation_updates_require_declared_value_kind
BEFORE UPDATE ON metric_observations
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1 FROM metric_definitions AS definition
    WHERE definition.id = NEW.metric_id
      AND (
          (definition.value_kind = 'integer' AND NEW.integer_value IS NOT NULL)
          OR (definition.value_kind = 'real' AND NEW.real_value IS NOT NULL)
          OR (definition.value_kind = 'text' AND NEW.text_value IS NOT NULL)
          OR (definition.value_kind = 'json' AND NEW.json_value IS NOT NULL)
      )
      AND (
          definition.scale_min IS NULL
          OR coalesce(NEW.integer_value, NEW.real_value) >= definition.scale_min
      )
      AND (
          definition.scale_max IS NULL
          OR coalesce(NEW.integer_value, NEW.real_value) <= definition.scale_max
      )
)
BEGIN
    SELECT RAISE(ABORT, 'metric value does not match its definition');
END;

CREATE TABLE collections (
    id INTEGER PRIMARY KEY,
    entity_kind TEXT NOT NULL DEFAULT 'collection' CHECK (entity_kind = 'collection'),
    collection_kind TEXT NOT NULL,
    source_id INTEGER REFERENCES data_sources(id) ON DELETE RESTRICT,
    observed_at TEXT,
    FOREIGN KEY (id, entity_kind)
        REFERENCES catalog_entities(id, entity_kind) ON DELETE CASCADE,
    CHECK (length(trim(collection_kind)) > 0)
) STRICT;

CREATE TABLE collection_items (
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position >= 0),
    entity_id INTEGER NOT NULL REFERENCES catalog_entities(id) ON DELETE CASCADE,
    note TEXT,
    provenance_id INTEGER NOT NULL REFERENCES provenance_records(id) ON DELETE RESTRICT,
    PRIMARY KEY (collection_id, position, provenance_id)
) STRICT;

CREATE TABLE assets (
    id INTEGER PRIMARY KEY,
    entity_kind TEXT NOT NULL DEFAULT 'asset' CHECK (entity_kind = 'asset'),
    asset_kind TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    media_type TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    width_px INTEGER CHECK (width_px IS NULL OR width_px > 0),
    height_px INTEGER CHECK (height_px IS NULL OR height_px > 0),
    duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    policy_id INTEGER NOT NULL REFERENCES rights_policies(id) ON DELETE RESTRICT,
    provenance_id INTEGER NOT NULL REFERENCES provenance_records(id) ON DELETE RESTRICT,
    FOREIGN KEY (id, entity_kind)
        REFERENCES catalog_entities(id, entity_kind) ON DELETE CASCADE,
    CHECK (length(trim(asset_kind)) > 0),
    CHECK (length(trim(media_type)) > 0),
    CHECK (
        length(content_sha256) = 64 AND content_sha256 = lower(content_sha256)
        AND content_sha256 NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE VIEW catalog_entity_integrity_violations AS
SELECT entity.id, entity.entity_kind
FROM catalog_entities AS entity
WHERE CASE entity.entity_kind
    WHEN 'genre' THEN NOT EXISTS (SELECT 1 FROM genres WHERE id = entity.id)
    WHEN 'artist' THEN NOT EXISTS (SELECT 1 FROM artists WHERE id = entity.id)
    WHEN 'work' THEN NOT EXISTS (SELECT 1 FROM works WHERE id = entity.id)
    WHEN 'recording' THEN NOT EXISTS (SELECT 1 FROM recordings WHERE id = entity.id)
    WHEN 'release_group' THEN NOT EXISTS (SELECT 1 FROM release_groups WHERE id = entity.id)
    WHEN 'release' THEN NOT EXISTS (SELECT 1 FROM releases WHERE id = entity.id)
    WHEN 'medium' THEN NOT EXISTS (SELECT 1 FROM media WHERE id = entity.id)
    WHEN 'track' THEN NOT EXISTS (SELECT 1 FROM tracks WHERE id = entity.id)
    WHEN 'label' THEN NOT EXISTS (SELECT 1 FROM labels WHERE id = entity.id)
    WHEN 'instrument' THEN NOT EXISTS (SELECT 1 FROM instruments WHERE id = entity.id)
    WHEN 'descriptor' THEN NOT EXISTS (SELECT 1 FROM descriptors WHERE id = entity.id)
    WHEN 'collection' THEN NOT EXISTS (SELECT 1 FROM collections WHERE id = entity.id)
    WHEN 'asset' THEN NOT EXISTS (SELECT 1 FROM assets WHERE id = entity.id)
END;

CREATE TRIGGER assets_require_provenance_policy
BEFORE INSERT ON assets
FOR EACH ROW
WHEN NEW.policy_id IS NOT (SELECT policy_id FROM provenance_records WHERE id = NEW.provenance_id)
BEGIN
    SELECT RAISE(ABORT, 'asset policy must match its provenance policy');
END;

CREATE TRIGGER asset_updates_require_provenance_policy
BEFORE UPDATE ON assets
FOR EACH ROW
WHEN NEW.policy_id IS NOT (SELECT policy_id FROM provenance_records WHERE id = NEW.provenance_id)
BEGIN
    SELECT RAISE(ABORT, 'asset policy must match its provenance policy');
END;

CREATE TABLE asset_links (
    asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    entity_id INTEGER NOT NULL REFERENCES catalog_entities(id) ON DELETE CASCADE,
    asset_role TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0),
    PRIMARY KEY (asset_id, entity_id, asset_role, position),
    CHECK (length(trim(asset_role)) > 0)
) STRICT;

CREATE TABLE copyright_notices (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL REFERENCES catalog_entities(id) ON DELETE CASCADE,
    notice_kind TEXT NOT NULL,
    notice_year INTEGER CHECK (notice_year IS NULL OR notice_year BETWEEN 1 AND 9999),
    holder_name TEXT,
    notice_text TEXT NOT NULL,
    provenance_id INTEGER NOT NULL REFERENCES provenance_records(id) ON DELETE RESTRICT,
    CHECK (length(notice_text) > 0)
) STRICT;

-- Claims preserve source disagreements while canonical tables hold projections.
CREATE TABLE entity_claims (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL REFERENCES catalog_entities(id) ON DELETE RESTRICT,
    claim_type TEXT NOT NULL,
    claim_key TEXT NOT NULL,
    normalized_value_json TEXT NOT NULL CHECK (json_valid(normalized_value_json)),
    language_tag TEXT,
    valid_from TEXT,
    valid_to TEXT,
    asserted_at TEXT NOT NULL,
    provenance_id INTEGER NOT NULL REFERENCES provenance_records(id) ON DELETE RESTRICT,
    policy_id INTEGER NOT NULL REFERENCES rights_policies(id) ON DELETE RESTRICT,
    claim_hash TEXT NOT NULL,
    UNIQUE (entity_id, claim_type, claim_key, provenance_id, claim_hash),
    CHECK (length(trim(claim_type)) > 0),
    CHECK (length(trim(claim_key)) > 0),
    CHECK (
        length(claim_hash) = 64 AND claim_hash = lower(claim_hash)
        AND claim_hash NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE TRIGGER entity_claims_require_provenance_policy
BEFORE INSERT ON entity_claims
FOR EACH ROW
WHEN NEW.policy_id IS NOT (SELECT policy_id FROM provenance_records WHERE id = NEW.provenance_id)
BEGIN
    SELECT RAISE(ABORT, 'claim policy must match its provenance policy');
END;

CREATE TRIGGER entity_claims_are_append_only
BEFORE UPDATE ON entity_claims
BEGIN
    SELECT RAISE(ABORT, 'entity claims are append-only');
END;

CREATE TRIGGER entity_claims_cannot_be_deleted
BEFORE DELETE ON entity_claims
BEGIN
    SELECT RAISE(ABORT, 'entity claims are append-only');
END;

CREATE TABLE claim_resolution_events (
    id INTEGER PRIMARY KEY,
    claim_id INTEGER NOT NULL REFERENCES entity_claims(id) ON DELETE RESTRICT,
    decision TEXT NOT NULL CHECK (decision IN ('accept', 'reject', 'supersede', 'unresolved')),
    resolver_kind TEXT NOT NULL,
    resolver_version TEXT NOT NULL,
    reason TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    decision_fingerprint TEXT NOT NULL UNIQUE,
    CHECK (
        length(decision_fingerprint) = 64
        AND decision_fingerprint = lower(decision_fingerprint)
        AND decision_fingerprint NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE TRIGGER claim_resolution_events_are_append_only
BEFORE UPDATE ON claim_resolution_events
BEGIN
    SELECT RAISE(ABORT, 'claim resolution events are append-only');
END;

CREATE TRIGGER claim_resolution_events_cannot_be_deleted
BEFORE DELETE ON claim_resolution_events
BEGIN
    SELECT RAISE(ABORT, 'claim resolution events are append-only');
END;

CREATE TABLE canonical_claim_selections (
    entity_id INTEGER NOT NULL REFERENCES catalog_entities(id) ON DELETE CASCADE,
    claim_type TEXT NOT NULL,
    claim_key TEXT NOT NULL,
    claim_id INTEGER NOT NULL REFERENCES entity_claims(id) ON DELETE RESTRICT,
    resolution_event_id INTEGER NOT NULL REFERENCES claim_resolution_events(id) ON DELETE RESTRICT,
    PRIMARY KEY (entity_id, claim_type, claim_key)
) STRICT;

CREATE TRIGGER canonical_claim_selections_require_matching_claim
BEFORE INSERT ON canonical_claim_selections
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1
    FROM entity_claims AS claim
    JOIN claim_resolution_events AS resolution ON resolution.claim_id = claim.id
    WHERE claim.id = NEW.claim_id
      AND claim.entity_id = NEW.entity_id
      AND claim.claim_type = NEW.claim_type
      AND claim.claim_key = NEW.claim_key
      AND resolution.id = NEW.resolution_event_id
      AND resolution.decision = 'accept'
)
BEGIN
    SELECT RAISE(ABORT, 'canonical selection requires an accepted matching claim');
END;

CREATE TRIGGER canonical_claim_updates_require_matching_claim
BEFORE UPDATE ON canonical_claim_selections
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1
    FROM entity_claims AS claim
    JOIN claim_resolution_events AS resolution ON resolution.claim_id = claim.id
    WHERE claim.id = NEW.claim_id
      AND claim.entity_id = NEW.entity_id
      AND claim.claim_type = NEW.claim_type
      AND claim.claim_key = NEW.claim_key
      AND resolution.id = NEW.resolution_event_id
      AND resolution.decision = 'accept'
)
BEGIN
    SELECT RAISE(ABORT, 'canonical selection requires an accepted matching claim');
END;

CREATE TABLE entity_match_decisions (
    id INTEGER PRIMARY KEY,
    left_entity_id INTEGER NOT NULL REFERENCES catalog_entities(id) ON DELETE RESTRICT,
    right_entity_id INTEGER NOT NULL REFERENCES catalog_entities(id) ON DELETE RESTRICT,
    decision TEXT NOT NULL CHECK (decision IN ('match', 'no_match', 'uncertain')),
    method_key TEXT NOT NULL,
    method_version TEXT NOT NULL,
    reason_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(reason_json) AND json_type(reason_json) = 'object'),
    provenance_id INTEGER REFERENCES provenance_records(id) ON DELETE RESTRICT,
    decided_at TEXT NOT NULL,
    decision_fingerprint TEXT NOT NULL UNIQUE,
    CHECK (left_entity_id < right_entity_id),
    CHECK (
        length(decision_fingerprint) = 64
        AND decision_fingerprint = lower(decision_fingerprint)
        AND decision_fingerprint NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE TRIGGER entity_match_decisions_require_same_kind
BEFORE INSERT ON entity_match_decisions
FOR EACH ROW
WHEN (SELECT entity_kind FROM catalog_entities WHERE id = NEW.left_entity_id)
    IS NOT (SELECT entity_kind FROM catalog_entities WHERE id = NEW.right_entity_id)
BEGIN
    SELECT RAISE(ABORT, 'identity decisions require entities of the same kind');
END;

CREATE TRIGGER entity_match_decisions_are_append_only
BEFORE UPDATE ON entity_match_decisions
BEGIN
    SELECT RAISE(ABORT, 'entity match decisions are append-only');
END;

CREATE TRIGGER entity_match_decisions_cannot_be_deleted
BEFORE DELETE ON entity_match_decisions
BEGIN
    SELECT RAISE(ABORT, 'entity match decisions are append-only');
END;

CREATE TABLE entity_redirects (
    from_entity_id INTEGER PRIMARY KEY REFERENCES catalog_entities(id) ON DELETE RESTRICT,
    to_entity_id INTEGER NOT NULL REFERENCES catalog_entities(id) ON DELETE RESTRICT,
    match_decision_id INTEGER NOT NULL REFERENCES entity_match_decisions(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    CHECK (from_entity_id <> to_entity_id)
) STRICT;

CREATE TRIGGER entity_redirects_require_match_decision
BEFORE INSERT ON entity_redirects
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1 FROM entity_match_decisions AS decision
    WHERE decision.id = NEW.match_decision_id
      AND decision.decision = 'match'
      AND decision.left_entity_id = min(NEW.from_entity_id, NEW.to_entity_id)
      AND decision.right_entity_id = max(NEW.from_entity_id, NEW.to_entity_id)
)
BEGIN
    SELECT RAISE(ABORT, 'entity redirect requires a matching identity decision');
END;

CREATE TRIGGER entity_redirects_prevent_cycles
BEFORE INSERT ON entity_redirects
FOR EACH ROW
WHEN EXISTS (
    WITH RECURSIVE redirects(entity_id) AS (
        SELECT NEW.to_entity_id
        UNION ALL
        SELECT entity_redirects.to_entity_id
        FROM entity_redirects
        JOIN redirects ON entity_redirects.from_entity_id = redirects.entity_id
    )
    SELECT 1 FROM redirects WHERE entity_id = NEW.from_entity_id
)
BEGIN
    SELECT RAISE(ABORT, 'entity redirect would create a cycle');
END;

CREATE TRIGGER entity_redirects_are_durable
BEFORE UPDATE ON entity_redirects
BEGIN
    SELECT RAISE(ABORT, 'entity redirects are durable');
END;

CREATE TRIGGER entity_redirects_cannot_be_deleted
BEFORE DELETE ON entity_redirects
BEGIN
    SELECT RAISE(ABORT, 'entity redirects are durable');
END;

CREATE TABLE relation_types (
    id INTEGER PRIMARY KEY,
    relation_key TEXT NOT NULL COLLATE NOCASE UNIQUE,
    subject_entity_kind TEXT NOT NULL,
    object_entity_kind TEXT NOT NULL,
    is_symmetric INTEGER NOT NULL DEFAULT 0 CHECK (is_symmetric IN (0, 1)),
    CHECK (length(trim(relation_key)) > 0)
) STRICT;

CREATE TABLE entity_relations (
    id INTEGER PRIMARY KEY,
    relation_type_id INTEGER NOT NULL REFERENCES relation_types(id) ON DELETE RESTRICT,
    subject_entity_id INTEGER NOT NULL REFERENCES catalog_entities(id) ON DELETE CASCADE,
    object_entity_id INTEGER NOT NULL REFERENCES catalog_entities(id) ON DELETE CASCADE,
    relation_instance_key TEXT NOT NULL DEFAULT '',
    properties_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(properties_json) AND json_type(properties_json) = 'object'),
    provenance_id INTEGER NOT NULL REFERENCES provenance_records(id) ON DELETE RESTRICT,
    UNIQUE (
        relation_type_id, subject_entity_id, object_entity_id,
        relation_instance_key, provenance_id
    ),
    CHECK (subject_entity_id <> object_entity_id)
) STRICT;

CREATE TRIGGER entity_relations_require_allowed_kinds
BEFORE INSERT ON entity_relations
FOR EACH ROW
WHEN (SELECT entity_kind FROM catalog_entities WHERE id = NEW.subject_entity_id)
        IS NOT (SELECT subject_entity_kind FROM relation_types WHERE id = NEW.relation_type_id)
    OR (SELECT entity_kind FROM catalog_entities WHERE id = NEW.object_entity_id)
        IS NOT (SELECT object_entity_kind FROM relation_types WHERE id = NEW.relation_type_id)
BEGIN
    SELECT RAISE(ABORT, 'entity relation kinds do not match the relation type');
END;

CREATE TRIGGER symmetric_entity_relations_require_canonical_order
BEFORE INSERT ON entity_relations
FOR EACH ROW
WHEN (SELECT is_symmetric FROM relation_types WHERE id = NEW.relation_type_id) = 1
 AND NEW.subject_entity_id > NEW.object_entity_id
BEGIN
    SELECT RAISE(ABORT, 'symmetric relations require ascending entity IDs');
END;

CREATE TRIGGER genre_hierarchy_prevents_cycles
BEFORE INSERT ON entity_relations
FOR EACH ROW
WHEN (SELECT relation_key FROM relation_types WHERE id = NEW.relation_type_id)
        = 'genre_subgenre_of'
 AND EXISTS (
    WITH RECURSIVE ancestors(entity_id) AS (
        SELECT NEW.object_entity_id
        UNION
        SELECT relation.object_entity_id
        FROM entity_relations AS relation
        JOIN relation_types AS type ON type.id = relation.relation_type_id
        JOIN ancestors ON ancestors.entity_id = relation.subject_entity_id
        WHERE type.relation_key = 'genre_subgenre_of'
    )
    SELECT 1 FROM ancestors WHERE entity_id = NEW.subject_entity_id
 )
BEGIN
    SELECT RAISE(ABORT, 'genre hierarchy relation would create a cycle');
END;

CREATE TRIGGER entity_relation_updates_require_allowed_kinds
BEFORE UPDATE ON entity_relations
FOR EACH ROW
WHEN (SELECT entity_kind FROM catalog_entities WHERE id = NEW.subject_entity_id)
        IS NOT (SELECT subject_entity_kind FROM relation_types WHERE id = NEW.relation_type_id)
    OR (SELECT entity_kind FROM catalog_entities WHERE id = NEW.object_entity_id)
        IS NOT (SELECT object_entity_kind FROM relation_types WHERE id = NEW.relation_type_id)
BEGIN
    SELECT RAISE(ABORT, 'entity relation kinds do not match the relation type');
END;

CREATE TRIGGER symmetric_entity_relation_updates_require_canonical_order
BEFORE UPDATE ON entity_relations
FOR EACH ROW
WHEN (SELECT is_symmetric FROM relation_types WHERE id = NEW.relation_type_id) = 1
 AND NEW.subject_entity_id > NEW.object_entity_id
BEGIN
    SELECT RAISE(ABORT, 'symmetric relations require ascending entity IDs');
END;

CREATE TRIGGER genre_hierarchy_updates_prevent_cycles
BEFORE UPDATE ON entity_relations
FOR EACH ROW
WHEN (SELECT relation_key FROM relation_types WHERE id = NEW.relation_type_id)
        = 'genre_subgenre_of'
 AND EXISTS (
    WITH RECURSIVE ancestors(entity_id) AS (
        SELECT NEW.object_entity_id
        UNION
        SELECT relation.object_entity_id
        FROM entity_relations AS relation
        JOIN relation_types AS type ON type.id = relation.relation_type_id
        JOIN ancestors ON ancestors.entity_id = relation.subject_entity_id
        WHERE type.relation_key = 'genre_subgenre_of'
          AND relation.id <> OLD.id
    )
    SELECT 1 FROM ancestors WHERE entity_id = NEW.subject_entity_id
 )
BEGIN
    SELECT RAISE(ABORT, 'genre hierarchy relation would create a cycle');
END;

INSERT INTO relation_types (
    relation_key, subject_entity_kind, object_entity_kind, is_symmetric
) VALUES
    ('genre_subgenre_of', 'genre', 'genre', 0),
    ('genre_related_to', 'genre', 'genre', 1),
    ('artist_member_of', 'artist', 'artist', 0),
    ('artist_influenced_by', 'artist', 'artist', 0),
    ('work_part_of', 'work', 'work', 0),
    ('work_based_on', 'work', 'work', 0),
    ('recording_remix_of', 'recording', 'recording', 0);

CREATE VIEW genre_hierarchy AS
SELECT
    relation.id AS relation_id,
    relation.subject_entity_id AS child_genre_id,
    relation.object_entity_id AS parent_genre_id,
    relation.provenance_id
FROM entity_relations AS relation
JOIN relation_types AS type ON type.id = relation.relation_type_id
JOIN genres AS child ON child.id = relation.subject_entity_id
JOIN genres AS parent ON parent.id = relation.object_entity_id
WHERE type.relation_key = 'genre_subgenre_of';

CREATE TABLE content_fragments (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL REFERENCES catalog_entities(id) ON DELETE CASCADE,
    fragment_key TEXT NOT NULL,
    fragment_kind TEXT NOT NULL,
    language_tag TEXT NOT NULL DEFAULT 'und',
    content_text TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL,
    provenance_id INTEGER NOT NULL REFERENCES provenance_records(id) ON DELETE RESTRICT,
    policy_id INTEGER NOT NULL REFERENCES rights_policies(id) ON DELETE RESTRICT,
    UNIQUE (entity_id, fragment_key, input_fingerprint),
    CHECK (length(trim(fragment_key)) > 0),
    CHECK (length(trim(fragment_kind)) > 0),
    CHECK (length(content_text) > 0),
    CHECK (
        length(content_sha256) = 64 AND content_sha256 = lower(content_sha256)
        AND content_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    CHECK (
        length(input_fingerprint) = 64 AND input_fingerprint = lower(input_fingerprint)
        AND input_fingerprint NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE TRIGGER content_fragments_require_provenance_policy
BEFORE INSERT ON content_fragments
FOR EACH ROW
WHEN NEW.policy_id IS NOT (SELECT policy_id FROM provenance_records WHERE id = NEW.provenance_id)
BEGIN
    SELECT RAISE(ABORT, 'content policy must match its provenance policy');
END;

CREATE TRIGGER content_fragment_updates_require_provenance_policy
BEFORE UPDATE ON content_fragments
FOR EACH ROW
WHEN NEW.policy_id IS NOT (SELECT policy_id FROM provenance_records WHERE id = NEW.provenance_id)
BEGIN
    SELECT RAISE(ABORT, 'content policy must match its provenance policy');
END;

CREATE TRIGGER content_fragments_require_approved_text_use
BEFORE INSERT ON content_fragments
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1 FROM active_rights_policy_permissions
    WHERE policy_id = NEW.policy_id
      AND use_kind IN ('local_search', 'display', 'embed')
      AND decision = 'allow'
)
BEGIN
    SELECT RAISE(ABORT, 'content fragments require an approved text use');
END;

CREATE VIEW embeddable_content_fragments AS
SELECT fragment.*
FROM content_fragments AS fragment
JOIN provenance_records AS provenance ON provenance.id = fragment.provenance_id
JOIN active_rights_policy_permissions AS permission
  ON permission.policy_id = fragment.policy_id
 AND permission.use_kind = 'embed'
 AND permission.decision = 'allow'
WHERE NOT EXISTS (
    SELECT 1 FROM active_suppressions AS suppression
    WHERE (
        (suppression.target_kind = 'entity'
            AND suppression.target_ref = CAST(fragment.entity_id AS TEXT))
        OR (suppression.target_kind = 'provenance'
            AND suppression.target_ref = CAST(fragment.provenance_id AS TEXT))
        OR (suppression.target_kind = 'source'
            AND suppression.target_ref = CAST(provenance.source_id AS TEXT))
    )
    AND suppression.use_kind IN ('all', 'embed')
);

-- Audio observations are method-versioned without selecting a model or format.
CREATE TABLE audio_feature_definitions (
    id INTEGER PRIMARY KEY,
    feature_key TEXT NOT NULL COLLATE NOCASE UNIQUE,
    name TEXT NOT NULL,
    value_kind TEXT NOT NULL CHECK (value_kind IN ('integer', 'real', 'text', 'json')),
    unit TEXT,
    description TEXT NOT NULL,
    CHECK (length(trim(feature_key)) > 0),
    CHECK (length(trim(name)) > 0)
) STRICT;

CREATE TABLE audio_feature_runs (
    id INTEGER PRIMARY KEY,
    method_key TEXT NOT NULL,
    method_version TEXT NOT NULL,
    config_fingerprint TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL,
    policy_id INTEGER NOT NULL REFERENCES rights_policies(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    UNIQUE (method_key, method_version, config_fingerprint, input_fingerprint),
    CHECK (
        length(config_fingerprint) = 64 AND config_fingerprint = lower(config_fingerprint)
        AND config_fingerprint NOT GLOB '*[^0-9a-f]*'
    ),
    CHECK (
        length(input_fingerprint) = 64 AND input_fingerprint = lower(input_fingerprint)
        AND input_fingerprint NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE TABLE audio_feature_observations (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL REFERENCES catalog_entities(id) ON DELETE CASCADE,
    feature_definition_id INTEGER NOT NULL
        REFERENCES audio_feature_definitions(id) ON DELETE RESTRICT,
    feature_run_id INTEGER NOT NULL REFERENCES audio_feature_runs(id) ON DELETE RESTRICT,
    integer_value INTEGER,
    real_value REAL,
    text_value TEXT,
    json_value TEXT CHECK (json_value IS NULL OR json_valid(json_value)),
    observed_at TEXT NOT NULL,
    provenance_id INTEGER REFERENCES provenance_records(id) ON DELETE RESTRICT,
    UNIQUE (entity_id, feature_definition_id, feature_run_id),
    CHECK (
        (integer_value IS NOT NULL) + (real_value IS NOT NULL)
        + (text_value IS NOT NULL) + (json_value IS NOT NULL) = 1
    )
) STRICT;

CREATE TRIGGER audio_features_require_declared_value_kind
BEFORE INSERT ON audio_feature_observations
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1 FROM audio_feature_definitions AS definition
    WHERE definition.id = NEW.feature_definition_id
      AND (
          (definition.value_kind = 'integer' AND NEW.integer_value IS NOT NULL)
          OR (definition.value_kind = 'real' AND NEW.real_value IS NOT NULL)
          OR (definition.value_kind = 'text' AND NEW.text_value IS NOT NULL)
          OR (definition.value_kind = 'json' AND NEW.json_value IS NOT NULL)
      )
)
BEGIN
    SELECT RAISE(ABORT, 'audio feature value does not match its definition');
END;

CREATE TRIGGER audio_feature_updates_require_declared_value_kind
BEFORE UPDATE ON audio_feature_observations
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1 FROM audio_feature_definitions AS definition
    WHERE definition.id = NEW.feature_definition_id
      AND (
          (definition.value_kind = 'integer' AND NEW.integer_value IS NOT NULL)
          OR (definition.value_kind = 'real' AND NEW.real_value IS NOT NULL)
          OR (definition.value_kind = 'text' AND NEW.text_value IS NOT NULL)
          OR (definition.value_kind = 'json' AND NEW.json_value IS NOT NULL)
      )
)
BEGIN
    SELECT RAISE(ABORT, 'audio feature value does not match its definition');
END;

CREATE TRIGGER audio_feature_runs_require_normalize_permission
BEFORE INSERT ON audio_feature_runs
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1 FROM active_rights_policy_permissions
    WHERE policy_id = NEW.policy_id
      AND use_kind = 'normalize'
      AND decision = 'allow'
)
BEGIN
    SELECT RAISE(ABORT, 'audio feature storage requires normalization permission');
END;

CREATE TRIGGER audio_features_require_recording_or_track
BEFORE INSERT ON audio_feature_observations
FOR EACH ROW
WHEN (SELECT entity_kind FROM catalog_entities WHERE id = NEW.entity_id)
    NOT IN ('recording', 'track')
BEGIN
    SELECT RAISE(ABORT, 'audio features require a recording or track');
END;

CREATE TRIGGER audio_feature_updates_require_recording_or_track
BEFORE UPDATE ON audio_feature_observations
FOR EACH ROW
WHEN (SELECT entity_kind FROM catalog_entities WHERE id = NEW.entity_id)
    NOT IN ('recording', 'track')
BEGIN
    SELECT RAISE(ABORT, 'audio features require a recording or track');
END;

CREATE TRIGGER audio_features_require_provenance_policy
BEFORE INSERT ON audio_feature_observations
FOR EACH ROW
WHEN NEW.provenance_id IS NOT NULL
 AND (SELECT policy_id FROM audio_feature_runs WHERE id = NEW.feature_run_id)
     IS NOT (SELECT policy_id FROM provenance_records WHERE id = NEW.provenance_id)
BEGIN
    SELECT RAISE(ABORT, 'audio feature policy must match its provenance policy');
END;

CREATE TRIGGER audio_feature_updates_require_provenance_policy
BEFORE UPDATE ON audio_feature_observations
FOR EACH ROW
WHEN NEW.provenance_id IS NOT NULL
 AND (SELECT policy_id FROM audio_feature_runs WHERE id = NEW.feature_run_id)
     IS NOT (SELECT policy_id FROM provenance_records WHERE id = NEW.provenance_id)
BEGIN
    SELECT RAISE(ABORT, 'audio feature policy must match its provenance policy');
END;

-- Suppression and purge history are append-only.
CREATE TABLE suppression_events (
    id INTEGER PRIMARY KEY,
    target_kind TEXT NOT NULL CHECK (target_kind IN (
        'source', 'snapshot', 'artifact', 'staged_record', 'source_object',
        'source_object_observation', 'normalization_export', 'provenance',
        'entity', 'claim', 'asset', 'derived_output'
    )),
    target_ref TEXT NOT NULL,
    use_kind TEXT NOT NULL CHECK (use_kind IN (
        'all', 'normalize', 'local_search', 'display', 'embed', 'train', 'export'
    )),
    event_action TEXT NOT NULL CHECK (event_action IN ('suppress', 'release')),
    reason TEXT NOT NULL,
    effective_at TEXT NOT NULL,
    expires_at TEXT,
    event_fingerprint TEXT NOT NULL UNIQUE,
    CHECK (length(trim(target_ref)) > 0),
    CHECK (length(trim(reason)) > 0),
    CHECK (
        length(event_fingerprint) = 64 AND event_fingerprint = lower(event_fingerprint)
        AND event_fingerprint NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE TRIGGER suppression_events_are_append_only
BEFORE UPDATE ON suppression_events
BEGIN
    SELECT RAISE(ABORT, 'suppression events are append-only');
END;

CREATE TRIGGER suppression_events_cannot_be_deleted
BEFORE DELETE ON suppression_events
BEGIN
    SELECT RAISE(ABORT, 'suppression events are append-only');
END;

CREATE VIEW active_suppressions AS
SELECT event.target_kind, event.target_ref, event.use_kind, event.reason, event.effective_at
FROM suppression_events AS event
WHERE event.id = (
    SELECT latest.id FROM suppression_events AS latest
    WHERE latest.target_kind = event.target_kind
      AND latest.target_ref = event.target_ref
      AND latest.use_kind = event.use_kind
    ORDER BY latest.effective_at DESC, latest.id DESC
    LIMIT 1
)
AND event.event_action = 'suppress'
AND (event.expires_at IS NULL OR event.expires_at > strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));

CREATE TABLE deletion_requests (
    id INTEGER PRIMARY KEY,
    request_ref TEXT NOT NULL UNIQUE,
    target_kind TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    reason TEXT NOT NULL,
    scope_json TEXT NOT NULL CHECK (json_valid(scope_json) AND json_type(scope_json) = 'object')
) STRICT;

CREATE TABLE purge_runs (
    id INTEGER PRIMARY KEY,
    deletion_request_id INTEGER NOT NULL REFERENCES deletion_requests(id) ON DELETE RESTRICT,
    run_fingerprint TEXT NOT NULL UNIQUE,
    started_at TEXT NOT NULL,
    CHECK (
        length(run_fingerprint) = 64 AND run_fingerprint = lower(run_fingerprint)
        AND run_fingerprint NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE TABLE purge_run_events (
    id INTEGER PRIMARY KEY,
    purge_run_id INTEGER NOT NULL REFERENCES purge_runs(id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK (event_kind IN (
        'started', 'raw_purged', 'derived_invalidated', 'backup_accounted',
        'completed', 'failed'
    )),
    event_at TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(details_json) AND json_type(details_json) = 'object')
) STRICT;

CREATE TRIGGER purge_run_events_are_append_only
BEFORE UPDATE ON purge_run_events
BEGIN
    SELECT RAISE(ABORT, 'purge run events are append-only');
END;

CREATE TRIGGER purge_run_events_cannot_be_deleted
BEFORE DELETE ON purge_run_events
BEGIN
    SELECT RAISE(ABORT, 'purge run events are append-only');
END;

CREATE TABLE tombstone_ledger (
    id INTEGER PRIMARY KEY,
    target_kind TEXT NOT NULL,
    target_digest TEXT NOT NULL,
    deletion_request_id INTEGER NOT NULL REFERENCES deletion_requests(id) ON DELETE RESTRICT,
    tombstoned_at TEXT NOT NULL,
    UNIQUE (target_kind, target_digest, deletion_request_id),
    CHECK (
        length(target_digest) = 64 AND target_digest = lower(target_digest)
        AND target_digest NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE TRIGGER tombstone_ledger_is_append_only
BEFORE UPDATE ON tombstone_ledger
BEGIN
    SELECT RAISE(ABORT, 'tombstones are append-only');
END;

CREATE TRIGGER tombstone_ledger_cannot_be_deleted
BEFORE DELETE ON tombstone_ledger
BEGIN
    SELECT RAISE(ABORT, 'tombstones are append-only');
END;

CREATE TABLE derived_outputs (
    id INTEGER PRIMARY KEY,
    output_kind TEXT NOT NULL,
    output_ref TEXT NOT NULL,
    content_sha256 TEXT,
    policy_id INTEGER NOT NULL REFERENCES rights_policies(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    UNIQUE (output_kind, output_ref),
    CHECK (
        content_sha256 IS NULL OR (
            length(content_sha256) = 64 AND content_sha256 = lower(content_sha256)
            AND content_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    )
) STRICT;

CREATE TABLE derivation_edges (
    parent_kind TEXT NOT NULL CHECK (parent_kind IN (
        'provenance', 'claim', 'entity', 'asset', 'content_fragment', 'derived_output'
    )),
    parent_ref TEXT NOT NULL,
    child_output_id INTEGER NOT NULL REFERENCES derived_outputs(id) ON DELETE CASCADE,
    PRIMARY KEY (parent_kind, parent_ref, child_output_id)
) STRICT;

CREATE TABLE derived_output_events (
    id INTEGER PRIMARY KEY,
    derived_output_id INTEGER NOT NULL REFERENCES derived_outputs(id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK (event_kind IN ('created', 'invalidated', 'purged')),
    event_at TEXT NOT NULL,
    purge_run_id INTEGER REFERENCES purge_runs(id) ON DELETE RESTRICT,
    reason TEXT NOT NULL
) STRICT;

CREATE TRIGGER derived_output_events_are_append_only
BEFORE UPDATE ON derived_output_events
BEGIN
    SELECT RAISE(ABORT, 'derived output events are append-only');
END;

CREATE TRIGGER derived_output_events_cannot_be_deleted
BEFORE DELETE ON derived_output_events
BEGIN
    SELECT RAISE(ABORT, 'derived output events are append-only');
END;

CREATE TABLE search_documents (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL REFERENCES catalog_entities(id) ON DELETE CASCADE,
    language_tag TEXT NOT NULL DEFAULT 'und',
    field_kind TEXT NOT NULL,
    search_text TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL,
    provenance_id INTEGER NOT NULL REFERENCES provenance_records(id) ON DELETE RESTRICT,
    policy_id INTEGER NOT NULL REFERENCES rights_policies(id) ON DELETE RESTRICT,
    UNIQUE (entity_id, language_tag, field_kind, input_fingerprint),
    CHECK (length(search_text) > 0),
    CHECK (
        length(input_fingerprint) = 64 AND input_fingerprint = lower(input_fingerprint)
        AND input_fingerprint NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE TRIGGER search_documents_require_provenance_policy
BEFORE INSERT ON search_documents
FOR EACH ROW
WHEN NEW.policy_id IS NOT (SELECT policy_id FROM provenance_records WHERE id = NEW.provenance_id)
BEGIN
    SELECT RAISE(ABORT, 'search policy must match its provenance policy');
END;

CREATE TRIGGER search_document_updates_require_provenance_policy
BEFORE UPDATE ON search_documents
FOR EACH ROW
WHEN NEW.policy_id IS NOT (SELECT policy_id FROM provenance_records WHERE id = NEW.provenance_id)
BEGIN
    SELECT RAISE(ABORT, 'search policy must match its provenance policy');
END;

CREATE TRIGGER search_documents_require_permission
BEFORE INSERT ON search_documents
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1 FROM active_rights_policy_permissions
    WHERE policy_id = NEW.policy_id
      AND use_kind = 'local_search'
      AND decision = 'allow'
)
OR EXISTS (
    SELECT 1
    FROM active_suppressions AS suppression
    JOIN provenance_records AS provenance ON provenance.id = NEW.provenance_id
    WHERE (
        (suppression.target_kind = 'entity'
            AND suppression.target_ref = CAST(NEW.entity_id AS TEXT))
        OR (suppression.target_kind = 'provenance'
            AND suppression.target_ref = CAST(NEW.provenance_id AS TEXT))
        OR (suppression.target_kind = 'source'
            AND suppression.target_ref = CAST(provenance.source_id AS TEXT))
    )
      AND use_kind IN ('all', 'local_search')
)
BEGIN
    SELECT RAISE(ABORT, 'local search is not allowed for this document');
END;

CREATE TRIGGER search_document_updates_require_permission
BEFORE UPDATE ON search_documents
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1 FROM active_rights_policy_permissions
    WHERE policy_id = NEW.policy_id
      AND use_kind = 'local_search'
      AND decision = 'allow'
)
OR EXISTS (
    SELECT 1
    FROM active_suppressions AS suppression
    JOIN provenance_records AS provenance ON provenance.id = NEW.provenance_id
    WHERE (
        (suppression.target_kind = 'entity'
            AND suppression.target_ref = CAST(NEW.entity_id AS TEXT))
        OR (suppression.target_kind = 'provenance'
            AND suppression.target_ref = CAST(NEW.provenance_id AS TEXT))
        OR (suppression.target_kind = 'source'
            AND suppression.target_ref = CAST(provenance.source_id AS TEXT))
    )
      AND use_kind IN ('all', 'local_search')
)
BEGIN
    SELECT RAISE(ABORT, 'local search is not allowed for this document');
END;

CREATE VIRTUAL TABLE search_documents_fts USING fts5(
    search_text,
    entity_id UNINDEXED,
    language_tag UNINDEXED,
    field_kind UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE VIEW searchable_documents AS
SELECT document.*
FROM search_documents AS document
JOIN provenance_records AS provenance ON provenance.id = document.provenance_id
JOIN active_rights_policy_permissions AS permission
  ON permission.policy_id = document.policy_id
 AND permission.use_kind = 'local_search'
 AND permission.decision = 'allow'
WHERE NOT EXISTS (
    SELECT 1
    FROM active_suppressions AS suppression
    WHERE (
        (suppression.target_kind = 'entity'
            AND suppression.target_ref = CAST(document.entity_id AS TEXT))
        OR (suppression.target_kind = 'provenance'
            AND suppression.target_ref = CAST(document.provenance_id AS TEXT))
        OR (suppression.target_kind = 'source'
            AND suppression.target_ref = CAST(provenance.source_id AS TEXT))
    )
      AND suppression.use_kind IN ('all', 'local_search')
);

CREATE TRIGGER search_documents_fts_insert
AFTER INSERT ON search_documents
BEGIN
    INSERT INTO search_documents_fts(
        rowid, search_text, entity_id, language_tag, field_kind
    ) VALUES (NEW.id, NEW.search_text, NEW.entity_id, NEW.language_tag, NEW.field_kind);
END;

CREATE TRIGGER search_documents_fts_delete
AFTER DELETE ON search_documents
BEGIN
    DELETE FROM search_documents_fts WHERE rowid = OLD.id;
END;

CREATE TRIGGER search_documents_fts_update
AFTER UPDATE ON search_documents
BEGIN
    DELETE FROM search_documents_fts WHERE rowid = OLD.id;
    INSERT INTO search_documents_fts(
        rowid, search_text, entity_id, language_tag, field_kind
    ) VALUES (NEW.id, NEW.search_text, NEW.entity_id, NEW.language_tag, NEW.field_kind);
END;

CREATE TRIGGER suppression_removes_search_documents
AFTER INSERT ON suppression_events
FOR EACH ROW
WHEN NEW.event_action = 'suppress'
 AND NEW.use_kind IN ('all', 'local_search')
BEGIN
    DELETE FROM search_documents
    WHERE (NEW.target_kind = 'entity' AND entity_id = CAST(NEW.target_ref AS INTEGER))
       OR (NEW.target_kind = 'provenance' AND provenance_id = CAST(NEW.target_ref AS INTEGER))
       OR (
            NEW.target_kind = 'source'
            AND provenance_id IN (
                SELECT id FROM provenance_records
                WHERE source_id = CAST(NEW.target_ref AS INTEGER)
            )
       );
END;

CREATE VIEW displayable_entity_names AS
SELECT name.*
FROM entity_names AS name
JOIN provenance_records AS provenance ON provenance.id = name.provenance_id
JOIN active_rights_policy_permissions AS permission
  ON permission.policy_id = provenance.policy_id
 AND permission.use_kind = 'display'
 AND permission.decision = 'allow'
WHERE NOT EXISTS (
    SELECT 1
    FROM active_suppressions AS suppression
    WHERE (
        (suppression.target_kind = 'entity'
            AND suppression.target_ref = CAST(name.entity_id AS TEXT))
        OR (suppression.target_kind = 'provenance'
            AND suppression.target_ref = CAST(name.provenance_id AS TEXT))
        OR (suppression.target_kind = 'source'
            AND suppression.target_ref = CAST(provenance.source_id AS TEXT))
    )
      AND suppression.use_kind IN ('all', 'display')
);

CREATE VIEW displayable_assets AS
SELECT asset.*
FROM assets AS asset
JOIN provenance_records AS provenance ON provenance.id = asset.provenance_id
JOIN active_rights_policy_permissions AS permission
  ON permission.policy_id = asset.policy_id
 AND permission.use_kind = 'display'
 AND permission.decision = 'allow'
WHERE NOT EXISTS (
    SELECT 1 FROM active_suppressions AS suppression
    WHERE (
        (suppression.target_kind = 'asset'
            AND suppression.target_ref = CAST(asset.id AS TEXT))
        OR (suppression.target_kind = 'entity' AND (
            suppression.target_ref = CAST(asset.id AS TEXT)
            OR EXISTS (
                SELECT 1 FROM asset_links AS link
                WHERE link.asset_id = asset.id
                  AND suppression.target_ref = CAST(link.entity_id AS TEXT)
            )
        ))
        OR (suppression.target_kind = 'provenance'
            AND suppression.target_ref = CAST(asset.provenance_id AS TEXT))
        OR (suppression.target_kind = 'source'
            AND suppression.target_ref = CAST(provenance.source_id AS TEXT))
    )
      AND suppression.use_kind IN ('all', 'display')
);

CREATE VIEW trainable_content_fragments AS
SELECT fragment.*
FROM content_fragments AS fragment
JOIN provenance_records AS provenance ON provenance.id = fragment.provenance_id
JOIN active_rights_policy_permissions AS permission
  ON permission.policy_id = fragment.policy_id
 AND permission.use_kind = 'train'
 AND permission.decision = 'allow'
WHERE NOT EXISTS (
    SELECT 1 FROM active_suppressions AS suppression
    WHERE (
        (suppression.target_kind = 'entity'
            AND suppression.target_ref = CAST(fragment.entity_id AS TEXT))
        OR (suppression.target_kind = 'provenance'
            AND suppression.target_ref = CAST(fragment.provenance_id AS TEXT))
        OR (suppression.target_kind = 'source'
            AND suppression.target_ref = CAST(provenance.source_id AS TEXT))
    )
      AND suppression.use_kind IN ('all', 'train')
);

CREATE VIEW exportable_entity_names AS
SELECT name.*
FROM entity_names AS name
JOIN provenance_records AS provenance ON provenance.id = name.provenance_id
JOIN active_rights_policy_permissions AS permission
  ON permission.policy_id = provenance.policy_id
 AND permission.use_kind = 'export'
 AND permission.decision = 'allow'
WHERE NOT EXISTS (
    SELECT 1 FROM active_suppressions AS suppression
    WHERE (
        (suppression.target_kind = 'entity'
            AND suppression.target_ref = CAST(name.entity_id AS TEXT))
        OR (suppression.target_kind = 'provenance'
            AND suppression.target_ref = CAST(name.provenance_id AS TEXT))
        OR (suppression.target_kind = 'source'
            AND suppression.target_ref = CAST(provenance.source_id AS TEXT))
    )
      AND suppression.use_kind IN ('all', 'export')
);

-- Ingestion metadata shares the rights and source records used by the
-- normalized catalog. Exact source bytes live in an external vault.
CREATE TABLE source_snapshots (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE RESTRICT,
    snapshot_ref TEXT NOT NULL UNIQUE,
    snapshot_kind TEXT NOT NULL CHECK (snapshot_kind IN ('full', 'delta', 'single_artifact')),
    upstream_version TEXT,
    manifest_sha256 TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    policy_id INTEGER NOT NULL REFERENCES rights_policies(id) ON DELETE RESTRICT,
    CHECK (length(trim(snapshot_ref)) > 0),
    CHECK (
        length(manifest_sha256) = 64
        AND manifest_sha256 = lower(manifest_sha256)
        AND manifest_sha256 NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE TRIGGER source_snapshots_are_immutable
BEFORE UPDATE ON source_snapshots
BEGIN
    SELECT RAISE(ABORT, 'source snapshots are immutable');
END;

CREATE TABLE source_artifacts (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES source_snapshots(id) ON DELETE CASCADE,
    artifact_ref TEXT NOT NULL,
    logical_name TEXT NOT NULL,
    media_type TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    sha256 TEXT NOT NULL,
    vault_key TEXT NOT NULL,
    policy_id INTEGER NOT NULL REFERENCES rights_policies(id) ON DELETE RESTRICT,
    UNIQUE (snapshot_id, artifact_ref),
    CHECK (length(trim(artifact_ref)) > 0),
    CHECK (length(logical_name) > 0),
    CHECK (length(trim(media_type)) > 0),
    CHECK (
        length(sha256) = 64
        AND sha256 = lower(sha256)
        AND sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    CHECK (vault_key = sha256)
) STRICT;

CREATE INDEX source_artifacts_hash_idx ON source_artifacts(sha256);

CREATE TRIGGER source_artifacts_are_immutable
BEFORE UPDATE ON source_artifacts
BEGIN
    SELECT RAISE(ABORT, 'source artifacts are immutable');
END;

CREATE TABLE parser_releases (
    id INTEGER PRIMARY KEY,
    parser_key TEXT NOT NULL COLLATE NOCASE,
    parser_version TEXT NOT NULL,
    build_sha256 TEXT NOT NULL,
    media_type TEXT NOT NULL,
    released_at TEXT NOT NULL,
    UNIQUE (parser_key, parser_version, build_sha256),
    CHECK (length(trim(parser_key)) > 0),
    CHECK (length(trim(parser_version)) > 0),
    CHECK (
        length(build_sha256) = 64
        AND build_sha256 = lower(build_sha256)
        AND build_sha256 NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE TRIGGER parser_releases_are_immutable
BEFORE UPDATE ON parser_releases
BEGIN
    SELECT RAISE(ABORT, 'parser releases are immutable');
END;

CREATE TABLE ingest_attempts (
    id INTEGER PRIMARY KEY,
    attempt_ref TEXT NOT NULL UNIQUE,
    snapshot_id INTEGER NOT NULL REFERENCES source_snapshots(id) ON DELETE RESTRICT,
    parser_release_id INTEGER NOT NULL REFERENCES parser_releases(id) ON DELETE RESTRICT,
    config_sha256 TEXT NOT NULL,
    pipeline_version TEXT NOT NULL,
    policy_id INTEGER NOT NULL REFERENCES rights_policies(id) ON DELETE RESTRICT,
    attempt_fingerprint TEXT NOT NULL UNIQUE,
    max_artifact_bytes INTEGER NOT NULL CHECK (max_artifact_bytes > 0),
    max_record_bytes INTEGER NOT NULL CHECK (max_record_bytes > 0),
    max_records INTEGER NOT NULL CHECK (max_records > 0),
    max_nesting_depth INTEGER NOT NULL CHECK (max_nesting_depth > 0),
    max_decompression_ratio REAL NOT NULL CHECK (max_decompression_ratio > 0),
    timeout_ms INTEGER NOT NULL CHECK (timeout_ms > 0),
    started_at TEXT NOT NULL,
    CHECK (length(trim(attempt_ref)) > 0),
    CHECK (
        length(config_sha256) = 64
        AND config_sha256 = lower(config_sha256)
        AND config_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    CHECK (
        length(attempt_fingerprint) = 64
        AND attempt_fingerprint = lower(attempt_fingerprint)
        AND attempt_fingerprint NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE TRIGGER ingest_attempts_are_immutable
BEFORE UPDATE ON ingest_attempts
BEGIN
    SELECT RAISE(ABORT, 'ingest attempts are immutable');
END;

CREATE TABLE ingest_attempt_events (
    id INTEGER PRIMARY KEY,
    ingest_attempt_id INTEGER NOT NULL REFERENCES ingest_attempts(id) ON DELETE CASCADE,
    stage TEXT NOT NULL CHECK (stage IN (
        'discover', 'verify', 'parse', 'stage', 'normalize', 'project', 'complete'
    )),
    event_kind TEXT NOT NULL CHECK (event_kind IN (
        'started', 'checkpoint', 'succeeded', 'failed', 'cancelled'
    )),
    event_at TEXT NOT NULL,
    counters_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(counters_json) AND json_type(counters_json) = 'object'),
    error_code TEXT,
    error_text TEXT
) STRICT;

CREATE TRIGGER ingest_attempt_events_are_append_only
BEFORE UPDATE ON ingest_attempt_events
BEGIN
    SELECT RAISE(ABORT, 'ingest attempt events are append-only');
END;

CREATE TRIGGER ingest_attempt_events_cannot_be_deleted
BEFORE DELETE ON ingest_attempt_events
BEGIN
    SELECT RAISE(ABORT, 'ingest attempt events are append-only');
END;

CREATE TABLE staged_records (
    id INTEGER PRIMARY KEY,
    ingest_attempt_id INTEGER NOT NULL REFERENCES ingest_attempts(id) ON DELETE CASCADE,
    artifact_id INTEGER NOT NULL REFERENCES source_artifacts(id) ON DELETE CASCADE,
    record_ordinal INTEGER NOT NULL CHECK (record_ordinal >= 0),
    byte_offset INTEGER CHECK (byte_offset IS NULL OR byte_offset >= 0),
    byte_length INTEGER CHECK (byte_length IS NULL OR byte_length >= 0),
    exact_record_sha256 TEXT NOT NULL,
    parsed_json TEXT CHECK (parsed_json IS NULL OR json_valid(parsed_json)),
    canonical_json_sha256 TEXT,
    parse_status TEXT NOT NULL CHECK (parse_status IN ('accepted', 'rejected', 'quarantined')),
    record_fingerprint TEXT NOT NULL UNIQUE,
    UNIQUE (ingest_attempt_id, artifact_id, record_ordinal),
    CHECK (
        length(exact_record_sha256) = 64
        AND exact_record_sha256 = lower(exact_record_sha256)
        AND exact_record_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    CHECK (
        canonical_json_sha256 IS NULL OR (
            length(canonical_json_sha256) = 64
            AND canonical_json_sha256 = lower(canonical_json_sha256)
            AND canonical_json_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    CHECK (
        length(record_fingerprint) = 64
        AND record_fingerprint = lower(record_fingerprint)
        AND record_fingerprint NOT GLOB '*[^0-9a-f]*'
    ),
    CHECK (parse_status <> 'accepted' OR parsed_json IS NOT NULL)
) STRICT;

CREATE TRIGGER staged_records_require_attempt_artifact_consistency
BEFORE INSERT ON staged_records
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1
    FROM ingest_attempts AS attempt
    JOIN source_artifacts AS artifact ON artifact.id = NEW.artifact_id
    WHERE attempt.id = NEW.ingest_attempt_id
      AND attempt.snapshot_id = artifact.snapshot_id
      AND artifact.byte_size <= attempt.max_artifact_bytes
      AND (NEW.byte_length IS NULL OR NEW.byte_length <= attempt.max_record_bytes)
      AND (NEW.byte_offset IS NULL OR NEW.byte_length IS NULL
           OR NEW.byte_offset + NEW.byte_length <= artifact.byte_size)
      AND (
          SELECT count(*) FROM staged_records AS existing
          WHERE existing.ingest_attempt_id = NEW.ingest_attempt_id
      ) < attempt.max_records
)
BEGIN
    SELECT RAISE(ABORT, 'staged record does not match its attempt, artifact, or safety limits');
END;

CREATE TRIGGER staged_records_are_immutable
BEFORE UPDATE ON staged_records
BEGIN
    SELECT RAISE(ABORT, 'staged records are immutable');
END;

CREATE TABLE source_objects (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE RESTRICT,
    record_kind TEXT NOT NULL,
    namespace TEXT NOT NULL DEFAULT '',
    scope_key TEXT NOT NULL DEFAULT '',
    external_id TEXT NOT NULL,
    first_observed_at TEXT NOT NULL,
    UNIQUE (source_id, record_kind, namespace, scope_key, external_id),
    CHECK (length(trim(record_kind)) > 0),
    CHECK (length(external_id) > 0)
) STRICT;

CREATE INDEX source_objects_lookup_idx
    ON source_objects(source_id, record_kind, namespace, scope_key, external_id);

CREATE TRIGGER source_object_identity_is_immutable
BEFORE UPDATE OF source_id, record_kind, namespace, scope_key, external_id ON source_objects
BEGIN
    SELECT RAISE(ABORT, 'source object identity is immutable');
END;

CREATE TABLE source_object_observations (
    id INTEGER PRIMARY KEY,
    source_object_id INTEGER NOT NULL REFERENCES source_objects(id) ON DELETE RESTRICT,
    staged_record_id INTEGER NOT NULL REFERENCES staged_records(id) ON DELETE RESTRICT,
    object_path TEXT NOT NULL DEFAULT '',
    observation_kind TEXT NOT NULL CHECK (observation_kind IN ('present', 'deleted')),
    source_updated_at TEXT,
    observed_at TEXT NOT NULL,
    observation_fingerprint TEXT NOT NULL UNIQUE,
    UNIQUE (source_object_id, staged_record_id, object_path),
    CHECK (
        length(observation_fingerprint) = 64
        AND observation_fingerprint = lower(observation_fingerprint)
        AND observation_fingerprint NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE TRIGGER source_object_observations_require_matching_source
BEFORE INSERT ON source_object_observations
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1
    FROM source_objects AS object
    JOIN staged_records AS record ON record.id = NEW.staged_record_id
    JOIN source_artifacts AS artifact ON artifact.id = record.artifact_id
    JOIN source_snapshots AS snapshot ON snapshot.id = artifact.snapshot_id
    WHERE object.id = NEW.source_object_id
      AND object.source_id = snapshot.source_id
      AND record.parse_status = 'accepted'
)
BEGIN
    SELECT RAISE(ABORT, 'source object observation requires an accepted record from the same source');
END;

CREATE TRIGGER source_object_observations_are_immutable
BEFORE UPDATE ON source_object_observations
BEGIN
    SELECT RAISE(ABORT, 'source object observations are immutable');
END;

CREATE VIEW latest_source_object_observations AS
SELECT observation.*
FROM source_object_observations AS observation
WHERE observation.id = (
    SELECT latest.id
    FROM source_object_observations AS latest
    WHERE latest.source_object_id = observation.source_object_id
    ORDER BY latest.observed_at DESC, latest.id DESC
    LIMIT 1
);

CREATE VIEW current_source_objects AS
SELECT object.*, observation.staged_record_id, observation.object_path,
       observation.source_updated_at, observation.observed_at
FROM source_objects AS object
JOIN latest_source_object_observations AS observation
  ON observation.source_object_id = object.id
WHERE observation.observation_kind = 'present';

CREATE TABLE quarantine_events (
    id INTEGER PRIMARY KEY,
    artifact_id INTEGER REFERENCES source_artifacts(id) ON DELETE CASCADE,
    staged_record_id INTEGER REFERENCES staged_records(id) ON DELETE CASCADE,
    reason_code TEXT NOT NULL CHECK (reason_code IN (
        'malformed', 'unsupported_media', 'encrypted', 'path_traversal',
        'size_limit', 'record_limit', 'nesting_limit', 'decompression_limit',
        'timeout', 'policy_denied', 'other'
    )),
    diagnostic_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(diagnostic_json) AND json_type(diagnostic_json) = 'object'),
    event_kind TEXT NOT NULL CHECK (event_kind IN ('quarantined', 'released', 'rejected')),
    event_at TEXT NOT NULL,
    reviewer TEXT,
    CHECK (artifact_id IS NOT NULL OR staged_record_id IS NOT NULL)
) STRICT;

CREATE TRIGGER quarantine_events_require_matching_artifact
BEFORE INSERT ON quarantine_events
FOR EACH ROW
WHEN NEW.artifact_id IS NOT NULL
 AND NEW.staged_record_id IS NOT NULL
 AND NEW.artifact_id IS NOT (SELECT artifact_id FROM staged_records WHERE id = NEW.staged_record_id)
BEGIN
    SELECT RAISE(ABORT, 'quarantine event artifact does not match its staged record');
END;

CREATE TRIGGER quarantine_events_are_append_only
BEFORE UPDATE ON quarantine_events
BEGIN
    SELECT RAISE(ABORT, 'quarantine events are append-only');
END;

CREATE TRIGGER quarantine_events_cannot_be_deleted
BEFORE DELETE ON quarantine_events
BEGIN
    SELECT RAISE(ABORT, 'quarantine events are append-only');
END;

CREATE TABLE normalization_exports (
    id INTEGER PRIMARY KEY,
    staged_record_id INTEGER NOT NULL REFERENCES staged_records(id) ON DELETE RESTRICT,
    source_object_observation_id INTEGER NOT NULL
        REFERENCES source_object_observations(id) ON DELETE RESTRICT,
    provenance_id INTEGER REFERENCES provenance_records(id) ON DELETE RESTRICT,
    projection_kind TEXT NOT NULL,
    output_fingerprint TEXT NOT NULL UNIQUE,
    exported_at TEXT NOT NULL,
    CHECK (length(trim(projection_kind)) > 0),
    CHECK (
        length(output_fingerprint) = 64
        AND output_fingerprint = lower(output_fingerprint)
        AND output_fingerprint NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE TRIGGER normalization_exports_require_matching_observation
BEFORE INSERT ON normalization_exports
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1 FROM source_object_observations AS observation
    WHERE observation.id = NEW.source_object_observation_id
      AND observation.staged_record_id = NEW.staged_record_id
)
BEGIN
    SELECT RAISE(ABORT, 'normalization export must match its source object observation');
END;

CREATE TRIGGER normalization_exports_require_permission
BEFORE INSERT ON normalization_exports
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1
    FROM staged_records AS record
    JOIN source_artifacts AS artifact ON artifact.id = record.artifact_id
    JOIN active_rights_policy_permissions AS permission ON permission.policy_id = artifact.policy_id
    WHERE record.id = NEW.staged_record_id
      AND record.parse_status = 'accepted'
      AND permission.use_kind = 'normalize'
      AND permission.decision = 'allow'
)
BEGIN
    SELECT RAISE(ABORT, 'record is quarantined or normalization is denied');
END;

CREATE TRIGGER normalization_exports_reject_suppressed_input
BEFORE INSERT ON normalization_exports
FOR EACH ROW
WHEN EXISTS (
    SELECT 1
    FROM staged_records AS record
    JOIN source_artifacts AS artifact ON artifact.id = record.artifact_id
    JOIN source_object_observations AS observation
      ON observation.id = NEW.source_object_observation_id
    JOIN active_suppressions AS suppression
    WHERE record.id = NEW.staged_record_id
      AND suppression.use_kind IN ('all', 'normalize')
      AND (
          (suppression.target_kind = 'staged_record'
              AND suppression.target_ref = CAST(record.id AS TEXT))
          OR (suppression.target_kind = 'artifact'
              AND suppression.target_ref = CAST(artifact.id AS TEXT))
          OR (suppression.target_kind = 'snapshot'
              AND suppression.target_ref = CAST(artifact.snapshot_id AS TEXT))
          OR (suppression.target_kind = 'source_object'
              AND suppression.target_ref = CAST(observation.source_object_id AS TEXT))
          OR (suppression.target_kind = 'source_object_observation'
              AND suppression.target_ref = CAST(observation.id AS TEXT))
      )
)
BEGIN
    SELECT RAISE(ABORT, 'record is suppressed for normalization');
END;

-- Layout runs are versioned derived artifacts. Publishing a run is explicit.
CREATE TABLE layout_runs (
    id INTEGER PRIMARY KEY,
    layout_key TEXT NOT NULL COLLATE NOCASE,
    revision INTEGER NOT NULL CHECK (revision > 0),
    algorithm_key TEXT NOT NULL,
    algorithm_revision TEXT NOT NULL,
    parameters_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(parameters_json) AND json_type(parameters_json) = 'object'),
    input_fingerprint TEXT NOT NULL,
    random_seed INTEGER,
    status TEXT NOT NULL CHECK (status IN ('pending', 'complete', 'failed', 'superseded')),
    policy_id INTEGER NOT NULL REFERENCES rights_policies(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    completed_at TEXT,
    UNIQUE (layout_key, revision),
    UNIQUE (id, layout_key),
    CHECK (length(trim(layout_key)) > 0),
    CHECK (length(trim(algorithm_key)) > 0),
    CHECK (length(trim(algorithm_revision)) > 0),
    CHECK (
        length(input_fingerprint) = 64
        AND input_fingerprint = lower(input_fingerprint)
        AND input_fingerprint NOT GLOB '*[^0-9a-f]*'
    ),
    CHECK ((status = 'complete') = (completed_at IS NOT NULL))
) STRICT;

CREATE TABLE layout_points (
    layout_run_id INTEGER NOT NULL REFERENCES layout_runs(id) ON DELETE CASCADE,
    entity_id INTEGER NOT NULL REFERENCES catalog_entities(id) ON DELETE CASCADE,
    x REAL NOT NULL CHECK (x BETWEEN -1000000000000.0 AND 1000000000000.0),
    y REAL NOT NULL CHECK (y BETWEEN -1000000000000.0 AND 1000000000000.0),
    display_weight REAL CHECK (
        display_weight IS NULL OR display_weight BETWEEN 0.0 AND 1000000000000.0
    ),
    color_hex TEXT CHECK (
        color_hex IS NULL OR (
            length(color_hex) = 7
            AND substr(color_hex, 1, 1) = '#'
            AND lower(substr(color_hex, 2)) NOT GLOB '*[^0-9a-f]*'
        )
    ),
    metadata_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(metadata_json) AND json_type(metadata_json) = 'object'),
    PRIMARY KEY (layout_run_id, entity_id)
) STRICT;

CREATE INDEX layout_points_entity_idx ON layout_points(entity_id, layout_run_id);

CREATE TABLE current_layouts (
    layout_key TEXT PRIMARY KEY COLLATE NOCASE,
    layout_run_id INTEGER NOT NULL,
    selected_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (layout_run_id, layout_key)
        REFERENCES layout_runs(id, layout_key) ON DELETE RESTRICT
) STRICT;

CREATE TRIGGER current_layouts_require_complete_run
BEFORE INSERT ON current_layouts
FOR EACH ROW
WHEN (SELECT status FROM layout_runs WHERE id = NEW.layout_run_id) <> 'complete'
BEGIN
    SELECT RAISE(ABORT, 'only a complete layout run can be selected');
END;

CREATE TRIGGER current_layout_updates_require_complete_run
BEFORE UPDATE ON current_layouts
FOR EACH ROW
WHEN (SELECT status FROM layout_runs WHERE id = NEW.layout_run_id) <> 'complete'
BEGIN
    SELECT RAISE(ABORT, 'only a complete layout run can be selected');
END;

CREATE VIEW displayable_map_points AS
WITH ranked_names AS (
    SELECT
        name.entity_id,
        name.name,
        row_number() OVER (
            PARTITION BY name.entity_id
            ORDER BY
                (name.name_kind = 'primary') DESC,
                name.is_preferred DESC,
                (name.language_tag = 'und') DESC,
                name.id
        ) AS rank
    FROM displayable_entity_names AS name
)
SELECT
    run.layout_key,
    run.revision AS layout_revision,
    point.entity_id,
    entity.entity_kind,
    name.name,
    point.x,
    point.y,
    point.display_weight,
    point.color_hex,
    point.metadata_json
FROM current_layouts AS current
JOIN layout_runs AS run ON run.id = current.layout_run_id
JOIN active_rights_policy_permissions AS permission
  ON permission.policy_id = run.policy_id
 AND permission.use_kind = 'display'
 AND permission.decision = 'allow'
JOIN layout_points AS point ON point.layout_run_id = run.id
JOIN catalog_entities AS entity ON entity.id = point.entity_id
JOIN ranked_names AS name ON name.entity_id = point.entity_id AND name.rank = 1
WHERE run.status = 'complete'
  AND NOT EXISTS (
      SELECT 1
      FROM active_suppressions AS suppression
      WHERE suppression.target_kind = 'entity'
        AND suppression.target_ref = CAST(point.entity_id AS TEXT)
        AND suppression.use_kind IN ('all', 'display')
  );

PRAGMA user_version = 1;

COMMIT;
