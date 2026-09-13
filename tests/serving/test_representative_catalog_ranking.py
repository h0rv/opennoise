import sqlite3
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import override

from opennoise.evidence.album_genres import AlbumGenreRepository, MembershipObservation
from opennoise.serving.representative_catalog_ranking import (
    RepresentativeCatalogRankingConfig,
    RepresentativeCatalogRankingRepository,
)

ROOT = Path(__file__).resolve().parents[2]


class RepresentativeCatalogRankingTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.execute("PRAGMA foreign_keys = ON")
        for name in (
            "0001_initial.sql",
            "0002_album_genres.sql",
            "0004_artist_genre_membership.sql",
        ):
            self.connection.executescript((ROOT / "migrations" / name).read_text())
        self.connection.executescript((ROOT / "migrations" / "smoke" / "fixture.sql").read_text())

    @override
    def tearDown(self) -> None:
        self.connection.close()

    def _direct(self, family: str) -> None:
        AlbumGenreRepository(self.connection).add_membership(
            MembershipObservation(
                release_group_id=5,
                genre_id=1,
                evidence_kind=(
                    "wikidata_p136" if family == "wikidata" else "musicbrainz_release_group_genre"
                ),
                evidence_level="release_group",
                source_family=family,
                source_record_id=f"{family}:fixture:5",
                source_genre_name="IDM",
                method_key="fixture",
                method_version="1",
                observed_at=datetime(2026, 9, 4, tzinfo=UTC),
                provenance_id=1,
                policy_id=1,
            )
        )

    def test_persists_direct_candidates_and_replays_exactly(self) -> None:
        self._direct("musicbrainz")
        self._direct("wikidata")
        repository = RepresentativeCatalogRankingRepository(self.connection)
        arguments = {
            "run_ref": "fixture:representative:1",
            "genre_ids": (1,),
            "config": RepresentativeCatalogRankingConfig(max_genres=1),
            "policy_id": 1,
            "generated_at": datetime(2026, 9, 4, tzinfo=UTC),
        }
        artifact, replayed = repository.build(**arguments)
        replay, replayed_again = repository.build(**arguments)

        self.assertFalse(replayed)
        self.assertTrue(replayed_again)
        self.assertEqual(artifact, replay)
        candidate = artifact.results[0].candidates[0]
        self.assertEqual(candidate.direct_source_family_count, 2)
        self.assertEqual(candidate.components[0].component_key, "direct_evidence")
        self.assertEqual(
            candidate.components[-1].component_key, "release_track_metadata_completeness"
        )
        self.assertEqual(
            self.connection.execute("SELECT count(*) FROM album_genre_ranking_items").fetchone(),
            (1,),
        )

    def test_abstains_when_the_requested_genre_has_no_direct_album_evidence(self) -> None:
        artifact, replayed = RepresentativeCatalogRankingRepository(self.connection).build(
            run_ref="fixture:representative:abstain",
            genre_ids=(15,),
            config=RepresentativeCatalogRankingConfig(max_genres=1),
            policy_id=1,
            generated_at=datetime(2026, 9, 4, tzinfo=UTC),
        )

        self.assertFalse(replayed)
        self.assertEqual(artifact.results[0].abstention_reason, "no_direct_album_genre_evidence")
        self.assertEqual(artifact.gate.candidates, 0)
        self.assertEqual(
            self.connection.execute("SELECT count(*) FROM album_genre_ranking_items").fetchone(),
            (0,),
        )


if __name__ == "__main__":
    unittest.main()
