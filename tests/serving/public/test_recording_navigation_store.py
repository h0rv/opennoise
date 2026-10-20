"""Real retained CC0 recording entry points and source-bound credit counterfactuals."""

# ruff: noqa: SLF001, E501, S603 -- Ordinary API, compact SQL, repository-controlled CLI.
import hashlib
import json
import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from typing import ClassVar, override

from opennoise.deployment.musicbrainz_credit_portable_release import PortableMusicBrainzCreditSource
from opennoise.pipeline import cultural_catalog as catalog
from opennoise.pipeline.recording_core_custody import (
    prepare_core_inventory,
    register_core_inventory,
)
from opennoise.serving.public.artist_navigation_store import PublicArtistNavigationStoreError
from opennoise.serving.public.recording_navigation_store import PublicRecordingNavigationStore
from tests._test_client import run_async

ROOT = Path(__file__).resolve().parents[3]
CORE = (
    ROOT
    / "data/release/musicbrainz-credit-catalog-v1/objects/musicbrainz-credit-catalog/sha256"
    / f"{catalog.CORE_SHA}.json"
)


def event(
    c: sqlite3.Connection, kind: str, ref: object, use: str, action: str = "suppress"
) -> None:
    """Append an explicit counterfactual suppression or release."""
    n = c.execute("SELECT count(*) FROM suppression_events").fetchone()[0]
    c.execute(
        """INSERT INTO suppression_events(target_kind,target_ref,use_kind,event_action,
        reason,effective_at,event_fingerprint) VALUES(?,?,?,?,?,?,?)""",
        (
            kind,
            str(ref),
            use,
            action,
            "Recording traversal counterfactual",
            f"2026-10-20T12:00:{n:02d}Z",
            hashlib.sha256(str((kind, ref, use, action, n)).encode()).hexdigest(),
        ),
    )
    c.commit()


