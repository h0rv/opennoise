"""Bounded official exact-MBID names for unresolved local catalog identities.

Search response tags, aliases, credits and scores never enter the projection.
Names are current display metadata, not a correction of historical source facts.
"""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import time
from contextlib import closing
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from opennoise.catalog.musicbrainz_candidate import (
    CandidateCatalogError,
    normalize_display_name,
    require_local_candidate_destination,
    verify_local_musicbrainz_candidate_catalog,
)
from opennoise.common import canonical_json, sha256_json

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from opennoise.catalog.musicbrainz_candidate import CandidateCatalogReceipt

_BATCH_SIZE: Final = 100
_MAX_ARTISTS: Final = 40_000
_MAX_PAGE_BYTES: Final = 2 * 1024 * 1024
_MAX_BINDING_BYTES: Final = 64 * 1024
_MAX_ARTIFACT_BYTES: Final = 96 * 1024 * 1024
_RETRIES: Final = 3
_BASE_URL: Final = "https://musicbrainz.org/ws/2/artist"
_DECLARATIONS: Final = {
    "revision": "local-musicbrainz-missing-artist-names-v1",
    "scope": "local_research_only",
    "public_export_authorized": False,
    "membership_claims_added": 0,
    "historical_inputs_used": False,
    "identity_join": "exact_musicbrainz_artist_uuid_only",
    "name_source": "official_musicbrainz_artist_search_current_metadata",
    "source_fields_projected": ["id", "name"],
    "tags_aliases_credits_scores_projected": False,
    "license": "CC0-1.0",
    "license_scope": "artist_identity_and_name_core_metadata_only",
    "selection": "unresolved_artists_by_direct_seed_support_descending_then_uuid",
}


