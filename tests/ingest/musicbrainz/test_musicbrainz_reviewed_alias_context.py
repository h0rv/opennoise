from __future__ import annotations

import hashlib
import io
import json
import tarfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from musix.ingest.musicbrainz.musicbrainz_model_adapter import (
    MusicBrainzModelAdapterPolicy,
    adapt_musicbrainz_seed_targets,
)
from musix.ingest.musicbrainz.musicbrainz_reviewed_alias_context import (
    ReviewedAliasContextError,
    adapt_reviewed_alias_context,
    build_reviewed_alias_context,
    combine_reviewed_alias_context_model_input,
)
from musix.ingest.musicbrainz.musicbrainz_reviewed_alias_context import (
    artifact_sha256 as context_artifact_sha256,
)
from musix.ingest.musicbrainz.musicbrainz_seed_targets import (
    ReviewedSeedAlias,
    extract_musicbrainz_seed_targets,
    write_seed_target_artifact,
)
from musix.taxonomy.genre_seed_universe import SeedInput, SeedName
from musix.taxonomy.seed_reconciliation import (
    SeedReconciliationArtifact,
    SeedReconciliationCoverage,
    SeedReconciliationDisposition,
)

_ARTIST = "00000000-0000-4000-8000-000000000001"


def _seed() -> SeedInput:
    return SeedInput(
        source_id="fixture-seed",
        source_content_sha256="a" * 64,
        artifact_sha256="b" * 64,
        names=(
            SeedName(
                source_item_id="item887",
                source_external_id="eno:887",
                name="intelligent dance music",
            ),
        ),
    )


def _archive(path: Path) -> None:
    record = json.dumps(
        {
            "id": _ARTIST,
            "genres": [],
            "tags": [
                {"name": "intelligent dance music", "count": 2},
                {"name": "IDM", "count": 4},
            ],
        }
    ).encode()
    with tarfile.open(path, "w:xz") as archive:
        schema = tarfile.TarInfo("JSON_DUMPS_SCHEMA_NUMBER")
        schema.size = 2
        archive.addfile(schema, io.BytesIO(b"1\n"))
        artists = tarfile.TarInfo("mbdump/artist")
        artists.size = len(record) + 1
        archive.addfile(artists, io.BytesIO(record + b"\n"))


