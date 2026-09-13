from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from opennoise.models.modeling import (
    DirectMembershipEvidence,
    GenreIdentity,
    PublicArtifact,
    PublicModelInput,
)
from opennoise.serving.public.artist_membership import (
    ApprovedPublicMembershipInput,
    NameUniverse,
    NameUniverseEntry,
    PublicArtistMembershipSourcePolicy,
    build_public_artist_membership_candidate,
)
from opennoise.serving.public.artist_membership_historical import (
    evaluate_public_artist_membership_historical,
)

_PUBLIC_DATABASE = Path(
    "/home/h0rv/projects/opennoise/.cache/public-release-custody-integrated/objects/cache/sha256/"
    "282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866.sqlite"
)
_HISTORICAL_DATABASE = Path(
    "/home/h0rv/projects/opennoise/.cache/historical-custody-vault/historical-h3/membership/sha256/"
    "098dc8780b3f4a8daf1240d36bec7eb7be563dc2275d998dbc7509c3fb1859df.sqlite"
)


class PublicArtistMembershipHistoricalTests(unittest.TestCase):
    def _synthetic_inputs(
        self, root: Path, *, ambiguous: bool = False
    ) -> tuple[Path, Path, Path, Path]:
        universe = NameUniverse(
            source_content_sha256="a" * 64,
            names=tuple(
                NameUniverseEntry(
                    source_item_id=f"seed:{index:04d}",
                    external_id=f"external:{index:04d}",
                    name="Jazz" if index == 0 else f"Unused {index}",
                )
                for index in range(6291)
            ),
        )
        model_input = PublicModelInput(
            artifacts=(
                PublicArtifact(
                    source="musicbrainz",
                    snapshot="synthetic",
                    artifact_key="artists.json",
                    content_sha256="b" * 64,
                    export_allowed=True,
                ),
            ),
            genres=(GenreIdentity(genre_id="genre:jazz", name="Jazz", evidence_refs=("g:jazz",)),),
            direct_memberships=(
                DirectMembershipEvidence(
                    artist_id="musicbrainz:artist:a1",
                    genre_id="genre:jazz",
                    facet="musicbrainz_tag",
                    value=1.0,
                    evidence_ref="mb:a1:jazz",
                ),
            ),
        )
        approved = ApprovedPublicMembershipInput(
            public_model_input=model_input,
            input_file_sha256="c" * 64,
            public_model_input_sha256=hashlib.sha256(
                json.dumps(
                    model_input.model_dump(mode="json"),
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode()
            ).hexdigest(),
            row_export_policy_sha256="d" * 64,
            declared_direct_row_count=1,
            declared_aggregate_row_count=0,
        )
        candidate = build_public_artist_membership_candidate(
            universe, approved, PublicArtistMembershipSourcePolicy()
        )
        candidate_path = root / "candidate.json"
        approved_path = root / "approved.json"
        candidate_path.write_text(candidate.model_dump_json(), encoding="utf-8")
        approved_path.write_text(approved.model_dump_json(), encoding="utf-8")

        public_path = root / "public.sqlite"
        with closing(sqlite3.connect(public_path)) as public:
            public.executescript(
                """
                CREATE TABLE identifier_types (id INTEGER PRIMARY KEY, type_key TEXT);
                CREATE TABLE entity_identifiers (
                    entity_id INTEGER, identifier_type_id INTEGER, normalized_value TEXT
                );
                CREATE TABLE entity_names (
                    entity_id INTEGER, name_kind TEXT, name TEXT,
                    language_tag TEXT, is_preferred INTEGER
                );
                """
            )
            public.execute("INSERT INTO identifier_types VALUES (1, 'musicbrainz_artist_id')")
            public.executemany(
                "INSERT INTO entity_identifiers VALUES (?, 1, ?)", ((1, "a1"), (2, "a2"))
            )
            public.executemany(
                "INSERT INTO entity_names VALUES (?, 'primary', ?, 'en', 1)",
                ((1, "Alpha"), (2, "Alpha" if ambiguous else "Other")),
            )
            public.execute("INSERT INTO entity_names VALUES (2, 'alias', 'Alpha', 'en', 0)")
            public.commit()

        historical_path = root / "historical.sqlite"
        with closing(sqlite3.connect(historical_path)) as historical:
            historical.executescript(
                """
                CREATE TABLE genres (id INTEGER PRIMARY KEY, name TEXT);
                CREATE TABLE historical_genre_artist_observations (
                    id INTEGER PRIMARY KEY, genre_id INTEGER, source_artist_name TEXT,
                    source_local_rank INTEGER
                );
                """
            )
            historical.execute("INSERT INTO genres VALUES (1, 'Jazz')")
            historical.execute(
                "INSERT INTO historical_genre_artist_observations VALUES (1, 1, 'Alpha', 1)"
            )
            historical.commit()
        return candidate_path, approved_path, public_path, historical_path

    def test_synthetic_evaluation_ranks_top_k_and_ignores_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._synthetic_inputs(Path(directory))
            report = evaluate_public_artist_membership_historical(*paths, k=1)
        self.assertEqual(report.matched_genre_count, 1)
        self.assertEqual(report.candidate_prediction_count, 1)
        self.assertEqual(report.candidate_overlap_count, 1)
        self.assertEqual(report.micro_recall_at_k, 1.0)

    def test_synthetic_evaluation_excludes_ambiguous_preferred_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._synthetic_inputs(Path(directory), ambiguous=True)
            report = evaluate_public_artist_membership_historical(*paths, k=1)
        self.assertEqual(report.mapped_historical_positive_count, 0)
        self.assertEqual(report.candidate_overlap_count, 0)

    def test_synthetic_evaluation_rejects_zero_top_k(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._synthetic_inputs(Path(directory))
            with self.assertRaisesRegex(ValueError, "positive"):
                evaluate_public_artist_membership_historical(*paths, k=0)

    def test_synthetic_evaluation_rejects_input_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate, approved, public, historical = self._synthetic_inputs(root)
            document = json.loads(candidate.read_text(encoding="utf-8"))
            document["input_sha256"] = "0" * 64
            candidate.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(ValueError):
                evaluate_public_artist_membership_historical(
                    candidate, approved, public, historical, k=1
                )

    def test_real_evaluation_is_positive_only_and_hash_bound(self) -> None:
        candidate = Path(".cache/public-artist-membership-real-input/candidate.json")
        approved = Path(".cache/public-artist-membership-real-input/approved-input.json")
        if not all(
            path.exists() for path in (_PUBLIC_DATABASE, _HISTORICAL_DATABASE, candidate, approved)
        ):
            self.skipTest("real custody artifacts are not present")
        report = evaluate_public_artist_membership_historical(
            candidate, approved, _PUBLIC_DATABASE, _HISTORICAL_DATABASE
        )
        self.assertFalse(report.absence_is_negative)
        self.assertFalse(report.independent_public_gold)
        self.assertEqual(report.historical_source_membership_count, 306136)
        self.assertEqual(report.historical_source_genre_count, 6289)
        self.assertEqual(report.matched_genre_count, 292)

    def test_candidate_input_hash_tampering_is_rejected(self) -> None:
        candidate = Path(".cache/public-artist-membership-real-input/candidate.json")
        approved = Path(".cache/public-artist-membership-real-input/approved-input.json")
        if not all(
            path.exists() for path in (_PUBLIC_DATABASE, _HISTORICAL_DATABASE, candidate, approved)
        ):
            self.skipTest("real custody artifacts are not present")
        with tempfile.TemporaryDirectory() as directory:
            tampered = Path(directory) / "candidate.json"
            document = json.loads(candidate.read_text(encoding="utf-8"))
            document["input_sha256"] = "0" * 64
            tampered.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(ValueError):
                evaluate_public_artist_membership_historical(
                    tampered, approved, _PUBLIC_DATABASE, _HISTORICAL_DATABASE
                )


if __name__ == "__main__":
    unittest.main()
