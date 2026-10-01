"""Exact-ID enrichment, source replay, homonyms and local output constraints."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from typing import override
from unittest.mock import patch

import httpx
import zstandard

from opennoise.catalog.musicbrainz_candidate import (
    CandidateCatalogError,
    build_local_musicbrainz_candidate_catalog,
    normalize_display_name,
    query_local_musicbrainz_candidate_genre,
    verify_local_musicbrainz_candidate_catalog,
)
from opennoise.catalog.musicbrainz_genre_labels import (
    acquire_native_musicbrainz_genre_labels,
    build_local_musicbrainz_genre_label_join,
    verify_native_musicbrainz_genre_labels,
)
from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.deployment.musicbrainz_direct_canonical_artist_name_custody import (
    DirectCanonicalArtistNameCustodyReceipt,
)
from opennoise.deployment.musicbrainz_direct_canonical_artist_name_custody import (
    receipt_sha256 as name_receipt_sha256,
)
from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreCustodyReceipt,
)
from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    receipt_sha256 as direct_receipt_sha256,
)
from opennoise.sources.musicbrainz import MusicBrainzClient

_ROOT = Path(__file__).resolve().parents[2]


def _uuid(value: int) -> str:
    return f"{value:08x}-0000-4000-8000-000000000000"


def _fixture(directory: Path) -> dict[str, Path]:
    claims = [
        {
            "seed_id": seed,
            "artist_mbid": _uuid(artist),
            "musicbrainz_genre_id": _uuid(100),
            "source_record_id": f"musicbrainz:artist:{_uuid(artist)}",
            "source_record_sha256": hashlib.sha256(_uuid(artist).encode()).hexdigest(),
            "source_evidence_ref": f"source:{seed}:{artist}",
        }
        for seed, artist in (("seed:a", 1), ("seed:a", 2), ("seed:a", 3), ("seed:b", 1))
    ]
    raw = b"".join(canonical_json(row) + b"\n" for row in claims)
    compressed = zstandard.ZstdCompressor().compress(raw)
    sha = hashlib.sha256(compressed).hexdigest()
    key = f"musicbrainz-direct-proper-genre-custody/sha256/{sha}.jsonl.zst"
    direct_store = directory / "direct"
    (direct_store / key).parent.mkdir(parents=True)
    (direct_store / key).write_bytes(compressed)
    direct = DirectProperGenreCustodyReceipt(
        source_seed_target_byte_sha256="a" * 64,
        source_seed_target_output_sha256="a" * 64,
        reconciliation_byte_sha256="b" * 64,
        reconciliation_output_sha256="b" * 64,
        claims_object_key=key,
        claims_object_sha256=sha,
        claims_object_byte_size=len(compressed),
        claims_uncompressed_sha256=hashlib.sha256(raw).hexdigest(),
        claim_count=4,
        seed_count=2,
        artist_mbid_count=3,
        source_record_sha256_count=3,
        output_sha256="0" * 64,
    )
    direct = direct.model_copy(update={"output_sha256": direct_receipt_sha256(direct)})
    direct_path = directory / "direct-receipt.json"
    direct_path.write_bytes(canonical_json(direct.model_dump(mode="json")) + b"\n")
    raw = b"".join(
        canonical_json({"artist_mbid": _uuid(artist), "canonical_name": label}) + b"\n"
        for artist, label in ((1, " Cafe\u0301\tBand\u202e "), (2, "Café Band"))
    )
    compressed = zstandard.ZstdCompressor().compress(raw)
    sha = hashlib.sha256(compressed).hexdigest()
    key = f"musicbrainz-direct-canonical-artist-name-custody/sha256/{sha}.jsonl.zst"
    name_store = directory / "names"
    (name_store / key).parent.mkdir(parents=True)
    (name_store / key).write_bytes(compressed)
    names = DirectCanonicalArtistNameCustodyReceipt(
        direct_custody_receipt_byte_sha256=sha256_file(direct_path)[0],
        direct_custody_receipt_output_sha256=direct.output_sha256,
        direct_claims_object_sha256=direct.claims_object_sha256,
        direct_artist_mbid_count=3,
        metadata_artifact_byte_sha256="c" * 64,
        metadata_artifact_output_sha256="c" * 64,
        metadata_database_sha256="d" * 64,
        metadata_database_bytes=1,
        metadata_source_archive_sha256="e" * 64,
        canonical_name_count=2,
        absent_direct_artist_mbid_count=1,
        names_object_key=key,
        names_object_sha256=sha,
        names_object_byte_size=len(compressed),
        names_uncompressed_sha256=hashlib.sha256(raw).hexdigest(),
        output_sha256="0" * 64,
    )
    names = names.model_copy(update={"output_sha256": name_receipt_sha256(names)})
    name_path = directory / "name-receipt.json"
    name_path.write_bytes(canonical_json(names.model_dump(mode="json")) + b"\n")
    return {
        "direct_receipt_path": direct_path,
        "direct_object_store": direct_store,
        "name_receipt_path": name_path,
        "name_object_store": name_store,
    }


class CandidateCatalogTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        cache = _ROOT / ".cache" / "test-tmp"
        cache.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=cache)
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.inputs = _fixture(self.directory)

    def test_exact_join_preserves_sources_and_homonyms_and_explicit_missing_names(self) -> None:
        output = self.directory / "catalog"
        receipt = build_local_musicbrainz_candidate_catalog(**self.inputs, output_directory=output)
        self.assertEqual(receipt.named_artist_count, 2)
        self.assertEqual(receipt.unresolved_artist_count, 1)
        quality = json.loads((output / "quality.json").read_bytes())
        self.assertEqual(quality["counts"]["display_collision_label_count"], 1)
        self.assertEqual(quality["counts"]["display_label_changed_count"], 1)
        preview = query_local_musicbrainz_candidate_genre(
            directory=output, seed_id="seed:a", limit=3
        )
        artists = preview["artists"]
        assert isinstance(artists, list)
        self.assertEqual(artists[0]["canonical_name"], " Cafe\u0301\tBand\u202e ")
        self.assertEqual(artists[0]["display_name"], "Café Band")
        self.assertEqual(artists[1]["display_name"], "Café Band")
        self.assertNotEqual(artists[0]["artist_mbid"], artists[1]["artist_mbid"])
        self.assertIsNone(artists[2]["canonical_name"])
        self.assertEqual(artists[2]["name_status"], "unresolved")
        self.assertEqual(artists[0]["observations"][0]["facet"], "artist_direct_proper_genre")
        self.assertFalse(preview["public_export_authorized"])
        repeated = build_local_musicbrainz_candidate_catalog(
            **self.inputs, output_directory=self.directory / "second"
        )
        self.assertEqual(receipt.logical_sha256, repeated.logical_sha256)
        self.assertEqual(receipt.output_sha256, repeated.output_sha256)

    def test_query_limits_unknown_seeds_and_generated_tampering(self) -> None:
        output = self.directory / "catalog"
        build_local_musicbrainz_candidate_catalog(**self.inputs, output_directory=output)
        preview = query_local_musicbrainz_candidate_genre(
            directory=output, seed_id="seed:a", limit=1
        )
        self.assertTrue(preview["truncated"])
        self.assertEqual(preview["artist_count"], 3)
        unknown = query_local_musicbrainz_candidate_genre(directory=output, seed_id="unknown")
        self.assertEqual(unknown["state"], "no_direct_observations")
        with self.assertRaises(CandidateCatalogError):
            query_local_musicbrainz_candidate_genre(directory=output, seed_id="seed:a", limit=101)
        with closing(sqlite3.connect(output / "catalog.sqlite")) as connection, connection:
            connection.execute("UPDATE artist SET canonical_name='fabricated'")
        with self.assertRaisesRegex(CandidateCatalogError, "database bytes"):
            verify_local_musicbrainz_candidate_catalog(directory=output)

    def test_mismatched_custody_and_public_or_symlink_outputs_fail_before_write(self) -> None:
        receipt_path = self.inputs["name_receipt_path"]
        raw = json.loads(receipt_path.read_bytes())
        raw["direct_custody_receipt_byte_sha256"] = "f" * 64
        receipt_path.write_text(json.dumps(raw))
        with self.assertRaisesRegex(CandidateCatalogError, "different direct cohort"):
            build_local_musicbrainz_candidate_catalog(
                **self.inputs, output_directory=self.directory / "fail"
            )
        self.assertFalse((self.directory / "fail").exists())
        with self.assertRaisesRegex(CandidateCatalogError, "inside project .cache"):
            build_local_musicbrainz_candidate_catalog(
                **self.inputs, output_directory=_ROOT / "dist" / "candidate"
            )
        escape = self.directory / "escape"
        escape.symlink_to(_ROOT / "dist", target_is_directory=True)
        with self.assertRaises(CandidateCatalogError):
            build_local_musicbrainz_candidate_catalog(
                **self.inputs, output_directory=escape / "candidate"
            )

    def test_display_normalization_preserves_semantics_and_abstains_on_control_only_names(
        self,
    ) -> None:
        self.assertEqual(normalize_display_name(" Björk & AC/DC "), "Björk & AC/DC")
        self.assertEqual(normalize_display_name("a\u200db"), "a\u200db")
        self.assertIsNone(normalize_display_name("\u202e\u200f\x00 \n"))


class NativeGenreLabelTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_uuid_labels_replay_offline_and_reject_projection_mutations(self) -> None:
        cache = _ROOT / ".cache" / "test-tmp"
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=cache) as temporary:
            directory = Path(temporary) / "labels"
            requests: list[str] = []

            def handle(request: httpx.Request) -> httpx.Response:
                requests.append(str(request.url))
                return httpx.Response(
                    200,
                    json={
                        "genre-count": 1,
                        "genre-offset": 0,
                        "genres": [{"id": _uuid(100), "name": "Native genre"}],
                    },
                )

            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
                client = MusicBrainzClient(http, user_agent="OpenNoise/0.1 (test@example.invalid)")
                labels = await acquire_native_musicbrainz_genre_labels(
                    client=client, directory=directory
                )
                self.assertEqual(labels["genre_count"], 1)
                genres = labels["genres"]
                assert isinstance(genres, list)
                self.assertEqual(genres[0]["musicbrainz_genre_id"], _uuid(100))
                with patch.object(
                    client, "fetch_genre_page_response", side_effect=AssertionError("network used")
                ):
                    replay = await acquire_native_musicbrainz_genre_labels(
                        client=client, directory=directory
                    )
                self.assertEqual(replay, labels)
            self.assertEqual(len(requests), 1)
            inputs = _fixture(Path(temporary))
            catalog = Path(temporary) / "catalog"
            build_local_musicbrainz_candidate_catalog(**inputs, output_directory=catalog)
            joined = build_local_musicbrainz_genre_label_join(
                catalog_directory=catalog,
                label_directory=directory,
                output_path=directory / "seed-join.json",
            )
            self.assertEqual(joined["resolved_seed_count"], 2)
            self.assertEqual(joined["abstained_seed_count"], 0)
            self.assertFalse(joined["historical_names_or_positions_read"])
            self.assertEqual(joined["membership_claims_added"], 0)
            genres[0]["canonical_name"] = "changed"
            labels["output_sha256"] = sha256_json(
                {k: v for k, v in labels.items() if k != "output_sha256"}
            )
            (directory / "labels.json").write_bytes(canonical_json(labels))
            with self.assertRaisesRegex(CandidateCatalogError, "names do not replay"):
                verify_native_musicbrainz_genre_labels(directory=directory)

    async def test_invalid_pagination_and_oversized_response_fail_without_label_artifact(
        self,
    ) -> None:
        cache = _ROOT / ".cache" / "test-tmp"
        cache.mkdir(parents=True, exist_ok=True)
        for payload in (
            {"genre-count": 1, "genre-offset": 1, "genres": [{"id": _uuid(100), "name": "x"}]},
            {"genre-count": 1, "genre-offset": 0, "genres": []},
        ):
            with tempfile.TemporaryDirectory(dir=cache) as temporary:
                directory = Path(temporary) / "labels"
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(
                        lambda _, current=payload: httpx.Response(200, json=current)
                    )
                ) as http:
                    client = MusicBrainzClient(
                        http, user_agent="OpenNoise/0.1 (test@example.invalid)"
                    )
                    with self.assertRaises(CandidateCatalogError):
                        await acquire_native_musicbrainz_genre_labels(
                            client=client, directory=directory
                        )
                self.assertFalse((directory / "labels.json").exists())
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    content=b" " * (128 * 1024 + 1),
                    headers={"content-type": "application/json"},
                )
            )
        ) as http:
            client = MusicBrainzClient(http, user_agent="OpenNoise/0.1 (test@example.invalid)")
            with self.assertRaisesRegex(ValueError, "byte bound"):
                await client.fetch_genre_page_response(offset=0)
