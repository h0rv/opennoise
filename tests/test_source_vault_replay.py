from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import HttpUrl, TypeAdapter

from opennoise.models.sources import DownloadSource
from opennoise.pipeline.source_vault_replay import (
    ReleaseManifestReplayInput,
    SourceVaultReplayError,
    SourceVaultReplayReport,
    _candidate_listenbrainz_config,
    _ingest_listenbrainz_candidate,
    _listenbrainz_joint_input,
    load_report,
    replay_combined_source_vault_to_candidate_database,
    replay_historical_source_declarations,
    replay_source_vault_to_candidate_database,
    restore_source_vault,
    verify_source_vault,
    write_report,
)
from opennoise.storage import LocalObjectStore


def _fixture_listenbrainz_source(item: dict[str, object], index: int) -> DownloadSource:
    return DownloadSource(
        id=str(item["source_key"]),
        adapter="listenbrainz_incremental_v1",
        snapshot=f"{2638 + index}-202608{24 + index:02}-000003-incremental",
        url=HttpUrl(f"https://example.test/listenbrainz/{index}"),
        discovery_url=HttpUrl("https://example.test/"),
        expected_content_type="application/json",
        compression="none",
        expected_bytes=int(item["byte_size"]),
        checksum_algorithm="sha256",
        checksum=str(item["artifact_sha256"]),
        data_license="CC0-1.0",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        rights_classification="public_domain",
        local_only=True,
        normalize=True,
        local_search=True,
        display=True,
        embed=True,
        train=True,
        export_metadata=True,
    )


