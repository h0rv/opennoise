"""Native artist browse through intact, jointly authorized retained primary credits."""

# ruff: noqa: SLF001, E501, S603, S608, RUF001 -- Ordinary sync API and explicit SQL counterfactuals.
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar, cast, override
from unittest.mock import patch

from opennoise.serving.public.artist_navigation_store import PublicArtistNavigationStoreError
from opennoise.serving.public.recording_navigation_store import PublicRecordingNavigationStore
from tests._test_client import run_async
from tests.serving.public import test_recording_title_search as fixture

ROOT = Path(__file__).resolve().parents[3]
ZAPPA = "e20747e7-55a4-452e-8766-7b985585082d"


class ArtistRecordingBrowseTests(unittest.TestCase):
    """Real retained native edges and independently scoped policy counterfactuals."""

    temporary: ClassVar[tempfile.TemporaryDirectory[str]]
    output: ClassVar[Path]
    c: sqlite3.Connection
    path: Path
    store: PublicRecordingNavigationStore

    @classmethod
    @override
    def setUpClass(cls) -> None:
        fixture.RecordingTitleSearchTests.setUpClass.__func__(
            cast("type[fixture.RecordingTitleSearchTests]", cls)
        )

    @override
    def setUp(self) -> None:
        fixture.RecordingTitleSearchTests.setUp(cast("fixture.RecordingTitleSearchTests", self))

    def observation(self, key: str, deny: str | None = None) -> int:
        return fixture.RecordingTitleSearchTests.observation(
            cast("fixture.RecordingTitleSearchTests", self), key, deny
        )

    def test_real_complete_inverse_edges_and_pages(self) -> None:
        expected: dict[str, set[str]] = {}
        for (
            artist,
            recording,
        ) in self.c.execute("""SELECT DISTINCT ai.normalized_value,ri.normalized_value
            FROM entity_artist_credits l JOIN recordings r ON r.id=l.entity_id
            JOIN artist_credit_members m ON m.artist_credit_id=l.artist_credit_id
            JOIN entity_identifiers ai ON ai.entity_id=m.artist_id
            JOIN identifier_types at ON at.id=ai.identifier_type_id AND at.type_key='musicbrainz_artist_id'
            JOIN entity_identifiers ri ON ri.entity_id=r.id
            JOIN identifier_types rt ON rt.id=ri.identifier_type_id AND rt.type_key='musicbrainz_recording_id'
            WHERE l.credit_kind='primary'"""):
            expected.setdefault(artist, set()).add(recording)
        actual = {}
        for artist, ids in expected.items():
            found = []
            for offset in range(0, len(ids), 10):
                page = self.store._recordings_for_artist_sync(artist, offset=offset)
                self.assertTrue(all(row.status == "available" for row in page.results))
                found.extend(row.recording_mbid for row in page.results)
            self.assertEqual(len(found), len(set(found)))
            self.assertEqual(set(found), ids)
            actual[artist] = found
        self.assertEqual(
            (len(actual), sum(map(len, actual.values())), max(map(len, actual.values()))),
            (351, 1242, 68),
        )

    def test_literal_filter_async_and_unknown_seed(self) -> None:
        full = self.store._recordings_for_artist_sync(ZAPPA)
        filtered = run_async(
            self.store.recordings_for_artist(ZAPPA, title_filter="ＢＥ-ＢＯＰ  TANGO")
        )
        self.assertEqual(filtered.results, (full.results[0],))
        self.assertEqual(
            self.store._recordings_for_artist_sync("00000000-0000-0000-0000-000000000001").results,
            (),
        )
        for kwargs in (
            {"title_filter": "*"},
            {"title_filter": "x" * 201},
            {"offset": True},
            {"limit": 11},
        ):
            with self.assertRaises(ValueError):
                self.store._recordings_for_artist_sync(ZAPPA, **kwargs)  # ty: ignore[invalid-argument-type] -- Deliberately heterogeneous invalid arguments.
        with self.assertRaises(ValueError):
            self.store._recordings_for_artist_sync(ZAPPA.upper())

    def seed(self) -> int:
        return int(
            self.c.execute(
                "SELECT entity_id FROM entity_identifiers WHERE normalized_value=?", (ZAPPA,)
            ).fetchone()[0]
        )

    def test_seed_name_identity_require_both_permissions(self) -> None:
        for table in ("entity_names", "entity_identifiers"):
            for denied in ("display", "local_search"):
                with self.subTest(table=table, denied=denied):
                    self.c.execute("SAVEPOINT counterfactual")
                    p = self.observation(table + denied, denied)
                    self.c.execute(
                        f"UPDATE {table} SET provenance_id=? WHERE entity_id=?", (p, self.seed())
                    )
                    self.c.commit()
                    self.assertEqual(self.store._recordings_for_artist_sync(ZAPPA).results, ())
                    # Recreate the per-test catalog for the next isolated counterfactual.
                    self.c.close()
                    self.path.unlink()
                    self.setUp()

    def test_link_definition_search_denial_and_intact_display(self) -> None:
        first = self.store._recordings_for_artist_sync(ZAPPA).results[0]
        entity = first.recording_entity_id
        denied = self.observation("link-search", "local_search")
        self.c.execute(
            "UPDATE entity_artist_credits SET provenance_id=? WHERE entity_id=?", (denied, entity)
        )
        self.c.commit()
        page = self.store._recordings_for_artist_sync(ZAPPA)
        self.assertNotIn(first.recording_mbid, [row.recording_mbid for row in page.results])
        self.assertEqual(len(page.results), 10)
        self.assertNotEqual(page.results[-1].recording_mbid, first.recording_mbid)
        self.c.execute(
            "UPDATE artist_credits SET provenance_id=? WHERE id=?",
            (denied, page.results[0].credits[0].artist_credit_id),
        )
        self.c.commit()
        self.assertNotIn(
            page.results[0].recording_mbid,
            [row.recording_mbid for row in self.store._recordings_for_artist_sync(ZAPPA).results],
        )

    def test_withheld_member_and_conflicting_credit_do_not_establish_association(self) -> None:
        multiple = self.c.execute("""SELECT l.entity_id,m.artist_id FROM entity_artist_credits l
            JOIN artist_credit_members m ON m.artist_credit_id=l.artist_credit_id
            WHERE l.credit_kind='primary' AND (SELECT count(*) FROM artist_credit_members mm WHERE mm.artist_credit_id=l.artist_credit_id)>1 LIMIT 1""").fetchone()
        entity, artist = multiple
        mbid = self.c.execute(
            "SELECT normalized_value FROM entity_identifiers i JOIN identifier_types t ON t.id=i.identifier_type_id WHERE i.entity_id=? AND t.type_key='musicbrainz_artist_id'",
            (artist,),
        ).fetchone()[0]
        other = self.c.execute(
            "SELECT m.artist_id FROM artist_credit_members m JOIN entity_artist_credits l ON l.artist_credit_id=m.artist_credit_id WHERE l.entity_id=? AND m.artist_id<>? LIMIT 1",
            (entity, artist),
        ).fetchone()[0]
        denied = self.observation("coartist-display", "display")
        self.c.execute("UPDATE entity_names SET provenance_id=? WHERE entity_id=?", (denied, other))
        self.c.commit()
        found = self.store._recordings_for_artist_sync(mbid)
        self.assertNotIn(entity, [row.recording_entity_id for row in found.results])

    def test_independent_identical_observation_and_conflicting_whole_credit(self) -> None:
        first = self.store._recordings_for_artist_sync(ZAPPA).results[0]
        original = first.credits[0]
        denied = self.observation("duplicate-denied", "display")
        self.c.execute(
            "INSERT INTO artist_credits(credit_key,provenance_id) VALUES('duplicate-test',?)",
            (original.definition_provenance_id,),
        )
        duplicate = int(self.c.execute("SELECT last_insert_rowid()").fetchone()[0])
        self.c.execute(
            """INSERT INTO artist_credit_members SELECT ?,position,artist_id,credited_name,join_phrase
            FROM artist_credit_members WHERE artist_credit_id=?""",
            (duplicate, original.artist_credit_id),
        )
        self.c.execute(
            "INSERT INTO entity_artist_credits VALUES(?,'primary',?,?)",
            (first.recording_entity_id, duplicate, denied),
        )
        self.c.commit()
        self.assertEqual(self.store._recordings_for_artist_sync(ZAPPA).results[0], first)
        self.c.execute(
            "UPDATE entity_artist_credits SET provenance_id=? WHERE artist_credit_id=?",
            (original.credit_provenance_id, duplicate),
        )
        self.c.commit()
        self.assertEqual(len(self.store._recordings_for_artist_sync(ZAPPA).results[0].credits), 2)
        self.c.execute(
            "UPDATE artist_credit_members SET credited_name='Conflicting exact credit' WHERE artist_credit_id=?",
            (duplicate,),
        )
        self.c.commit()
        self.assertNotIn(
            first.recording_mbid,
            [r.recording_mbid for r in self.store._recordings_for_artist_sync(ZAPPA).results],
        )

    def test_overflow_and_identity_ambiguity_fail_closed(self) -> None:
        with (
            patch(
                "opennoise.serving.public.recording_navigation_store.MAX_ARTIST_CREDIT_OBSERVATIONS",
                1,
            ),
            self.assertRaisesRegex(PublicArtistNavigationStoreError, "bound"),
        ):
            self.store._recordings_for_artist_sync(ZAPPA)
        with (
            patch(
                "opennoise.serving.public.recording_navigation_store.MAX_TITLE_OBSERVATIONS",
                1,
            ),
            self.assertRaisesRegex(PublicArtistNavigationStoreError, "bound"),
        ):
            self.store._recordings_for_artist_sync(ZAPPA)
        self.c.execute(
            """INSERT INTO entity_identifiers(entity_id,identifier_type_id,namespace,value,normalized_value,provenance_id)
            SELECT (SELECT id FROM artists WHERE id<>? LIMIT 1),identifier_type_id,namespace,value,normalized_value,provenance_id FROM entity_identifiers
            WHERE entity_id=? AND normalized_value=? LIMIT 1""",
            (self.seed(), self.seed(), ZAPPA),
        )
        self.c.commit()
        with self.assertRaises(PublicArtistNavigationStoreError):
            self.store._recordings_for_artist_sync(ZAPPA)

    def test_cli_artist_mode_and_exclusive_filter(self) -> None:
        self.c.commit()
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        command = [
            sys.executable,
            str(ROOT / "scripts/query_recording_context.py"),
            "--database",
            str(self.path),
            "--database-sha256",
            digest,
        ]
        result = subprocess.run(
            [*command, "--artist-mbid", ZAPPA, "--title-filter", "Be-Bop Tango"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(len(json.loads(result.stdout)["results"]), 1)
        for args in (
            ["--query", "Tango", "--title-filter", "Tango"],
            ["--artist-mbid", ZAPPA, "--query", "Tango"],
        ):
            self.assertNotEqual(
                subprocess.run([*command, *args], capture_output=True, check=False).returncode, 0
            )
