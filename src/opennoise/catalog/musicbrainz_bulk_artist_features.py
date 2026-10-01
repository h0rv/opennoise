"""Fixed-hash, stratified native feature expansion beyond already retained artists."""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import time
from collections import Counter
from contextlib import closing
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import httpx
from pydantic import TypeAdapter

from opennoise.catalog.musicbrainz_artist_names import _fetch_page, _page_rows, _request_url
from opennoise.catalog.musicbrainz_candidate import (
    CandidateCatalogError,
    require_local_candidate_destination,
    verify_local_musicbrainz_candidate_catalog,
)
from opennoise.catalog.musicbrainz_open_features import (
    _POLICY,
    _copy_bytes,
    build_open_artist_feature_projection,
    iter_open_artist_feature_rows,
    verify_open_artist_features,
)
from opennoise.common import canonical_json, sha256_file, sha256_json

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_MAX_ARTISTS: Final = 15_000
_BATCH_SIZE: Final = 100
_DOMAIN: Final = "opennoise-additional-native-rich-artists-v1"


def _fixed_hash(identity: str) -> str:
    return hashlib.sha256(f"{_DOMAIN}|{identity}".encode()).hexdigest()


def _round_robin(buckets: dict[str, list[str]], selected: set[str], target: int) -> None:
    positions = dict.fromkeys(buckets, 0)
    while len(selected) < target:
        progressed = False
        for seed in sorted(buckets):
            position = positions[seed]
            values = buckets[seed]
            while position < len(values) and values[position] in selected:
                position += 1
            positions[seed] = position
            if position < len(values):
                selected.add(values[position])
                positions[seed] += 1
                progressed = True
                if len(selected) == target:
                    return
        if not progressed:
            return


def select_additional_artist_cohort(
    *, catalog_directory: Path, existing_feature_directory: Path, artist_limit: int = _MAX_ARTISTS
) -> dict[str, object]:
    """Sample a degree-one half-stratum, then every native seed, solely by exact UUID hash."""
    if isinstance(artist_limit, bool) or not 1 <= artist_limit <= _MAX_ARTISTS:
        raise CandidateCatalogError(
            "additional native feature acquisition is bounded to 15,000 artists"
        )
    catalog = verify_local_musicbrainz_candidate_catalog(directory=catalog_directory)
    existing_receipt = verify_open_artist_features(directory=existing_feature_directory)
    existing = {
        str(row["artist_mbid"])
        for row in iter_open_artist_feature_rows(directory=existing_feature_directory)
    }
    database = catalog_directory / "catalog.sqlite"
    by_artist: dict[str, list[str]] = {}
    with closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        for artist, seed in connection.execute(
            "SELECT artist_mbid,seed_id FROM seed_artist ORDER BY artist_mbid,seed_id"
        ):
            if str(artist) not in existing:
                by_artist.setdefault(str(artist), []).append(str(seed))
    hashes = {identity: _fixed_hash(identity) for identity in by_artist}
    all_buckets: dict[str, list[str]] = {}
    singleton_buckets: dict[str, list[str]] = {}
    for identity, seeds in by_artist.items():
        for seed in seeds:
            all_buckets.setdefault(seed, []).append(identity)
            if len(seeds) == 1:
                singleton_buckets.setdefault(seed, []).append(identity)
    for buckets in (all_buckets, singleton_buckets):
        for values in buckets.values():
            values.sort(key=lambda identity: (hashes[identity], identity))
    selected: set[str] = set()
    singleton_target = (artist_limit + 1) // 2
    _round_robin(singleton_buckets, selected, singleton_target)
    singleton_reserved = len(selected)
    _round_robin(all_buckets, selected, artist_limit)
    if len(selected) != artist_limit or selected & existing:
        raise CandidateCatalogError(
            "additional native feature cohort cannot meet its disjoint bounded selection"
        )
    degree = Counter(len(by_artist[identity]) for identity in selected)
    selection = {
        "revision": "additional-native-feature-cohort-v1",
        "catalog_output_sha256": catalog.output_sha256,
        "existing_feature_output_sha256": existing_receipt["output_sha256"],
        "selection": "fixed_uuid_hash_native_seed_round_robin_with_reserved_degree_one_half",
        "hash_domain": _DOMAIN,
        "artist_limit": artist_limit,
        "reserved_singleton_target": singleton_target,
        "reserved_singletons_selected": singleton_reserved,
        "singleton_artist_count": degree[1],
        "selected_native_seed_count": len(
            {seed for identity in selected for seed in by_artist[identity]}
        ),
        "selected_direct_pair_count": sum(len(by_artist[identity]) for identity in selected),
        "existing_artist_count": len(existing),
        "excluded_existing_artist_count": len(existing),
        "artist_degree_counts": {str(key): value for key, value in sorted(degree.items())},
        "artist_ids": sorted(selected),
    }
    selection["output_sha256"] = sha256_json(selection)
    return selection


