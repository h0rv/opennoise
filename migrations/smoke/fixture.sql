PRAGMA foreign_keys = ON;

CREATE TEMP TABLE smoke_assertions (
    passed INTEGER NOT NULL CHECK (passed = 1)
) STRICT;

INSERT INTO rights_policies (
    id, policy_key, policy_version, classification, basis
) VALUES (1, 'open-fixture', 1, 'open_license', 'Migration smoke fixture');

INSERT INTO rights_policy_permissions (policy_id, use_kind, decision, reason) VALUES
    (1, 'normalize', 'allow', 'Fixture'),
    (1, 'local_search', 'allow', 'Fixture'),
    (1, 'display', 'allow', 'Fixture'),
    (1, 'embed', 'allow', 'Fixture'),
    (1, 'train', 'deny', 'Fixture'),
    (1, 'export', 'deny', 'Fixture');

INSERT INTO rights_policy_seals (policy_id, sealed_at)
VALUES (1, '2026-01-01T00:00:00Z');

INSERT INTO data_sources (id, source_key, name, default_policy_id)
VALUES (1, 'fixture', 'Fixture', 1);

INSERT INTO provenance_records (
    id, source_id, policy_id, snapshot_ref, artifact_sha256,
    record_fingerprint, parser_release_ref, ingest_attempt_ref, observed_at
) VALUES (
    1, 1, 1, 'snapshot-1',
    '0000000000000000000000000000000000000000000000000000000000000000',
    '1111111111111111111111111111111111111111111111111111111111111111',
    'fixture-parser-1', 'attempt-1', '2026-01-01T00:00:00Z'
);

INSERT INTO catalog_entities (id, entity_kind) VALUES
    (1, 'genre'), (2, 'artist'), (3, 'work'), (4, 'recording'),
    (5, 'release_group'), (6, 'release'), (7, 'medium'), (8, 'track'),
    (9, 'label'), (10, 'instrument'), (11, 'descriptor'),
    (12, 'collection'), (13, 'asset'), (14, 'artist'), (15, 'genre'),
    (16, 'recording');

INSERT INTO genres (id, slug, name) VALUES
    (1, 'idm', 'IDM'), (15, 'electronic', 'Electronic');
INSERT INTO artists (id, artist_kind) VALUES (2, 'person'), (14, 'person');
INSERT INTO works (id, work_kind, language_tag) VALUES (3, 'song', 'en');
INSERT INTO recordings (id, duration_ms) VALUES (4, 300000), (16, 300000);
INSERT INTO recording_works (recording_id, work_id, provenance_id) VALUES (4, 3, 1);
INSERT INTO release_groups (id, group_kind) VALUES (5, 'album');
INSERT INTO releases (id, release_group_id, status, packaging)
VALUES (6, 5, 'official', 'digipak');
INSERT INTO media (id, release_id, position, format, track_count)
VALUES (7, 6, 1, 'CD', 1);
INSERT INTO tracks (id, medium_id, recording_id, position, number_text)
VALUES (8, 7, 4, 1, '1');
INSERT INTO labels (id, label_kind) VALUES (9, 'original_production');
INSERT INTO release_labels (release_id, label_id, catalog_number, provenance_id)
VALUES (6, 9, 'FIX-001', 1);
INSERT INTO instruments (id, instrument_kind) VALUES (10, 'electronic');
INSERT INTO descriptors (id, descriptor_kind, slug) VALUES (11, 'mood', 'dreamy');
INSERT INTO collections (id, collection_kind, source_id, observed_at)
VALUES (12, 'editorial_list', 1, '2026-01-01T00:00:00Z');
INSERT INTO assets (
    id, asset_kind, content_sha256, media_type, byte_size, policy_id, provenance_id
) VALUES (
    13, 'cover',
    '2222222222222222222222222222222222222222222222222222222222222222',
    'image/png', 100, 1, 1
);

INSERT INTO entity_provenance (entity_id, provenance_id, is_primary)
SELECT id, 1, 1 FROM catalog_entities;

INSERT INTO entity_names (
    entity_id, name_kind, name, language_tag, is_preferred, provenance_id, fingerprint
) VALUES
    (2, 'primary', 'Aphex Twin', 'en', 1, 1,
        '3333333333333333333333333333333333333333333333333333333333333333'),
    (2, 'alias', 'AFX', 'und', 0, 1,
        '4444444444444444444444444444444444444444444444444444444444444444'),
    (5, 'primary', 'Selected Ambient Works', 'en', 1, 1,
        '5555555555555555555555555555555555555555555555555555555555555555');

