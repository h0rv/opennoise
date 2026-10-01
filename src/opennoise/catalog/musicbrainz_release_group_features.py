"""Bounded native release-group style observations with exact credit context.

All credits, genres and tags of one release group share one evidence group;
release-group observations never become artist-direct membership facts.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import Counter
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import httpx
from pydantic import TypeAdapter

from opennoise.catalog.musicbrainz_artist_names import _fetch_page
from opennoise.catalog.musicbrainz_candidate import (
    CandidateCatalogError,
    require_local_candidate_destination,
)
from opennoise.catalog.musicbrainz_open_features import _SENTINELS, _copy_bytes
from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.sources.musicbrainz import MusicBrainzReleaseGroup

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

_BATCH_SIZE: Final = 100
_MAX_PER_ARTIST: Final = 200
_POLICY: Final = {
    "revision": "local-musicbrainz-native-release-group-features-v1",
    "scope": "local_noncommercial_research",
    "source_role": "native_release_group_observations_with_credit_context",
    "public_export_authorized": False,
    "historical_inputs_used": False,
    "audio_inputs_used": False,
    "fixed_seed_vocabulary_used": False,
    "artist_membership_inferred_from_context": False,
    "core_metadata_license": "CC0-1.0",
    "tags_and_genre_associations_license": "CC-BY-NC-SA-3.0",
    "attribution": "MusicBrainz contributors; https://musicbrainz.org/",
    "evidence_grouping": "release_group_uuid_across_all_facets_and_credited_artists",
    "selection": "first_bounded_native_browse_pages_not_relevance_or_full_discography",
}


def _url(artist: str, offset: int) -> str:
    return str(
        httpx.URL(
            "https://musicbrainz.org/ws/2/release-group",
            params={
                "artist": artist,
                "limit": _BATCH_SIZE,
                "offset": offset,
                "fmt": "json",
                "inc": "genres+tags+artist-credits",
            },
        )
    )


def _page(  # noqa: C901 - complete browse source boundary.
    directory: Path, binding: dict[str, object]
) -> list[MusicBrainzReleaseGroup]:
    artist = str(binding["artist_mbid"])
    offset = TypeAdapter(int).validate_python(binding["offset"], strict=True)
    if artist not in _SENTINELS or offset not in (0, _BATCH_SIZE):
        raise CandidateCatalogError(
            "release-group page lies outside the bounded sentinel acquisition"
        )
    relative = f"pages/{artist}-{offset:03d}.json"
    if binding.get("path") != relative or binding.get("request_url") != _url(artist, offset):
        raise CandidateCatalogError("release-group page has a different native request binding")
    path = directory / relative
    if path.is_symlink() or path.parent.is_symlink():
        raise CandidateCatalogError("native release-group page must not be symbolic")
    sha, size = sha256_file(path)
    if (sha, size) != (binding["response_sha256"], binding["byte_size"]) or size > 2 * 1024 * 1024:
        raise CandidateCatalogError("native release-group page bytes differ from the receipt")
    companion = json.loads(path.with_suffix(".receipt.json").read_bytes())
    if companion != binding:
        raise CandidateCatalogError("native release-group document and its receipt differ")
    raw = TypeAdapter(dict[str, object]).validate_json(path.read_bytes())
    count = raw.get("release-group-count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise CandidateCatalogError("native release-group page has an invalid total")
    if raw.get("release-group-offset") != offset:
        raise CandidateCatalogError("native release-group page offset differs")
    groups = TypeAdapter(list[MusicBrainzReleaseGroup]).validate_json(
        canonical_json(raw["release-groups"])
    )
    if len(groups) != min(_BATCH_SIZE, max(0, count - offset)):
        raise CandidateCatalogError("native release-group page is incomplete")
    if len({str(row.id) for row in groups}) != len(groups):
        raise CandidateCatalogError("native release-group page repeats an identity")
    if any(artist not in {str(c.artist.id) for c in row.artist_credit} for row in groups):
        raise CandidateCatalogError("native browse result does not credit its exact queried artist")
    return groups


async def acquire_native_release_group_features(  # noqa: C901 - bounded source boundary.
    *,
    directory: Path,
    license_path: Path,
    client: httpx.AsyncClient,
    user_agent: str,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, object]:
    """Acquire at most twenty native browse pages with three bounded attempts each."""
    require_local_candidate_destination(directory)
    if (directory / "receipt.json").exists():
        return verify_native_release_group_features(directory=directory)
    directory.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 - bounded metadata cache.
    (directory / "pages").mkdir(exist_ok=True)
    _copy_bytes(license_path, directory / "source-license.html")
    documents: list[dict[str, object]] = []
    next_request_at = 0.0
    for artist in _SENTINELS:
        for offset in range(0, _MAX_PER_ARTIST, _BATCH_SIZE):
            path = directory / "pages" / f"{artist}-{offset:03d}.json"
            receipt_path = path.with_suffix(".receipt.json")
            if (
                path.exists() != receipt_path.exists()
                or path.is_symlink()
                or receipt_path.is_symlink()
            ):
                raise CandidateCatalogError(
                    "native release-group page has an incomplete prior write"
                )
            if not path.exists():
                url = _url(artist, offset)
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
                        "native release-group acquisition exhausted retries"
                    )
                binding = {
                    "artist_mbid": artist,
                    "offset": offset,
                    "request_url": url,
                    "path": f"pages/{path.name}",
                    "http_status": 200,
                    "response_sha256": hashlib.sha256(raw).hexdigest(),
                    "byte_size": len(raw),
                    "observed_at": datetime.now(UTC).isoformat(),
                }
                path.write_bytes(raw)
                receipt_path.write_bytes(canonical_json(binding) + b"\n")
            binding = TypeAdapter(dict[str, object]).validate_json(receipt_path.read_bytes())
            _page(directory, binding)
            documents.append(binding)
            if progress is not None:
                progress(len(documents), len(_SENTINELS) * 2)
            total = json.loads(path.read_bytes())["release-group-count"]
            if offset + _BATCH_SIZE >= total:
                break
    source = {
        **_POLICY,
        "artist_mbids": list(_SENTINELS),
        "maximum_release_groups_per_artist": _MAX_PER_ARTIST,
        "documents": documents,
        "license_page_sha256": sha256_file(directory / "source-license.html")[0],
    }
    (directory / "source.json").write_bytes(canonical_json(source) + b"\n")
    return build_native_release_group_feature_projection(directory=directory)


def iter_native_release_group_feature_rows(  # noqa: C901 - bounded native source replay.
    *, directory: Path
) -> Iterator[dict[str, object]]:
    """Reconstruct deduplicated group facts while preserving all exact source evidence refs."""
    source = TypeAdapter(dict[str, object]).validate_json((directory / "source.json").read_bytes())
    if any(source.get(key) != value for key, value in _POLICY.items()):
        raise CandidateCatalogError("native release-group source roles or field licenses differ")
    license_raw = (directory / "source-license.html").read_bytes()
    if hashlib.sha256(license_raw).hexdigest() != source.get("license_page_sha256"):
        raise CandidateCatalogError("native release-group source license capture differs")
    documents = TypeAdapter(list[dict[str, object]]).validate_python(source["documents"])
    if not 1 <= len(documents) <= 20:  # noqa: PLR2004 - ten artists, at most two pages each.
        raise CandidateCatalogError("native release-group documents exceed bounded acquisition")
    grouped: dict[str, dict[str, object]] = {}
    sources: dict[str, list[dict[str, object]]] = {}
    artist_offsets: dict[str, list[int]] = {}
    artist_totals: dict[str, int] = {}
    for binding in documents:
        rows = _page(directory, binding)
        artist = str(binding["artist_mbid"])
        artist_offsets.setdefault(artist, []).append(
            TypeAdapter(int).validate_python(binding["offset"], strict=True)
        )
        total = int(
            json.loads((directory / str(binding["path"])).read_bytes())["release-group-count"]
        )
        if artist_totals.setdefault(artist, total) != total:
            raise CandidateCatalogError("native release-group total changed between bounded pages")
        for row in rows:
            identity = str(row.id)
            facts: dict[str, object] = {
                "release_group_mbid": identity,
                "title": row.title,
                "artist_mbids": [str(credit.artist.id) for credit in row.artist_credit],
                "artist_credit": [credit.model_dump(mode="json") for credit in row.artist_credit],
                "genres": [genre.model_dump(mode="json") for genre in row.genres],
                "tags": [tag.model_dump(mode="json") for tag in row.tags],
                "first_release_date": row.first_release_date,
                "primary_type": row.primary_type,
                "secondary_types": list(row.secondary_types),
                "source_role": _POLICY["source_role"],
                "evidence_group_ids": [f"release_group:{identity}"],
            }
            if grouped.setdefault(identity, facts) != facts:
                raise CandidateCatalogError(
                    "same native release group has conflicting source facts"
                )
            sources.setdefault(identity, []).append(
                {
                    "source_document": binding["path"],
                    "source_response_sha256": binding["response_sha256"],
                    "queried_artist_mbid": artist,
                }
            )
    if set(artist_offsets) != set(_SENTINELS):
        raise CandidateCatalogError("native release-group acquisition omits a sentinel artist")
    for artist, offsets in artist_offsets.items():
        required = list(range(0, min(_MAX_PER_ARTIST, artist_totals[artist]), _BATCH_SIZE)) or [0]
        if offsets != required:
            raise CandidateCatalogError(
                "native release-group pagination does not cover its declared bound"
            )
    for identity in sorted(grouped):
        yield {
            **grouped[identity],
            "sources": sources[identity],
            "evidence_refs": [
                f"release-group/{identity}",
                *sorted({f"source:{r['source_response_sha256']}" for r in sources[identity]}),
            ],
        }


def _manifest(directory: Path, rows: list[dict[str, object]]) -> dict[str, object]:
    genres: Counter[str] = Counter()
    tags: Counter[str] = Counter()
    for row in rows:
        genres.update(
            str(g["name"])
            for g in TypeAdapter(list[dict[str, object]]).validate_python(row["genres"])
            if isinstance(g["count"], int) and int(g["count"]) > 0
        )
        tags.update(
            str(g["name"])
            for g in TypeAdapter(list[dict[str, object]]).validate_python(row["tags"])
            if isinstance(g["count"], int) and int(g["count"]) > 0
        )
    sha, size = sha256_file(directory / "release-features.jsonl")
    return {
        **_POLICY,
        "source_byte_sha256": sha256_file(directory / "source.json")[0],
        "release_group_count": len(rows),
        "positive_genre_observation_count": sum(genres.values()),
        "positive_tag_observation_count": sum(tags.values()),
        "distinct_positive_genre_count": len(genres),
        "distinct_positive_tag_count": len(tags),
        "queried_artist_count": len(_SENTINELS),
        "rows_sha256": sha,
        "rows_byte_size": size,
    }


def build_native_release_group_feature_projection(*, directory: Path) -> dict[str, object]:
    """Seal native release facts without materializing artist membership claims."""
    require_local_candidate_destination(directory)
    rows = list(iter_native_release_group_feature_rows(directory=directory))
    (directory / "release-features.jsonl").write_bytes(
        b"".join(canonical_json(row) + b"\n" for row in rows)
    )
    receipt = _manifest(directory, rows)
    receipt["output_sha256"] = sha256_json(receipt)
    (directory / "receipt.json").write_bytes(canonical_json(receipt) + b"\n")
    return verify_native_release_group_features(directory=directory)


def verify_native_release_group_features(*, directory: Path) -> dict[str, object]:
    """Require exact native group source replay, including evidence-group identity."""
    rows = list(iter_native_release_group_feature_rows(directory=directory))
    if (directory / "release-features.jsonl").read_bytes() != b"".join(
        canonical_json(row) + b"\n" for row in rows
    ):
        raise CandidateCatalogError(
            "native release-group features do not replay from exact source bytes"
        )
    receipt = _manifest(directory, rows)
    receipt["output_sha256"] = sha256_json(receipt)
    if receipt != json.loads((directory / "receipt.json").read_bytes()):
        raise CandidateCatalogError(
            "native release-group receipt or source-role declarations differ"
        )
    return receipt