async def acquire_additional_artist_features(  # noqa: PLR0913 - independent fixed selection inputs.
    *,
    catalog_directory: Path,
    existing_feature_directory: Path,
    directory: Path,
    client: httpx.AsyncClient,
    user_agent: str,
    artist_limit: int = _MAX_ARTISTS,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, object]:
    """Acquire at most 150 additional exact-ID batches without replacing prior artifacts."""
    require_local_candidate_destination(directory)
    if (directory / "receipt.json").exists():
        return verify_open_artist_features(directory=directory)
    selection = select_additional_artist_cohort(
        catalog_directory=catalog_directory,
        existing_feature_directory=existing_feature_directory,
        artist_limit=artist_limit,
    )
    identities = TypeAdapter(list[str]).validate_python(selection["artist_ids"])
    directory.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 - bounded metadata cache.
    selection_raw = canonical_json(selection) + b"\n"
    selection_path = directory / "selection.json"
    if selection_path.exists() and selection_path.read_bytes() != selection_raw:
        raise CandidateCatalogError("retained additional feature selection changed")
    selection_path.write_bytes(selection_raw)
    _copy_bytes(
        existing_feature_directory / "source-license.html", directory / "source-license.html"
    )
    target = directory / "new-pages"
    target.mkdir(exist_ok=True)
    documents: list[dict[str, object]] = []
    next_request_at = 0.0
    for start in range(0, len(identities), _BATCH_SIZE):
        index = start // _BATCH_SIZE
        ids = identities[start : start + _BATCH_SIZE]
        path = target / f"batch-{index:04d}.json"
        companion = target / f"batch-{index:04d}-receipt.json"
        if path.exists() != companion.exists() or path.is_symlink() or companion.is_symlink():
            raise CandidateCatalogError("additional feature page has an incomplete prior write")
        if not path.exists():
            url = _request_url(ids)
            for attempt in range(3):
                await asyncio.sleep(max(0.0, next_request_at - time.monotonic()))
                next_request_at = time.monotonic() + 1.1
                try:
                    raw = await _fetch_page(client, url, user_agent)
                    break
                except (httpx.HTTPStatusError, httpx.TransportError):
                    if attempt == 2:  # noqa: PLR2004 - final bounded attempt.
                        raise
                    next_request_at = time.monotonic() + 3 * (attempt + 1)
            else:
                raise CandidateCatalogError(
                    "additional feature acquisition exhausted bounded retries"
                )
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
            companion.write_bytes(canonical_json(binding) + b"\n")
        _page_rows(target, index, ids)
        binding = TypeAdapter(dict[str, object]).validate_json(companion.read_bytes())
        documents.append({**binding, "path": f"new-pages/{path.name}"})
        if progress is not None:
            progress(min(start + _BATCH_SIZE, len(identities)), len(identities))
    source = {
        **_POLICY,
        "catalog_output_sha256": selection["catalog_output_sha256"],
        "existing_feature_output_sha256": selection["existing_feature_output_sha256"],
        "selection_output_sha256": selection["output_sha256"],
        "selection_byte_sha256": sha256_file(selection_path)[0],
        "new_artist_ids": identities,
        "selection": selection["selection"],
        "documents": documents,
        "license_url": "https://musicbrainz.org/doc/About/Data_License",
        "license_page_sha256": sha256_file(directory / "source-license.html")[0],
    }
    (directory / "source.json").write_bytes(canonical_json(source) + b"\n")
    return build_open_artist_feature_projection(directory=directory)
