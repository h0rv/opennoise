import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from opennoise.ingest.musicbrainz.artist_credit_catalog_candidate import (
    materialize_artist_credit_candidate,
)
from opennoise.ingest.musicbrainz.artist_credit_enrichment import (
    _projection_sha256,
)
from opennoise.ingest.musicbrainz.release_hydration import MusicBrainzHydrationError

RELEASE = "10000000-0000-4000-8000-000000000001"
GROUP = "20000000-0000-4000-8000-000000000001"
TRACK = "30000000-0000-4000-8000-000000000001"
RECORDING = "40000000-0000-4000-8000-000000000001"
ARTIST = "50000000-0000-4000-8000-000000000001"


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _inputs(
    root: Path, *, credit_hydration_sha: str | None = None
) -> tuple[Path, Path, Path, str, str]:
    root.mkdir(parents=True, exist_ok=True)
    hydration = {
        "selection_sha256": "a" * 64,
        "source_representative_artifact_sha256": "b" * 64,
        "releases": [
            {
                "release_id": RELEASE,
                "release_group_id": GROUP,
                "title": "Release",
                "release_group_title": "Group",
                "media": [
                    {
                        "position": 1,
                        "tracks": [
                            {
                                "track_id": TRACK,
                                "recording_id": RECORDING,
                                "title": "Track",
                                "position": 1,
                                "number": "1",
                            }
                        ],
                    }
                ],
                "evidence": [
                    {
                        "representative_kind": "release_group",
                        "representative_id": GROUP,
                        "representative_rank": 1,
                        "endpoint": f"release/{RELEASE}",
                        "response_sha256": "c" * 64,
                    }
                ],
            }
        ],
    }
    hydration_path = root / "hydration.json"
    hydration_bytes = json.dumps(hydration).encode()
    hydration_path.write_bytes(hydration_bytes)
    hydration_sha = _sha256(hydration_bytes)
    payload: dict[str, object] = {
        "id": RELEASE,
        "artist-credit": [{"artist": {"id": ARTIST, "name": "Artist"}, "name": "Artist"}],
        "media": [
            {
                "tracks": [
                    {
                        "recording": {
                            "id": RECORDING,
                            "artist-credit": [
                                {"artist": {"id": ARTIST, "name": "Artist"}, "name": "Artist"}
                            ],
                        }
                    }
                ]
            }
        ],
    }
    endpoint = f"release/{RELEASE}"
    projection = _projection_sha256(endpoint=endpoint, payload=payload)
    cache = root / "cache"
    cache.mkdir()
    (cache / "release.json").write_text(
        json.dumps(
            {
                "record_kind": "success",
                "endpoint": endpoint,
                "response_sha256": "d" * 64,
                "projection_sha256": projection,
                "payload": payload,
            }
        )
    )
    relations = []
    for kind, entity_id in (("release", RELEASE), ("recording", RECORDING)):
        relations.append(
            {
                "entity_kind": kind,
                "entity_id": entity_id,
                "source_endpoint": endpoint,
                "observed_response_sha256": "d" * 64,
                "projection_sha256": projection,
                "members": [
                    {
                        "position": 0,
                        "artist_id": ARTIST,
                        "artist_name": "Artist",
                        "credited_name": "Artist",
                        "join_phrase": "",
                    }
                ],
            }
        )
    credit = {
        "source_hydration_sha256": credit_hydration_sha or hydration_sha,
        "requested_release_ids": [RELEASE],
        "credits": relations,
        "abstentions": [],
        "failures": [],
        "cache_mode": "offline_cache_only",
    }
    credit_path = root / "credits.json"
    credit_bytes = json.dumps(credit).encode()
    credit_path.write_bytes(credit_bytes)
    return hydration_path, credit_path, cache, hydration_sha, _sha256(credit_bytes)


