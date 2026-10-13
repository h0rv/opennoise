"""Synthetic offline fixtures, not listener judgments or authentic audio."""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from opennoise.deployment import fma_audition as m


class AuditionTests(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[Any, ...]:
        tracks, audio, packs = {}, {}, {}
        for collection, ids in (("original", range(1, 13)), ("expanded", range(13, 25))):
            directory = root / collection / "audio"
            directory.mkdir(parents=True)
            attached = {}
            for identity in ids:
                body = b"synthetic fixture, never actual audio"
                (directory / f"{identity}.mp3").write_bytes(body)
                row: dict[str, Any] = dict.fromkeys(m.CREDIT_FIELDS, "")
                row.update(
                    track_id=identity,
                    artist_id=identity,
                    title=f"Track {identity}",
                    artist_name=f"Artist {identity}",
                    license_url="http://creativecommons.org/licenses/by/4.0/",
                    license_title="Creative Commons Attribution",
                    audio_path=f"{identity}.mp3",
                    audio_bytes=len(body),
                    audio_sha256=hashlib.sha256(body).hexdigest(),
                    decode={"full_decode": True},
                )
                attached[str(identity)] = row
                tracks[str(identity)] = {"collection": collection}
            audio[collection] = {"tracks": attached}
            packs[collection] = {
                "components": {str(i): i for i in ids},
                "rows": [
                    {"track_id": i, "neighbor_ids": [j for j in ids if j != i][:6], "reason": None}
                    for i in ids
                ],
                "provenance": {"test_only": True},
            }
        genres = []
        for offset, cell in enumerate(
            ("single/root", "single/child", "multiple/root", "multiple/child")
        ):
            for k in range(3):
                identity = offset * 3 + k + 1
                ids = [identity] if cell.startswith("single") else [identity, identity + 12]
                genres.append(
                    {
                        "genre_id": identity,
                        "title": str(identity),
                        "parent_id": None if cell.endswith("root") else 1,
                        "track_ids": ids,
                        "starting_ids": ids,
                    }
                )
        return (
            {"genres": genres, "tracks": tracks},
            audio,
            packs,
            {i: i for i in range(1, 25)},
            {"test_only": "fixture"},
        )

    def test_deterministic_separate_blank_packets_and_credit_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = self.fixture(root / "site")
            with patch.object(m, "_inputs", return_value=fixture):
                a = m.build_audition(root / "site", root, root / "a")
                b = m.build_audition(root / "site", root, root / "b")
                self.assertEqual(a, b)
                with self.assertRaises(ValueError):
                    m.build_audition(root / "site", root, root / "a")
            for slot in (1, 2):
                dest = root / "a" / f"listener-{slot}"
                items = json.loads((dest / "items.json").read_bytes())["items"]
                self.assertEqual(len(items), 24)
                self.assertNotIn("descriptor", (dest / "items.json").read_text())
                self.assertFalse((dest / "assignment-key.json").exists())
                with (dest / "review-form.csv").open() as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 24)
                self.assertTrue(
                    all(
                        not value
                        for row in rows
                        for key, value in row.items()
                        if key not in ("item_id", "reviewer_slot")
                    )
                )
                manifest = json.loads((dest / "MANIFEST.json").read_bytes())
                self.assertEqual(
                    set(manifest) | {"MANIFEST.json"},
                    {str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file()},
                )
                for name, record in manifest.items():
                    self.assertEqual(
                        hashlib.sha256((dest / name).read_bytes()).hexdigest(), record["sha256"]
                    )

    def test_popularity_pool_unsupported_and_no_stratum_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index, _, packs, listens, _ = self.fixture(Path(directory))
            _, queries, denominator = m.select_items(index, packs, listens)
            for row in queries:
                self.assertEqual(row["popularity"], max(row["eligible_ids"]))
                self.assertNotIn(row["query"], row["eligible_ids"])
            self.assertEqual(len(denominator["default_queries"]), 24)
            for pack in packs.values():
                for row in pack["rows"]:
                    row.update(neighbor_ids=[], reason="outside_training_support")
            _, unsupported, _ = m.select_items(index, packs, listens)
            self.assertEqual(len(unsupported), 12)
            self.assertTrue(
                all(row["descriptor"] is None and row["popularity"] is None for row in unsupported)
            )
            index["genres"].pop()
            with self.assertRaisesRegex(ValueError, "stratum"):
                m.select_items(index, packs, listens)

    def test_hash_rights_and_budget_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = self.fixture(root / "site")
            for field, bad in (
                ("license_url", "http://creativecommons.org/licenses/by-nc/4.0/"),
                ("audio_sha256", "0" * 64),
            ):
                changed = copy.deepcopy(fixture)
                for pool in changed[1].values():
                    for row in pool["tracks"].values():
                        row[field] = bad
                with (
                    patch.object(m, "_inputs", return_value=changed),
                    self.assertRaisesRegex(ValueError, "license/hash"),
                ):
                    m.build_audition(root / "site", root, root / field)
            with (
                patch.object(m, "_inputs", return_value=fixture),
                patch.object(m, "MAX_SLOT_AUDIO", 1),
                self.assertRaisesRegex(ValueError, "64 MB"),
            ):
                m.build_audition(root / "site", root, root / "budget")

    def test_index_tampering_and_symlinks_fail_before_source_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "genre-discovery.json").write_text('{"changed": true}')
            with (
                patch.object(m, "genre_index", return_value={"changed": False}),
                patch.object(m, "verify_sources") as verify,
                self.assertRaisesRegex(ValueError, "discovery index"),
            ):
                m.build_audition(root, root, root / "output")
            verify.assert_not_called()
            self.assertFalse((root / "output").exists())
            (root / "linked").symlink_to(root / "genre-discovery.json")
            with self.assertRaisesRegex(ValueError, "symlink"):
                m._body(root / "linked")  # noqa: SLF001 -- path boundary regression.

    def test_raw_native_license_mismatch_rejected_before_packet_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "site"
            index, audio, packs, _, _ = self.fixture(site)
            source = root / "source"
            source.mkdir()
            (source / "source-receipt.json").write_text("{}")
            source_hash = hashlib.sha256(b"{}").hexdigest()
            index["collections"] = {}
            for key in audio:
                explorer = site / key / "explorer"
                (explorer / "playable-neighbors").mkdir(parents=True)
                config = {"manifest": f"{key}/audio/manifest.json"}
                body = json.dumps(audio[key]).encode()
                (site / config["manifest"]).write_bytes(body)
                config["manifest_sha256"] = hashlib.sha256(body).hexdigest()
                body = json.dumps(packs[key]).encode()
                relative = f"{key}/explorer/playable-neighbors/manifest.json"
                (site / relative).write_bytes(body)
                config["playable_neighbors"] = {
                    "manifest_path": relative,
                    "manifest_sha256": hashlib.sha256(body).hexdigest(),
                }
                index["collections"][key] = config
                (explorer / "static-receipt.json").write_text(
                    json.dumps({"source_receipt_sha256": source_hash})
                )
            index["tracks"]["1"].update(track_id=1, artist_id=1, genre_ids=[])
            (site / "genre-discovery.json").write_text(json.dumps(index))
            raw = {"track_id": "1", "license_url": "http://creativecommons.org/licenses/by-nc/4.0/"}
            with (
                patch.object(m, "genre_index", return_value=index),
                patch.object(
                    m,
                    "verify_sources",
                    return_value={"members": {"fma_metadata/raw_tracks.csv": {}}},
                ),
                patch.object(m, "source_rows", return_value=(iter([raw]), None, [])),
                patch.object(
                    m, "project_row", return_value={"track_id": 1, "artist_id": 1, "genre_ids": []}
                ),
                self.assertRaisesRegex(ValueError, "native license or credit"),
            ):
                m.build_audition(site, source, root / "out")
            self.assertFalse((root / "out").exists())