class RecordingNavigationTests(unittest.TestCase):
    """Existing checked-in native sources, without network or model fitting."""

    temporary: ClassVar[tempfile.TemporaryDirectory[str]]
    output: ClassVar[Path]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.output = Path(cls.temporary.name) / "catalog"
        catalog.build(
            CORE,
            catalog.CORE_SHA,
            ROOT / "data/examples/cultural-context",
            catalog.PACKS[0][1],
            ROOT / "data/examples/independent-cultural-context",
            catalog.PACKS[1][1],
            cls.output,
            register_core_custody=True,
        )

    @override
    def setUp(self) -> None:
        self.path = Path(self.temporary.name) / (self._testMethodName + ".sqlite")
        with (
            closing(sqlite3.connect(self.output / "musicbrainz-first.sqlite")) as source,
            closing(sqlite3.connect(self.path)) as dest,
        ):
            source.backup(dest)
        self.c = sqlite3.connect(self.path)
        self.addCleanup(self.c.close)
        self.store = PublicRecordingNavigationStore(self.path)
        self.mbid, self.recording, self.credit, self.link, self.definition = self.c.execute("""
            SELECT i.normalized_value,r.id,l.artist_credit_id,l.provenance_id,a.provenance_id
            FROM recordings r JOIN entity_identifiers i ON i.entity_id=r.id
            JOIN identifier_types t ON t.id=i.identifier_type_id
            JOIN entity_artist_credits l ON l.entity_id=r.id AND l.credit_kind='primary'
            JOIN artist_credits a ON a.id=l.artist_credit_id
            WHERE t.type_key='musicbrainz_recording_id' ORDER BY r.id LIMIT 1""").fetchone()

    def test_all_retained_recordings_exact_order_credits_and_context(self) -> None:
        source = json.loads(CORE.read_bytes())
        raw = json.loads(source["credit_artifact_json"])
        expected = {r["entity_id"]: r for r in raw["credits"] if r["entity_kind"] == "recording"}
        self.assertEqual(len(expected), 1031)
        results = {}
        member_count = 0
        artists = set()
        with_genres = 0
        for mbid, row in expected.items():
            result = self.store._recording_context_sync(mbid, 10, 5)
            self.assertEqual(result.status, "available")
            self.assertEqual(len(result.credits), 1)
            members = result.credits[0].members
            observed = [
                (m.position, m.musicbrainz_artist_id, m.credited_name, m.join_phrase)
                for m in members
            ]
            self.assertEqual(
                observed,
                [
                    (m["position"], m["artist_id"], m["credited_name"], m["join_phrase"])
                    for m in row["members"]
                ],
            )
            artists.update(m.musicbrainz_artist_id for m in members)
            member_count += len(members)
            with_genres += any(m.artist_genres.genres for m in members)
            results[mbid] = observed
        self.assertEqual((member_count, len(artists), with_genres), (1242, 351, 81))
        other = PublicRecordingNavigationStore(self.output / "wikidata-first.sqlite")
        # All native identities and source order survive the other insertion order.
        for mbid, observed in results.items():
            result = other._recording_context_sync(mbid, 1, 1)
            self.assertEqual(
                [
                    (m.position, m.musicbrainz_artist_id, m.credited_name, m.join_phrase)
                    for m in result.credits[0].members
                ],
                observed,
            )

    def test_source_chain_veto_and_release_preserve_intact_credits(self) -> None:
        baseline = self.store._recording_context_sync(self.mbid)
        for kind, query in (
            ("source", "SELECT source_id FROM provenance_records WHERE id=?"),
            ("provenance", "SELECT id FROM provenance_records WHERE id=?"),
            (
                "snapshot",
                "SELECT ss.id FROM source_snapshots ss JOIN provenance_records p ON p.source_id=ss.source_id AND p.snapshot_ref=ss.snapshot_ref WHERE p.id=?",
            ),
            (
                "artifact",
                "SELECT a.id FROM source_artifacts a JOIN source_snapshots ss ON ss.id=a.snapshot_id JOIN provenance_records p ON p.source_id=ss.source_id AND p.snapshot_ref=ss.snapshot_ref AND a.sha256=p.artifact_sha256 WHERE p.id=?",
            ),
        ):
            ref = self.c.execute(query, (self.link,)).fetchone()[0]
            for use in ("display", "all"):
                with self.subTest(kind=kind, use=use):
                    event(self.c, kind, ref, use)
                    result = self.store._recording_context_sync(self.mbid)
                    self.assertEqual(result.status, "credit_unavailable")
                    self.assertEqual(result.credits, ())
                    event(self.c, kind, ref, use, "release")
                    self.assertEqual(self.store._recording_context_sync(self.mbid), baseline)
        event(self.c, "provenance", self.link, "embed")
        self.assertEqual(self.store._recording_context_sync(self.mbid), baseline)

    def test_unknown_and_denied_recording_indistinguishable(self) -> None:
        unknown = self.store._recording_context_sync("00000000-0000-0000-0000-000000000001")
        event(self.c, "entity", self.recording, "display")
        denied = self.store._recording_context_sync(self.mbid)
        self.assertEqual(
            denied.model_dump(exclude={"recording_mbid"}),
            unknown.model_dump(exclude={"recording_mbid"}),
        )
        self.assertIsNone(denied.recording_entity_id)
        self.assertIsNone(denied.title)

    def test_member_veto_never_returns_partial_credit(self) -> None:
        artist = self.c.execute(
            "SELECT artist_id FROM artist_credit_members WHERE artist_credit_id=? LIMIT 1",
            (self.credit,),
        ).fetchone()[0]
        event(self.c, "entity", artist, "display")
        result = self.store._recording_context_sync(self.mbid)
        self.assertEqual(result.status, "credit_unavailable")
        self.assertEqual(result.credits, ())

    def test_ambiguous_recording_owner_fails_without_identity_repair(self) -> None:
        self.c.execute("INSERT INTO catalog_entities(entity_kind) VALUES('recording')")
        other = self.c.execute("SELECT max(id) FROM catalog_entities").fetchone()[0]
        self.c.execute("INSERT INTO recordings(id) VALUES(?)", (other,))
        self.c.execute(
            """INSERT INTO entity_identifiers(entity_id,identifier_type_id,namespace,
            value,normalized_value,provenance_id) SELECT ?,identifier_type_id,namespace,value,
            normalized_value,provenance_id FROM entity_identifiers WHERE entity_id=? AND
            identifier_type_id=(SELECT id FROM identifier_types WHERE type_key='musicbrainz_recording_id')""",
            (other, self.recording),
        )
        self.c.commit()
        with self.assertRaisesRegex(PublicArtistNavigationStoreError, "ambiguous"):
            self.store._recording_context_sync(self.mbid)

    def test_gapped_native_order_rejected_not_reindexed(self) -> None:
        self.c.execute(
            "UPDATE artist_credit_members SET position=position+10 WHERE artist_credit_id=?",
            (self.credit,),
        )
        self.c.commit()
        with self.assertRaisesRegex(PublicArtistNavigationStoreError, "ordered credit"):
            self.store._recording_context_sync(self.mbid)

    def test_invalid_requests_and_async_entry(self) -> None:
        for value in ("bad", self.mbid.upper(), None, True):
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                self.store._recording_context_sync(value)  # ty: ignore[invalid-argument-type]
        for limit in (0, 11, True, "1"):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                self.store._recording_context_sync(self.mbid, limit, 5)  # ty: ignore[invalid-argument-type]
        self.assertEqual(
            run_async(self.store.recording_context(self.mbid)),
            self.store._recording_context_sync(self.mbid),
        )

    def test_cli_real_input_pin_and_uri_special_path(self) -> None:
        special = self.path.with_name("catalog #?.sqlite")
        with closing(sqlite3.connect(special)) as target:
            self.c.backup(target)
        pin = hashlib.sha256(special.read_bytes()).hexdigest()
        args = [
            str(ROOT / ".venv/bin/python"),
            str(ROOT / "scripts/query_recording_context.py"),
            "--database",
            str(special),
            "--database-sha256",
            pin,
            "--recording-mbid",
            self.mbid,
        ]
        result = subprocess.run(args, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)["status"], "available")
        args[args.index(pin)] = "0" * 64
        self.assertNotEqual(subprocess.run(args, capture_output=True, check=False).returncode, 0)

    def test_inventory_exact_bytes_and_idempotent_registration(self) -> None:
        source = PortableMusicBrainzCreditSource.model_validate_json(CORE.read_bytes())
        manifest = json.loads((self.output / "core-custody.json").read_bytes())
        inventory = prepare_core_inventory(CORE, source, replayed_at=manifest["replayed_at"])
        self.assertEqual(
            hashlib.sha256(inventory.hydration).hexdigest(), source.hydration_artifact_sha256
        )
        self.assertEqual(
            hashlib.sha256(inventory.credits).hexdigest(), source.credit_artifact_sha256
        )
        before = self.c.total_changes
        register_core_inventory(self.c, inventory)
        self.c.commit()
        # Reuse the exact snapshot/artifact rows; spelling canonicalization writes no new facts.
        self.assertEqual(
            self.c.execute(
                "SELECT count(*) FROM source_snapshots WHERE snapshot_ref LIKE 'hydration:%' OR snapshot_ref LIKE 'artist-credit:%'"
            ).fetchone()[0],
            2,
        )
        self.assertEqual(self.store._recording_context_sync(self.mbid).status, "available")
        self.assertLessEqual(self.c.total_changes - before, 2)
        wrong = self.path.with_name("wrong-source.json")
        wrong.write_bytes(CORE.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "approved portable bytes"):
            prepare_core_inventory(wrong, source, replayed_at=manifest["replayed_at"])

    def test_conflicting_registration_rolls_back_both_sources(self) -> None:
        source = PortableMusicBrainzCreditSource.model_validate_json(CORE.read_bytes())
        manifest = json.loads((self.output / "core-custody.json").read_bytes())
        inventory = prepare_core_inventory(CORE, source, replayed_at=manifest["replayed_at"])
        self.c.execute(
            "DELETE FROM source_artifacts WHERE snapshot_id IN(SELECT id FROM source_snapshots WHERE snapshot_ref LIKE 'hydration:%' OR snapshot_ref LIKE 'artist-credit:%')"
        )
        self.c.execute(
            "DELETE FROM source_snapshots WHERE snapshot_ref LIKE 'hydration:%' OR snapshot_ref LIKE 'artist-credit:%'"
        )
        self.c.execute(
            "UPDATE data_sources SET license_name=CASE WHEN source_key='musicbrainz_public_core_release_hydration' THEN 'CC0' ELSE 'restricted' END WHERE source_key LIKE 'musicbrainz_public_%'"
        )
        self.c.commit()
        with self.assertRaisesRegex(ValueError, "source declaration differs"):
            register_core_inventory(self.c, inventory)
        self.assertEqual(
            self.c.execute(
                "SELECT count(*) FROM source_snapshots WHERE snapshot_ref LIKE 'hydration:%' OR snapshot_ref LIKE 'artist-credit:%'"
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            self.c.execute(
                "SELECT license_name FROM data_sources WHERE source_key='musicbrainz_public_core_release_hydration'"
            ).fetchone()[0],
            "CC0",
        )

    def test_legacy_default_keeps_missing_inventory_unavailable(self) -> None:
        legacy = Path(self.temporary.name) / "legacy-default"
        catalog.build(
            CORE,
            catalog.CORE_SHA,
            ROOT / "data/examples/cultural-context",
            catalog.PACKS[0][1],
            ROOT / "data/examples/independent-cultural-context",
            catalog.PACKS[1][1],
            legacy,
        )
        with closing(sqlite3.connect(legacy / "musicbrainz-first.sqlite")) as c:
            self.assertEqual(
                c.execute(
                    "SELECT count(*) FROM source_snapshots WHERE snapshot_ref LIKE 'hydration:%' OR snapshot_ref LIKE 'artist-credit:%'"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                c.execute(
                    "SELECT DISTINCT license_name FROM data_sources WHERE source_key LIKE 'musicbrainz_public_%'"
                ).fetchall(),
                [("CC0",)],
            )
        result = PublicRecordingNavigationStore(
            legacy / "musicbrainz-first.sqlite"
        )._recording_context_sync(self.mbid)
        self.assertEqual(result.status, "recording_unavailable")
        self.assertIsNone(result.title)

    def test_conflicting_primary_credits_are_not_arbitrarily_selected(self) -> None:
        other = self.c.execute(
            "SELECT artist_id,credited_name FROM artist_credit_members WHERE artist_credit_id!=? LIMIT 1",
            (self.credit,),
        ).fetchone()
        c = self.c.execute(
            "INSERT INTO artist_credits(credit_key,provenance_id) VALUES('explicit-conflict',?)",
            (self.definition,),
        )
        credit = c.lastrowid
        self.c.execute(
            "INSERT INTO artist_credit_members(artist_credit_id,position,artist_id,credited_name,join_phrase) VALUES(?,0,?,?, '')",
            (credit, *other),
        )
        self.c.execute(
            "INSERT INTO entity_artist_credits(entity_id,credit_kind,artist_credit_id,provenance_id) VALUES(?,'primary',?,?)",
            (self.recording, credit, self.link),
        )
        self.c.commit()
        result = self.store._recording_context_sync(self.mbid)
        self.assertEqual(result.status, "credit_conflict")
        self.assertEqual(result.credits, ())

    def test_other_musicbrainz_kind_uuid_and_legacy_noise_do_not_collide(self) -> None:
        self.c.execute("INSERT INTO catalog_entities(entity_kind) VALUES('artist')")
        owner = self.c.execute("SELECT max(id) FROM catalog_entities").fetchone()[0]
        self.c.execute("INSERT INTO artists(id) VALUES(?)", (owner,))
        for key in ("musicbrainz_artist_id", "source_id"):
            self.c.execute(
                "INSERT OR IGNORE INTO identifier_types(type_key,name) VALUES(?,?)", (key, key)
            )
            self.c.execute(
                "INSERT INTO entity_identifiers(entity_id,identifier_type_id,namespace,value,normalized_value,provenance_id) VALUES(?,(SELECT id FROM identifier_types WHERE type_key=?),'musicbrainz',?,?,?)",
                (owner, key, self.mbid, self.mbid, self.link),
            )
        self.c.execute("INSERT INTO catalog_entities(entity_kind) VALUES('release_group')")
        nonartist = self.c.execute("SELECT max(id) FROM catalog_entities").fetchone()[0]
        self.c.execute(
            "INSERT INTO entity_identifiers(entity_id,identifier_type_id,namespace,value,normalized_value,provenance_id) VALUES(?,(SELECT id FROM identifier_types WHERE type_key='source_id'),'musicbrainz',?,?,?)",
            (nonartist, self.mbid, self.mbid, self.link),
        )
        self.c.commit()
        self.assertEqual(self.store._recording_context_sync(self.mbid).status, "available")

    def test_wrong_kind_expected_key_and_own_conflicting_values_fail(self) -> None:
        self.c.execute("INSERT INTO catalog_entities(entity_kind) VALUES('artist')")
        owner = self.c.execute("SELECT max(id) FROM catalog_entities").fetchone()[0]
        self.c.execute("INSERT INTO artists(id) VALUES(?)", (owner,))
        self.c.execute(
            "INSERT INTO entity_identifiers(entity_id,identifier_type_id,namespace,value,normalized_value,provenance_id) VALUES(?,(SELECT id FROM identifier_types WHERE type_key='musicbrainz_recording_id'),'musicbrainz',?,?,?)",
            (owner, self.mbid, self.mbid, self.link),
        )
        self.c.commit()
        with self.assertRaisesRegex(PublicArtistNavigationStoreError, "wrong-kind"):
            self.store._recording_context_sync(self.mbid)
        self.c.execute("DELETE FROM entity_identifiers WHERE entity_id=?", (owner,))
        self.c.execute(
            "UPDATE entity_identifiers SET value='raw-mismatch' WHERE entity_id=? AND identifier_type_id=(SELECT id FROM identifier_types WHERE type_key='musicbrainz_recording_id')",
            (self.recording,),
        )
        self.c.commit()
        with self.assertRaisesRegex(PublicArtistNavigationStoreError, "conflicting"):
            self.store._recording_context_sync(self.mbid)

    def test_pinned_immutable_read_ignores_late_wal_and_cli_refuses_sidecars(self) -> None:
        baseline = self.store._recording_context_sync(self.mbid)
        self.c.execute("PRAGMA journal_mode=WAL")
        self.c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        pin = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.c.execute(
            "UPDATE entity_names SET name='EXPLICIT WAL COUNTERFACTUAL' WHERE entity_id=?",
            (self.recording,),
        )
        self.c.commit()
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), pin)
        self.assertEqual(
            self.store._recording_context_sync(self.mbid).title, "EXPLICIT WAL COUNTERFACTUAL"
        )
        pinned = PublicRecordingNavigationStore(self.path, immutable=True)._recording_context_sync(
            self.mbid
        )
        self.assertEqual(pinned, baseline)
        result = subprocess.run(
            [
                str(ROOT / ".venv/bin/python"),
                str(ROOT / "scripts/query_recording_context.py"),
                "--database",
                str(self.path),
                "--database-sha256",
                pin,
                "--recording-mbid",
                self.mbid,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sidecars", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_cli_ignores_wal_created_after_first_physical_digest(self) -> None:
        baseline = self.store._recording_context_sync(self.mbid)
        self.c.execute("PRAGMA journal_mode=WAL")
        self.c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.c.close()
        self.assertFalse(Path(str(self.path) + "-wal").exists())
        pin = hashlib.sha256(self.path.read_bytes()).hexdigest()
        # The child opens a writer only AFTER the CLI's standalone checks/first hash.
        # Keeping it alive leaves the committed counterfactual exclusively in WAL.
        code = r"""
import importlib.util, pathlib, sqlite3, sys
spec=importlib.util.spec_from_file_location('query_cli',sys.argv[1])
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
path=pathlib.Path(sys.argv[2]); pin=sys.argv[3]; recording=int(sys.argv[5])
original=module._digest
writer=None
calls=0
def late_wal(p):
    global writer,calls
    observed=original(p)
    if calls==0:
        writer=sqlite3.connect(path)
        writer.execute("UPDATE entity_names SET name='LATE UNHASHED WAL TITLE' WHERE entity_id=?",(recording,))
        writer.commit()
        if original(p)!=pin:
            raise ValueError('counterfactual changed main file')
    calls+=1
    return observed
module._digest=late_wal
sys.argv=['query_recording_context','--database',str(path),'--database-sha256',pin,'--recording-mbid',sys.argv[4]]
module.main()
if calls!=2 or original(path)!=pin:
    raise ValueError('physical main-file binding changed')
"""
        result = subprocess.run(
            [
                str(ROOT / ".venv/bin/python"),
                "-c",
                code,
                str(ROOT / "scripts/query_recording_context.py"),
                str(self.path),
                pin,
                self.mbid,
                str(self.recording),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(json.loads(result.stdout)["title"], baseline.title)
        self.assertNotIn("LATE UNHASHED", result.stdout)