class ArtistCreditCatalogCandidateTests(unittest.TestCase):
    def test_materializes_verified_partition_and_replays_core_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hydration, credit, cache, hydration_sha, credit_sha = _inputs(root)
            report_path = root / "candidate-report.json"
            report = materialize_artist_credit_candidate(
                hydration_artifact_path=hydration,
                credit_artifact_path=credit,
                cache_directory=cache,
                candidate_database_path=root / "candidate.sqlite",
                expected_hydration_sha256=hydration_sha,
                expected_credit_sha256=credit_sha,
                report_path=report_path,
            )
            self.assertEqual((report.release_relations, report.recording_relations), (1, 1))
            self.assertEqual(report.ordered_credit_members, 2)
            self.assertEqual(
                report.idempotent_core_replay,
                {"releases": 0, "media": 0, "tracks": 0, "recordings": 0},
            )
            self.assertEqual(
                (report.foreign_key_violations, report.provenance_record_count), (0, 2)
            )
            persisted = json.loads(report_path.read_text())
            self.assertEqual(persisted["candidate_database_path"], report.candidate_database_path)
            self.assertEqual(
                persisted["database_sha256"], _sha256((root / "candidate.sqlite").read_bytes())
            )

    def test_rejects_tampered_cache_before_creating_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hydration, credit, cache, hydration_sha, credit_sha = _inputs(root)
            entry = json.loads((cache / "release.json").read_text())
            entry["payload"]["artist-credit"][0]["name"] = "Tampered"
            (cache / "release.json").write_text(json.dumps(entry))
            target = root / "candidate.sqlite"
            with self.assertRaisesRegex(MusicBrainzHydrationError, "projection SHA-256"):
                materialize_artist_credit_candidate(
                    hydration_artifact_path=hydration,
                    credit_artifact_path=credit,
                    cache_directory=cache,
                    candidate_database_path=target,
                    expected_hydration_sha256=hydration_sha,
                    expected_credit_sha256=credit_sha,
                )
            self.assertFalse(target.exists())

    def test_rejects_source_binding_mismatch_and_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hydration, credit, cache, hydration_sha, credit_sha = _inputs(
                root, credit_hydration_sha="f" * 64
            )
            with self.assertRaisesRegex(MusicBrainzHydrationError, "different hydration"):
                materialize_artist_credit_candidate(
                    hydration_artifact_path=hydration,
                    credit_artifact_path=credit,
                    cache_directory=cache,
                    candidate_database_path=root / "candidate.sqlite",
                    expected_hydration_sha256=hydration_sha,
                    expected_credit_sha256=credit_sha,
                )
            hydration, credit, cache, hydration_sha, credit_sha = _inputs(root / "second")
            target = root / "existing.sqlite"
            target.write_bytes(b"unchanged")
            with self.assertRaisesRegex(MusicBrainzHydrationError, "already exists"):
                materialize_artist_credit_candidate(
                    hydration_artifact_path=hydration,
                    credit_artifact_path=credit,
                    cache_directory=cache,
                    candidate_database_path=target,
                    expected_hydration_sha256=hydration_sha,
                    expected_credit_sha256=credit_sha,
                )
            self.assertEqual(target.read_bytes(), b"unchanged")

    def test_rejects_conflicting_duplicate_hydration_before_staging(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hydration, credit, cache, _, _ = _inputs(root)
            hydration_payload = json.loads(hydration.read_text())
            duplicate = hydration_payload["releases"][0].copy()
            duplicate["title"] = "Conflicting duplicate"
            hydration_payload["releases"].append(duplicate)
            hydration_bytes = json.dumps(hydration_payload).encode()
            hydration.write_bytes(hydration_bytes)
            hydration_sha = _sha256(hydration_bytes)
            credit_payload = json.loads(credit.read_text())
            credit_payload["source_hydration_sha256"] = hydration_sha
            credit_bytes = json.dumps(credit_payload).encode()
            credit.write_bytes(credit_bytes)
            target = root / "conflicting.sqlite"
            with self.assertRaisesRegex(MusicBrainzHydrationError, "conflicting metadata"):
                materialize_artist_credit_candidate(
                    hydration_artifact_path=hydration,
                    credit_artifact_path=credit,
                    cache_directory=cache,
                    candidate_database_path=target,
                    expected_hydration_sha256=hydration_sha,
                    expected_credit_sha256=_sha256(credit_bytes),
                )
            self.assertFalse(target.exists())