def _reconciliation() -> SeedReconciliationArtifact:
    disposition = SeedReconciliationDisposition(
        source_item_id="item887",
        source_external_id="eno:887",
        seed_name="intelligent dance music",
        normalized_name="intelligent dance music",
        disposition="unresolved",
        reason="fixture",
    )
    identity = hashlib.sha256(
        json.dumps(
            [
                {
                    "source_item_id": disposition.source_item_id,
                    "source_external_id": disposition.source_external_id,
                    "name": disposition.seed_name,
                }
            ],
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    preliminary = SeedReconciliationArtifact(
        seed_input_sha256="b" * 64,
        seed_source_id="fixture-seed",
        seed_source_content_sha256="a" * 64,
        seed_identity_sha256=identity,
        taxonomy_artifact_sha256="c" * 64,
        input_sha256="d" * 64,
        seed_count=1,
        dispositions=(disposition,),
        coverage=SeedReconciliationCoverage(
            seed_count=1,
            reconciled_count=0,
            public_only_count=0,
            musicbrainz_only_count=0,
            review_only_count=0,
            ambiguous_count=0,
            unresolved_count=1,
            public_identity_count=0,
            musicbrainz_identity_count=0,
            musicbrainz_genre_identity_count=0,
            musicbrainz_tag_identity_count=0,
            collision_seed_count=0,
        ),
        output_sha256="0" * 64,
    )
    digest = hashlib.sha256(
        json.dumps(
            preliminary.model_dump(mode="json", exclude={"output_sha256"}),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return preliminary.model_copy(update={"output_sha256": digest})


class ReviewedAliasContextTests(unittest.TestCase):
    def test_deferred_context_matches_eager_alias_and_builds_combined_input(self) -> None:
        alias = ReviewedSeedAlias(
            source_item_id="item887",
            alias="IDM",
            approval_ref="reviewed:idm-v1",
            facets=("tag",),
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "artist.tar.xz"
            baseline_path = root / "baseline.json"
            aliases_path = root / "aliases.json"
            _archive(archive)
            baseline = extract_musicbrainz_seed_targets(archive, _seed())
            eager = extract_musicbrainz_seed_targets(archive, _seed(), reviewed_aliases=(alias,))
            write_seed_target_artifact(baseline_path, baseline)
            original_bytes = baseline_path.read_bytes()
            aliases_path.write_text(json.dumps([alias.model_dump(mode="json")]))

            context = build_reviewed_alias_context(
                baseline_path=baseline_path, alias_config_path=aliases_path
            )
            combined = adapt_reviewed_alias_context(
                baseline,
                _reconciliation(),
                context,
                MusicBrainzModelAdapterPolicy(expected_seed_count=1),
            )
            baseline_result = adapt_musicbrainz_seed_targets(
                baseline,
                _reconciliation(),
                MusicBrainzModelAdapterPolicy(expected_seed_count=1),
            )
            materialized, receipt = combine_reviewed_alias_context_model_input(
                baseline_result.model_input,
                baseline_result.report,
                context,
            )

            self.assertEqual(baseline_path.read_bytes(), original_bytes)
            self.assertEqual(len(context.memberships), 1)
            deferred = context.memberships[0]
            eager_alias = next(row for row in eager.evidence if row.target_identity == "tag:idm")
            self.assertEqual(
                (
                    deferred.seed_source_item_id,
                    deferred.artist_id,
                    deferred.facet,
                    deferred.tag_identity,
                    deferred.tag_name,
                    deferred.positive_weight,
                    deferred.source_record_id,
                    deferred.source_record_ordinal,
                    deferred.source_record_sha256,
                    deferred.source_record_byte_length,
                ),
                (
                    eager_alias.seed_source_item_id,
                    eager_alias.artist_id,
                    eager_alias.facet,
                    eager_alias.target_identity,
                    eager_alias.target_name,
                    eager_alias.positive_weight,
                    eager_alias.source_record_id,
                    eager_alias.source_record_ordinal,
                    eager_alias.source_record_sha256,
                    eager_alias.source_record_byte_length,
                ),
            )
            self.assertEqual(deferred.approval_ref, alias.approval_ref)
            self.assertIn(context.alias_mapping_sha256, eager_alias.evidence_ref)
            self.assertEqual(deferred.tag_count, 4)
            self.assertEqual(deferred.positive_weight, 4.0)
            self.assertEqual(combined.baseline_unique_seed_artist_count, 1)
            self.assertEqual(combined.reviewed_alias_unique_seed_artist_count, 1)
            self.assertEqual(combined.combined_unique_seed_artist_count, 1)
            self.assertEqual(len(combined.combined_aggregates), 1)
            self.assertEqual(combined.combined_aggregates[0].positive_weight, 6.0)
            self.assertEqual(len(combined.combined_aggregates[0].source_evidence_refs), 2)
            self.assertEqual(len(combined.model_input.direct_memberships), 1)
            self.assertEqual(combined.model_input.direct_memberships[0].value, 6.0)
            self.assertIn(
                "reviewed-alias-context-union:",
                combined.model_input.direct_memberships[0].evidence_ref,
            )
            self.assertEqual(
                combined.model_input.artifacts[-1].content_sha256,
                context.output_sha256,
            )
            self.assertNotEqual(combined.output_sha256, baseline.output_sha256)
            self.assertEqual(
                [
                    (row.artist_id, row.genre_id, row.facet, row.value)
                    for row in materialized.direct_memberships
                ],
                [
                    (row.artist_id, row.genre_id, row.facet, row.value)
                    for row in combined.model_input.direct_memberships
                ],
            )
            self.assertEqual(
                receipt.combined_model_input_sha256,
                hashlib.sha256(
                    json.dumps(
                        materialized.model_dump(mode="json"),
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode()
                ).hexdigest(),
            )

    def test_rejects_unknown_alias_seed_and_mismatched_baseline_binding(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "artist.tar.xz"
            baseline_path = root / "baseline.json"
            aliases_path = root / "aliases.json"
            _archive(archive)
            baseline = extract_musicbrainz_seed_targets(archive, _seed())
            write_seed_target_artifact(baseline_path, baseline)
            invalid = ReviewedSeedAlias(
                source_item_id="item-missing",
                alias="IDM",
                approval_ref="reviewed:idm-v1",
                facets=("tag",),
            )
            aliases_path.write_text(json.dumps([invalid.model_dump(mode="json")]))
            with self.assertRaisesRegex(ReviewedAliasContextError, "known noncanonical"):
                build_reviewed_alias_context(
                    baseline_path=baseline_path, alias_config_path=aliases_path
                )

            valid = invalid.model_copy(update={"source_item_id": "item887"})
            aliases_path.write_text(json.dumps([valid.model_dump(mode="json")]))
            context = build_reviewed_alias_context(
                baseline_path=baseline_path, alias_config_path=aliases_path
            )
            mismatched = context.model_copy(update={"baseline_output_sha256": "f" * 64})
            mismatched = mismatched.model_copy(
                update={"output_sha256": context_artifact_sha256(mismatched)}
            )
            with self.assertRaisesRegex(ReviewedAliasContextError, "does not bind"):
                adapt_reviewed_alias_context(
                    baseline,
                    _reconciliation(),
                    mismatched,
                    MusicBrainzModelAdapterPolicy(expected_seed_count=1),
                )
