"""Retain richer native artist metadata independently of any seed vocabulary.

Tags are source observations with votes, not fixed genre memberships or inferred
labels. Core metadata is CC0; tag and genre associations are CC-BY-NC-SA-3.0.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import sqlite3
import time
from collections import Counter
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

import httpx
from pydantic import TypeAdapter

from opennoise.catalog.musicbrainz_artist_names import (
    _fetch_page,
    _page_rows,
    _request_url,
    verify_artist_name_enrichment,
)
from opennoise.catalog.musicbrainz_candidate import (
    CandidateCatalogError,
    require_local_candidate_destination,
    verify_local_musicbrainz_candidate_catalog,
)
from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.sources.musicbrainz import MusicBrainzArtist

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

_MAX_NEW_ARTISTS: Final = 5_000
_PER_SEED: Final = 32
_BATCH_SIZE: Final = 100
_LICENSE_URL: Final = "https://musicbrainz.org/doc/About/Data_License"
_SENTINELS: Final = (
    "f22942a1-6f70-4f48-866e-238cb2308fbd",  # Aphex Twin
    "3bcff06f-675a-451f-9075-99e8657047e8",  # Four Tet
    "69158f97-4c07-4c4e-baf8-4e4ab1ed666e",  # Boards of Canada
    "410c9baf-5469-44f6-9852-826524b80c61",  # Autechre
    "9ddce51c-2b75-4b3e-ac8c-1db09e7c89c6",  # Burial
    "4d86ad4e-28d8-4e9f-8cf4-735c57060fdc",  # Squarepusher
    "69d9c5ba-7bba-4cb7-ab32-8ccc48ad4f97",  # Floating Points
    "735e3514-a8ae-401f-af3b-6300df1b8d2c",  # Caribou
    "ff95eb47-41c4-4f7f-a104-cdc30f02e872",  # Brian Eno
    "0b0c25f4-f31c-46a5-a4fb-ccbf53d663bd",  # Jon Hopkins
)
_POLICY: Final = {
    "revision": "local-musicbrainz-open-artist-features-v1",
    "scope": "local_noncommercial_research",
    "public_export_authorized": False,
    "historical_inputs_used": False,
    "audio_inputs_used": False,
    "fixed_seed_vocabulary_used_for_tag_projection": False,
    "membership_claims_added": 0,
    "identity_join": "exact_musicbrainz_artist_uuid_only",
    "source_role": "native_artist_search_metadata",
    "core_metadata_license": "CC0-1.0",
    "tags_and_genre_associations_license": "CC-BY-NC-SA-3.0",
    "attribution": "MusicBrainz contributors; https://musicbrainz.org/",
    "derived_output_license_obligations": (
        "Attribution, NonCommercial, ShareAlike; no public export authorized"
    ),
}


def _cohort(catalog_directory: Path, limit: int) -> list[str]:
    if isinstance(limit, bool) or not len(_SENTINELS) <= limit <= _MAX_NEW_ARTISTS:
        raise CandidateCatalogError("new feature cohort must contain between 10 and 5,000 artists")
    database = catalog_directory / "catalog.sqlite"
    by_seed: dict[str, list[str]] = {}
    with closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        native_ids = {str(row[0]) for row in connection.execute("SELECT artist_mbid FROM artist")}
        if not set(_SENTINELS) <= native_ids:
            raise CandidateCatalogError("feature sentinel UUIDs are absent from the source cohort")
        for seed, artist in connection.execute(
            "WITH degree AS (SELECT artist_mbid,COUNT(*) support FROM seed_artist "
            "GROUP BY artist_mbid),"
            "ranked AS (SELECT s.seed_id,s.artist_mbid,ROW_NUMBER() OVER (PARTITION BY s.seed_id "
            "ORDER BY d.support DESC,s.artist_mbid) rank FROM seed_artist s "
            "JOIN artist a USING(artist_mbid) JOIN degree d USING(artist_mbid) "
            "WHERE a.canonical_name IS NOT NULL) SELECT seed_id,artist_mbid FROM ranked "
            "WHERE rank<=? ORDER BY seed_id,rank",
            (_PER_SEED,),
        ):
            by_seed.setdefault(str(seed), []).append(str(artist))
    selected = set(_SENTINELS)
    for rank in range(_PER_SEED):
        for seed in sorted(by_seed):
            if rank < len(by_seed[seed]):
                selected.add(by_seed[seed][rank])
            if len(selected) >= limit:
                return sorted(selected)
    return sorted(selected)


def _copy_bytes(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if source.read_bytes() != destination.read_bytes():
            raise CandidateCatalogError("retained open feature metadata cache is byte-mutated")
    else:
        if destination.is_symlink():
            raise CandidateCatalogError("retained feature metadata must not follow a symlink")
        shutil.copyfile(source, destination)


async def acquire_open_artist_features(  # noqa: C901, PLR0912, PLR0913, PLR0915 - bounded source workflow.
    *,
    catalog_directory: Path,
    name_directory: Path,
    license_path: Path,
    directory: Path,
    client: httpx.AsyncClient,
    user_agent: str,
    new_artist_limit: int = _MAX_NEW_ARTISTS,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, object]:
    """Reuse verified source pages, then acquire at most fifty additional exact-ID batches."""
    require_local_candidate_destination(directory)
    catalog = verify_local_musicbrainz_candidate_catalog(directory=catalog_directory)
    names = verify_artist_name_enrichment(
        catalog_directory=catalog_directory, directory=name_directory
    )
    if (directory / "receipt.json").exists():
        return verify_open_artist_features(directory=directory)
    identities = _cohort(catalog_directory, new_artist_limit)
    selection = {
        "catalog_output_sha256": catalog.output_sha256,
        "name_overlay_output_sha256": names["output_sha256"],
        "new_artist_limit": new_artist_limit,
        "new_artist_ids": identities,
        "selection": "native_seed_round_robin_by_support_then_uuid_plus_explicit_sentinels",
        "sentinel_artist_ids": list(_SENTINELS),
    }
    directory.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 - bounded metadata cache writes.
    selection_path = directory / "selection.json"
    selection_raw = canonical_json(selection) + b"\n"
    if selection_path.exists() and selection_path.read_bytes() != selection_raw:
        raise CandidateCatalogError("feature acquisition selection differs from retained cohort")
    selection_path.write_bytes(selection_raw)
    _copy_bytes(license_path, directory / "source-license.html")
    pages = TypeAdapter(list[dict[str, object]]).validate_python(names["pages"])
    for index, _ in enumerate(pages):
        for suffix in (".json", "-receipt.json"):
            _copy_bytes(
                name_directory / f"batch-{index:04d}{suffix}",
                directory / "retained-pages" / f"batch-{index:04d}{suffix}",
            )
    documents: list[dict[str, object]] = []
    for index, page in enumerate(pages):
        ids = TypeAdapter(list[str]).validate_python(page["artist_mbids"])
        _page_rows(directory / "retained-pages", index, ids)
        documents.append({**page, "path": f"retained-pages/batch-{index:04d}.json"})
    target = directory / "new-pages"
    target.mkdir(exist_ok=True)
    next_request_at = 0.0
    for start in range(0, len(identities), _BATCH_SIZE):
        index = start // _BATCH_SIZE
        ids = identities[start : start + _BATCH_SIZE]
        path = target / f"batch-{index:04d}.json"
        binding_path = target / f"batch-{index:04d}-receipt.json"
        if path.exists() != binding_path.exists() or path.is_symlink() or binding_path.is_symlink():
            raise CandidateCatalogError(
                "new feature batch has an incomplete or symbolic prior write"
            )
        if not path.exists():
            url = _request_url(ids)
            for attempt in range(3):
                await asyncio.sleep(max(0.0, next_request_at - time.monotonic()))
                next_request_at = time.monotonic() + 1.1
                try:
                    raw = await _fetch_page(client, url, user_agent)
                    break
                except (httpx.HTTPStatusError, httpx.TransportError):
                    if attempt == 2:  # noqa: PLR2004 - last bounded attempt.
                        raise
                    next_request_at = time.monotonic() + 3.0 * (attempt + 1)
            else:
                raise CandidateCatalogError("new feature metadata exhausted bounded retries")
            binding = {
                "batch_index": index,
                "artist_mbids": ids,
                "request_url": url,
                "response_sha256": hashlib.sha256(raw).hexdigest(),
                "byte_size": len(raw),
                "http_status": 200,
                "observed_at": datetime.now(UTC).isoformat(),
            }
            path.write_bytes(raw)
            binding_path.write_bytes(canonical_json(binding) + b"\n")
        _page_rows(target, index, ids)
        binding = TypeAdapter(dict[str, object]).validate_json(binding_path.read_bytes())
        documents.append({**binding, "path": f"new-pages/batch-{index:04d}.json"})
        if progress is not None:
            progress(min(start + _BATCH_SIZE, len(identities)), len(identities))
    source = {
        **_POLICY,
        **selection,
        "documents": documents,
        "license_url": _LICENSE_URL,
        "license_page_sha256": sha256_file(directory / "source-license.html")[0],
    }
    (directory / "source.json").write_bytes(canonical_json(source) + b"\n")
    return build_open_artist_feature_projection(directory=directory)


def iter_open_artist_feature_rows(  # noqa: C901, PLR0912 - complete native source replay boundary.
    *, directory: Path
) -> Iterator[dict[str, object]]:
    """Replay native artist facts directly from retained exact-ID official response bytes."""
    source = TypeAdapter(dict[str, object]).validate_json((directory / "source.json").read_bytes())
    if any(source.get(key) != value for key, value in _POLICY.items()):
        raise CandidateCatalogError("open feature source-role or license declarations differ")
    if source.get("license_url") != _LICENSE_URL:
        raise CandidateCatalogError("native source license must retain its exact official URL")
    license_raw = (directory / "source-license.html").read_bytes()
    if hashlib.sha256(license_raw).hexdigest() != source.get("license_page_sha256"):
        raise CandidateCatalogError("retained official source license bytes differ")
    if b"Attribution-NonCommercial-ShareAlike 3.0" not in license_raw or b"CC0" not in license_raw:
        raise CandidateCatalogError("official license capture does not establish both field scopes")
    documents = TypeAdapter(list[dict[str, object]]).validate_python(source["documents"])
    if not 1 <= len(documents) <= 450:  # noqa: PLR2004 - 400 retained +50 new pages maximum.
        raise CandidateCatalogError("feature documents exceed bounded source pages")
    seen: set[str] = set()
    for binding in documents:
        relative = Path(str(binding["path"]))
        if (
            relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 2  # noqa: PLR2004 - category/document path only.
        ):
            raise CandidateCatalogError("feature source page path is not a safe relative document")
        path = directory / relative
        ids = TypeAdapter(list[str]).validate_python(binding["artist_mbids"])
        index = binding["batch_index"]
        if not isinstance(index, int) or isinstance(index, bool):
            raise CandidateCatalogError("feature source page index must be an integer")
        if (
            relative.parts[0] not in {"retained-pages", "new-pages"}
            or relative.name != f"batch-{index:04d}.json"
        ):
            raise CandidateCatalogError(
                "feature document must be the exact batch verified by its receipt"
            )
        if path.is_symlink() or path.parent.is_symlink():
            raise CandidateCatalogError("feature source documents must not follow symlinks")
        companion = TypeAdapter(dict[str, object]).validate_json(
            path.with_name(f"batch-{index:04d}-receipt.json").read_bytes()
        )
        if companion != {key: value for key, value in binding.items() if key != "path"}:
            raise CandidateCatalogError("feature document differs from its complete page receipt")
        _page_rows(path.parent, index, ids)
        raw = path.read_bytes()
        if (
            hashlib.sha256(raw).hexdigest() != binding["response_sha256"]
            or len(raw) != binding["byte_size"]
        ):
            raise CandidateCatalogError("feature source bytes differ from its document binding")
        page = TypeAdapter(dict[str, object]).validate_json(raw)
        for row in TypeAdapter(list[dict[str, object]]).validate_python(page["artists"]):
            native_tags = TypeAdapter(list[dict[str, object]]).validate_python(row.get("tags", []))
            for tag in native_tags:
                name, count = tag.get("name"), tag.get("count")
                if (
                    not isinstance(name, str)
                    or not name
                    or len(name) > 4096  # noqa: PLR2004 - source label bound.
                    or (
                        count is not None
                        and (not isinstance(count, int) or isinstance(count, bool))
                    )
                ):
                    raise CandidateCatalogError(
                        "native tag must preserve a bounded label and integer vote"
                    )
            artist = MusicBrainzArtist.model_validate_json(canonical_json({**row, "tags": []}))
            identity = str(artist.id)
            if identity in seen:
                raise CandidateCatalogError("open artist metadata repeats an exact artist identity")
            seen.add(identity)
            yield {
                "artist_mbid": identity,
                "name": artist.name,
                "tags": [{"name": tag["name"], "count": tag.get("count")} for tag in native_tags],
                "genres": [genre.model_dump(mode="json") for genre in artist.genres],
                "country": artist.country,
                "type": artist.type,
                "area": artist.area.model_dump(mode="json") if artist.area else None,
                "begin_area": artist.begin_area.model_dump(mode="json")
                if artist.begin_area
                else None,
                "life_span": artist.life_span.model_dump(mode="json") if artist.life_span else None,
                "source_document": str(relative),
                "source_response_sha256": binding["response_sha256"],
                "source_role": "native_artist_search_metadata",
            }


def _manifest(directory: Path, rows: list[dict[str, object]]) -> dict[str, object]:
    tags: Counter[str] = Counter()
    positive = tagged = 0
    for row in rows:
        native = TypeAdapter(list[dict[str, object]]).validate_python(row["tags"])
        positive_rows = [
            tag for tag in native if isinstance(tag["count"], int) and int(tag["count"]) > 0
        ]
        tagged += bool(positive_rows)
        positive += len(positive_rows)
        tags.update(str(tag["name"]) for tag in positive_rows)
    source = TypeAdapter(dict[str, object]).validate_json((directory / "source.json").read_bytes())
    return {
        **_POLICY,
        "source_byte_sha256": sha256_file(directory / "source.json")[0],
        "catalog_output_sha256": source["catalog_output_sha256"],
        "artist_count": len(rows),
        "positive_tagged_artist_count": tagged,
        "positive_tag_observation_count": positive,
        "distinct_positive_raw_tag_count": len(tags),
        "artist_area_count": sum(row["area"] is not None for row in rows),
        "artist_life_span_count": sum(
            isinstance(row["life_span"], dict)
            and any(row["life_span"].get(key) is not None for key in ("begin", "end"))
            for row in rows
        ),
        "source_document_count": len(
            TypeAdapter(list[object]).validate_python(source["documents"])
        ),
        "new_artist_requested_count": len(
            TypeAdapter(list[str]).validate_python(source["new_artist_ids"])
        ),
        "sentinel_artist_ids": list(_SENTINELS),
        "sentinels_resolved": {
            identity: next((row["name"] for row in rows if row["artist_mbid"] == identity), None)
            for identity in _SENTINELS
        },
        "rows_sha256": sha256_file(directory / "artist-features.jsonl")[0],
        "rows_byte_size": sha256_file(directory / "artist-features.jsonl")[1],
    }


def build_open_artist_feature_projection(*, directory: Path) -> dict[str, object]:
    """Seal native sparse metadata rows without mapping tags to a fixed genre list."""
    require_local_candidate_destination(directory)
    if (directory / "receipt.json").exists():
        return verify_open_artist_features(directory=directory)
    rows = sorted(
        iter_open_artist_feature_rows(directory=directory), key=lambda row: str(row["artist_mbid"])
    )
    (directory / "artist-features.jsonl").write_bytes(
        b"".join(canonical_json(row) + b"\n" for row in rows)
    )
    receipt = _manifest(directory, rows)
    receipt["output_sha256"] = sha256_json(receipt)
    (directory / "receipt.json").write_bytes(canonical_json(receipt) + b"\n")
    return verify_open_artist_features(directory=directory)


def verify_open_artist_features(*, directory: Path) -> dict[str, object]:
    """Require complete native metadata and exact byte/role replay with no HTTP client."""
    rows = sorted(
        iter_open_artist_feature_rows(directory=directory), key=lambda row: str(row["artist_mbid"])
    )
    expected = b"".join(canonical_json(row) + b"\n" for row in rows)
    if (directory / "artist-features.jsonl").read_bytes() != expected:
        raise CandidateCatalogError(
            "rich artist metadata rows do not replay from native source bytes"
        )
    receipt = _manifest(directory, rows)
    receipt["output_sha256"] = sha256_json(receipt)
    if receipt != json.loads((directory / "receipt.json").read_bytes()):
        raise CandidateCatalogError(
            "rich artist feature receipt or source-role declarations differ"
        )
    return receipt