class _Name(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    id: UUID
    name: str = Field(min_length=1, max_length=4096)


class _SearchPage(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    count: int = Field(ge=0, le=_BATCH_SIZE)
    offset: int = Field(ge=0, le=0)
    artists: tuple[_Name, ...] = Field(max_length=_BATCH_SIZE)


def _request_url(identities: list[str]) -> str:
    if not 1 <= len(identities) <= _BATCH_SIZE or len(set(identities)) != len(identities):
        raise CandidateCatalogError("artist name batch has invalid identity cardinality")
    if any(str(UUID(identity)) != identity for identity in identities):
        raise CandidateCatalogError("artist name request requires canonical UUIDs")
    return str(
        httpx.URL(
            _BASE_URL,
            params={"query": "arid:(" + " OR ".join(identities) + ")", "fmt": "json", "limit": 100},
        )
    )


def _cohort(
    catalog_directory: Path, limit: int
) -> tuple[CandidateCatalogReceipt, list[str], dict[str, int]]:
    if isinstance(limit, bool) or not 1 <= limit <= _MAX_ARTISTS:
        raise CandidateCatalogError("artist name cohort must stay within 40,000 identities")
    catalog = verify_local_musicbrainz_candidate_catalog(directory=catalog_directory)
    database = catalog_directory / "catalog.sqlite"
    with closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        rows = connection.execute(
            "SELECT a.artist_mbid,COUNT(s.seed_id) FROM artist a "
            "JOIN seed_artist s USING(artist_mbid) WHERE a.canonical_name IS NULL "
            "GROUP BY a.artist_mbid ORDER BY COUNT(s.seed_id) DESC,a.artist_mbid LIMIT ?",
            (limit,),
        ).fetchall()
    return catalog, [str(row[0]) for row in rows], {str(row[0]): int(row[1]) for row in rows}


def _page_rows(directory: Path, index: int, identities: list[str]) -> list[dict[str, object]]:
    path = directory / f"batch-{index:04d}.json"
    receipt_path = directory / f"batch-{index:04d}-receipt.json"
    if path.is_symlink() or receipt_path.is_symlink():
        raise CandidateCatalogError("artist search cache pages must not be symlinks")
    if receipt_path.stat().st_size > _MAX_BINDING_BYTES:
        raise CandidateCatalogError("artist search page receipt exceeds byte bound")
    binding = TypeAdapter(dict[str, object]).validate_json(receipt_path.read_bytes())
    if path.stat().st_size > _MAX_PAGE_BYTES:
        raise CandidateCatalogError("artist search metadata exceeds byte bound")
    raw = path.read_bytes()
    expected = {
        "batch_index": index,
        "artist_mbids": identities,
        "request_url": _request_url(identities),
        "response_sha256": hashlib.sha256(raw).hexdigest(),
        "byte_size": len(raw),
        "http_status": 200,
    }
    if any(binding.get(key) != value for key, value in expected.items()):
        raise CandidateCatalogError("artist name batch bytes, URL or exact-ID cohort do not replay")
    page = _SearchPage.model_validate_json(raw)
    returned = {str(artist.id): artist.name for artist in page.artists}
    if len(returned) != len(page.artists) or len(returned) != page.count:
        raise CandidateCatalogError("artist search returned duplicate or incomplete identities")
    if not returned.keys() <= set(identities):
        raise CandidateCatalogError("artist search returned an identity outside the exact-ID query")
    rows: list[dict[str, object]] = []
    for identity in identities:
        name = returned.get(identity)
        display = normalize_display_name(name) if name is not None else None
        rows.append(
            {
                "artist_mbid": identity,
                "canonical_name": name,
                "display_name": display,
                "status": (
                    "missing_official_identity"
                    if name is None
                    else "unusable_display"
                    if display is None
                    else "exact"
                ),
                "source_response_sha256": binding["response_sha256"],
                "source_batch_index": index,
            }
        )
    return rows


def _projection(*, catalog_directory: Path, directory: Path, limit: int) -> dict[str, object]:
    catalog, identities, support = _cohort(catalog_directory, limit)
    rows: list[dict[str, object]] = []
    pages: list[dict[str, object]] = []
    for start in range(0, len(identities), _BATCH_SIZE):
        index = start // _BATCH_SIZE
        rows.extend(_page_rows(directory, index, identities[start : start + _BATCH_SIZE]))
        pages.append(
            TypeAdapter(dict[str, object]).validate_json(
                (directory / f"batch-{index:04d}-receipt.json").read_bytes()
            )
        )
    resolved = [str(row["artist_mbid"]) for row in rows if row["canonical_name"] is not None]
    return {
        **_DECLARATIONS,
        "catalog_output_sha256": catalog.output_sha256,
        "catalog_database_sha256": catalog.database_sha256,
        "catalog_direct_object_sha256": catalog.direct_object_sha256,
        "selection_limit": limit,
        "selected_artist_count": len(identities),
        "batch_count": len(pages),
        "maximum_http_attempts": len(pages) * _RETRIES,
        "resolved_artist_count": len(resolved),
        "missing_official_identity_count": sum(
            row["status"] == "missing_official_identity" for row in rows
        ),
        "unusable_display_count": sum(row["status"] == "unusable_display" for row in rows),
        "newly_named_direct_pair_count": sum(support[identity] for identity in resolved),
        "combined_named_artist_count": catalog.named_artist_count + len(resolved),
        "remaining_unresolved_artist_count": catalog.unresolved_artist_count - len(resolved),
        "pages": pages,
        "rows": rows,
    }


async def _fetch_page(client: httpx.AsyncClient, url: str, user_agent: str) -> bytes:
    async with client.stream(
        "GET", url, headers={"User-Agent": user_agent, "Accept": "application/json"}
    ) as response:
        response.raise_for_status()
        if response.headers.get("content-type", "").partition(";")[0] != "application/json":
            raise CandidateCatalogError("artist search must return JSON metadata")
        chunks = bytearray()
        async for chunk in response.aiter_bytes():
            chunks.extend(chunk)
            if len(chunks) > _MAX_PAGE_BYTES:
                raise CandidateCatalogError("artist search metadata exceeds byte bound")
        return bytes(chunks)


async def acquire_artist_name_enrichment(  # noqa: C901, PLR0913 - bounded acquisition contract.
    *,
    catalog_directory: Path,
    directory: Path,
    client: httpx.AsyncClient,
    user_agent: str,
    limit: int = _MAX_ARTISTS,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, object]:
    """Retain at most 400 sequential search batches with three bounded attempts each."""
    require_local_candidate_destination(directory)
    if not user_agent.strip() or "/" not in user_agent or "(" not in user_agent:
        raise CandidateCatalogError("artist name acquisition needs app version and contact")
    if (directory / "name-enrichment.json").exists():
        result = verify_artist_name_enrichment(
            catalog_directory=catalog_directory, directory=directory
        )
        if result["selection_limit"] != limit:
            raise CandidateCatalogError(
                "existing artist name overlay has a different selection limit"
            )
        return result
    _, identities, _ = _cohort(catalog_directory, limit)
    directory.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 - bounded metadata cache.
    next_request_at = 0.0
    for start in range(0, len(identities), _BATCH_SIZE):
        index = start // _BATCH_SIZE
        batch = identities[start : start + _BATCH_SIZE]
        path = directory / f"batch-{index:04d}.json"
        binding_path = directory / f"batch-{index:04d}-receipt.json"
        if path.is_symlink() or binding_path.is_symlink():
            raise CandidateCatalogError("artist search cache pages must not be symlinks")
        if path.exists() != binding_path.exists():
            raise CandidateCatalogError("artist name batch has an incomplete prior write")
        if not path.exists():
            url = _request_url(batch)
            for attempt in range(_RETRIES):
                await asyncio.sleep(max(0.0, next_request_at - time.monotonic()))
                next_request_at = time.monotonic() + 1.1
                try:
                    raw = await _fetch_page(client, url, user_agent)
                    break
                except (httpx.HTTPStatusError, httpx.TransportError):
                    if attempt + 1 == _RETRIES:
                        raise
                    next_request_at = time.monotonic() + 3.0 * (attempt + 1)
            else:
                raise CandidateCatalogError(
                    "artist name acquisition exhausted its bounded attempts"
                )
            binding = {
                "batch_index": index,
                "artist_mbids": batch,
                "request_url": url,
                "response_sha256": hashlib.sha256(raw).hexdigest(),
                "byte_size": len(raw),
                "http_status": 200,
                "observed_at": datetime.now(UTC).isoformat(),
            }
            path.write_bytes(raw)
            binding_path.write_bytes(canonical_json(binding) + b"\n")
        _page_rows(directory, index, batch)
        if progress is not None:
            progress(min(start + _BATCH_SIZE, len(identities)), len(identities))
    result = _projection(catalog_directory=catalog_directory, directory=directory, limit=limit)
    result["output_sha256"] = sha256_json(result)
    (directory / "name-enrichment.json").write_bytes(canonical_json(result) + b"\n")
    return verify_artist_name_enrichment(catalog_directory=catalog_directory, directory=directory)


def verify_artist_name_enrichment(*, catalog_directory: Path, directory: Path) -> dict[str, object]:
    """Recompute every name from bounded retained source bytes and exact unresolved IDs."""
    path = directory / "name-enrichment.json"
    if path.stat().st_size > _MAX_ARTIFACT_BYTES:
        raise CandidateCatalogError("artist name overlay exceeds byte bound")
    result = TypeAdapter(dict[str, object]).validate_json(path.read_bytes())
    if result.get("output_sha256") != sha256_json(
        {key: value for key, value in result.items() if key != "output_sha256"}
    ):
        raise CandidateCatalogError("artist name overlay hash does not replay")
    limit = result.get("selection_limit")
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise CandidateCatalogError("artist name overlay requires a bounded integer selection")
    replay = _projection(catalog_directory=catalog_directory, directory=directory, limit=limit)
    replay["output_sha256"] = sha256_json(replay)
    if replay != result:
        raise CandidateCatalogError("artist name projection or source declarations do not replay")
    return result
