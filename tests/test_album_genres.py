import sqlite3
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import override

from pydantic import ValidationError

from musix.album_genres import (
    AlbumGenreRepository,
    EvidenceFacetsStrategy,
    EvidenceRankingRequest,
    MembershipObservation,
    MembershipProjection,
    TransparentWeightedStrategy,
    UserPairwiseStrategy,
    membership_from_musicbrainz,
    parse_rank_strategy,
)
from musix.sources.musicbrainz import AdapterLimits, iter_release_group_jsonl

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = (
    ROOT / "migrations" / "0001_initial.sql",
    ROOT / "migrations" / "0002_album_genres.sql",
)
FIXTURE = ROOT / "migrations" / "smoke" / "fixture.sql"
ADAPTER_FIXTURES = ROOT / "tests" / "fixtures"


class AlbumGenreTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.database = sqlite3.connect(":memory:")
        self.database.execute("PRAGMA foreign_keys = ON")
        for migration in MIGRATIONS:
            self.database.executescript(migration.read_text(encoding="utf-8"))
        self.database.executescript(FIXTURE.read_text(encoding="utf-8"))
        self.database.executescript(
            """
            INSERT INTO catalog_entities (id, entity_kind) VALUES
                (17, 'release_group'), (18, 'release_group');
            INSERT INTO release_groups (id, group_kind) VALUES
                (17, 'album'), (18, 'album');
            """
        )
        self.repository = AlbumGenreRepository(self.database)

    @override
    def tearDown(self) -> None:
        self.database.close()

    @staticmethod
    def observation(
        release_group_id: int,
        *,
        source_family: str = "musicbrainz",
        source_record_id: str | None = None,
    ) -> MembershipObservation:
        return MembershipObservation(
            release_group_id=release_group_id,
            genre_id=1,
            evidence_kind=(
                "wikidata_p136"
                if source_family == "wikidata"
                else "musicbrainz_release_group_genre"
            ),
            evidence_level="release_group",
            source_family=source_family,
            source_record_id=source_record_id or f"{source_family}:{release_group_id}:idm",
            source_genre_name="IDM",
            source_count=4,
            source_total=10,
            method_key="direct_source_claim",
            method_version="1",
            observed_at=datetime(2026, 8, 30, tzinfo=UTC),
            provenance_id=1,
            policy_id=1,
        )

    def test_membership_is_idempotent_and_append_only(self) -> None:
        first = self.repository.add_membership(self.observation(5))
        second = self.repository.add_membership(self.observation(5))

        self.assertFalse(first.reused)
        self.assertTrue(second.reused)
        self.assertEqual(first.observation_id, second.observation_id)
        with self.assertRaises(sqlite3.IntegrityError):
            self.database.execute("UPDATE album_genre_membership_observations SET source_count = 5")

    def test_projects_typed_adapter_evidence_into_sqlite(self) -> None:
        with (ADAPTER_FIXTURES / "musicbrainz_release_groups.jsonl").open("rb") as stream:
            adapted = next(iter_release_group_jsonl(stream, AdapterLimits()))
        observation = membership_from_musicbrainz(
            adapted.evidence[0],
            MembershipProjection(
                release_group_id=5,
                genre_id=1,
                observed_at=datetime(2026, 8, 30, tzinfo=UTC),
                provenance_id=1,
                policy_id=1,
            ),
        )

        stored = self.repository.add_membership(observation)

        row = self.database.execute(
            """
            SELECT evidence_kind, source_record_id
            FROM album_genre_membership_observations WHERE id = ?
            """,
            (stored.observation_id,),
        ).fetchone()
        self.assertEqual(row, ("musicbrainz_release_group_genre", observation.source_record_id))

    def test_membership_model_keeps_editions_separate(self) -> None:
        payload = self.observation(5).model_dump()
        payload["evidence_level"] = "release"
        with self.assertRaises(ValidationError):
            MembershipObservation.model_validate(payload)

        wrong_source = self.observation(5).model_dump()
        wrong_source["source_family"] = "unrelated"
        with self.assertRaises(ValidationError):
            MembershipObservation.model_validate(wrong_source)

    def test_unweighted_baseline_ranks_by_direct_source_evidence(self) -> None:
        observations = (
            self.observation(5),
            self.observation(5, source_family="wikidata"),
            self.observation(17),
        )
        for observation in observations:
            self.repository.add_membership(observation)

        artifact = self.repository.publish_evidence_baseline(
            EvidenceRankingRequest(
                run_ref="fixture:idm:evidence:1",
                genre_id=1,
                strategy=EvidenceFacetsStrategy(),
                input_fingerprint="abababababababababababababababababababababababababababababababab",
                policy_id=1,
                generated_at=datetime(2026, 8, 30, tzinfo=UTC),
            )
        )

        self.assertEqual([item.release_group_id for item in artifact.items], [5, 17])
        self.assertEqual(artifact.items[0].score, 2.0)
        self.assertEqual(artifact.items[0].evidence_coverage, 1.0)
        self.assertEqual(artifact.items[1].evidence_coverage, 0.5)
        self.assertIn("No weights were applied", artifact.items[0].explanation)
        self.assertEqual(
            self.database.execute(
                "SELECT count(*) FROM displayable_album_genre_ranking_items"
            ).fetchone(),
            (2,),
        )

    def test_display_views_filter_suppressed_album_and_evidence(self) -> None:
        self.repository.add_membership(self.observation(5))
        self.repository.publish_evidence_baseline(
            EvidenceRankingRequest(
                run_ref="fixture:idm:suppression:1",
                genre_id=1,
                strategy=EvidenceFacetsStrategy(),
                input_fingerprint="cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd",
                policy_id=1,
                generated_at=datetime(2026, 8, 30, tzinfo=UTC),
            )
        )
        self.database.execute(
            """
            INSERT INTO suppression_events (
                target_kind, target_ref, use_kind, event_action, reason,
                effective_at, event_fingerprint
            ) VALUES ('entity', '5', 'display', 'suppress', 'Test', ?, ?)
            """,
            (
                "2026-08-30T00:00:00Z",
                "edededededededededededededededededededededededededededededededed",
            ),
        )

        self.assertEqual(
            self.database.execute(
                "SELECT count(*) FROM displayable_album_genre_memberships"
            ).fetchone(),
            (0,),
        )
        self.assertEqual(
            self.database.execute(
                "SELECT count(*) FROM displayable_album_genre_ranking_items"
            ).fetchone(),
            (0,),
        )

    def test_policy_must_match_source_provenance(self) -> None:
        payload = self.observation(5).model_dump()
        payload["policy_id"] = 2
        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.add_membership(MembershipObservation.model_validate(payload))

    def test_ranking_hides_when_one_evidence_source_is_suppressed(self) -> None:
        self.database.executescript(
            """
            INSERT INTO data_sources (id, source_key, name, default_policy_id)
            VALUES (200, 'second-fixture', 'Second fixture', 1);
            INSERT INTO provenance_records (
                id, source_id, policy_id, snapshot_ref, artifact_sha256,
                record_fingerprint, parser_release_ref, ingest_attempt_ref, observed_at
            ) VALUES (
                200, 200, 1, 'snapshot-2',
                'd0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0',
                'd1d1d1d1d1d1d1d1d1d1d1d1d1d1d1d1d1d1d1d1d1d1d1d1d1d1d1d1d1d1d1d1',
                'fixture-parser-1', 'attempt-2', '2026-01-01T00:00:00Z'
            );
            """
        )
        first = self.observation(5)
        second_payload = self.observation(5, source_family="wikidata").model_dump()
        second_payload["provenance_id"] = 200
        self.repository.add_membership(first)
        self.repository.add_membership(MembershipObservation.model_validate(second_payload))
        self.repository.publish_evidence_baseline(
            EvidenceRankingRequest(
                run_ref="fixture:idm:partial-suppression:1",
                genre_id=1,
                strategy=EvidenceFacetsStrategy(),
                input_fingerprint=(
                    "acacacacacacacacacacacacacacacacacacacacacacacacacacacacacacacac"
                ),
                policy_id=1,
                generated_at=datetime(2026, 8, 30, tzinfo=UTC),
            )
        )
        self.database.execute(
            """
            INSERT INTO suppression_events (
                target_kind, target_ref, use_kind, event_action, reason,
                effective_at, event_fingerprint
            ) VALUES ('provenance', '1', 'display', 'suppress', 'Test', ?, ?)
            """,
            (
                "2026-08-30T00:00:00Z",
                "adadadadadadadadadadadadadadadadadadadadadadadadadadadadadadadad",
            ),
        )

        self.assertEqual(
            self.database.execute(
                "SELECT count(*) FROM displayable_album_genre_memberships"
            ).fetchone(),
            (1,),
        )
        self.assertEqual(
            self.database.execute(
                "SELECT count(*) FROM displayable_album_genre_ranking_items"
            ).fetchone(),
            (0,),
        )

    def test_all_three_rank_strategies_are_typed_and_selectable(self) -> None:
        facets = parse_rank_strategy({"strategy": "evidence_facets"})
        weighted = parse_rank_strategy(
            {
                "strategy": "transparent_weighted",
                "weights": [{"component_key": "specificity", "weight": 1.0}],
            }
        )
        pairwise = parse_rank_strategy(
            {
                "strategy": "user_pairwise",
                "judgment_set_ref": "local:album-pairs:1",
                "minimum_comparisons": 20,
            }
        )

        self.assertIsInstance(facets, EvidenceFacetsStrategy)
        self.assertIsInstance(weighted, TransparentWeightedStrategy)
        self.assertIsInstance(pairwise, UserPairwiseStrategy)
        with self.assertRaises(ValidationError):
            parse_rank_strategy(
                {
                    "strategy": "transparent_weighted",
                    "weights": [
                        {"component_key": "specificity", "weight": 1.0},
                        {"component_key": "specificity", "weight": 2.0},
                    ],
                }
            )
        with self.assertRaises(ValidationError):
            parse_rank_strategy(
                {
                    "strategy": "transparent_weighted",
                    "weights": [{"component_key": "specificity", "weight": float("inf")}],
                }
            )


if __name__ == "__main__":
    unittest.main()
