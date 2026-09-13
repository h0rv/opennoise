import math
import sqlite3
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import override

from pydantic import ValidationError

from opennoise.evidence.membership import (
    ArtistGenreEvidence,
    ArtistGenreRepository,
    DirectArtistGenreProjection,
    EvaluationClaim,
    EvaluationPrediction,
    FeatureValue,
    FeatureWeight,
    MaterializationManifest,
    MembershipRunRequest,
    ReleasePropagationManifest,
    RepresentationVector,
    SimilarityManifest,
    evaluate_predictions,
    evidence_from_musicbrainz,
    representation_similarity,
)
from opennoise.sources.musicbrainz import AdapterLimits, iter_artist_jsonl
from scripts.evaluate_membership import EvaluationDocument, evaluate_document

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = tuple(sorted((ROOT / "migrations").glob("[0-9][0-9][0-9][0-9]_*.sql")))
FIXTURE = ROOT / "migrations" / "smoke" / "fixture.sql"
ARTIST_FIXTURE = ROOT / "tests" / "fixtures" / "musicbrainz_artists.jsonl"
NOW = datetime(2026, 8, 31, tzinfo=UTC)
SOURCE_COUNT = 3
SOURCE_PROVENANCE = {"fixture": 1, "musicbrainz": 201, "wikidata": 202, "listenbrainz": 203}


class MembershipTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.database = sqlite3.connect(":memory:")
        self.database.row_factory = sqlite3.Row
        self.database.execute("PRAGMA foreign_keys = ON")
        for migration in MIGRATIONS:
            self.database.executescript(migration.read_text(encoding="utf-8"))
        self.database.executescript(FIXTURE.read_text(encoding="utf-8"))
        self.database.executescript(
            """
            INSERT INTO data_sources (id, source_key, name, default_policy_id) VALUES
                (201, 'musicbrainz', 'MusicBrainz fixture', 1),
                (202, 'wikidata', 'Wikidata fixture', 1),
                (203, 'listenbrainz', 'ListenBrainz fixture', 1);
            INSERT INTO provenance_records (
                id, source_id, policy_id, snapshot_ref, artifact_sha256,
                record_fingerprint, parser_release_ref, ingest_attempt_ref, observed_at
            ) VALUES
                (201, 201, 1, 'snapshot-mb',
                 '2020202020202020202020202020202020202020202020202020202020202020',
                 '2121212121212121212121212121212121212121212121212121212121212121',
                 'fixture-parser-1', 'attempt-mb', '2026-01-01T00:00:00Z'),
                (202, 202, 1, 'snapshot-wd',
                 '2222222222222222222222222222222222222222222222222222222222222222',
                 '2323232323232323232323232323232323232323232323232323232323232323',
                 'fixture-parser-1', 'attempt-wd', '2026-01-01T00:00:00Z'),
                (203, 203, 1, 'snapshot-lb',
                 '2424242424242424242424242424242424242424242424242424242424242424',
                 '2525252525252525252525252525252525252525252525252525252525252525',
                 'fixture-parser-1', 'attempt-lb', '2026-01-01T00:00:00Z');
            """
        )
        self.repository = ArtistGenreRepository(self.database)

    @override
    def tearDown(self) -> None:
        self.database.close()

    @staticmethod
    def evidence(
        artist_id: int,
        genre_id: int,
        *,
        source_key: str = "musicbrainz",
        value: float = 1.0,
        record_suffix: str = "claim",
    ) -> ArtistGenreEvidence:
        return ArtistGenreEvidence(
            artist_id=artist_id,
            genre_id=genre_id,
            evidence_kind="direct_source_claim",
            evidence_value=value,
            source_key=source_key,
            source_record_id=f"{source_key}:{artist_id}:{genre_id}:{record_suffix}",
            method_key="direct_fixture_claim",
            method_version="1",
            parameter_manifest={"value_semantics": "fixture_count"},
            observed_at=NOW,
            provenance_id=SOURCE_PROVENANCE[source_key],
            policy_id=1,
        )

    @staticmethod
    def direct_manifest(*source_keys: str, max_inputs: int = 100) -> MaterializationManifest:
        return MaterializationManifest(
            method="direct_evidence",
            included_evidence_kinds=("direct_source_claim",),
            included_source_keys=source_keys,
            max_input_evidence=max_inputs,
            max_output_items=100,
        )

    def request(
        self,
        run_ref: str,
        manifest: MaterializationManifest,
        *,
        revision: int = 1,
    ) -> MembershipRunRequest:
        return MembershipRunRequest(
            run_ref=run_ref,
            revision=revision,
            manifest=manifest,
            policy_id=1,
            generated_at=NOW,
        )

    def test_musicbrainz_local_fixture_projects_direct_claim(self) -> None:
        with ARTIST_FIXTURE.open("rb") as stream:
            adapted = next(iter_artist_jsonl(stream, AdapterLimits()))
        relationship = adapted.relationships[0]
        evidence = evidence_from_musicbrainz(
            relationship,
            DirectArtistGenreProjection(
                artist_id=2,
                genre_id=1,
                source_record_id=(
                    f"{relationship.artist_external_id}:{relationship.genre_external_id}"
                ),
                source_key="musicbrainz",
                observed_at=NOW,
                provenance_id=201,
                policy_id=1,
                missing_weight_value=1.0,
            ),
        )

        stored = self.repository.add_evidence(evidence)
        reused = self.repository.add_evidence(evidence)

        self.assertFalse(stored.reused)
        self.assertTrue(reused.reused)
        self.assertEqual(stored.evidence_id, reused.evidence_id)
        self.assertEqual(evidence.source_key, "musicbrainz")

    def test_evidence_is_strict_finite_and_append_only(self) -> None:
        stored = self.repository.add_evidence(self.evidence(2, 1))
        with self.assertRaises(sqlite3.IntegrityError):
            self.database.execute(
                "UPDATE artist_genre_evidence SET evidence_value = 2 WHERE id = ?",
                (stored.evidence_id,),
            )
        payload = self.evidence(2, 1).model_dump()
        payload["evidence_value"] = math.inf
        with self.assertRaises(ValidationError):
            ArtistGenreEvidence.model_validate(payload)

    def test_evidence_source_must_match_provenance_source(self) -> None:
        payload = self.evidence(2, 1, source_key="musicbrainz").model_dump()
        payload["source_key"] = "wikidata"

        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.add_evidence(ArtistGenreEvidence.model_validate(payload))

    def test_release_propagation_is_bounded_idempotent_and_explainable(self) -> None:
        self.database.execute(
            """
            INSERT INTO album_genre_membership_observations (
                release_group_id, genre_id, evidence_kind, evidence_level,
                source_family, source_record_id, source_genre_name, source_count,
                method_key, method_version, observed_at, provenance_id, policy_id,
                record_fingerprint
            ) VALUES (5, 1, 'musicbrainz_release_group_genre', 'release_group',
                      'musicbrainz', 'mb:rg:5:genre:1', 'IDM', 7,
                      'direct_musicbrainz_genre', '1', ?, 1, 1, ?)
            """,
            (NOW.isoformat(), "1212121212121212121212121212121212121212121212121212121212121212"),
        )

        manifest = ReleasePropagationManifest(missing_source_count_value=1.0)
        first = self.repository.propagate_release_evidence(manifest)
        second = self.repository.propagate_release_evidence(manifest)

        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        row = self.database.execute(
            """
            SELECT artist_id, genre_id, evidence_value, source_album_evidence_id,
                   parameter_manifest_json
            FROM artist_genre_evidence
            """
        ).fetchone()
        self.assertEqual((row[0], row[1], row[2], row[3]), (2, 1, 7.0, 1))
        self.assertIn("full_value_to_each_credited_artist", str(row[4]))
        self.database.execute(
            """
            INSERT INTO album_genre_membership_observations (
                release_group_id, genre_id, evidence_kind, evidence_level,
                source_family, source_record_id, source_genre_name, source_count,
                method_key, method_version, observed_at, provenance_id, policy_id,
                record_fingerprint
            ) VALUES (5, 1, 'musicbrainz_release_group_genre', 'release_group',
                      'musicbrainz', 'mb:rg:5:genre:1:second', 'IDM', 3,
                      'direct_musicbrainz_genre', '1', ?, 1, 1, ?)
            """,
            (NOW.isoformat(), "1414141414141414141414141414141414141414141414141414141414141414"),
        )
        with self.assertRaises(ValueError):
            self.repository.propagate_release_evidence(
                ReleasePropagationManifest(missing_source_count_value=1.0, max_input_evidence=1)
            )

    def test_release_propagation_rejects_suppressed_credit_provenance(self) -> None:
        self.database.execute(
            "UPDATE entity_artist_credits SET provenance_id = 202 WHERE entity_id = 5"
        )
        self.database.execute(
            """
            INSERT INTO suppression_events (
                target_kind, target_ref, use_kind, event_action, reason,
                effective_at, event_fingerprint
            ) VALUES ('provenance', '202', 'normalize', 'suppress', 'Fixture', ?, ?)
            """,
            (
                NOW.isoformat(),
                "2626262626262626262626262626262626262626262626262626262626262626",
            ),
        )
        self.database.execute(
            """
            INSERT INTO album_genre_membership_observations (
                release_group_id, genre_id, evidence_kind, evidence_level,
                source_family, source_record_id, source_genre_name, source_count,
                method_key, method_version, observed_at, provenance_id, policy_id,
                record_fingerprint
            ) VALUES (5, 1, 'musicbrainz_release_group_genre', 'release_group',
                      'musicbrainz', 'mb:rg:5:genre:blocked', 'IDM', 7,
                      'direct_musicbrainz_genre', '1', ?, 1, 1, ?)
            """,
            (
                NOW.isoformat(),
                "2727272727272727272727272727272727272727272727272727272727272727",
            ),
        )

        inserted = self.repository.propagate_release_evidence(
            ReleasePropagationManifest(missing_source_count_value=1.0)
        )

        self.assertEqual(inserted, 0)
        self.assertEqual(
            self.database.execute("SELECT count(*) FROM artist_genre_evidence").fetchone()[0],
            0,
        )

    def test_broad_materialization_preserves_sources_and_is_idempotent(self) -> None:
        for artist_id in (2, 14):
            for genre_id in (1, 15):
                for source_key in ("musicbrainz", "wikidata", "listenbrainz"):
                    self.repository.add_evidence(
                        self.evidence(
                            artist_id,
                            genre_id,
                            source_key=source_key,
                            value=float(artist_id + genre_id),
                        )
                    )
        manifest = self.direct_manifest("musicbrainz", "wikidata", "listenbrainz")

        first = self.repository.materialize(self.request("fixture:direct:1", manifest))
        second = self.repository.materialize(self.request("fixture:direct:1", manifest))

        self.assertFalse(first.reused)
        self.assertTrue(second.reused)
        self.assertEqual(first.input_fingerprint, second.input_fingerprint)
        self.assertEqual(len(first.items), 4)
        self.assertTrue(all(item.evidence_count == SOURCE_COUNT for item in first.items))
        self.assertTrue(all(item.source_count == SOURCE_COUNT for item in first.items))
        self.assertEqual(
            self.database.execute(
                "SELECT count(*) FROM displayable_artist_genre_memberships"
            ).fetchone()[0],
            4,
        )

    def test_same_run_ref_rejects_changed_complete_input(self) -> None:
        manifest = self.direct_manifest("musicbrainz")
        self.repository.add_evidence(self.evidence(2, 1))
        request = self.request("fixture:fingerprint:1", manifest)
        self.repository.materialize(request)
        self.repository.add_evidence(self.evidence(14, 15))

        with self.assertRaises(ValueError):
            self.repository.materialize(request)

    def test_same_run_ref_rejects_changed_run_identity(self) -> None:
        manifest = self.direct_manifest("musicbrainz")
        self.repository.add_evidence(self.evidence(2, 1))
        self.repository.materialize(self.request("fixture:identity:1", manifest))

        with self.assertRaises(ValueError):
            self.repository.materialize(self.request("fixture:identity:1", manifest, revision=2))

    def test_bounds_fail_instead_of_silently_truncating(self) -> None:
        self.repository.add_evidence(self.evidence(2, 1, record_suffix="one"))
        self.repository.add_evidence(self.evidence(2, 1, record_suffix="two"))

        with self.assertRaises(ValueError):
            self.repository.materialize(
                self.request("fixture:bounded:1", self.direct_manifest("musicbrainz", max_inputs=1))
            )

    def test_display_view_requires_every_linked_evidence_to_remain_safe(self) -> None:
        first = self.repository.add_evidence(self.evidence(2, 1, source_key="musicbrainz"))
        self.repository.add_evidence(self.evidence(2, 1, source_key="wikidata"))
        manifest = self.direct_manifest("musicbrainz", "wikidata")
        self.repository.materialize(self.request("fixture:suppression:1", manifest))
        self.database.execute(
            """
            INSERT INTO suppression_events (
                target_kind, target_ref, use_kind, event_action, reason,
                effective_at, event_fingerprint
            ) VALUES ('provenance', '201', 'display', 'suppress', 'Fixture', ?, ?)
            """,
            (
                NOW.isoformat(),
                "1313131313131313131313131313131313131313131313131313131313131313",
            ),
        )

        self.assertGreater(first.evidence_id, 0)
        self.assertEqual(
            self.database.execute(
                "SELECT count(*) FROM displayable_artist_genre_memberships"
            ).fetchone()[0],
            0,
        )

    def test_similarity_contracts_require_explicit_weights(self) -> None:
        left = RepresentationVector(
            entity_ref="artist:1",
            components=(FeatureValue(key="idm", value=2.0), FeatureValue(key="jazz", value=1.0)),
        )
        right = RepresentationVector(
            entity_ref="artist:2",
            components=(FeatureValue(key="idm", value=1.0), FeatureValue(key="jazz", value=1.0)),
        )
        weights = (FeatureWeight(key="idm", weight=2.0), FeatureWeight(key="jazz", weight=1.0))

        jaccard = representation_similarity(
            left, right, SimilarityManifest(metric="weighted_jaccard", feature_weights=weights)
        )
        cosine = representation_similarity(
            left, right, SimilarityManifest(metric="weighted_cosine", feature_weights=weights)
        )

        self.assertAlmostEqual(jaccard.score, 3.0 / 5.0)
        self.assertGreater(cosine.score, jaccard.score)
        self.assertNotEqual(jaccard.manifest_sha256, cosine.manifest_sha256)
        with self.assertRaises(ValueError):
            representation_similarity(
                left,
                right,
                SimilarityManifest(
                    metric="weighted_jaccard",
                    feature_weights=(FeatureWeight(key="idm", weight=1.0),),
                ),
            )

    def test_evaluation_uses_fixed_denominators_and_set_stability(self) -> None:
        known = (
            EvaluationClaim(artist_ref="a1", genre_ref="g1"),
            EvaluationClaim(artist_ref="a2", genre_ref="g2"),
            EvaluationClaim(artist_ref="a3", genre_ref="g3"),
        )
        predictions = (
            EvaluationPrediction(artist_ref="a1", genre_ref="g1", source_keys=("musicbrainz",)),
            EvaluationPrediction(artist_ref="a2", genre_ref="wrong", source_keys=("wikidata",)),
        )
        previous = (
            EvaluationPrediction(artist_ref="a1", genre_ref="g1", source_keys=("musicbrainz",)),
            EvaluationPrediction(artist_ref="a4", genre_ref="g4", source_keys=("listenbrainz",)),
        )

        metrics = evaluate_predictions(
            predictions,
            known,
            previous,
            eligible_artist_refs=frozenset({"a1", "a2", "a3", "a4"}),
            expected_source_keys=frozenset({"musicbrainz", "wikidata", "listenbrainz"}),
        )

        self.assertEqual(metrics.known_positive_prediction_fraction, 0.5)
        self.assertAlmostEqual(metrics.known_positive_recall, 1.0 / 3.0)
        self.assertEqual(metrics.coverage, 0.5)
        self.assertAlmostEqual(metrics.source_coverage, 2.0 / 3.0)
        self.assertAlmostEqual(metrics.stability, 1.0 / 3.0)

    def test_local_evaluation_document_is_reproducible(self) -> None:
        document = EvaluationDocument.model_validate_json(
            (ROOT / "tests" / "fixtures" / "membership_evaluation.json").read_text(encoding="utf-8")
        )

        metrics = evaluate_document(document)

        self.assertEqual(metrics.known_positive_prediction_fraction, 0.5)
        self.assertAlmostEqual(metrics.source_coverage, 2.0 / 3.0)

    def test_evaluation_rejects_padded_fixed_denominators(self) -> None:
        payload = {
            "predictions": [],
            "known_claims": [],
            "eligible_artist_refs": [" artist:1"],
            "expected_source_keys": ["musicbrainz"],
        }

        with self.assertRaises(ValidationError):
            EvaluationDocument.model_validate(payload)


if __name__ == "__main__":
    unittest.main()
