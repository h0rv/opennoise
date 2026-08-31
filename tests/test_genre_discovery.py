import asyncio
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from musix.adapters.everynoise import (
    SourceSpec,
    adapt_quint_historical_representatives,
    adapt_quint_html,
)
from musix.genre_discovery import import_historical_representatives
from musix.ingest import ImportOptions, import_jsonl


class GenreDiscoveryTests(unittest.TestCase):
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