INSERT INTO artist_credits (id, credit_key, provenance_id) VALUES (1, 'credit-1', 1);
INSERT INTO artist_credit_members (
    artist_credit_id, position, artist_id, credited_name
) VALUES (1, 0, 2, 'Aphex Twin');
INSERT INTO entity_artist_credits (
    entity_id, credit_kind, artist_credit_id, provenance_id
) VALUES (4, 'primary', 1, 1), (5, 'primary', 1, 1), (8, 'primary', 1, 1);

INSERT INTO contributor_roles (id, role_key, name) VALUES (1, 'performer', 'Performer');
INSERT INTO contributions (
    entity_id, artist_id, role_id, instrument_id, position, provenance_id
) VALUES (4, 2, 1, 10, 0, 1);

INSERT INTO identifier_types (id, type_key, name) VALUES (1, 'isrc', 'ISRC');
INSERT INTO entity_identifiers (
    entity_id, identifier_type_id, value, normalized_value, provenance_id
) VALUES
    (4, 1, 'GB-AAA-26-00001', 'gbaaa2600001', 1),
    (16, 1, 'GB-AAA-26-00001', 'gbaaa2600001', 1);

INSERT INTO territories (id, territory_code, name) VALUES (1, 'US', 'United States');
INSERT INTO release_events (
    release_id, territory_id, date_year, date_month, provenance_id
) VALUES (6, 1, 2026, 1, 1);
INSERT INTO storefronts (id, source_id, storefront_key, name)
VALUES (1, 1, 'us', 'Fixture US');
INSERT INTO catalog_availability (
    entity_id, storefront_id, territory_id, availability,
    restriction_reason, product_key, delivery_variant, is_playable,
    observed_at, provenance_id
) VALUES (
    8, 1, 1, 'available', NULL, 'subscription', 'lossless', 1,
    '2026-01-01T00:00:00Z', 1
);
INSERT INTO catalog_equivalences (
    left_entity_id, right_entity_id, storefront_id,
    equivalence_kind, decision, provenance_id
) VALUES (4, 16, 1, 'storefront_substitute', 'equivalent', 1);

INSERT INTO descriptor_observations (
    subject_entity_id, descriptor_entity_id, weight, observed_at,
    provenance_id, fingerprint
) VALUES (
    2, 1, 0.9, '2026-01-01T00:00:00Z', 1,
    '6666666666666666666666666666666666666666666666666666666666666666'
);

INSERT INTO metric_definitions (
    id, metric_key, name, value_kind, unit, scale_min, scale_max
) VALUES (1, 'fixture_popularity', 'Fixture popularity', 'real', 'score', 0, 100);
INSERT INTO metric_observations (
    entity_id, metric_id, territory_id, real_value, observed_at,
    provenance_id, fingerprint
) VALUES (
    2, 1, 1, 75.0, '2026-01-01T00:00:00Z', 1,
    '7777777777777777777777777777777777777777777777777777777777777777'
);

INSERT INTO collection_items (collection_id, position, entity_id, provenance_id)
VALUES (12, 0, 2, 1);
INSERT INTO asset_links (asset_id, entity_id, asset_role) VALUES (13, 6, 'front_cover');

INSERT INTO entity_relations (
    relation_type_id, subject_entity_id, object_entity_id, provenance_id
) VALUES (
    (SELECT id FROM relation_types WHERE relation_key = 'genre_subgenre_of'),
    1, 15, 1
);

INSERT INTO entity_claims (
    id, entity_id, claim_type, claim_key, normalized_value_json,
    asserted_at, provenance_id, policy_id, claim_hash
) VALUES (
    1, 2, 'name', 'primary', '"Aphex Twin"', '2026-01-01T00:00:00Z', 1, 1,
    '8888888888888888888888888888888888888888888888888888888888888888'
);
INSERT INTO claim_resolution_events (
    id, claim_id, decision, resolver_kind, resolver_version,
    reason, decided_at, decision_fingerprint
) VALUES (
    1, 1, 'accept', 'fixture', '1', 'Fixture', '2026-01-01T00:00:00Z',
    '9999999999999999999999999999999999999999999999999999999999999999'
);
INSERT INTO canonical_claim_selections (
    entity_id, claim_type, claim_key, claim_id, resolution_event_id
) VALUES (2, 'name', 'primary', 1, 1);

INSERT INTO entity_match_decisions (
    id, left_entity_id, right_entity_id, decision, method_key,
    method_version, decided_at, decision_fingerprint
) VALUES (
    1, 2, 14, 'match', 'fixture', '1', '2026-01-01T00:00:00Z',
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
);
INSERT INTO entity_redirects (
    from_entity_id, to_entity_id, match_decision_id, created_at
) VALUES (14, 2, 1, '2026-01-01T00:00:00Z');

INSERT INTO content_fragments (
    entity_id, fragment_key, fragment_kind, content_text, content_sha256,
    input_fingerprint, provenance_id, policy_id
) VALUES (
    2, 'name', 'name', 'Aphex Twin',
    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
    'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc', 1, 1
);