class SourceVaultReplayTests(unittest.TestCase):
    def _assert_combined_sync_validation_does_not_publish(
        self,
        report: SourceVaultReplayReport,
        vault: Path,
        root: Path,
        manifest: Path,
        source_manifest: Path,
    ) -> None:
        target = root / "sync-validation.sqlite"
        with (
            patch("opennoise.pipeline.source_vault_replay._require_verified_vault_objects"),
            patch(
                "opennoise.pipeline.source_vault_replay._ingest_listenbrainz_candidate",
                wraps=_ingest_listenbrainz_candidate,
            ),
            self.assertRaisesRegex(
                SourceVaultReplayError, "combined candidate database replay failed"
            ) as error,
        ):
            replay_combined_source_vault_to_candidate_database(
                report,
                vault,
                target,
                manifest_path=manifest,
                source_manifest_path=source_manifest,
            )
        self.assertIsInstance(error.exception.__cause__, ValueError)
        self.assertIn(
            "verified local artifact bytes do not match source", str(error.exception.__cause__)
        )
        self.assertFalse(target.exists())

    def _fixture(self, root: Path) -> tuple[Path, Path, list[bytes]]:
        vault = root / "vault"
        raw = vault / "raw" / "sha256"
        raw.mkdir(parents=True)
        payloads = [b"first source\n", b"second source\n"]
        inputs = []
        for index, payload in enumerate(payloads):
            digest = hashlib.sha256(payload).hexdigest()
            (raw / digest).write_bytes(payload)
            inputs.append(
                {
                    "source_key": f"source_{index}",
                    "artifact_sha256": digest,
                    "byte_size": len(payload),
                }
            )
        manifest = root / "release-manifest.json"
        manifest.write_text(
            json.dumps({"release_id": "test-release", "inputs": inputs}), encoding="utf-8"
        )
        return manifest, vault, payloads

    def _manifest_payload(self, manifest: Path) -> dict[str, object]:
        return TypeAdapter(dict[str, object]).validate_json(manifest.read_bytes())

    def test_verify_binds_manifest_and_publishes_then_restores(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, vault, payloads = self._fixture(root)
            store = LocalObjectStore(root / "objects")
            with patch(
                "opennoise.pipeline.source_vault_replay.load_release_manifest",
                return_value=self._manifest_payload(manifest),
            ):
                report = verify_source_vault(manifest, vault, object_store=store)
            self.assertTrue(report.complete)
            self.assertEqual(report.object_count, 2)
            report_path = root / "report.json"
            write_report(report, report_path)
            loaded = load_report(report_path)
            self.assertEqual(
                loaded.manifest_sha256, hashlib.sha256(manifest.read_bytes()).hexdigest()
            )
            destination = root / "restored"
            with patch(
                "opennoise.pipeline.source_vault_replay.load_release_manifest",
                return_value=self._manifest_payload(manifest),
            ):
                restore_source_vault(loaded, store, destination, manifest_path=manifest)
            restored = [
                (destination / item.object_key.value).read_bytes() for item in loaded.objects
            ]
            self.assertEqual(restored, payloads)

    def test_verify_rejects_wrong_size_or_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, vault, _ = self._fixture(root)
            item = next((vault / "raw" / "sha256").iterdir())
            item.write_bytes(b"tampered")
            with (
                patch(
                    "opennoise.pipeline.source_vault_replay.load_release_manifest",
                    return_value=self._manifest_payload(manifest),
                ),
                self.assertRaises(SourceVaultReplayError),
            ):
                verify_source_vault(manifest, vault)

    def test_restore_requires_fresh_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, vault, _ = self._fixture(root)
            store = LocalObjectStore(root / "objects")
            with patch(
                "opennoise.pipeline.source_vault_replay.load_release_manifest",
                return_value=self._manifest_payload(manifest),
            ):
                report = verify_source_vault(manifest, vault, object_store=store)
            destination = root / "restored"
            destination.mkdir()
            with self.assertRaises(SourceVaultReplayError):
                restore_source_vault(report, store, destination, manifest_path=manifest)

    def test_verify_rejects_manifest_subset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, vault, _ = self._fixture(root)
            with self.assertRaises(SourceVaultReplayError):
                verify_source_vault(manifest, vault)

    def test_verify_rejects_noncanonical_manifest_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, vault, _ = self._fixture(root)
            alias = root / "alias.json"
            alias.write_bytes(manifest.read_bytes())
            with self.assertRaises(SourceVaultReplayError):
                verify_source_vault(alias, vault)

    def test_report_rejects_forged_object_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, vault, _ = self._fixture(root)
            with patch(
                "opennoise.pipeline.source_vault_replay.load_release_manifest",
                return_value=self._manifest_payload(manifest),
            ):
                report = verify_source_vault(manifest, vault)
            forged = report.model_dump(mode="json")
            forged["objects"][0]["object_key"]["value"] = "raw/sha256/not-the-artifact"
            with self.assertRaises(ValueError):
                SourceVaultReplayReport.model_validate(forged)

    def test_candidate_database_replays_only_available_wikidata_adapter(self) -> None:
        wikidata_payload = (
            Path(__file__).parent / "fixtures" / "wikidata_music_slice.json"
        ).read_bytes()
        listenbrainz_payload = b"not an adapter fixture"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault"
            raw = vault / "raw" / "sha256"
            raw.mkdir(parents=True)
            wikidata_sha = hashlib.sha256(wikidata_payload).hexdigest()
            listenbrainz_sha = hashlib.sha256(listenbrainz_payload).hexdigest()
            (raw / wikidata_sha).write_bytes(wikidata_payload)
            (raw / listenbrainz_sha).write_bytes(listenbrainz_payload)
            manifest = root / "release-manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            payload = {
                "release_id": "test-release",
                "inputs": [
                    {
                        "source_key": "wikidata_phase3_artists_00",
                        "snapshot_ref": "wikidata_phase3_artists_00:query:test:artifact:test",
                        "source_manifest_sha256": "0" * 64,
                        "artifact_sha256": wikidata_sha,
                        "byte_size": len(wikidata_payload),
                    },
                    {
                        "source_key": "listenbrainz_incremental_20260824",
                        "snapshot_ref": "listenbrainz_incremental_20260824:test",
                        "source_manifest_sha256": "1" * 64,
                        "artifact_sha256": listenbrainz_sha,
                        "byte_size": len(listenbrainz_payload),
                    },
                ],
            }
            with patch(
                "opennoise.pipeline.source_vault_replay.load_release_manifest", return_value=payload
            ):
                report = verify_source_vault(manifest, vault)
                candidate = replay_source_vault_to_candidate_database(
                    report,
                    vault,
                    root / "candidate.sqlite",
                    manifest_path=manifest,
                )
            self.assertEqual(
                (candidate.ingested_object_count, candidate.unsupported_object_count), (1, 1)
            )
            self.assertFalse(candidate.certified_database)
            self.assertTrue((root / "candidate.sqlite").is_file())
            (raw / wikidata_sha).unlink()
            with (
                patch(
                    "opennoise.pipeline.source_vault_replay.load_release_manifest",
                    return_value=payload,
                ),
                patch("opennoise.clients.downloads.httpx.AsyncClient") as client_factory,
                self.assertRaises(SourceVaultReplayError),
            ):
                replay_source_vault_to_candidate_database(
                    report,
                    vault,
                    root / "missing-source.sqlite",
                    manifest_path=manifest,
                )
            client_factory.assert_not_called()
            self.assertFalse((root / "missing-source.sqlite").exists())

    def test_listenbrainz_candidate_fails_before_daily_processing_on_config_drift(self) -> None:
        """The sealed joint receipt pins candidate settings before large inputs are read."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault"
            raw = vault / "raw" / "sha256"
            raw.mkdir(parents=True)
            configuration_sha256 = hashlib.sha256(
                _candidate_listenbrainz_config().model_dump_json().encode()
            ).hexdigest()
            good_payload = json.dumps({"configuration_sha256": configuration_sha256}).encode()
            good_sha = hashlib.sha256(good_payload).hexdigest()
            (raw / good_sha).write_bytes(good_payload)
            inputs = (
                {
                    "source_key": "listenbrainz_joint_20260824_20260830",
                    "snapshot_ref": "listenbrainz_joint_20260824_20260830:joint:test",
                    "source_manifest_sha256": "0" * 64,
                    "artifact_sha256": good_sha,
                    "byte_size": len(good_payload),
                },
            )
            parsed = tuple(ReleaseManifestReplayInput.model_validate(item) for item in inputs)
            self.assertEqual(_listenbrainz_joint_input(parsed, vault).artifact_sha256, good_sha)
            bad_payload = json.dumps({"configuration_sha256": "0" * 64}).encode()
            bad_sha = hashlib.sha256(bad_payload).hexdigest()
            (raw / bad_sha).write_bytes(bad_payload)
            bad = (
                ReleaseManifestReplayInput(
                    source_key="listenbrainz_joint_20260824_20260830",
                    snapshot_ref="listenbrainz_joint_20260824_20260830:joint:test",
                    source_manifest_sha256="0" * 64,
                    artifact_sha256=bad_sha,
                    byte_size=len(bad_payload),
                ),
            )
            with self.assertRaisesRegex(SourceVaultReplayError, "configuration differs"):
                _listenbrainz_joint_input(bad, vault)

    def test_listenbrainz_candidate_rejects_same_size_tampered_joint_before_parse(self) -> None:
        """The joint receipt is hashed before its configuration is trusted."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "vault" / "raw" / "sha256"
            raw.mkdir(parents=True)
            configuration_sha256 = hashlib.sha256(
                _candidate_listenbrainz_config().model_dump_json().encode()
            ).hexdigest()
            expected_payload = json.dumps({"configuration_sha256": configuration_sha256}).encode()
            expected_sha = hashlib.sha256(expected_payload).hexdigest()
            (raw / expected_sha).write_bytes(b"x" * len(expected_payload))
            joint = (
                ReleaseManifestReplayInput(
                    source_key="listenbrainz_joint_20260824_20260830",
                    snapshot_ref="listenbrainz_joint_20260824_20260830:joint:test",
                    source_manifest_sha256="0" * 64,
                    artifact_sha256=expected_sha,
                    byte_size=len(expected_payload),
                ),
            )
            with self.assertRaisesRegex(SourceVaultReplayError, "does not match report"):
                _listenbrainz_joint_input(joint, root / "vault")

    def test_combined_candidate_rehashes_and_ingests_54_wikidata_and_7_dailies(self) -> None:
        """The one-database path has a complete 62-object receipt before either ingest runs."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault"
            raw = vault / "raw" / "sha256"
            raw.mkdir(parents=True)
            inputs: list[dict[str, object]] = []

            def add(source_key: str, snapshot: str, payload: bytes) -> None:
                digest = hashlib.sha256(payload).hexdigest()
                (raw / digest).write_bytes(payload)
                inputs.append(
                    {
                        "source_key": source_key,
                        "snapshot_ref": f"{source_key}:{snapshot}",
                        "source_manifest_sha256": "0" * 64,
                        "artifact_sha256": digest,
                        "byte_size": len(payload),
                    }
                )

            for index in range(54):
                add(f"wikidata_phase3_fixture_{index:02}", "query:fixture", f"wd-{index}".encode())
            for index in range(7):
                add(
                    f"listenbrainz_incremental_202608{24 + index}",
                    f"fixture-{index}",
                    f"lb-{index}".encode(),
                )
            configuration_sha256 = hashlib.sha256(
                _candidate_listenbrainz_config().model_dump_json().encode()
            ).hexdigest()
            joint_payload = json.dumps({"configuration_sha256": configuration_sha256}).encode()
            add("listenbrainz_joint_20260824_20260830", "joint:fixture", joint_payload)
            manifest = root / "release-manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            source_manifest = root / "sources.toml"
            source_manifest.write_text("", encoding="utf-8")
            payload = {"release_id": "test-release", "inputs": inputs}
            progress: list[str] = []
            daily_sources = tuple(
                _fixture_listenbrainz_source(item, index)
                for index, item in enumerate(inputs[54:61])
            )

            async def ingest_wikidata(
                *_args: object, database_path: Path, **_kwargs: object
            ) -> None:
                with sqlite3.connect(database_path) as connection:
                    connection.execute("PRAGMA user_version = 10")

            def ingest_listenbrainz(
                *_args: object, derived_vault_path: Path, **_kwargs: object
            ) -> tuple[int, int, str]:
                joint = inputs[-1]
                digest = str(joint["artifact_sha256"])
                target = derived_vault_path / "raw" / "sha256" / digest
                target.parent.mkdir(parents=True)
                target.write_bytes(joint_payload)
                return 17, 2, digest

            with (
                patch(
                    "opennoise.pipeline.source_vault_replay.load_release_manifest",
                    return_value=payload,
                ),
                patch(
                    "opennoise.pipeline.source_vault_replay._candidate_listenbrainz_sources",
                    return_value=(
                        tuple(
                            ReleaseManifestReplayInput.model_validate(item)
                            for item in inputs[54:61]
                        ),
                        daily_sources,
                    ),
                ),
                patch(
                    "opennoise.pipeline.source_vault_replay._ingest_wikidata_objects",
                    side_effect=ingest_wikidata,
                ) as wikidata_ingest,
                patch(
                    "opennoise.pipeline.source_vault_replay._ingest_listenbrainz_candidate",
                    side_effect=ingest_listenbrainz,
                ) as listenbrainz_ingest,
            ):
                report = verify_source_vault(manifest, vault)
                candidate = replay_combined_source_vault_to_candidate_database(
                    report,
                    vault,
                    root / "combined.sqlite",
                    manifest_path=manifest,
                    source_manifest_path=source_manifest,
                    progress=progress.append,
                )
                tampered = raw / str(inputs[54]["artifact_sha256"])
                tampered.write_bytes(b"x" * tampered.stat().st_size)
                with self.assertRaisesRegex(SourceVaultReplayError, "does not match report"):
                    replay_combined_source_vault_to_candidate_database(
                        report,
                        vault,
                        root / "tampered.sqlite",
                        manifest_path=manifest,
                        source_manifest_path=source_manifest,
                    )
                self._assert_combined_sync_validation_does_not_publish(
                    report, vault, root, manifest, source_manifest
                )
            self.assertEqual(candidate.verified_object_count, 62)
            self.assertEqual(len(candidate.wikidata_objects), 54)
            self.assertEqual(len(candidate.listenbrainz_daily_objects), 7)
            self.assertIn("historical declaration replay proves", candidate.blockers[0])
            self.assertEqual(
                (candidate.accepted_record_count, candidate.quarantined_record_count), (17, 2)
            )
            self.assertTrue((root / "combined.sqlite").is_file())
            self.assertEqual(
                progress,
                [
                    "rehashing source-vault receipt",
                    "source-vault receipt verified",
                    "replaying Wikidata objects",
                    "Wikidata replay complete; replaying ListenBrainz daily objects",
                    "ListenBrainz persistence returned; validating sealed joint receipt",
                    "sealed joint receipt matched; checkpointing candidate database",
                    "candidate database checkpointed; publishing",
                    "candidate database published",
                ],
            )
            self.assertEqual(wikidata_ingest.call_count, 2)
            listenbrainz_ingest.assert_called_once()

    def test_phase3_historical_declarations_replay_all_sealed_digests(self) -> None:
        report = replay_historical_source_declarations(
            Path("config/releases/phase3-public-20260831/release-manifest.json"),
            Path("config/data_sources.toml"),
        )
        self.assertEqual(report.object_count, 62)
        self.assertTrue(
            all(item.expected_sha256 == item.replayed_sha256 for item in report.objects)
        )
