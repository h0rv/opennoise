"""Behavioral checks for the local exact artist-signature audit."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING

from opennoise.peers.direct_custody_graph import (
    DirectCustodyPeerGraphError,
    build_direct_custody_peer_graph,
)
from opennoise.peers.signature_concentration import (
    _candidate_concentrations,
    build_signature_concentration_report,
)
from tests.peers.test_direct_custody_graph import _build_fixture

if TYPE_CHECKING:
    from collections.abc import Iterable


def _database(path: Path, memberships: Iterable[tuple[str, str]]) -> None:
    """Create the minimum graph tables used by the concentration calculation."""
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(
            """
            CREATE TABLE seed_artist (seed_id TEXT, artist_mbid TEXT);
            CREATE TABLE pair_edge (
              left_seed_id TEXT, right_seed_id TEXT,
              shared_artist_count INTEGER, disposition TEXT
            );
            """
        )
        connection.executemany("INSERT INTO seed_artist VALUES (?, ?)", memberships)
        connection.executemany(
            "INSERT INTO pair_edge VALUES (?, ?, ?, 'candidate')",
            (("a", "b", 2), ("a", "c", 2), ("b", "c", 2)),
        )
        connection.commit()


class SignatureConcentrationTests(unittest.TestCase):
    def test_repeated_exact_cohort_is_flagged_but_ordinary_overlap_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            database = Path(name) / "fixture.sqlite"
            memberships = [
                (seed, f"artist-{number:04d}")
                for number in range(1_000)
                for seed in ("a", "b", "c")
            ]
            memberships.extend(
                [("a", "ordinary-a"), ("b", "ordinary-a"), ("a", "ordinary-b"), ("c", "ordinary-b")]
            )
            # Pair support includes the two ordinary artists for a-b and a-c.
            _database(database, memberships)
            with closing(sqlite3.connect(database)) as connection:
                connection.execute(
                    "UPDATE pair_edge SET shared_artist_count = 1001 "
                    "WHERE left_seed_id = 'a' AND right_seed_id = 'b'"
                )
                connection.execute(
                    "UPDATE pair_edge SET shared_artist_count = 1001 "
                    "WHERE left_seed_id = 'a' AND right_seed_id = 'c'"
                )
                connection.execute(
                    "UPDATE pair_edge SET shared_artist_count = 1000 "
                    "WHERE left_seed_id = 'b' AND right_seed_id = 'c'"
                )
                connection.commit()
                candidates, suspects, top = _candidate_concentrations(connection)
            self.assertEqual(candidates, 3)
            self.assertEqual(suspects, 3)
            self.assertEqual(
                [(pair.left_seed_id, pair.right_seed_id) for pair in top],
                [("b", "c"), ("a", "b"), ("a", "c")],
            )
            self.assertEqual(top[0].dominant_signature, ("a", "b", "c"))

    def test_stored_shared_artist_count_must_match_membership_support(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            database = Path(name) / "fixture.sqlite"
            _database(database, [("a", "x"), ("b", "x"), ("a", "y"), ("b", "y")])
            with closing(sqlite3.connect(database)) as connection:
                connection.execute(
                    "DELETE FROM pair_edge WHERE NOT (left_seed_id = 'a' AND right_seed_id = 'b')"
                )
                connection.execute(
                    "UPDATE pair_edge SET shared_artist_count = 3 WHERE left_seed_id = 'a'"
                )
                connection.commit()
                with self.assertRaisesRegex(ValueError, "stored graph count"):
                    _candidate_concentrations(connection)

    def test_ordinary_small_overlap_is_not_suspect(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            database = Path(name) / "fixture.sqlite"
            _database(database, [("a", "x"), ("b", "x"), ("a", "y"), ("b", "y")])
            with closing(sqlite3.connect(database)) as connection:
                connection.execute(
                    "DELETE FROM pair_edge WHERE NOT (left_seed_id = 'a' AND right_seed_id = 'b')"
                )
                connection.commit()
                candidates, suspects, top = _candidate_concentrations(connection)
            self.assertEqual((candidates, suspects, top), (1, 0, ()))

    def test_tampered_graph_receipt_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            custody, object_store, _ = _build_fixture(
                directory, {"a": ("00000001-0000-4000-8000-000000000000",)}
            )
            database = directory / "graph.sqlite"
            receipt_path = directory / "graph.receipt.json"
            build_direct_custody_peer_graph(
                custody=custody,
                object_store=object_store,
                custody_receipt_byte_sha256="0" * 64,
                database=database,
                receipt_output=receipt_path,
            )
            payload = json.loads(receipt_path.read_text(encoding="utf-8"))
            payload["output_sha256"] = "0" * 64
            receipt_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(DirectCustodyPeerGraphError):
                build_signature_concentration_report(database=database, receipt_path=receipt_path)


if __name__ == "__main__":
    unittest.main()
