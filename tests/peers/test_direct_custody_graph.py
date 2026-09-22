"""Behavioral checks for the portable proper-genre custody peer graph."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreCustodyError,
    DirectProperGenreCustodyReceipt,
    build_portable_direct_proper_genre_custody,
)
from opennoise.peers.direct_custody_graph import (
    DirectCustodyPeerGraphReceipt,
    build_direct_custody_peer_graph,
    verify_direct_custody_peer_graph_receipt,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

_SECOND_LINK_CALL: int = 2


def _uuid(value: int) -> str:
    """Return a deterministic UUID accepted by the MusicBrainz boundary."""
    return f"{value:08x}-0000-4000-8000-000000000000"


def _build_fixture(
    directory: Path, assignments: Mapping[str, tuple[str, ...]], *, suffix: str = "a"
) -> tuple[DirectProperGenreCustodyReceipt, Path, str]:
    """Create a tiny valid custody stream with optional per-pair duplicate genres."""
    seed_target = directory / f"seed-target-{suffix}.json"
    reconciliation = directory / f"reconciliation-{suffix}.json"
    evidence: list[dict[str, str]] = []
    dispositions: list[dict[str, object]] = []
    genre_number = 100
    for seed, artists in sorted(assignments.items()):
        identities: list[dict[str, str]] = []
        for artist in artists:
            repeats = 2 if seed == "a" and artist == _uuid(1) else 1
            for _ in range(repeats):
                genre = _uuid(genre_number)
                genre_number += 1
                identities.append({"namespace": "musicbrainz_genre_id", "identifier": genre})
                evidence.append(
                    {
                        "seed_source_item_id": seed,
                        "seed_name": seed,
                        "artist_id": artist,
                        "facet": "genre",
                        "match_kind": "exact",
                        "target_identity": genre,
                        "target_name": seed,
                        "target_namespace": "musicbrainz_genre_id",
                        "source_record_id": f"musicbrainz:artist:{artist}",
                        "source_record_sha256": hashlib.sha256(artist.encode()).hexdigest(),
                        "evidence_ref": f"evidence:{seed}:{genre}",
                    }
                )
        dispositions.append({"source_item_id": seed, "musicbrainz_identities": identities})
    seed_target.write_text(
        json.dumps({"evidence": evidence, "output_sha256": "b" * 64}), encoding="utf-8"
    )
    reconciliation.write_text(
        json.dumps({"dispositions": dispositions, "output_sha256": "c" * 64}),
        encoding="utf-8",
    )
    object_store = directory / f"objects-{suffix}"
    receipt = build_portable_direct_proper_genre_custody(
        seed_target=seed_target,
        seed_target_byte_sha256=hashlib.sha256(seed_target.read_bytes()).hexdigest(),
        seed_target_output_sha256="b" * 64,
        reconciliation=reconciliation,
        object_store=object_store,
        receipt_output=directory / f"custody-{suffix}.json",
    )
    return (
        receipt,
        object_store,
        hashlib.sha256((directory / f"custody-{suffix}.json").read_bytes()).hexdigest(),
    )


class DirectCustodyPeerGraphTests(unittest.TestCase):
    def _build_graph(
        self, directory: Path, assignments: Mapping[str, tuple[str, ...]], *, suffix: str = "a"
    ) -> tuple[DirectCustodyPeerGraphReceipt, Path]:
        custody, object_store, byte_sha = _build_fixture(directory, assignments, suffix=suffix)
        database = directory / f"graph-{suffix}.sqlite"
        receipt_path = directory / f"graph-{suffix}.receipt.json"
        receipt = build_direct_custody_peer_graph(
            custody=custody,
            object_store=object_store,
            custody_receipt_byte_sha256=byte_sha,
            database=database,
            receipt_output=receipt_path,
        )
        verify_direct_custody_peer_graph_receipt(receipt, database=database)
        return receipt, database

    def test_pair_symmetry_raw_metrics_and_stable_top_k_order(self) -> None:
        artists = (_uuid(1), _uuid(2))
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            receipt, database = self._build_graph(
                directory,
                {"a": artists, "b": artists, "c": artists, "isolated": (_uuid(9),)},
            )
            self.assertEqual(receipt.candidate_pair_count, 3)
            self.assertEqual(receipt.isolated_seed_count, 1)
            with closing(sqlite3.connect(database)) as connection:
                edge = connection.execute(
                    "SELECT shared_artist_count, raw_jaccard, idf_weighted_jaccard, disposition "
                    "FROM pair_edge WHERE left_seed_id = 'a' AND right_seed_id = 'b'"
                ).fetchone()
                directions = connection.execute(
                    "SELECT seed_id, rank, peer_seed_id FROM peer_neighbor "
                    "WHERE (seed_id = 'a' AND peer_seed_id = 'b') "
                    "OR (seed_id = 'b' AND peer_seed_id = 'a') ORDER BY seed_id"
                ).fetchall()
                ordered = connection.execute(
                    "SELECT peer_seed_id FROM peer_neighbor WHERE seed_id = 'a' ORDER BY rank"
                ).fetchall()
            self.assertEqual(edge, (2, 1.0, 1.0, "candidate"))
            self.assertEqual(directions, [("a", 1, "b"), ("b", 1, "a")])
            self.assertEqual(ordered, [("b",), ("c",)])

    def test_idf_weight_reduces_hub_pair_score_at_same_raw_jaccard(self) -> None:
        rare = (_uuid(10), _uuid(11))
        hubs = (_uuid(12), _uuid(13))
        assignments = {
            "a": (*rare, _uuid(14)),
            "b": (*rare, _uuid(15)),
            "c": (*hubs, _uuid(16)),
            "d": (*hubs, _uuid(17)),
            "e": (*hubs, _uuid(18)),
            "f": (*hubs, _uuid(19)),
        }
        with tempfile.TemporaryDirectory() as name:
            receipt, database = self._build_graph(Path(name), assignments)
            self.assertEqual(receipt.candidate_pair_count, 7)
            with closing(sqlite3.connect(database)) as connection:
                rows = connection.execute(
                    "SELECT left_seed_id, right_seed_id, raw_jaccard, idf_weighted_jaccard "
                    "FROM pair_edge WHERE (left_seed_id = 'a' AND right_seed_id = 'b') "
                    "OR (left_seed_id = 'c' AND right_seed_id = 'd') ORDER BY left_seed_id"
                ).fetchall()
                weights = connection.execute(
                    "SELECT artist_mbid, seed_degree, weight FROM artist_weight "
                    "WHERE artist_mbid IN (?, ?) ORDER BY seed_degree",
                    (hubs[0], rare[0]),
                ).fetchall()
            self.assertEqual(rows[0][2], rows[1][2])
            self.assertGreater(rows[0][3], rows[1][3])
            self.assertGreater(weights[0][2], weights[1][2])

    def test_one_overlap_is_abstained_and_zero_overlap_is_explicitly_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            receipt, database = self._build_graph(
                Path(name),
                {
                    "weak-a": (_uuid(20), _uuid(21)),
                    "weak-b": (_uuid(20), _uuid(22)),
                    "alone": (_uuid(23),),
                },
            )
            self.assertEqual(receipt.candidate_pair_count, 0)
            self.assertEqual(receipt.one_overlap_abstention_count, 1)
            self.assertEqual(receipt.isolated_seed_count, 1)
            with closing(sqlite3.connect(database)) as connection:
                states = dict(connection.execute("SELECT seed_id, state FROM seed_node"))
                edge = connection.execute(
                    "SELECT shared_artist_count, disposition FROM pair_edge"
                ).fetchone()
            self.assertEqual(
                states,
                {"alone": "isolated", "weak-a": "only_weak_overlap", "weak-b": "only_weak_overlap"},
            )
            self.assertEqual(edge, (1, "abstained_one_overlap"))

    def test_duplicate_seed_artist_claims_are_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            receipt, database = self._build_graph(
                Path(name), {"a": (_uuid(1),), "b": (_uuid(1), _uuid(2))}
            )
            self.assertEqual(receipt.duplicate_seed_artist_claim_count, 1)
            self.assertEqual(receipt.claim_count, 4)
            self.assertEqual(receipt.unique_seed_artist_count, 3)
            with closing(sqlite3.connect(database)) as connection:
                count = connection.execute(
                    "SELECT count(*) FROM seed_artist WHERE seed_id = 'a'"
                ).fetchone()[0]
            self.assertEqual(count, 1)

    def test_swapped_custody_receipt_fails_against_other_object_store(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            _first, first_store, _ = _build_fixture(
                directory, {"a": (_uuid(30),), "b": (_uuid(31),)}, suffix="first"
            )
            second, _, second_byte_sha = _build_fixture(
                directory, {"a": (_uuid(32),), "b": (_uuid(33),)}, suffix="second"
            )
            with self.assertRaises(DirectProperGenreCustodyError):
                build_direct_custody_peer_graph(
                    custody=second,
                    object_store=first_store,
                    custody_receipt_byte_sha256=second_byte_sha,
                    database=directory / "swapped.sqlite",
                    receipt_output=directory / "swapped.receipt.json",
                )

    def test_second_link_failure_removes_only_the_database_link_created_here(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            custody, object_store, byte_sha = _build_fixture(
                directory, {"a": (_uuid(40),)}, suffix="link-failure"
            )
            database = directory / "link-failure.sqlite"
            receipt_output = directory / "link-failure.receipt.json"
            real_link = os.link
            calls = 0

            def fail_second_link(source: Path, destination: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == _SECOND_LINK_CALL:
                    raise PermissionError("simulated sidecar link failure")
                real_link(source, destination)

            with (
                patch("opennoise.peers.direct_custody_graph.os.link", fail_second_link),
                self.assertRaises(PermissionError),
            ):
                build_direct_custody_peer_graph(
                    custody=custody,
                    object_store=object_store,
                    custody_receipt_byte_sha256=byte_sha,
                    database=database,
                    receipt_output=receipt_output,
                )
            self.assertFalse(database.exists())
            self.assertFalse(receipt_output.exists())


if __name__ == "__main__":
    unittest.main()
