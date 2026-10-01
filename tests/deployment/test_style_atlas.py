"""Named style identity, source-role separation and evidence-only geometry checks."""

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import numpy as np
from scipy import sparse

from opennoise.deployment.style_atlas import (
    PAGE_SIZE,
    ROLES,
    _cohorts,
    _proposal_support,
    build_style_atlas,
    evidence_tier,
    source_memberships,
    source_positions,
    style_id,
)
from opennoise.ml.artist_feature_enrichment import fit_enrichment


class StyleAtlasTests(unittest.TestCase):
    def test_existing_cache_output_is_rejected_before_reading_inputs(self) -> None:
        cache = Path(__file__).resolve().parents[2] / ".cache"
        with tempfile.TemporaryDirectory(dir=cache) as temporary:
            output = Path(temporary)
            with self.assertRaises(FileExistsError):
                build_style_atlas(
                    source=output / "missing-source",
                    features=output / "missing-features",
                    enrichment_directory=output / "missing-enrichment",
                    output=output,
                )

    def test_default_display_is_source_supported_and_preserves_legitimate_punctuation(self) -> None:
        self.assertEqual(evidence_tier("ambient", 1, ["genre-id"]), "dictionary_named_style")
        for value in ("nu-jazz", "coupé-décalé", "rock 'n' roll"):
            self.assertEqual(evidence_tier(value, 5, []), "repeated_source_candidate")
            self.assertEqual(evidence_tier(value, 4, []), "raw_source_candidate")
        for value in ('"air with heart"', "!hyperfocus", "my best", "'air'"):
            self.assertEqual(evidence_tier(value, 100, []), "raw_source_candidate")
        for value in (
            "top 100",
            "top10",
            "milane records",
            "sxsw",
            "south by southwest",
            "download festival",
            "hong kong actor",
            "komponist",
            "violinist",
            "lithuanian",
            "covid-19",
            "death by murder",
            "27 club",
            "fixme",
            "model",
        ):
            self.assertEqual(evidence_tier(value, 100, []), "raw_source_candidate")
            self.assertEqual(
                evidence_tier(value, 100, ["dictionary-name-only"]), "raw_source_candidate"
            )
        for value in ("finnish string quartet", "festival trap"):
            self.assertEqual(evidence_tier(value, 100, []), "repeated_source_candidate")

    def test_proposal_query_reference_must_belong_to_its_actual_cue(self) -> None:
        profiles = {"one": ("ambient", "drone"), "two": ("ambient", "drone")}
        model = fit_enrichment(profiles, {})
        row = {
            "artist_mbid": "query",
            "features": [
                {
                    "namespace": "artist_tag",
                    "value": "ambient",
                    "weight": 1,
                    "evidence_refs": ["ambient:source"],
                },
                {
                    "namespace": "artist_tag",
                    "value": "punk",
                    "weight": 1,
                    "evidence_refs": ["punk:source"],
                },
            ],
        }
        memberships, _ = source_memberships(row)
        proposal = model.proposals(row)[0]
        _proposal_support(proposal, memberships, model)
        evidence = proposal["evidence"]
        assert isinstance(evidence, list)
        evidence[0]["query_evidence_refs"] = ["punk:source"]
        with self.assertRaisesRegex(ValueError, "cue differs"):
            _proposal_support(proposal, memberships, model)

    def test_proper_cue_can_cite_same_value_tag_union_but_requires_actual_genre(self) -> None:
        profiles = {"one": ("ambient", "drone"), "two": ("ambient", "drone")}
        model = fit_enrichment(profiles, {"one": ("ambient",), "two": ("ambient",)})
        row = {
            "artist_mbid": "query",
            "features": [
                {
                    "namespace": namespace,
                    "value": "ambient",
                    "weight": 1,
                    "evidence_refs": [namespace + ":source"],
                }
                for namespace in ("artist_genre", "artist_tag")
            ],
        }
        memberships, _ = source_memberships(row)
        proposal = model.proposals(row)[0]
        _proposal_support(proposal, memberships, model)
        memberships[0]["source_features"] = [
            feature
            for feature in memberships[0]["source_features"]
            if feature["namespace"] != "artist_genre"
        ]
        with self.assertRaisesRegex(ValueError, "cue differs"):
            _proposal_support(proposal, memberships, model)

    def test_raw_tags_and_release_context_never_become_native_genre_facts(self) -> None:
        features = [
            {
                "namespace": namespace,
                "value": "ambient",
                "weight": 1,
                "evidence_refs": ["source:" + namespace],
            }
            for namespace in ("artist_genre", "artist_tag", "release_genre")
        ]
        memberships, values = source_memberships({"features": features})
        self.assertEqual(values, {"ambient"})
        self.assertEqual({row["role"] for row in memberships}, set(ROLES[:2]))
        self.assertTrue(all(row["native_fact"] is False for row in memberships))
        observed = next(row for row in memberships if row["role"] == ROLES[0])
        self.assertEqual(len(observed["source_features"]), 2)
        self.assertTrue(all(row["style_id"] == style_id("ambient") for row in memberships))

    def test_nonmusical_metadata_is_not_a_style(self) -> None:
        memberships, values = source_memberships(
            {
                "features": [
                    {"namespace": namespace, "value": value, "weight": 1, "evidence_refs": ["x"]}
                    for namespace, value in (
                        ("area", "Berlin"),
                        ("decade", "1990s"),
                        ("artist_tag", "seen live"),
                    )
                ]
            }
        )
        self.assertEqual(memberships, [])
        self.assertEqual(values, set())

    def test_identical_support_columns_are_searchable_but_unpositioned(self) -> None:
        matrix = sparse.csr_matrix(np.asarray([[1, 1, 1], [1, 1, 1], [0, 0, 1]]))
        positions, edges, duplicates = source_positions(["a", "b", "c"], matrix)
        self.assertEqual(duplicates, {"a", "b"})
        self.assertEqual(positions, {})
        self.assertEqual(edges, [])

    def test_sparse_geometry_requires_distinct_joint_source_support(self) -> None:
        matrix = sparse.csr_matrix(
            np.asarray([[1, 1, 0], [1, 1, 0], [1, 0, 1], [0, 1, 1], [0, 0, 1]])
        )
        positions, edges, duplicates = source_positions(["a", "b", "c"], matrix)
        self.assertEqual(duplicates, set())
        self.assertEqual(set(positions), {style_id("a"), style_id("b")})
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["source_joint_artist_support"], 2)

    def test_dense_pair_work_is_rejected_before_cooccurrence_multiplication(self) -> None:
        matrix = sparse.csr_matrix(np.ones((300, 512)))
        with self.assertRaisesRegex(ValueError, "pair bound"):
            source_positions([str(index) for index in range(512)], matrix)

    def test_all_cohort_pages_preserve_exact_identities_and_roles(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary,
            closing(sqlite3.connect(":memory:")) as database,
        ):
            database.executescript(
                "CREATE TABLE artists(mbid TEXT PRIMARY KEY, name TEXT);"
                "CREATE TABLE members(style TEXT, role TEXT, artist TEXT, score REAL);"
            )
            expected = set()
            for index in range(PAGE_SIZE + 3):
                artist = f"00000000-0000-0000-0000-{index:012d}"
                expected.add(artist)
                database.execute("INSERT INTO artists VALUES (?, ?)", (artist, "Name"))
                database.execute(
                    "INSERT INTO members VALUES (?, ?, ?, NULL)",
                    (style_id("ambient"), ROLES[0], artist),
                )
            database.execute(
                "INSERT INTO members VALUES (?, ?, ?, NULL)",
                (style_id("ambient"), ROLES[1], artist),
            )
            directory = Path(temporary)
            styles = [{"id": style_id("ambient"), "name": "ambient"}]
            _cohorts(directory, database, styles)
            detail = json.loads((directory / styles[0]["detail_path"]).read_bytes())
            pages = detail["cohorts"][ROLES[0]]["pages"]
            self.assertEqual(len(pages), 2)
            artists = set()
            for page in pages:
                payload = json.loads((directory / page).read_bytes())
                self.assertEqual(payload["role"], ROLES[0])
                self.assertFalse(payload["native_fact"])
                artists.update(row["artist_mbid"] for row in payload["artists"])
            self.assertEqual(artists, expected)
            self.assertEqual(detail["cohorts"][ROLES[1]]["artist_count"], 1)
            self.assertEqual(detail["source_artist_support"], PAGE_SIZE + 3)
            self.assertEqual(detail["cohorts"][ROLES[2]]["artist_count"], 0)
