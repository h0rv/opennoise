"""Named style identity, source-role separation and evidence-only geometry checks."""

import errno
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import numpy as np
from scipy import sparse

from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.deployment.style_atlas import (
    PAGE_SIZE,
    ROLES,
    _clone_file,
    _cohorts,
    _fallback_names,
    _pack,
    _profiles,
    _proposal_support,
    build_style_atlas,
    evidence_tier,
    refresh_style_atlas_display,
    source_memberships,
    source_positions,
    style_id,
)
from opennoise.ml.artist_feature_enrichment import fit_enrichment


class StyleAtlasTests(unittest.TestCase):
    def test_display_refresh_preserves_hardlinked_profiles_maps_and_old_display_bytes(self) -> None:
        cache = Path(__file__).resolve().parents[2] / ".cache"
        with tempfile.TemporaryDirectory(dir=cache) as temporary:
            directory = Path(temporary)
            source = directory / "source"
            source.mkdir()
            style = {
                "id": style_id("records"),
                "name": "records",
                "source_artist_support": 5,
                "native_genre_ids": [],
                "detail_path": "styles/records.json",
                "x": 0.5,
                "evidence_tier": "repeated_source_candidate",
                "default_visible": True,
                "artist_map_path": "style-artist-maps/records.json",
            }
            payloads = {
                "data.json": {"styles": [style], "coverage": {}},
                "styles/records.json": {**style, "cohorts": {"retained": True}},
                "artists/000.json": {"artists": {"source": "retained"}},
                "cohorts/retained.json": {"source": "retained"},
                "source-geometry.json": {"geometry": "retained"},
                "style-artist-maps/records.json": {"map": "retained"},
            }
            files = {}
            for relative, value in payloads.items():
                path = source / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(canonical_json(value) + b"\n")
                files[relative] = {"sha256": sha256_file(path)[0], "bytes": path.stat().st_size}
            receipt = {
                "scope": "local_research_only",
                "public_export_authorized": False,
                "builder_sha256": "old-builder",
                "code_bindings": {},
                "files": files,
            }
            receipt["output_sha256"] = sha256_json(receipt)
            (source / "receipt.json").write_bytes(canonical_json(receipt))
            output = directory / "output"
            refresh_style_atlas_display(source=source, output=output)
            updated = json.loads((output / "data.json").read_bytes())["styles"][0]
            self.assertFalse(updated["default_visible"])
            self.assertEqual(updated["artist_map_path"], style["artist_map_path"])
            for relative, binding in files.items():
                self.assertEqual(sha256_file(source / relative)[0], binding["sha256"])
                if relative not in {"data.json", "styles/records.json"}:
                    self.assertEqual(sha256_file(output / relative)[0], binding["sha256"])
                    self.assertEqual(
                        (output / relative).stat().st_ino, (source / relative).stat().st_ino
                    )
                else:
                    self.assertNotEqual(
                        (output / relative).stat().st_ino, (source / relative).stat().st_ino
                    )

    def test_clone_copies_only_across_devices(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "source"
            source.write_bytes(b"retained")
            with patch(
                "opennoise.deployment.style_atlas.os.link",
                side_effect=OSError(errno.EXDEV, "cross device"),
            ):
                _clone_file(source, directory / "copied")
            self.assertEqual((directory / "copied").read_bytes(), source.read_bytes())
            with (
                patch(
                    "opennoise.deployment.style_atlas.os.link",
                    side_effect=OSError(errno.EACCES, "permission"),
                ),
                self.assertRaises(OSError),
            ):
                _clone_file(source, directory / "rejected")

    def test_name_overlays_bind_named_and_unresolved_exact_corpus(self) -> None:
        artist = "00000000-0000-0000-0000-000000000001"
        missing = "00000000-0000-0000-0000-000000000002"
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "artist-search.json").write_text(
                json.dumps(
                    {"artists": [[artist, artist, "unresolved"], [missing, missing, "unresolved"]]}
                )
            )
            overlay = directory / "artist-names.jsonl"
            overlay.write_text(
                json.dumps(
                    {
                        "artist_mbid": artist,
                        "name": "Recovered",
                        "evidence_ref": "mbdump/artist:row:1:sha256:" + "a" * 64,
                    }
                )
                + "\n"
            )
            missing_overlay = directory / "missing-artist-names.jsonl"
            missing_overlay.write_text(json.dumps({"artist_mbid": missing}) + "\n")
            receipt = {
                "name_overlay_sha256": sha256_file(overlay)[0],
                "missing_names_sha256": sha256_file(missing_overlay)[0],
            }
            names = _fallback_names(directory, directory / "artist-features.jsonl", receipt)
            self.assertEqual(set(names), {artist})
            missing_overlay.write_text(json.dumps({"artist_mbid": artist}) + "\n")
            receipt["missing_names_sha256"] = sha256_file(missing_overlay)[0]
            with self.assertRaisesRegex(ValueError, "missing name overlay"):
                _fallback_names(directory, directory / "artist-features.jsonl", receipt)

    def test_bulk_names_fill_missing_profiles_and_preserve_preferred_source_name(self) -> None:
        preferred = "f22942a1-6f70-4f48-866e-238cb2308fbd"
        missing = "00000000-0000-0000-0000-000000000001"
        with (
            tempfile.TemporaryDirectory() as temporary,
            closing(sqlite3.connect(":memory:")) as database,
        ):
            directory = Path(temporary)
            source = directory / "source"
            (source / "artists").mkdir(parents=True)
            files = {}
            for artist, name, status in (
                (preferred, "Aphex Twin", "exact"),
                (missing, missing, "unresolved"),
            ):
                relative = f"artists/{artist[:3]}.json"
                files[relative] = {}
                (source / relative).write_text(
                    json.dumps({"artists": {artist: {"name": name, "name_status": status}}})
                )
            database.executescript(
                "CREATE TABLE artists(mbid TEXT PRIMARY KEY,source BLOB,proposals BLOB,name TEXT);"
                "CREATE TABLE artist_names(mbid TEXT PRIMARY KEY,name TEXT,status TEXT);"
            )
            for artist in (preferred, missing):
                database.execute(
                    "INSERT INTO artists VALUES (?, ?, ?, NULL)", (artist, _pack([]), _pack([]))
                )
            fallbacks = {
                preferred: {"name": "Aphex", "evidence_ref": "bulk:preferred"},
                missing: {"name": "Recovered Name", "evidence_ref": "bulk:missing"},
            }
            output = directory / "output"
            _profiles(source, {"files": files}, output, database, fallbacks)
            profiles = {}
            for path in (output / "artists").glob("*.json"):
                profiles.update(json.loads(path.read_bytes())["artists"])
            self.assertEqual(profiles[preferred]["name"], "Aphex Twin")
            self.assertEqual(profiles[preferred]["name_status"], "exact")
            self.assertEqual(profiles[missing]["name"], "Recovered Name")
            self.assertEqual(profiles[missing]["name_evidence_ref"], "bulk:missing")
            self.assertEqual(profiles[missing]["name_status"], "exact_verified_bulk_name_fallback")

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
            "records",
            "composers",
            "pianists",
            "guitarists",
            "organist",
            "jazz musicians",
            "death by covid-19",
            "death from pneumonia",
            "death due to natural causes",
        ):
            self.assertEqual(evidence_tier(value, 100, []), "raw_source_candidate")
            self.assertEqual(
                evidence_tier(value, 100, ["dictionary-name-only"]), "raw_source_candidate"
            )
        for value in (
            "finnish string quartet",
            "festival trap",
            "comfy synth",
            "denpa",
            "soft visual",
            "death metal",
            "deathcore",
            "japanese jazz",
            "unknown source label",
        ):
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