INSERT INTO audio_feature_definitions (
    id, feature_key, name, value_kind, description
) VALUES (1, 'fixture_value', 'Fixture value', 'real', 'Smoke fixture only');
INSERT INTO audio_feature_runs (
    id, method_key, method_version, config_fingerprint,
    input_fingerprint, policy_id, created_at
) VALUES (
    1, 'fixture', '1',
    'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',
    'eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
    1, '2026-01-01T00:00:00Z'
);
INSERT INTO audio_feature_observations (
    entity_id, feature_definition_id, feature_run_id,
    real_value, observed_at, provenance_id
) VALUES (4, 1, 1, 0.5, '2026-01-01T00:00:00Z', 1);

INSERT INTO search_documents (
    entity_id, field_kind, search_text, input_fingerprint, provenance_id, policy_id
) VALUES (
    2, 'primary_name', 'Aphex Twin',
    'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff', 1, 1
);

INSERT INTO smoke_assertions
SELECT count(*) = 1
FROM search_documents_fts AS search
JOIN searchable_documents AS document ON document.id = search.rowid
WHERE search_documents_fts MATCH 'aphex';
INSERT INTO smoke_assertions SELECT count(*) = 1 FROM genre_hierarchy;
INSERT INTO smoke_assertions SELECT count(*) = 1 FROM embeddable_content_fragments;
INSERT INTO smoke_assertions SELECT count(*) = 0 FROM trainable_content_fragments;
INSERT INTO smoke_assertions SELECT count(*) = 0 FROM exportable_entity_names;
INSERT INTO smoke_assertions SELECT count(*) = 1 FROM displayable_assets;
INSERT INTO smoke_assertions SELECT count(*) = 2 FROM entity_identifiers
WHERE normalized_value = 'gbaaa2600001';
INSERT INTO smoke_assertions SELECT count(*) = 1 FROM catalog_availability;
INSERT INTO smoke_assertions SELECT count(*) = 1 FROM catalog_equivalences;

INSERT INTO suppression_events (
    target_kind, target_ref, use_kind, event_action,
    reason, effective_at, event_fingerprint
) VALUES (
    'entity', '6', 'display', 'suppress',
    'Fixture', '2026-01-01T00:00:00Z',
    '1010101010101010101010101010101010101010101010101010101010101010'
);

INSERT INTO smoke_assertions SELECT count(*) = 0 FROM displayable_assets;

INSERT INTO suppression_events (
    target_kind, target_ref, use_kind, event_action,
    reason, effective_at, event_fingerprint
) VALUES (
    'source', '1', 'embed', 'suppress', 'Fixture',
    '2026-01-01T00:00:00Z',
    '1111111111111111111111111111111111111111111111111111111111111110'
);

INSERT INTO smoke_assertions SELECT count(*) = 0 FROM embeddable_content_fragments;

INSERT INTO suppression_events (
    target_kind, target_ref, use_kind, event_action,
    reason, effective_at, event_fingerprint
) VALUES (
    'entity', '2', 'local_search', 'suppress', 'Fixture',
    '2026-01-01T00:00:00Z',
    '1212121212121212121212121212121212121212121212121212121212121212'
);

INSERT INTO smoke_assertions SELECT count(*) = 0 FROM search_documents;
INSERT INTO smoke_assertions SELECT count(*) = 0 FROM search_documents_fts;
INSERT INTO smoke_assertions SELECT count(*) = 0 FROM searchable_documents;

INSERT INTO rights_policies (
    id, policy_key, policy_version, classification, local_only, basis
) VALUES (
    2, 'local-fixture', 1, 'user_authorized_local', 1,
    'User supplied local smoke fixture'
);

INSERT INTO rights_policy_permissions (policy_id, use_kind, decision, reason) VALUES
    (2, 'normalize', 'allow', 'Fixture'),
    (2, 'local_search', 'allow', 'Fixture'),
    (2, 'display', 'deny', 'Fixture'),
    (2, 'embed', 'deny', 'Fixture'),
    (2, 'train', 'deny', 'Fixture'),
    (2, 'export', 'deny', 'Fixture');
INSERT INTO rights_policy_seals (policy_id, sealed_at)
VALUES (2, '2026-01-01T00:00:00Z');

INSERT INTO data_sources (
    id, source_key, name, acquisition_kind, default_policy_id
) VALUES (2, 'local_input', 'Local input', 'user_supplied_local', 2);

INSERT INTO source_snapshots (
    id, source_id, snapshot_ref, snapshot_kind, manifest_sha256, acquired_at, policy_id
) VALUES (
    1, 2, 'local-snapshot-1', 'single_artifact',
    '2020202020202020202020202020202020202020202020202020202020202020',
    '2026-01-01T00:00:00Z', 2
);

