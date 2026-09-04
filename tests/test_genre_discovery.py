import asyncio
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from musix.adapters.everynoise import (
    SourceSpec,
    adapt_historical_genre_artist_map,
    adapt_quint_historical_representatives,
    adapt_quint_html,
)
from musix.genre_discovery import (
    import_historical_genre_memberships,
    import_historical_representatives,
    query_displayable_historical_artist_genres,
    query_displayable_historical_genre_members,
    query_displayable_historical_genre_memberships,
)
from musix.ingest import ImportOptions, import_jsonl


class GenreDiscoveryTests(unittest.TestCase):
    def test_bounded_h3_projection_is_sealed_and_media_free(self) -> None:
        fixture_path = (
            Path(__file__).parent / "fixtures" / "everynoise" / "neroyuki_h3_pop_sample.json"
        )
        raw = fixture_path.read_bytes()
        fixture = json.loads(raw)

        self.assertEqual(
            hashlib.sha256(raw).hexdigest(),
            "3ec106419821b7de25bbac2590c71f3d30a3508a467d023523e878b58b5a8551",
        )
        self.assertEqual(fixture["source"]["status"], "discovery_only")
        self.assertEqual(fixture["projection"]["dropped_fields"], ["sample_song", "preview_url"])
        self.assertEqual(fixture["projection"]["artist_memberships"], 3)
        for record in fixture["records"]:
            self.assertEqual(set(record), {"genre", "artist", "artist_id"})

    def test_genre_membership_adapter_drops_all_preview_metadata(self) -> None:
        raw = b"""[
          {"genre":"pop","artists":[
            {"artist":"Taylor Swift","artist_id":"06HL4z0CvFAxyc27GXpf02","sample_song":"Cruel Summer","preview_url":"https://p.scdn.co/mp3-preview/never-fetch"},
            {"artist":"The Weeknd","artist_id":"1Xyo4u8uXC1ZmMpatF05PJ"}
          ]}
        ]"""
        source = SourceSpec.model_validate(
            {
                "source_id": "enao-h3-test-source",
                "namespace": "enao-h3-test",
                "snapshot": "git:test",
                "url": "https://example.invalid/genre-artists.json",
                "expected_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "expected_records": 1,
                "adapter": "enao_genre_artist_map_v1",
            }
        )

        result = adapt_historical_genre_artist_map(
            raw,
            source,
            source_revision_date="2024-11-16",
        )

        self.assertEqual(result.discarded_preview_metadata_count, 1)
        self.assertEqual(result.discarded_sample_metadata_count, 1)
        self.assertEqual(result.discarded_track_identifier_count, 0)
        self.assertEqual(result.source_membership_count, 2)
        self.assertEqual(result.quarantined_membership_count, 0)
        self.assertEqual(result.empty_genre_rows, 0)
        self.assertEqual(
            [
                (record.genre_name, record.artist_name, record.source_artist_id)
                for record in result.records
            ],
            [
                ("pop", "Taylor Swift", "06HL4z0CvFAxyc27GXpf02"),
                ("pop", "The Weeknd", "1Xyo4u8uXC1ZmMpatF05PJ"),
            ],
        )
        rendered = result.model_dump_json()
        self.assertNotIn("preview_url", rendered)
        self.assertNotIn("sample_song", rendered)
        self.assertNotIn('"track_id":', rendered)
        self.assertNotIn("p.scdn.co", rendered)

    def test_genre_membership_import_is_local_only_and_idempotent(self) -> None:  # noqa: PLR0915
        h2_raw = (
            b'<div id=item1 class="genre scanme" style="color: #ad8907; top: 4997px; '
            b'left: 783px; font-size: 160%" '
            b'onclick=\'playx("1V6gIisPpYqgFeWbMLI0bA", "pop", this);\' '
            b"title='e.g. Demi Lovato \"Heart Attack\"'>pop</div>"
        )
        h2_source = SourceSpec.model_validate(
            {
                "source_id": "enao-test-source",
                "namespace": "enao-test",
                "snapshot": "final-map:2023-11-19",
                "url": "https://example.invalid/final-map",
                "expected_bytes": len(h2_raw),
                "sha256": hashlib.sha256(h2_raw).hexdigest(),
                "expected_records": 1,
                "adapter": "enao_html_map_v1",
            }
        )
        h3_raw = (
            b'[{"genre":"pop","artists":[{"artist":"Taylor Swift",'
            b'"artist_id":"06HL4z0CvFAxyc27GXpf02",'
            b'"preview_url":"https://p.scdn.co/mp3-preview/never-fetch"}]}]'
        )
        h3_source = SourceSpec.model_validate(
            {
                "source_id": "enao-h3-test-source",
                "namespace": "enao-h3-test",
                "snapshot": "git:test",
                "url": "https://example.invalid/genre-artists.json",
                "expected_bytes": len(h3_raw),
                "sha256": hashlib.sha256(h3_raw).hexdigest(),
                "expected_records": 1,
                "adapter": "enao_genre_artist_map_v1",
            }
        )
        catalog = adapt_quint_html(h2_raw, h2_source)
        membership = adapt_historical_genre_artist_map(
            h3_raw,
            h3_source,
            source_revision_date="2024-11-16",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog_path = root / "catalog.jsonl"
            catalog_path.write_bytes(catalog.catalog_jsonl())
            database_path = root / "musix.sqlite"
            asyncio.run(
                import_jsonl(
                    ImportOptions(
                        input_path=catalog_path,
                        database_path=database_path,
                        vault_path=root / "vault",
                        source_key=h2_source.source_id,
                        source_name="Every Noise test source",
                    )
                )
            )
            first = import_historical_genre_memberships(
                database_path,
                membership,
                base_source_key=h2_source.source_id,
            )
            second = import_historical_genre_memberships(
                database_path,
                membership,
                base_source_key=h2_source.source_id,
            )
            display_enabled = import_historical_genre_memberships(
                database_path,
                membership,
                base_source_key=h2_source.source_id,
                enable_local_display=True,
            )

            self.assertEqual(first, second)
            self.assertEqual(first.genre_memberships, 1)
            self.assertEqual(first.matched_genres, 1)
            self.assertEqual(first.unmatched_genres, 0)
            self.assertEqual(first.discarded_preview_metadata_count, 1)
            self.assertEqual(first.discarded_sample_metadata_count, 0)
            self.assertEqual(first.discarded_track_identifier_count, 0)
            self.assertFalse(first.local_display_enabled)
            self.assertTrue(display_enabled.local_display_enabled)
            hidden = query_displayable_historical_genre_memberships(
                database_path,
                source_sha256=h3_source.sha256,
                policy_key=first.policy_key,
            )
            visible = query_displayable_historical_genre_memberships(
                database_path,
                source_sha256=h3_source.sha256,
                policy_key=display_enabled.policy_key,
            )
            inverse = query_displayable_historical_artist_genres(
                database_path,
                source_sha256=h3_source.sha256,
                policy_key=display_enabled.policy_key,
                source_artist_id="06HL4z0CvFAxyc27GXpf02",
            )
            members = query_displayable_historical_genre_members(
                database_path,
                source_sha256=h3_source.sha256,
                policy_key=display_enabled.policy_key,
                genre_id=1,
                limit=6,
            )
            connection = sqlite3.connect(database_path)
            try:
                policy = connection.execute(
                    """SELECT permission.decision
                       FROM rights_policy_permissions AS permission
                       JOIN rights_policies AS policy ON policy.id = permission.policy_id
                       WHERE policy.policy_key = ? AND permission.use_kind = 'display'""",
                    (f"historical-membership:discovery-only:{h3_source.sha256}",),
                ).fetchone()
                display_policy = connection.execute(
                    """SELECT permission.decision
                       FROM rights_policy_permissions AS permission
                       JOIN rights_policies AS policy ON policy.id = permission.policy_id
                       WHERE policy.policy_key = ? AND permission.use_kind = 'display'""",
                    (f"historical-membership:local-display:{h3_source.sha256}",),
                ).fetchone()
                export_policy = connection.execute(
                    """SELECT permission.decision
                       FROM rights_policy_permissions AS permission
                       JOIN rights_policies AS policy ON policy.id = permission.policy_id
                       WHERE policy.policy_key = ? AND permission.use_kind = 'export'""",
                    (f"historical-membership:local-display:{h3_source.sha256}",),
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(policy, ("deny",))
            self.assertEqual(display_policy, ("allow",))
            self.assertEqual(export_policy, ("deny",))
            self.assertEqual(hidden.genre_memberships, 0)
            self.assertEqual(visible.genre_memberships, 1)
            self.assertIsNotNone(inverse)
            if inverse is not None:
                self.assertEqual(inverse.genre_names, ("pop",))
                self.assertEqual(inverse.state, "derived_partial")
            self.assertEqual(members.genre_id, 1)
            self.assertEqual(len(members.members), 1)
            self.assertEqual(members.members[0].source_artist_name, "Taylor Swift")
            self.assertEqual(members.members[0].rank, 1)
            self.assertIsNone(members.members[0].source_local_rank)
            self.assertTrue(members.members[0].evidence_ref.startswith("historical:"))

    def test_representative_import_is_idempotent_and_policy_safe(self) -> None:
        raw = (
            b'<div id=item1 preview_url="https://p.scdn.co/mp3-preview/legacy" '
            b'class="genre scanme" style="color: #ad8907; top: 4997px; left: 783px; '
            b'font-size: 160%" onclick=\'playx("1V6gIisPpYqgFeWbMLI0bA", "pop", this);\' '
            b"title='e.g. Demi Lovato \"Heart Attack\"'>pop"
            b'<a href="https://everynoise.com/engenremap-pop.html">nav</a></div>'
        )
        source = SourceSpec.model_validate(
            {
                "source_id": "enao-test-source",
                "namespace": "enao-test",
                "snapshot": "final-map:2023-11-19",
                "url": "https://example.invalid/final-map",
                "expected_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "expected_records": 1,
                "adapter": "enao_html_map_v1",
            }
        )
        catalog = adapt_quint_html(raw, source)
        historical = adapt_quint_historical_representatives(raw, source)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog_path = root / "catalog.jsonl"
            catalog_path.write_bytes(catalog.catalog_jsonl())
            database_path = root / "musix.sqlite"
            asyncio.run(
                import_jsonl(
                    ImportOptions(
                        input_path=catalog_path,
                        database_path=database_path,
                        vault_path=root / "vault",
                        source_key=source.source_id,
                        source_name="Every Noise test source",
                    )
                )
            )
            first = import_historical_representatives(database_path, historical)
            connection = sqlite3.connect(database_path)
            try:
                connection.execute(
                    """INSERT INTO rights_policies
                       (policy_key, policy_version, classification, basis)
                       VALUES ('later-source-default', 1, 'unknown', 'test deny default')"""
                )
                later_policy_id = int(
                    connection.execute("SELECT last_insert_rowid()").fetchone()[0]
                )
                connection.execute(
                    "UPDATE data_sources SET default_policy_id = ? WHERE source_key = ?",
                    (later_policy_id, source.source_id),
                )
                connection.commit()
            finally:
                connection.close()
            second = import_historical_representatives(database_path, historical)
            self.assertEqual(first.representative_artists, 1)
            self.assertEqual(first.representative_tracks, 1)
            self.assertEqual(second, first)

            connection = sqlite3.connect(database_path)
            try:
                row = connection.execute(
                    """SELECT source_track_title, recording_source_id, safe_external_url,
                              legacy_preview_state, source_artifact_sha256
                       FROM displayable_historical_genre_tracks"""
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(
                row,
                (
                    "Heart Attack",
                    "1V6gIisPpYqgFeWbMLI0bA",
                    "https://open.spotify.com/track/1V6gIisPpYqgFeWbMLI0bA",
                    "disabled_legacy",
                    source.sha256,
                ),
            )

            connection = sqlite3.connect(database_path)
            try:
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute("DELETE FROM historical_genre_track_observations")
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        """INSERT INTO historical_genre_track_observations
                           (genre_id, artist_observation_id, source_track_title,
                            recording_provider, recording_source_id, safe_external_url,
                            legacy_preview_state, source_revision_date,
                            source_artifact_sha256, provenance_id, policy_id,
                            record_fingerprint)
                           SELECT genre_id, artist_observation_id, source_track_title,
                                  recording_provider, recording_source_id,
                                  'https://open.spotify.com/track/not-the-recording',
                                  legacy_preview_state, source_revision_date,
                                  source_artifact_sha256, provenance_id, policy_id, ?
                           FROM historical_genre_track_observations LIMIT 1""",
                        ("0" * 64,),
                    )
                source_id = int(
                    connection.execute(
                        "SELECT id FROM data_sources WHERE source_key = ?",
                        (source.source_id,),
                    ).fetchone()[0]
                )
                connection.execute(
                    """INSERT INTO suppression_events
                       (target_kind, target_ref, use_kind, event_action, reason,
                        effective_at, event_fingerprint)
                       VALUES ('source', ?, 'display', 'suppress', 'test suppression',
                               '2026-01-01T00:00:00Z', ?)""",
                    (str(source_id), "1" * 64),
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT count(*) FROM displayable_historical_genre_tracks"
                    ).fetchone()[0],
                    0,
                )
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
