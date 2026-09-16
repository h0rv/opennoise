"""Contracts for static, evidence-backed artist discovery."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from opennoise.deployment.static_discovery import (
    StaticDiscoveryExportError,
    StaticDiscoveryNode,
    build_static_discovery_payload,
    unavailable_static_discovery_payload,
)

_NODES = (
    StaticDiscoveryNode(node_id="item-post-punk", name="post-punk"),
    StaticDiscoveryNode(node_id="item-jazz", name="jazz"),
    StaticDiscoveryNode(node_id="item-hyperpop", name="hyperpop"),
    StaticDiscoveryNode(node_id="item-empty", name="empty genre"),
)


class StaticDiscoveryTests(unittest.TestCase):
    """Static discovery must retain only export-authorized direct observations."""

    def test_direct_flow_is_reciprocal_explained_and_ambiguity_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "catalog.sqlite"
            _fixture(database)
            payload = build_static_discovery_payload(database, _NODES)

        self.assertEqual(payload.availability, "ready")
        assert payload.coverage is not None
        self.assertEqual(payload.coverage.direct_catalog_observation_count, 7)
        self.assertEqual(payload.coverage.bound_direct_observation_count, 5)
        self.assertEqual(payload.coverage.exact_label_bound_catalog_genre_count, 2)
        self.assertEqual(payload.coverage.genres_with_direct_artists, 2)
        self.assertEqual(payload.coverage.artists_with_direct_map_genres, 3)
        self.assertEqual({item.node_id for item in payload.genres}, {"item-post-punk", "item-jazz"})
        self.assertNotIn("item-hyperpop", {item.node_id for item in payload.genres})
        self.assertNotIn("item-empty", {item.node_id for item in payload.genres})

        artists = {item.artist_id: item for item in payload.artists}
        self.assertNotIn("artist:6", artists, "export-denied observations must not publish")
        self.assertNotIn("artist:7", artists, "display-denied observations must not publish")
        alpha = artists["artist:1"]
        self.assertEqual(alpha.name, "Alpha", "English display names take precedence")
        self.assertEqual(artists["artist:2"].name, "Beta", "native names remain the fallback")
        self.assertEqual(
            {item.node_id for item in alpha.memberships}, {"item-post-punk", "item-jazz"}
        )
        self.assertEqual(len(alpha.shared_genre_artists), 2)
        beta = alpha.shared_genre_artists[0]
        self.assertEqual(beta.artist_id, "artist:2")
        self.assertEqual(beta.shared_genre_ids, ("item-jazz", "item-post-punk"))
        self.assertEqual(beta.shared_genre_count, 2)
        self.assertEqual(beta.score, 1.0)
        self.assertEqual(beta.method, "shared_direct_catalog_genre")
        self.assertTrue(
            all(
                evidence.method_key == "wikidata_p136"
                for membership in alpha.memberships
                for evidence in membership.evidence
            )
        )

    def test_missing_database_fails_and_unavailable_state_is_explicit(self) -> None:
        with self.assertRaises(StaticDiscoveryExportError):
            build_static_discovery_payload(Path("missing.sqlite"), _NODES)
        unavailable = unavailable_static_discovery_payload()
        self.assertEqual(unavailable.availability, "unavailable")
        self.assertEqual(unavailable.genres, ())
        self.assertEqual(unavailable.artists, ())


def _fixture(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(
            """
            CREATE TABLE genres (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE artists (id INTEGER PRIMARY KEY);
            CREATE TABLE displayable_entity_names (
                id INTEGER PRIMARY KEY, entity_id INTEGER NOT NULL, name TEXT NOT NULL,
                language_tag TEXT NOT NULL,
                is_preferred INTEGER NOT NULL
            );
            CREATE TABLE provenance_records (id INTEGER PRIMARY KEY, policy_id INTEGER NOT NULL);
            CREATE TABLE active_rights_policy_permissions (
                policy_id INTEGER NOT NULL, use_kind TEXT NOT NULL, decision TEXT NOT NULL
            );
            CREATE TABLE displayable_artist_genre_evidence (
                id INTEGER PRIMARY KEY, artist_id INTEGER NOT NULL, genre_id INTEGER NOT NULL,
                source_key TEXT NOT NULL, source_record_id TEXT NOT NULL, method_key TEXT NOT NULL,
                method_version TEXT NOT NULL, provenance_id INTEGER NOT NULL,
                evidence_kind TEXT NOT NULL
            );
            INSERT INTO genres VALUES
                (10, 'post-punk'), (20, 'jazz'), (30, 'hyperpop'), (31, 'Hyperpop'),
                (40, 'catalog only');
            INSERT INTO artists VALUES (1), (2), (3), (4), (5), (6), (7);
            INSERT INTO displayable_entity_names VALUES
                (1, 1, 'ألفا', 'ar', 1), (8, 1, 'Alpha', 'en', 0),
                (2, 2, 'Beta', 'no', 1), (3, 3, 'Gamma', 'und', 1),
                (4, 4, 'Unmapped', 'en', 1), (5, 5, 'Ambiguous', 'en', 1),
                (6, 6, 'Denied', 'en', 1), (7, 7, 'Display denied', 'en', 1);
            INSERT INTO provenance_records VALUES (1, 100), (2, 200), (3, 300);
            INSERT INTO active_rights_policy_permissions VALUES
                (100, 'export', 'allow'), (100, 'display', 'allow'),
                (200, 'export', 'deny'), (200, 'display', 'allow'),
                (300, 'export', 'allow'), (300, 'display', 'deny');
            INSERT INTO displayable_artist_genre_evidence VALUES
                (1, 1, 10, 'wikidata:a', 'alpha-post-punk', 'wikidata_p136',
                 '1', 1, 'direct_source_claim'),
                (2, 1, 20, 'wikidata:a', 'alpha-jazz', 'wikidata_p136',
                 '1', 1, 'direct_source_claim'),
                (3, 2, 10, 'wikidata:b', 'beta-post-punk', 'wikidata_p136',
                 '1', 1, 'direct_source_claim'),
                (4, 2, 20, 'wikidata:b', 'beta-jazz', 'wikidata_p136',
                 '1', 1, 'direct_source_claim'),
                (5, 3, 20, 'wikidata:c', 'gamma-jazz', 'wikidata_p136',
                 '1', 1, 'direct_source_claim'),
                (6, 4, 40, 'wikidata:d', 'unmapped', 'wikidata_p136',
                 '1', 1, 'direct_source_claim'),
                (7, 5, 30, 'wikidata:e', 'ambiguous', 'wikidata_p136',
                 '1', 1, 'direct_source_claim'),
                (8, 6, 10, 'wikidata:f', 'denied', 'wikidata_p136', '1', 2, 'direct_source_claim'),
                (9, 6, 10, 'wikidata:g', 'candidate', 'propagated', '1', 1, 'aggregate_candidate'),
                (10, 7, 10, 'wikidata:h', 'display-denied', 'wikidata_p136',
                 '1', 3, 'direct_source_claim');
            """
        )
        connection.commit()


if __name__ == "__main__":
    unittest.main()