INSERT INTO source_artifacts (
    id, snapshot_id, artifact_ref, logical_name, media_type,
    byte_size, sha256, vault_key, policy_id
) VALUES (
    1, 1, 'artifact-1', 'fixture.json', 'application/json', 2,
    '2121212121212121212121212121212121212121212121212121212121212121',
    '2121212121212121212121212121212121212121212121212121212121212121', 2
);

INSERT INTO parser_releases (
    id, parser_key, parser_version, build_sha256, media_type, released_at
) VALUES (
    1, 'fixture-json', '1',
    '2222222222222222222222222222222222222222222222222222222222222222',
    'application/json', '2026-01-01T00:00:00Z'
);

INSERT INTO ingest_attempts (
    id, attempt_ref, snapshot_id, parser_release_id, config_sha256,
    pipeline_version, policy_id, attempt_fingerprint,
    max_artifact_bytes, max_record_bytes, max_records, max_nesting_depth,
    max_decompression_ratio, timeout_ms, started_at
) VALUES (
    1, 'attempt-1', 1, 1,
    '2323232323232323232323232323232323232323232323232323232323232323',
    '1', 2,
    '2424242424242424242424242424242424242424242424242424242424242424',
    1000, 1000, 10, 10, 10.0, 1000, '2026-01-01T00:00:00Z'
);

INSERT INTO staged_records (
    id, ingest_attempt_id, artifact_id, record_ordinal,
    exact_record_sha256, parsed_json, canonical_json_sha256,
    parse_status, record_fingerprint
) VALUES
    (1, 1, 1, 0,
        '2525252525252525252525252525252525252525252525252525252525252525',
        '{}',
        '2626262626262626262626262626262626262626262626262626262626262626',
        'accepted',
        '2727272727272727272727272727272727272727272727272727272727272727'),
    (2, 1, 1, 1,
        '2828282828282828282828282828282828282828282828282828282828282828',
        NULL, NULL, 'quarantined',
        '2929292929292929292929292929292929292929292929292929292929292929');

INSERT INTO source_objects (
    id, source_id, record_kind, namespace, scope_key, external_id, first_observed_at
) VALUES (1, 2, 'artist', 'fixture', '', 'artist-1', '2026-01-01T00:00:00Z');

INSERT INTO source_object_observations (
    id, source_object_id, staged_record_id, observation_kind,
    observed_at, observation_fingerprint
) VALUES (
    1, 1, 1, 'present', '2026-01-01T00:00:00Z',
    '3030303030303030303030303030303030303030303030303030303030303030'
);

INSERT INTO quarantine_events (
    staged_record_id, reason_code, event_kind, event_at
) VALUES (2, 'malformed', 'quarantined', '2026-01-01T00:00:00Z');

INSERT INTO normalization_exports (
    staged_record_id, source_object_observation_id, projection_kind,
    output_fingerprint, exported_at
) VALUES (
    1, 1, 'artist',
    '3131313131313131313131313131313131313131313131313131313131313131',
    '2026-01-01T00:00:00Z'
);

INSERT INTO layout_runs (
    id, layout_key, revision, algorithm_key, algorithm_revision,
    input_fingerprint, status, policy_id, completed_at
) VALUES (
    1, 'genres', 1, 'fixture', '1',
    '3232323232323232323232323232323232323232323232323232323232323232',
    'complete', 1, '2026-01-01T00:00:00Z'
);
INSERT INTO entity_names (
    entity_id, name_kind, name, language_tag, is_preferred, provenance_id, fingerprint
) VALUES (
    1, 'primary', 'IDM', 'und', 1, 1,
    '3333333333333333333333333333333333333333333333333333333333333332'
);
INSERT INTO layout_points (layout_run_id, entity_id, x, y, display_weight, color_hex)
VALUES (1, 1, 0.25, -0.5, 1.0, '#123abc');
INSERT INTO current_layouts (layout_key, layout_run_id) VALUES ('genres', 1);

INSERT INTO smoke_assertions SELECT count(*) = 1 FROM normalization_exports;
INSERT INTO smoke_assertions SELECT count(*) = 1 FROM current_source_objects;
INSERT INTO smoke_assertions SELECT count(*) = 1 FROM quarantine_events;
INSERT INTO smoke_assertions SELECT count(*) = 1 FROM displayable_map_points;
INSERT INTO smoke_assertions SELECT count(*) = 0 FROM pragma_foreign_key_check;
INSERT INTO smoke_assertions SELECT count(*) = 0 FROM catalog_entity_integrity_violations;
INSERT INTO smoke_assertions SELECT integrity_check = 'ok' FROM pragma_integrity_check;
