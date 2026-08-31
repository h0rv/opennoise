#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
audit_dir=$(mktemp -d /tmp/musix-schema-smoke.XXXXXX)
trap 'rm -rf "$audit_dir"' EXIT
database="$audit_dir/musix.sqlite"

sqlite3 -bail "$database" < "$repo_root/migrations/0001_initial.sql"
sqlite3 -bail "$database" < "$repo_root/migrations/0002_album_genres.sql"
sqlite3 -bail "$database" < "$repo_root/migrations/0003_genre_discovery.sql"
sqlite3 -bail "$database" < "$repo_root/migrations/smoke/fixture.sql"

expect_rejection() {
    local sql=$1
    local expected=$2
    local output

    if output=$(sqlite3 -bail "$database" "$sql" 2>&1); then
        printf 'expected rejection but statement succeeded: %s\n' "$sql" >&2
        return 1
    fi
    if [[ $output != *"$expected"* ]]; then
        printf 'unexpected rejection: %s\n' "$output" >&2
        return 1
    fi
}

expect_rejection \
    "INSERT INTO metric_observations(entity_id,metric_id,text_value,observed_at,provenance_id,fingerprint) VALUES(2,1,'wrong','2026-01-01T00:00:00Z',1,'adadadadadadadadadadadadadadadadadadadadadadadadadadadadadadadad');" \
    'metric value does not match its definition'
expect_rejection \
    "INSERT INTO entity_relations(relation_type_id,subject_entity_id,object_entity_id,provenance_id) VALUES((SELECT id FROM relation_types WHERE relation_key='genre_subgenre_of'),15,1,1);" \
    'genre hierarchy relation would create a cycle'
expect_rejection \
    "INSERT INTO rights_policy_permissions VALUES(2,'export','allow','probe');" \
    'a local-only policy cannot allow export'
expect_rejection \
    "INSERT INTO staged_records(ingest_attempt_id,artifact_id,record_ordinal,byte_length,exact_record_sha256,parsed_json,parse_status,record_fingerprint) VALUES(1,1,10,1001,'adadadadadadadadadadadadadadadadadadadadadadadadadadadadadadadad','{}','accepted','aeaeaeaeaeaeaeaeaeaeaeaeaeaeaeaeaeaeaeaeaeaeaeaeaeaeaeaeaeaeaeae');" \
    'staged record does not match its attempt, artifact, or safety limits'
expect_rejection \
    "INSERT INTO normalization_exports(staged_record_id,source_object_observation_id,projection_kind,output_fingerprint,exported_at) VALUES(2,1,'bad','abababababababababababababababababababababababababababababababa01','2026-01-01T00:00:00Z');" \
    'record is quarantined or normalization is denied'

test "$(sqlite3 "$database" 'SELECT count(*) FROM pragma_foreign_key_check;')" = 0
test "$(sqlite3 "$database" 'PRAGMA integrity_check;')" = ok
test "$(sqlite3 "$database" 'SELECT count(*) FROM catalog_entity_integrity_violations;')" = 0
