from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from opennoise.checkpoints.cross_source_artist_genre_corroboration import (
    CrossSourceArtistGenreCorroborationError,
    build_cross_source_artist_genre_corroboration_audit,
)
from opennoise.common import sha256_json
from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    build_portable_direct_proper_genre_custody,
)
from opennoise.evidence.lastfm_artisttags2007_seed_candidates import (
    LastFmArtistTags2007SeedCandidate,
    LastFmArtistTags2007SeedCandidateArtifact,
    LastFmArtistTags2007SeedParseCoverage,
)

_MATCHED_ARTIST = "11111111-1111-4111-8111-111111111111"
_UNMATCHED_ARTIST = "33333333-3333-4333-8333-333333333333"
_GENRE = "22222222-2222-4222-8222-222222222222"


class CrossSourceArtistGenreCorroborationTests(unittest.TestCase):
    def test_counts_only_exact_mbid_and_canonical_seed_overlap(self) -> None:
        with self._inputs() as (receipt_path, object_store, candidate_path):
            report = build_cross_source_artist_genre_corroboration_audit(
                musicbrainz_receipt=receipt_path,
                musicbrainz_object_store=object_store,
                lastfm_candidate_artifact=candidate_path,
            )
        self.assertEqual(
            report.musicbrainz_direct_proper_genre.direct_proper_genre_observation_count, 1
        )
        self.assertEqual(
            report.lastfm_artisttags2007_literal_candidate.literal_candidate_row_count, 2
        )
        self.assertEqual(report.exact_artist_seed_overlap.exact_artist_seed_pair_count, 1)
        self.assertEqual(
            report.exact_artist_seed_overlap.musicbrainz_observations_with_lastfm_candidate_count,
            1,
        )
        self.assertFalse(report.factual_membership_claimed)
        self.assertFalse(report.independent_gold_claimed)
        self.assertFalse(report.public_or_static_artifact_read)

    def test_rejects_candidates_from_a_different_seed_vocabulary(self) -> None:
        with (
            self._inputs(seed_vocabulary_sha256="f" * 64) as (
                receipt_path,
                object_store,
                candidate_path,
            ),
            self.assertRaisesRegex(
                CrossSourceArtistGenreCorroborationError, "canonical seed vocabulary"
            ),
        ):
            build_cross_source_artist_genre_corroboration_audit(
                musicbrainz_receipt=receipt_path,
                musicbrainz_object_store=object_store,
                lastfm_candidate_artifact=candidate_path,
            )

    @staticmethod
    def _inputs(*, seed_vocabulary_sha256: str | None = None) -> _CrossSourceInputs:
        return _CrossSourceInputs(seed_vocabulary_sha256)


class _CrossSourceInputs:
    def __init__(self, seed_vocabulary_sha256: str | None) -> None:
        self._seed_vocabulary_sha256 = seed_vocabulary_sha256
        self._temporary: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> tuple[Path, Path, Path]:
        self._temporary = tempfile.TemporaryDirectory()
        root = Path(self._temporary.name)
        source = root / "seed-target.json"
        reconciliation = root / "reconciliation.json"
        object_store = root / "objects"
        receipt_path = root / "receipt.json"
        source.write_text(
            json.dumps(
                {
                    "evidence": [
                        {
                            "seed_source_item_id": "seed:one",
                            "seed_name": "one",
                            "artist_id": _MATCHED_ARTIST,
                            "facet": "genre",
                            "match_kind": "exact",
                            "target_identity": _GENRE,
                            "target_name": "one",
                            "target_namespace": "musicbrainz_genre_id",
                            "source_record_id": f"musicbrainz:artist:{_MATCHED_ARTIST}",
                            "source_record_sha256": "a" * 64,
                            "evidence_ref": "source:one",
                        }
                    ],
                    "output_sha256": "b" * 64,
                }
            ),
            encoding="utf-8",
        )
        reconciliation.write_text(
            json.dumps(
                {
                    "dispositions": [
                        {
                            "source_item_id": "seed:one",
                            "musicbrainz_identities": [
                                {"namespace": "musicbrainz_genre_id", "identifier": _GENRE}
                            ],
                        }
                    ],
                    "output_sha256": "c" * 64,
                }
            ),
            encoding="utf-8",
        )
        build_portable_direct_proper_genre_custody(
            seed_target=source,
            seed_target_byte_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            seed_target_output_sha256="b" * 64,
            reconciliation=reconciliation,
            object_store=object_store,
            receipt_output=receipt_path,
        )
        candidate_path = root / "lastfm-candidates.json"
        vocabulary_sha256 = (
            self._seed_vocabulary_sha256 or hashlib.sha256(reconciliation.read_bytes()).hexdigest()
        )
        artifact = _candidate_artifact(vocabulary_sha256)
        candidate_path.write_text(artifact.model_dump_json(), encoding="utf-8")
        return receipt_path, object_store, candidate_path

    def __exit__(self, *unused: object) -> None:
        assert self._temporary is not None
        self._temporary.cleanup()


def _candidate_artifact(seed_vocabulary_sha256: str) -> LastFmArtistTags2007SeedCandidateArtifact:
    coverage = LastFmArtistTags2007SeedParseCoverage(
        total_row_count=2,
        accepted_positive_row_count=2,
        malformed_row_count=0,
        invalid_utf8_row_count=0,
        invalid_mbid_row_count=0,
        invalid_count_row_count=0,
        nonpositive_count_row_count=0,
        duplicate_artist_tag_row_count=0,
        literal_candidate_row_count=2,
        literal_unmatched_row_count=0,
        ambiguous_seed_name_row_count=0,
        unretained_abstention_row_count=0,
    )
    candidates = (
        LastFmArtistTags2007SeedCandidate(
            source_row_ordinal=1,
            source_row_sha256="e" * 64,
            musicbrainz_artist_id=_MATCHED_ARTIST,
            source_artist_name="Matched",
            source_tag="one",
            source_count=4,
            seed_source_item_id="seed:one",
            seed_name="one",
        ),
        LastFmArtistTags2007SeedCandidate(
            source_row_ordinal=2,
            source_row_sha256="f" * 64,
            musicbrainz_artist_id=_UNMATCHED_ARTIST,
            source_artist_name="Unmatched",
            source_tag="two",
            source_count=5,
            seed_source_item_id="seed:two",
            seed_name="two",
        ),
    )
    provisional = LastFmArtistTags2007SeedCandidateArtifact.model_construct(
        local_only=True,
        construction_allowed=False,
        factual_direct_membership=False,
        independent_gold_input=False,
        archive_sha256="b2b78000279c00c49ad6c0e764203dfbe4deb18a8012c1f43b7fb64933741c4f",
        archive_byte_count=1,
        seed_vocabulary_sha256=seed_vocabulary_sha256,
        seed_vocabulary_byte_count=1,
        seed_vocabulary_revision="seed-reconciliation-v3",
        seed_count=6291,
        distinct_literal_seed_name_count=2,
        ambiguous_literal_seed_name_count=0,
        parse_coverage=coverage,
        candidates=candidates,
        abstentions=(),
        unretained_abstention_row_count=0,
        output_sha256="0" * 64,
    )
    payload = provisional.model_dump(exclude={"output_sha256"})
    payload["output_sha256"] = sha256_json(payload)
    return LastFmArtistTags2007SeedCandidateArtifact.model_validate(payload)
