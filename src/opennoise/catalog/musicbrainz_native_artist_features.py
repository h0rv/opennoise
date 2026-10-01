"""Independent native artist names, genres and tags for exact release-credit UUIDs."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import time
from contextlib import closing
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, Final
from uuid import UUID

import httpx
from pydantic import TypeAdapter

from opennoise.catalog.musicbrainz_candidate import (
    CandidateCatalogError,
    require_local_candidate_destination,
    verify_local_musicbrainz_candidate_catalog,
)
from opennoise.catalog.musicbrainz_open_features import _copy_bytes
from opennoise.catalog.musicbrainz_release_group_features import (
    iter_native_release_group_feature_rows,
    verify_native_release_group_features,
)
from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.sources.musicbrainz import MusicBrainzArtist

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

_MAX_ARTISTS: Final = 100
_MAX_BYTES: Final = 2 * 1024 * 1024
_POLICY: Final = {
    "revision": "local-musicbrainz-native-artist-features-v1",
    "scope": "local_noncommercial_research",
    "source_role": "native_artist_lookup_metadata",
    "identity_join": "exact_musicbrainz_artist_uuid_only",
    "public_export_authorized": False,
    "historical_inputs_used": False,
    "audio_inputs_used": False,
    "fixed_seed_vocabulary_used": False,
    "artist_genres_inferred_from_release_genres": False,
    "core_metadata_license": "CC0-1.0",
    "tags_and_genre_associations_license": "CC-BY-NC-SA-3.0",
    "attribution": "MusicBrainz contributors; https://musicbrainz.org/",
}


def _url(identity: str) -> str:
    if str(UUID(identity)) != identity:
        raise CandidateCatalogError("native artist feature request requires a canonical UUID")
    return str(
        httpx.URL(
            f"https://musicbrainz.org/ws/2/artist/{identity}",
            params={"fmt": "json", "inc": "genres+tags"},
        )
    )


def _selection(catalog_directory: Path, release_directory: Path) -> dict[str, object]:
    catalog = verify_local_musicbrainz_candidate_catalog(directory=catalog_directory)
    release_receipt = verify_native_release_group_features(directory=release_directory)
    database = catalog_directory / "catalog.sqlite"
    with closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        existing = {str(row[0]) for row in connection.execute("SELECT artist_mbid FROM artist")}
    credited = {
        str(identity)
        for row in iter_native_release_group_feature_rows(directory=release_directory)
        for identity in TypeAdapter(list[str]).validate_python(row["artist_mbids"])
    }
    selected = sorted(credited - existing)
    if not 1 <= len(selected) <= _MAX_ARTISTS:
        raise CandidateCatalogError(
            "new native credited-artist acquisition must stay within 100 UUIDs"
        )
    return {
        "catalog_output_sha256": catalog.output_sha256,
        "release_features_output_sha256": release_receipt["output_sha256"],
        "selection": "exact_native_release_group_credit_uuid_difference_from_direct_catalog",
        "artist_ids": selected,
        "source_credited_artist_count": len(credited),
    }


async def _fetch(
    client: httpx.AsyncClient, url: str, user_agent: str
) -> tuple[int, bytes, str | None]:
    async with client.stream(
        "GET", url, headers={"User-Agent": user_agent, "Accept": "application/json"}
    ) as response:
        if response.status_code not in {200, 301, 302, 404}:
            response.raise_for_status()
        data = bytearray()
        async for chunk in response.aiter_bytes():
            data.extend(chunk)
            if len(data) > _MAX_BYTES:
                raise CandidateCatalogError(
                    "native artist feature response exceeds metadata byte bound"
                )
        if (
            response.status_code == HTTPStatus.OK
            and response.headers.get("content-type", "").partition(";")[0] != "application/json"
        ):
            raise CandidateCatalogError("native artist feature response must be JSON metadata")
        location = response.headers.get("location")
        return response.status_code, bytes(data), str(location) if location is not None else None


async def acquire_native_artist_features(  # noqa: PLR0913 - exact independent source inputs.
    *,
    catalog_directory: Path,
    release_directory: Path,
    directory: Path,
    license_path: Path,
    client: httpx.AsyncClient,
    user_agent: str,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, object]:
    """Acquire at most one hundred exact native artist lookups, rate-limited and resumable."""
    require_local_candidate_destination(directory)
    if (directory / "receipt.json").exists():
        return verify_native_artist_features(directory=directory)
    selection = _selection(catalog_directory, release_directory)
    ids = TypeAdapter(list[str]).validate_python(selection["artist_ids"])
    directory.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 - bounded metadata cache.
    (directory / "pages").mkdir(exist_ok=True)
    _copy_bytes(license_path, directory / "source-license.html")
    documents: list[dict[str, object]] = []
    next_request_at = 0.0
    for index, identity in enumerate(ids):
        path = directory / "pages" / f"{identity}.json"
        receipt_path = path.with_suffix(".receipt.json")
        if path.exists() != receipt_path.exists() or path.is_symlink() or receipt_path.is_symlink():
            raise CandidateCatalogError("native artist lookup has an incomplete prior write")
        if not path.exists():
            url = _url(identity)
            for attempt in range(3):
                await asyncio.sleep(max(0.0, next_request_at - time.monotonic()))
                next_request_at = time.monotonic() + 1.1
                try:
                    status, raw, location = await _fetch(client, url, user_agent)
                    break
                except (httpx.HTTPStatusError, httpx.TransportError):
                    if attempt == 2:  # noqa: PLR2004 - last bounded attempt.
                        raise
                    next_request_at = time.monotonic() + 3 * (attempt + 1)
            else:
                raise CandidateCatalogError("native artist lookup exhausted its bounded attempts")
            binding = {
                "artist_mbid": identity,
                "path": f"pages/{identity}.json",
                "request_url": url,
                "response_sha256": hashlib.sha256(raw).hexdigest(),
                "byte_size": len(raw),
                "http_status": status,
                "redirect_location": location,
                "observed_at": datetime.now(UTC).isoformat(),
            }
            path.write_bytes(raw)
            receipt_path.write_bytes(canonical_json(binding) + b"\n")
        binding = TypeAdapter(dict[str, object]).validate_json(receipt_path.read_bytes())
        documents.append(binding)
        if progress is not None:
            progress(index + 1, len(ids))
    source = {
        **_POLICY,
        **selection,
        "documents": documents,
        "license_page_sha256": sha256_file(directory / "source-license.html")[0],
    }
    (directory / "source.json").write_bytes(canonical_json(source) + b"\n")
    return build_native_artist_feature_projection(directory=directory)


def iter_native_artist_feature_rows(  # noqa: C901, PLR0912 - complete independent source replay.
    *, directory: Path
) -> Iterator[dict[str, object]]:
    """Preserve native artist genres and tags without borrowing any release observation."""
    source = TypeAdapter(dict[str, object]).validate_json((directory / "source.json").read_bytes())
    if any(source.get(key) != value for key, value in _POLICY.items()):
        raise CandidateCatalogError(
            "native artist feature source role or field-license scope differs"
        )
    license_raw = (directory / "source-license.html").read_bytes()
    if hashlib.sha256(license_raw).hexdigest() != source.get("license_page_sha256"):
        raise CandidateCatalogError("native artist feature license capture differs")
    ids = TypeAdapter(list[str]).validate_python(source["artist_ids"])
    documents = TypeAdapter(list[dict[str, object]]).validate_python(source["documents"])
    if not 1 <= len(ids) <= _MAX_ARTISTS or len(ids) != len(set(ids)):
        raise CandidateCatalogError(
            "native artist feature identities exceed the unique bounded cohort"
        )
    if [binding.get("artist_mbid") for binding in documents] != ids:
        raise CandidateCatalogError(
            "native artist lookup documents do not cover the exact selected IDs"
        )
    for binding in documents:
        identity = str(binding["artist_mbid"])
        relative = f"pages/{identity}.json"
        if binding.get("path") != relative or binding.get("request_url") != _url(identity):
            raise CandidateCatalogError(
                "native artist feature document has a different exact request"
            )
        path = directory / relative
        if path.is_symlink() or path.parent.is_symlink():
            raise CandidateCatalogError("native artist feature source must not be symbolic")
        if (
            sha256_file(path) != (binding["response_sha256"], binding["byte_size"])
            or path.stat().st_size > _MAX_BYTES
        ):
            raise CandidateCatalogError("native artist feature source bytes differ")
        if json.loads(path.with_suffix(".receipt.json").read_bytes()) != binding:
            raise CandidateCatalogError(
                "native artist feature document and complete receipt differ"
            )
        status = binding.get("http_status")
        if not isinstance(status, int) or isinstance(status, bool):
            raise CandidateCatalogError("native artist lookup status must be an integer")
        if status in {301, 302, 404}:
            continue
        if status != HTTPStatus.OK:
            raise CandidateCatalogError("native artist feature document has an unsupported status")
        raw = TypeAdapter(dict[str, object]).validate_json(path.read_bytes())
        artist = MusicBrainzArtist.model_validate_json(canonical_json({**raw, "tags": []}))
        if str(artist.id) != identity:
            raise CandidateCatalogError("native artist lookup must not substitute a different UUID")
        tags = TypeAdapter(list[dict[str, object]]).validate_python(raw.get("tags", []))
        for tag in tags:
            name, count = tag.get("name"), tag.get("count")
            if (
                not isinstance(name, str)
                or not name
                or (count is not None and (not isinstance(count, int) or isinstance(count, bool)))
            ):
                raise CandidateCatalogError(
                    "native artist tag must preserve its label and integer vote"
                )
        yield {
            "artist_mbid": identity,
            "name": artist.name,
            "tags": [{"name": tag["name"], "count": tag.get("count")} for tag in tags],
            "genres": [genre.model_dump(mode="json") for genre in artist.genres],
            "country": artist.country,
            "type": artist.type,
            "area": artist.area.model_dump(mode="json") if artist.area else None,
            "begin_area": artist.begin_area.model_dump(mode="json") if artist.begin_area else None,
            "life_span": artist.life_span.model_dump(mode="json") if artist.life_span else None,
            "source_document": relative,
            "source_response_sha256": binding["response_sha256"],
            "source_role": _POLICY["source_role"],
            "native_artist_genres_status": "observed_native_artist_record",
        }


def _manifest(directory: Path, rows: list[dict[str, object]]) -> dict[str, object]:
    source = json.loads((directory / "source.json").read_bytes())
    sha, size = sha256_file(directory / "artist-features.jsonl")
    return {
        **_POLICY,
        "source_byte_sha256": sha256_file(directory / "source.json")[0],
        "artist_count": len(rows),
        "artist_requested_count": len(source["artist_ids"]),
        "missing_or_redirected_artist_count": len(source["artist_ids"]) - len(rows),
        "positive_artist_genre_observation_count": sum(
            sum(
                isinstance(g["count"], int) and int(g["count"]) > 0
                for g in TypeAdapter(list[dict[str, object]]).validate_python(row["genres"])
            )
            for row in rows
        ),
        "positive_artist_tag_observation_count": sum(
            sum(
                isinstance(g["count"], int) and int(g["count"]) > 0
                for g in TypeAdapter(list[dict[str, object]]).validate_python(row["tags"])
            )
            for row in rows
        ),
        "resolved_artist_names": {str(row["artist_mbid"]): row["name"] for row in rows},
        "rows_sha256": sha,
        "rows_byte_size": size,
    }


def build_native_artist_feature_projection(*, directory: Path) -> dict[str, object]:
    """Seal separately custodied artist source facts, preserving all existing model inputs."""
    require_local_candidate_destination(directory)
    if (directory / "receipt.json").exists():
        return verify_native_artist_features(directory=directory)
    rows = list(iter_native_artist_feature_rows(directory=directory))
    (directory / "artist-features.jsonl").write_bytes(
        b"".join(canonical_json(row) + b"\n" for row in rows)
    )
    receipt = _manifest(directory, rows)
    receipt["output_sha256"] = sha256_json(receipt)
    (directory / "receipt.json").write_bytes(canonical_json(receipt) + b"\n")
    return verify_native_artist_features(directory=directory)


def verify_native_artist_features(*, directory: Path) -> dict[str, object]:
    """Recompute exact native artist facts and require identical field roles and artifact bytes."""
    rows = list(iter_native_artist_feature_rows(directory=directory))
    if (directory / "artist-features.jsonl").read_bytes() != b"".join(
        canonical_json(row) + b"\n" for row in rows
    ):
        raise CandidateCatalogError(
            "native artist feature projection differs from exact independent source bytes"
        )
    receipt = _manifest(directory, rows)
    receipt["output_sha256"] = sha256_json(receipt)
    if receipt != json.loads((directory / "receipt.json").read_bytes()):
        raise CandidateCatalogError("native artist feature receipt or source role differs")
    return receipt
