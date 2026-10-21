"""Retained title lookup, literal matching and independently authorized observations."""

# ruff: noqa: SLF001, E501, S603 -- Ordinary sync API and compact explicit SQLite fixtures.
import hashlib
import json
import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from typing import ClassVar, override
from unittest.mock import patch
from uuid import UUID

from opennoise.pipeline import cultural_catalog as catalog
from opennoise.serving.public.artist_navigation_store import PublicArtistNavigationStoreError
from opennoise.serving.public.membership_export_eligibility import ExportEligibility
from opennoise.serving.public.recording_navigation_store import PublicRecordingNavigationStore
from tests._test_client import run_async
from tests.serving.public import test_recording_navigation_store as credit_fixture

ROOT = credit_fixture.ROOT


class RecordingTitleSearchTests(unittest.TestCase):
    """Checked-in retained metadata plus explicitly synthetic policy counterfactuals."""

    temporary: ClassVar[tempfile.TemporaryDirectory[str]]
    output: ClassVar[Path]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.output = Path(cls.temporary.name) / "catalog"
        catalog.build(
            credit_fixture.CORE,
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
            closing(sqlite3.connect(self.output / "musicbrainz-first.sqlite")) as a,
            closing(sqlite3.connect(self.path)) as b,
        ):
            a.backup(b)
        self.c = sqlite3.connect(self.path)
        self.c.row_factory = sqlite3.Row
        self.addCleanup(self.c.close)
        self.store = PublicRecordingNavigationStore(self.path)

    def observation(self, key: str, deny: str | None = None) -> int:
        """Create a complete synthetic registered source with immutable explicit permissions."""
        p = self.c.execute(
            "INSERT INTO rights_policies(policy_key,policy_version,classification,local_only,basis,reviewed_at) VALUES(?,1,'public_domain',0,'Synthetic CC0 metadata fixture','2026-01-01')",
            ("test:" + key,),
        ).lastrowid
        for use in ("normalize", "display", "local_search"):
            self.c.execute(
                "INSERT INTO rights_policy_permissions(policy_id,use_kind,decision,reason) VALUES(?,?,?,'Synthetic fixture')",
                (p, use, "deny" if use == deny else "allow"),
            )
        self.c.execute(
            "INSERT INTO rights_policy_seals(policy_id,sealed_at) VALUES(?,'2026-01-01')", (p,)
        )
        source = self.c.execute(
            "INSERT INTO data_sources(source_key,name,license_name,default_policy_id) VALUES(?,?,'CC0-1.0',?)",
            ("test:" + key, key, p),
        ).lastrowid
        digest = hashlib.sha256(key.encode()).hexdigest()
        snapshot = self.c.execute(
            "INSERT INTO source_snapshots(source_id,snapshot_ref,snapshot_kind,manifest_sha256,acquired_at,policy_id) VALUES(?,?,'single_artifact',?,'2026-01-01',?)",
            (source, key, digest, p),
        ).lastrowid
        self.c.execute(
            "INSERT INTO source_artifacts(snapshot_id,artifact_ref,logical_name,media_type,byte_size,sha256,vault_key,policy_id) VALUES(?,?,'Synthetic metadata','application/json',?,?,?,?)",
            (snapshot, key, len(key.encode()), digest, digest, p),
        )
        provenance_id = self.c.execute(
            "INSERT INTO provenance_records(source_id,policy_id,snapshot_ref,artifact_sha256,record_fingerprint,parser_release_ref,ingest_attempt_ref,observed_at) VALUES(?,?,?,?,?,'synthetic-test','synthetic-test','2026-01-01')",
            (source, p, key, digest, digest),
        ).lastrowid
        if provenance_id is None:
            raise RuntimeError("Synthetic provenance insertion returned no ID")
        return provenance_id

    def recording(
        self, title: str, number: int, title_prov: int, identity_prov: int | None = None
    ) -> tuple[int, str]:
        """Create a distinct recording; equal title strings never supply identity."""
        entity = self.c.execute(
            "INSERT INTO catalog_entities(entity_kind) VALUES('recording')"
        ).lastrowid
        if entity is None:
            raise RuntimeError("Synthetic recording insertion returned no ID")
        self.c.execute("INSERT INTO recordings(id) VALUES(?)", (entity,))
        mbid = str(UUID(int=number))
        self.c.execute(
            "INSERT INTO entity_identifiers(entity_id,identifier_type_id,namespace,value,normalized_value,provenance_id) VALUES(?,(SELECT id FROM identifier_types WHERE type_key='musicbrainz_recording_id'),'musicbrainz',?,?,?)",
            (entity, mbid, mbid, identity_prov or title_prov),
        )
        self.c.execute(
            "INSERT INTO entity_names(entity_id,name_kind,name,language_tag,is_preferred,provenance_id,fingerprint) VALUES(?,'primary',?,'und',1,?,?)",
            (entity, title, title_prov, hashlib.sha256(str((entity, title)).encode()).hexdigest()),
        )
        self.c.commit()
        return int(entity), mbid

    def test_complete_retained_titles_reach_every_native_recording(self) -> None:
        rows = self.c.execute(
            "SELECT DISTINCT name FROM entity_names WHERE entity_id IN(SELECT id FROM recordings)"
        ).fetchall()
        reached = set()
        members = 0
        for row in rows:
            result = self.store._search_recordings_sync(row[0])
            self.assertTrue(result.results)
            members += len(result.results)
            reached.update(r.recording_mbid for r in result.results)
            self.assertTrue(all(r.status == "available" for r in result.results))
        self.assertEqual((len(rows), members, len(reached)), (1023, 1135, 1031))

    def test_nfkc_casefold_whitespace_literals_and_no_diacritic_guess(self) -> None:
        p = self.observation("unicode")
        _, mbid = self.recording("\uff21  B\u212a\t Straße Café rock*", 10001, p)
        self.assertEqual(
            self.store._search_recordings_sync("a bk STRASSE").results[0].recording_mbid, mbid
        )
        self.assertIn(
            mbid,
            [r.recording_mbid for r in self.store._search_recordings_sync("cafe\u0301").results],
        )
        self.assertNotIn(
            mbid, [r.recording_mbid for r in self.store._search_recordings_sync("cafe").results]
        )
        self.assertIn(
            mbid, [r.recording_mbid for r in self.store._search_recordings_sync("rock*").results]
        )
        self.assertFalse(self.store._search_recordings_sync("rock OR missing").results)

    def test_duplicate_titles_preserve_native_id_order_and_pages(self) -> None:
        p = self.observation("duplicates")
        _, b = self.recording("Unique duplicate title", 102, p)
        _, a = self.recording("Unique duplicate title", 101, p)
        self.assertEqual(
            [
                r.recording_mbid
                for r in self.store._search_recordings_sync("unique duplicate").results
            ],
            [a, b],
        )
        self.assertEqual(
            self.store._search_recordings_sync("unique duplicate", 1, 1).results[0].recording_mbid,
            b,
        )
        self.assertEqual(
            run_async(self.store.search_recordings("unique duplicate", limit=1))
            .results[0]
            .recording_mbid,
            a,
        )

    def test_both_permissions_for_identity_and_title_before_pagination(self) -> None:
        allowed = self.observation("allowed")
        private_title = self.observation("private-title", "local_search")
        private_id = self.observation("private-id", "local_search")
        display_title = self.observation("private-display-title", "display")
        display_id = self.observation("private-display-id", "display")
        self.recording("Special sequence 0 private title", 100, private_title, allowed)
        self.recording("Special sequence 1 private identity", 101, allowed, private_id)
        self.recording("Special sequence 1 display denied title", 104, display_title, allowed)
        self.recording("Special sequence 1 display denied identity", 105, allowed, display_id)
        _, a = self.recording("Special sequence 2 visible", 102, allowed)
        _, b = self.recording("Special sequence 3 visible", 103, allowed)
        self.assertEqual(
            [
                r.recording_mbid
                for r in self.store._search_recordings_sync("special sequence").results
            ],
            [a, b],
        )
        self.assertEqual(
            self.store._search_recordings_sync("special sequence", 1, 1).results[0].recording_mbid,
            b,
        )

    def test_source_use_veto_release_and_ambiguous_identity(self) -> None:
        p = self.observation("veto")
        entity, mbid = self.recording("Only veto candidate", 200, p)
        baseline = self.store._search_recordings_sync("only veto candidate")
        for use in ("local_search", "display", "all"):
            credit_fixture.event(self.c, "provenance", p, use)
            self.assertFalse(self.store._search_recordings_sync("only veto candidate").results)
            credit_fixture.event(self.c, "provenance", p, use, "release")
            self.assertEqual(self.store._search_recordings_sync("only veto candidate"), baseline)
        self.recording("Other exact owner", 200, p)
        with self.assertRaisesRegex(PublicArtistNavigationStoreError, "ambiguous"):
            self.store._search_recordings_sync("only veto candidate")
        self.assertIsNotNone(entity)
        self.assertEqual(mbid, baseline.results[0].recording_mbid)

    def test_query_and_scan_bounds_fail_instead_of_partial_pages(self) -> None:
        for query in ("", "!!!", "x" * 201, None):
            with self.subTest(query=query), self.assertRaises(ValueError):
                self.store._search_recordings_sync(query)  # ty: ignore[invalid-argument-type]
        for offset, limit in ((True, 1), (10001, 1), (0, 11), (0, False)):
            with self.assertRaises(ValueError):
                self.store._search_recordings_sync("a", offset, limit)

        with (
            patch("opennoise.serving.public.recording_navigation_store.MAX_TITLE_OBSERVATIONS", 1),
            self.assertRaisesRegex(PublicArtistNavigationStoreError, "scan bound"),
        ):
            self.store._search_recordings_sync("a")
        with (
            patch("opennoise.serving.public.recording_navigation_store.MAX_TITLE_CANDIDATES", 1),
            self.assertRaisesRegex(PublicArtistNavigationStoreError, "candidate bound"),
        ):
            self.store._search_recordings_sync("a")

    def test_cli_text_mode_and_legacy_exact_mode(self) -> None:
        pin = hashlib.sha256(self.path.read_bytes()).hexdigest()
        args = [
            str(ROOT / ".venv/bin/python"),
            str(ROOT / "scripts/query_recording_context.py"),
            "--database",
            str(self.path),
            "--database-sha256",
            pin,
        ]
        text = subprocess.run(
            [*args, "--query", "Fear of the Dark"], capture_output=True, text=True, check=True
        )
        result = json.loads(text.stdout)
        self.assertEqual(len(result["results"]), 2)
        mbid = result["results"][0]["recording_mbid"]
        exact = subprocess.run(
            [*args, "--recording-mbid", mbid], capture_output=True, text=True, check=True
        )
        self.assertEqual(
            json.loads(exact.stdout),
            self.store._recording_context_sync(mbid).model_dump(mode="json"),
        )
        bad = subprocess.run(
            [*args, "--query", "Fear", "--recording-mbid", mbid], capture_output=True, check=False
        )
        self.assertNotEqual(bad.returncode, 0)

    def test_shared_search_mode_does_not_invent_a_name_view(self) -> None:
        helper = ExportEligibility(self.c, None, use_kind="local_search")
        self.assertIsNotNone(helper.chain(1))
        with self.assertRaisesRegex(ValueError, "not name selection"):
            helper.name(1)
