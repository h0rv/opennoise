PRAGMA foreign_keys = ON;

BEGIN IMMEDIATE;

-- Historical compatibility is deliberately a separately named, immutable
-- projection. It does not turn legacy display coordinates into public-model
-- embeddings or infer missing historical page data.
CREATE TABLE historical_compatibility_runs (
    id INTEGER PRIMARY KEY,
    revision TEXT NOT NULL CHECK (revision = 'historical-compatibility-v1'),
    source_id TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL UNIQUE,
    object_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    UNIQUE (source_sha256, manifest_sha256),
    CHECK (length(trim(source_id)) > 0),
    CHECK (length(trim(object_key)) > 0),
    CHECK (
        length(source_sha256) = 64 AND source_sha256 = lower(source_sha256)
        AND source_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    CHECK (
        length(manifest_sha256) = 64 AND manifest_sha256 = lower(manifest_sha256)
        AND manifest_sha256 NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE TABLE historical_compatibility_coverage (
    run_id INTEGER NOT NULL REFERENCES historical_compatibility_runs(id) ON DELETE RESTRICT,
    stage TEXT NOT NULL CHECK (stage IN ('H1', 'H2', 'H3', 'H4', 'H5', 'H6')),
    state TEXT NOT NULL CHECK (state IN ('complete', 'partial', 'missing')),
    retained_record_count INTEGER NOT NULL CHECK (retained_record_count >= 0),
    quarantined_record_count INTEGER NOT NULL DEFAULT 0 CHECK (quarantined_record_count >= 0),
    expected_record_count INTEGER CHECK (expected_record_count IS NULL OR expected_record_count >= 0),
    retained_fields_json TEXT NOT NULL
        CHECK (json_valid(retained_fields_json) AND json_type(retained_fields_json) = 'array'),
    missing_fields_json TEXT NOT NULL
        CHECK (json_valid(missing_fields_json) AND json_type(missing_fields_json) = 'array'),
    accounting_note TEXT NOT NULL CHECK (length(trim(accounting_note)) > 0),
    PRIMARY KEY (run_id, stage),
    CHECK (
        expected_record_count IS NULL
        OR retained_record_count + quarantined_record_count <= expected_record_count
    ),
    CHECK (
        (state = 'complete' AND json_array_length(missing_fields_json) = 0)
        OR (state != 'complete' AND json_array_length(missing_fields_json) > 0)
    )
) STRICT;

CREATE TRIGGER historical_compatibility_runs_are_immutable
BEFORE UPDATE ON historical_compatibility_runs
BEGIN SELECT RAISE(ABORT, 'historical compatibility runs are immutable'); END;

CREATE TRIGGER historical_compatibility_runs_cannot_be_deleted
BEFORE DELETE ON historical_compatibility_runs
BEGIN SELECT RAISE(ABORT, 'historical compatibility runs are immutable'); END;

CREATE TRIGGER historical_compatibility_coverage_is_immutable
BEFORE UPDATE ON historical_compatibility_coverage
BEGIN SELECT RAISE(ABORT, 'historical compatibility coverage is immutable'); END;

CREATE TRIGGER historical_compatibility_coverage_cannot_be_deleted
BEFORE DELETE ON historical_compatibility_coverage
BEGIN SELECT RAISE(ABORT, 'historical compatibility coverage is immutable'); END;

PRAGMA user_version = 12;

COMMIT;
