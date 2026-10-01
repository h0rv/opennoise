"""Cross-source fixture verification for the executable local discovery query."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from uuid import UUID

from opennoise.analysis.listenbrainz_playlist_release_group_overlap import (
    NativeReleaseGroupEvidence,
    PlaylistRecordingOccurrence,
)
from opennoise.analysis.playlist_album_evidence_join import (
    DirectArtistGenreEvidence,
    PlaylistAlbumEvidenceContext,
    PlaylistAlbumEvidenceJoinReport,
    ReleaseGroupCreditedArtistEvidence,
)
from opennoise.analysis.playlist_album_evidence_join import (
    report_sha256 as playlist_hash,
)
from opennoise.ingest.musicbrainz.model_adapter import adapter_report_sha256
from opennoise.ingest.musicbrainz.release_group_album_examples import report_sha256
from opennoise.ingest.musicbrainz.release_group_native_observation import NativeGenreObservation
from opennoise.serving.local.musicbrainz_album_context import (
    AlbumContextError,
    query_album_context,
    response_json,
    verify_playlist_context_report,
)
from opennoise.serving.local.musicbrainz_artist_evidence import LocalMusicBrainzArtistEvidenceStore
from opennoise.taxonomy.seeds.reconciliation import (
    SeedReconciliationArtifact,
    SeedReconciliationCoverage,
    SeedReconciliationDisposition,
    _seed_identity_hash_from_dispositions,
    _sha256,
)
from tests.serving.local.test_musicbrainz_artist_evidence import _database, _sources


def _album_report():  # noqa: ANN202 -- Reuse the established typed album fixture.
    from tests.serving.local.test_musicbrainz_album_discovery import (  # noqa: PLC0415 -- Fixture is not a discovered test class.
        MusicBrainzAlbumDiscoveryTests,
    )

    fixture = MusicBrainzAlbumDiscoveryTests()
    fixture.setUp()
    report = fixture.report
    row = report.seed_rows[0].model_copy(update={"seed_source_item_id": "item2"})
    report = report.model_copy(
        update={
            "seed_rows": (row,),
            "source_archive_sha256": "a" * 64,
        }
    )
    return report.model_copy(update={"output_sha256": report_sha256(report)})


def _playlist_report(source, album):  # noqa: ANN001, ANN202 -- Typed established fixture inputs.
    artist_credits = tuple(
        ReleaseGroupCreditedArtistEvidence(
            artist_mbid=credit.artist_mbid,
            artist_name=f"Artist {index}",
            credited_name=f"Artist {index}",
            joinphrase="",
            credit_position=index,
            record_content_sha256=album.record_content_sha256,
        )
        for index, credit in enumerate(album.credited_artist_mbids)
    )
    context = PlaylistAlbumEvidenceContext(
        release_group_mbid=album.release_group_mbid,
        playlist_occurrences=(
            PlaylistRecordingOccurrence(
                playlist_mbid=UUID("00000000-0000-4000-8000-000000000080"),
                recording_mbid=UUID("00000000-0000-4000-8000-000000000090"),
                ordinal=0,
                curator_kind="unknown",
            ),
        ),
        native_release_group_evidence=(
            NativeReleaseGroupEvidence(
                release_group_mbid=UUID(album.release_group_mbid),
                record_content_sha256=album.record_content_sha256,
                proper_genres=(
                    NativeGenreObservation(
                        genre_mbid=album.genre_mbid,
                        name=album.genre_name,
                        vote_count=album.genre_vote_count,
                    ),
                ),
                positive_tags=(),
            ),
        ),
        native_proper_genre_status="present",
        credited_artists=artist_credits,
        direct_anchor_artist_seed_evidence=(),
    )
    report = PlaylistAlbumEvidenceJoinReport(
        playlist_overlap_report_sha256="f" * 64,
        release_group_evidence_artifact_sha256=source.output_sha256,
        release_group_evidence_database_sha256=source.evidence_database_sha256,
        artist_credit_archive_sha256=source.source_archive_sha256,
        artist_credit_archive_bytes=source.source_archive_bytes,
        requested_release_group_count=1,
        release_groups_with_native_proper_genres=1,
        release_groups_with_credited_artist_evidence=1,
        credited_artists_with_direct_evidence=0,
        contexts=(context,),
        output_sha256="0" * 64,
    )
    return report.model_copy(update={"output_sha256": playlist_hash(report)})


class AlbumContextTests(unittest.TestCase):
    def test_exact_artist_context_roles_and_determinism(self) -> None:
        with TemporaryDirectory() as temporary:
            store = LocalMusicBrainzArtistEvidenceStore(_sources(_database(Path(temporary) / "db")))
            store.start()
            report = _album_report()
            first = query_album_context(report, store, genre_name="Rock")
            second = query_album_context(report, store, genre_name="Rock")
            self.assertEqual(response_json(first), response_json(second))
            self.assertEqual(first.result_count, 1)
            result = first.results[0]
            self.assertEqual(result.playlist_status, "unavailable")
            self.assertEqual(len(result.credited_artist_contexts), 2)
            self.assertEqual(
                {
                    row.facet
                    for row in result.credited_artist_contexts[0].direct_artist_observations
                },
                {"musicbrainz_genre", "musicbrainz_tag"},
            )
            self.assertEqual(
                result.credited_artist_contexts[0].direct_artist_observations[0].evidence_reference,
                "ref:four",
            )
            self.assertFalse(first.export_allowed)
            self.assertFalse(first.model_input_allowed)
            empty = query_album_context(report, store, genre_name="ROCK")
            self.assertEqual(empty.query, "ROCK")
            self.assertEqual(empty.result_count, 0)
            with self.assertRaisesRegex(AlbumContextError, "limit"):
                query_album_context(report, store, genre_name="Rock", limit=cast("int", 1.5))

    def test_playlist_exact_paths_conflicts_and_receipt_tampering(self) -> None:
        with TemporaryDirectory() as temporary:
            store = LocalMusicBrainzArtistEvidenceStore(_sources(_database(Path(temporary) / "db")))
            store.start()
            report = _album_report()
            playlist = _playlist_report(
                store.sources.evidence_artifact, report.seed_rows[0].examples[0]
            )
            result = query_album_context(report, store, genre_name="Rock", playlist_report=playlist)
            self.assertEqual(result.results[0].playlist_status, "matched")
            no_match = query_album_context(
                report, store, genre_name="rock", playlist_report=playlist
            )
            self.assertEqual(no_match.results[0].playlist_status, "no_exact_matches")
            with self.assertRaisesRegex(AlbumContextError, "hash"):
                verify_playlist_context_report(
                    playlist.model_copy(update={"output_sha256": "0" * 64})
                )
            context = playlist.contexts[0]
            duplicate = playlist.model_copy(update={"contexts": (context, context)})
            duplicate = duplicate.model_copy(update={"output_sha256": playlist_hash(duplicate)})
            with self.assertRaisesRegex(AlbumContextError, "identical recording"):
                verify_playlist_context_report(duplicate)
            bad_credit = context.credited_artists[0].model_copy(
                update={"record_content_sha256": "f" * 64}
            )
            bad_context = context.model_copy(
                update={"credited_artists": (bad_credit, context.credited_artists[1])}
            )
            bad = playlist.model_copy(update={"contexts": (bad_context,)})
            bad = bad.model_copy(update={"output_sha256": playlist_hash(bad)})
            with self.assertRaisesRegex(AlbumContextError, "credit record hash"):
                verify_playlist_context_report(bad)
            changed = context.model_copy(
                update={"credited_artists": tuple(reversed(context.credited_artists))}
            )
            # Source order is determined by retained credit positions, not container order.
            ordered = playlist.model_copy(update={"contexts": (changed,)})
            ordered = ordered.model_copy(update={"output_sha256": playlist_hash(ordered)})
            query_album_context(report, store, genre_name="Rock", playlist_report=ordered)
            changed_credit = context.credited_artists[0].model_copy(
                update={"artist_mbid": "00000000-0000-4000-8000-000000000099"}
            )
            changed = context.model_copy(
                update={"credited_artists": (changed_credit, context.credited_artists[1])}
            )
            conflict = playlist.model_copy(update={"contexts": (changed,)})
            conflict = conflict.model_copy(update={"output_sha256": playlist_hash(conflict)})
            with self.assertRaisesRegex(AlbumContextError, "conflicting artist"):
                query_album_context(report, store, genre_name="Rock", playlist_report=conflict)
            direct = DirectArtistGenreEvidence(
                artist_mbid=changed_credit.artist_mbid,
                seed_id="item2",
                facets=("musicbrainz_genre",),
                evidence_references=("ref:forged",),
            )
            forged_context = changed.model_copy(
                update={"direct_anchor_artist_seed_evidence": (direct,)}
            )
            forged = conflict.model_copy(
                update={
                    "contexts": (forged_context,),
                    "credited_artists_with_direct_evidence": 1,
                }
            )
            forged = forged.model_copy(update={"output_sha256": playlist_hash(forged)})
            with self.assertRaisesRegex(AlbumContextError, "outside exact album credits"):
                query_album_context(report, store, genre_name="Rock", playlist_report=forged)
            occurrence = context.playlist_occurrences[0].model_copy(update={"ordinal": 1})
            second_path = context.model_copy(update={"playlist_occurrences": (occurrence,)})
            multi = playlist.model_copy(update={"contexts": (context, second_path)})
            multi = multi.model_copy(update={"output_sha256": playlist_hash(multi)})
            result = query_album_context(report, store, genre_name="Rock", playlist_report=multi)
            self.assertEqual(len(result.results[0].playlist_contexts), 2)

    def test_bounds_source_binding_and_exact_artist_queries(self) -> None:
        with TemporaryDirectory() as temporary:
            store = LocalMusicBrainzArtistEvidenceStore(_sources(_database(Path(temporary) / "db")))
            report = _album_report()
            with self.assertRaisesRegex(AlbumContextError, "startup-certified"):
                query_album_context(report, store, genre_name="Rock")
            store.start()
            wrong = report.model_copy(update={"source_archive_sha256": "f" * 64})
            with self.assertRaisesRegex(AlbumContextError, "archives differ"):
                query_album_context(wrong, store, genre_name="Rock")
            first_artist = report.seed_rows[0].examples[0].credited_artist_mbids[0].artist_mbid
            exact = query_album_context(report, store, artist_mbid=first_artist)
            self.assertEqual(exact.result_count, 1)
            self.assertEqual(exact.query, first_artist)
            absent = query_album_context(
                report, store, artist_mbid="00000000-0000-4000-8000-000000000099"
            )
            self.assertEqual(absent.result_count, 0)
            second_artist = report.seed_rows[0].examples[0].credited_artist_mbids[1].artist_mbid
            truncated = query_album_context(report, store, artist_mbid=second_artist, limit=1)
            self.assertEqual(truncated.total_album_count, 2)
            self.assertEqual(truncated.remaining_album_count, 1)

    def test_cli_reads_real_verified_fixture_files(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = _sources(_database(root / "evidence.sqlite"))
            dispositions = tuple(
                SeedReconciliationDisposition(
                    source_item_id=row.source_item_id,
                    source_external_id=row.source_external_id,
                    seed_name=row.seed_name,
                    normalized_name=row.normalized_name,
                    disposition="unresolved",
                    reason="fixture",
                )
                for row in sources.reconciliation.dispositions
            )
            coverage = SeedReconciliationCoverage(
                seed_count=2,
                reconciled_count=0,
                public_only_count=0,
                musicbrainz_only_count=0,
                review_only_count=0,
                ambiguous_count=0,
                unresolved_count=2,
                public_identity_count=0,
                musicbrainz_identity_count=0,
                musicbrainz_genre_identity_count=0,
                musicbrainz_tag_identity_count=0,
                collision_seed_count=0,
            )
            reconciliation = SeedReconciliationArtifact(
                seed_input_sha256="b" * 64,
                seed_source_id="fixture",
                seed_source_content_sha256="e" * 64,
                seed_identity_sha256=_seed_identity_hash_from_dispositions(dispositions),
                taxonomy_artifact_sha256="a" * 64,
                input_sha256="b" * 64,
                seed_count=2,
                dispositions=dispositions,
                coverage=coverage,
                output_sha256="0" * 64,
            )
            reconciliation = reconciliation.model_copy(
                update={
                    "output_sha256": _sha256(
                        reconciliation.model_dump(mode="json", exclude={"output_sha256"})
                    )
                }
            )
            adapter = sources.adapter_report.model_copy(
                update={
                    "seed_reconciliation_output_sha256": reconciliation.output_sha256,
                    "seed_identity_fingerprint": reconciliation.seed_identity_sha256,
                }
            )
            adapter = adapter.model_copy(update={"output_sha256": adapter_report_sha256(adapter)})
            sources = replace(sources, reconciliation=reconciliation, adapter_report=adapter)
            reconciliation_path = root / "reconciliation.json"
            reconciliation_path.write_text(reconciliation.model_dump_json())
            report = _album_report().model_copy(
                update={
                    "seed_reconciliation_sha256": hashlib.sha256(
                        reconciliation_path.read_bytes()
                    ).hexdigest()
                }
            )
            report = report.model_copy(update={"output_sha256": report_sha256(report)})
            paths = {
                "--album-report": (root / "album.json", report),
                "--evidence-artifact": (root / "evidence.json", sources.evidence_artifact),
                "--adapter-report": (root / "adapter.json", adapter),
            }
            command = [
                sys.executable,
                "scripts/query_local_musicbrainz_album_context.py",
                "--evidence-db",
                str(sources.database),
                "--reconciliation",
                str(reconciliation_path),
                "--genre-name",
                "Rock",
            ]
            for flag, (path, artifact) in paths.items():
                path.write_text(artifact.model_dump_json())
                command.extend((flag, str(path)))
            process = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
            self.assertEqual(process.returncode, 0, process.stderr)
            payload = json.loads(process.stdout)
            self.assertEqual(payload["result_count"], 1)
            self.assertFalse(payload["serving_allowed"])
