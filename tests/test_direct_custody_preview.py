"""Source identity and abstention boundaries of the static local explorer."""

from __future__ import annotations

import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from opennoise.deployment.direct_custody_preview import (
    ArtistProposal,
    ModelGenre,
    ModelPeer,
    _verify_source_agreement,
    assemble_preview,
    build_local_direct_custody_preview,
    exact_native_label,
    source_graph_positions,
    verify_observation_projection,
)
from opennoise.ml.direct_custody_neighborhoods import observation_index


def source_fixture(connection: sqlite3.Connection) -> tuple[ModelGenre, ...]:
    """Build a real overlap, one inferred proposal, and one isolated source genre."""
    connection.executescript(
        "CREATE TABLE seed_artist(seed_id TEXT,artist_mbid TEXT);"
        "CREATE TABLE direct_claim(seed_id TEXT,musicbrainz_genre_id TEXT);"
        "CREATE TABLE artist(artist_mbid TEXT,display_name TEXT,name_status TEXT);"
        "INSERT INTO seed_artist VALUES ('a','artist1'),('a','artist2'),"
        "('b','artist1'),('b','artist2'),('b','artist3'),('c','artist4');"
        "INSERT INTO direct_claim VALUES ('a','uuid-a'),('b','uuid-b'),('c','uuid-c');"
        "INSERT INTO artist VALUES ('artist1','One','exact'),('artist2','Two','exact'),"
        "('artist3','Three','exact'),('artist4',NULL,'unresolved');"
    )
    return (
        ModelGenre(
            seed_id="a",
            observed_artist_count=2,
            state="supported",
            peers=(
                ModelPeer(
                    seed_id="b",
                    score=0.5,
                    shared_artist_count=2,
                    role="inferred_genre_overlap_neighbor",
                ),
            ),
            artist_candidates=(
                ArtistProposal(
                    artist_mbid="artist3",
                    score=0.5,
                    role="inferred_artist_candidate",
                    via_seed_ids=("b",),
                ),
            ),
        ),
        ModelGenre(
            seed_id="b",
            observed_artist_count=3,
            state="supported",
            peers=(
                ModelPeer(
                    seed_id="a",
                    score=0.5,
                    shared_artist_count=2,
                    role="inferred_genre_overlap_neighbor",
                ),
            ),
            artist_candidates=(),
        ),
        ModelGenre(
            seed_id="c",
            observed_artist_count=1,
            state="abstained_insufficient_shared_artists",
            peers=(),
            artist_candidates=(),
        ),
    )


class DirectCustodyPreviewTests(unittest.TestCase):
    def test_labels_do_not_affect_layout_and_isolated_genre_stays_unplaced(self) -> None:
        with closing(sqlite3.connect(":memory:")) as connection:
            rows = source_fixture(connection)
            positions = source_graph_positions(rows)
            self.assertEqual(positions, source_graph_positions(tuple(reversed(rows))))
            self.assertEqual(set(positions), {"a", "b"})
            first = json.loads(
                json.dumps(assemble_preview(connection, rows, {"uuid-a": "jazz", "uuid-b": "rock"}))
            )
            second = json.loads(
                json.dumps(
                    assemble_preview(
                        connection, rows, {"uuid-a": "another label", "uuid-b": "a label"}
                    )
                )
            )
            for a, b in zip(first["genres"], second["genres"], strict=True):
                self.assertEqual((a["x"], a["y"]), (b["x"], b["y"]))
            self.assertEqual(first["unplaced_count"], 1)
            isolated = first["genres"][2]
            self.assertIsNone(isolated["x"])
            self.assertEqual(isolated["direct_artist_ids"], ["artist4"])

    def test_direct_artists_and_proposals_remain_separate_with_direct_traversal(self) -> None:
        with closing(sqlite3.connect(":memory:")) as connection:
            data = json.loads(
                json.dumps(assemble_preview(connection, source_fixture(connection), {}))
            )
            genre = data["genres"][0]
            self.assertEqual(genre["direct_artist_ids"], ["artist1", "artist2"])
            self.assertEqual(genre["proposals"][0]["artist_mbid"], "artist3")
            self.assertEqual(data["artists"]["artist3"]["genre_ids"], ["b"])
            self.assertEqual(data["artists"]["artist4"]["name"], "artist4")

    def test_inferred_proposal_cannot_be_a_direct_observation(self) -> None:
        with closing(sqlite3.connect(":memory:")) as connection:
            rows = source_fixture(connection)
            proposal = rows[0].artist_candidates[0].model_copy(update={"artist_mbid": "artist1"})
            rows = (rows[0].model_copy(update={"artist_candidates": (proposal,)}), *rows[1:])
            with self.assertRaisesRegex(ValueError, "mixed with a direct"):
                assemble_preview(connection, rows, {})

    def test_proposal_explanations_must_replay_source_genres(self) -> None:
        with closing(sqlite3.connect(":memory:")) as connection:
            rows = source_fixture(connection)
            proposal = rows[0].artist_candidates[0].model_copy(update={"via_seed_ids": ("c",)})
            rows = (rows[0].model_copy(update={"artist_candidates": (proposal,)}), *rows[1:])
            with self.assertRaisesRegex(ValueError, "explanations do not replay"):
                assemble_preview(connection, rows, {})

    def test_ambiguous_native_id_mapping_abstains_even_when_labels_match(self) -> None:
        labels = {"id-a": "same", "id-b": "same"}
        self.assertEqual(
            exact_native_label("seed", {"id-a"}, labels), ("same", "exact_native_uuid")
        )
        self.assertEqual(
            exact_native_label("seed", {"id-a", "id-b"}, labels)[1], "ambiguous_native_uuid"
        )
        self.assertEqual(exact_native_label("seed", {"absent"}, labels)[1], "missing_native_label")

    def test_model_catalog_source_binding_mismatch_fails(self) -> None:
        model = {
            "custody_object_sha256": "a",
            "custody_receipt_output_sha256": "b",
            "scope": "local_research_only",
            "public_export_authorized": False,
            "serving_authorized": False,
        }
        catalog = SimpleNamespace(direct_object_sha256="a", direct_receipt_output_sha256="b")
        _verify_source_agreement(model, model, catalog)
        with self.assertRaisesRegex(ValueError, "custody hashes differ"):
            _verify_source_agreement({**model, "custody_object_sha256": "wrong"}, model, catalog)
        with self.assertRaisesRegex(ValueError, "local research"):
            _verify_source_agreement({**model, "public_export_authorized": True}, model, catalog)

    def test_model_matrix_pairs_must_exactly_replay_catalog_projection(self) -> None:
        with closing(sqlite3.connect(":memory:")) as connection:
            source_fixture(connection)
            source = {
                "a": ("artist1", "artist2"),
                "b": ("artist1", "artist2", "artist3"),
                "c": ("artist4",),
            }
            verify_observation_projection(observation_index(source), connection)
            source["a"] = ("artist1", "artist3")
            with self.assertRaisesRegex(ValueError, "exact source catalog pairs"):
                verify_observation_projection(observation_index(source), connection)

    def test_public_destination_rejected_before_any_inputs_are_read(self) -> None:
        with self.assertRaisesRegex(ValueError, "inside project .cache"):
            build_local_direct_custody_preview(
                model_directory=Path("absent"),
                catalog_directory=Path("absent"),
                label_directory=Path("absent"),
                output=Path("dist/new"),
            )


if __name__ == "__main__":
    unittest.main()
