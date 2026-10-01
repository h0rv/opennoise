"""Retain and replay native MusicBrainz genre labels for exact UUID display joins."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter

from opennoise.catalog.musicbrainz_candidate import (
    CandidateCatalogError,
    normalize_display_name,
    require_local_candidate_destination,
    verify_local_musicbrainz_candidate_catalog,
)
from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.sources.musicbrainz import MusicBrainzGenrePage

if TYPE_CHECKING:
    from pathlib import Path

    from opennoise.sources.musicbrainz import MusicBrainzClient

_PAGE_SIZE: Final = 100
_MAX_GENRES: Final = 10_000
_PAGE_BYTES: Final = 128 * 1024


def _page_path(directory: Path, offset: int) -> Path:
    return directory / f"page-{offset:05d}.json"


def _replay_pages(  # noqa: C901 - the complete pagination checks share one source boundary.
    directory: Path, pages: list[dict[str, object]]
) -> list[dict[str, object]]:
    """Require exact pagination, stable total, complete UUID coverage and unique identities."""
    genres: dict[str, dict[str, object]] = {}
    expected_total: int | None = None
    for index, binding in enumerate(pages):
        offset = index * _PAGE_SIZE
        path = _page_path(directory, offset)
        raw = path.read_bytes()
        if (
            len(raw) > _PAGE_BYTES
            or binding.get("response_sha256") != hashlib.sha256(raw).hexdigest()
        ):
            raise CandidateCatalogError("native genre dictionary page differs from its receipt")
        if binding.get("offset") != offset or binding.get("byte_size") != len(raw):
            raise CandidateCatalogError("native genre page offset or byte count does not replay")
        expected_url = f"https://musicbrainz.org/ws/2/genre/all?fmt=json&limit=100&offset={offset}"
        if binding.get("request_url") != expected_url:
            raise CandidateCatalogError("native genre page is not bound to its exact source URL")
        page = MusicBrainzGenrePage.model_validate_json(raw)
        if expected_total is None:
            expected_total = page.genre_count
        if page.genre_count != expected_total or page.genre_offset != offset:
            raise CandidateCatalogError("native genre pagination total or offset changed")
        if len(page.genres) != min(_PAGE_SIZE, max(0, expected_total - offset)):
            raise CandidateCatalogError("native genre dictionary has incomplete pagination")
        for genre in page.genres:
            identity = str(genre.id)
            if identity in genres:
                raise CandidateCatalogError("native genre dictionary has duplicate UUIDs")
            genres[identity] = {
                "musicbrainz_genre_id": identity,
                "canonical_name": genre.name,
                "display_name": normalize_display_name(genre.name),
                "source_response_sha256": binding["response_sha256"],
                "source_request_url": binding["request_url"],
            }
    if expected_total is None or len(genres) != expected_total:
        raise CandidateCatalogError("native genre dictionary does not cover its declared total")
    if len(pages) != max(1, (expected_total + _PAGE_SIZE - 1) // _PAGE_SIZE):
        raise CandidateCatalogError("native genre dictionary has extra pagination rows")
    return [genres[key] for key in sorted(genres)]


async def acquire_native_musicbrainz_genre_labels(
    *, client: MusicBrainzClient, directory: Path
) -> dict[str, object]:
    """Acquire at most 100 metadata pages, caching exact source bytes for offline replay."""
    require_local_candidate_destination(directory)
    directory.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 - tiny bounded local cache writes.
    if (directory / "labels.json").exists():
        return verify_native_musicbrainz_genre_labels(directory=directory)
    pages: list[dict[str, object]] = []
    offset = 0
    while offset < _MAX_GENRES:
        page_path = _page_path(directory, offset)
        binding_path = directory / f"page-{offset:05d}-receipt.json"
        if page_path.exists() != binding_path.exists():
            raise CandidateCatalogError("native genre page has an incomplete prior write")
        if page_path.exists() and binding_path.exists():
            binding = TypeAdapter(dict[str, object]).validate_json(binding_path.read_bytes())
            raw = page_path.read_bytes()
            if len(raw) > _PAGE_BYTES or sha256_file(page_path)[0] != binding.get(
                "response_sha256"
            ):
                raise CandidateCatalogError("cached native genre page is byte-mutated")
            page = MusicBrainzGenrePage.model_validate_json(raw)
        else:
            response = await client.fetch_genre_page_response(offset=offset)
            raw, page = response.raw_bytes, response.page
            binding: dict[str, object] = {
                "offset": offset,
                "request_url": response.request_url,
                "response_sha256": hashlib.sha256(raw).hexdigest(),
                "byte_size": len(raw),
                "observed_at": response.received_at.isoformat(),
                "http_status": 200,
            }
            if page_path.exists() or binding_path.exists():
                raise CandidateCatalogError("native genre page has an incomplete prior write")
            page_path.write_bytes(raw)
            binding_path.write_bytes(canonical_json(binding) + b"\n")
        pages.append(binding)
        if offset + _PAGE_SIZE >= page.genre_count:
            break
        offset += _PAGE_SIZE
    genres = _replay_pages(directory, pages)
    labels = {
        "revision": "local-musicbrainz-native-genre-labels-v1",
        "scope": "local_research_only",
        "public_export_authorized": False,
        "identity_join": "exact_musicbrainz_genre_uuid_only",
        "membership_claims_added": 0,
        "source": "MusicBrainz",
        "license": "CC0-1.0",
        "license_scope": "native_genre_identity_and_name_core_metadata_only",
        "genre_count": len(genres),
        "pages": pages,
        "genres": genres,
        "output_sha256": "0" * 64,
    }
    labels["output_sha256"] = sha256_json({k: v for k, v in labels.items() if k != "output_sha256"})
    (directory / "labels.json").write_bytes(canonical_json(labels) + b"\n")
    return verify_native_musicbrainz_genre_labels(directory=directory)


def verify_native_musicbrainz_genre_labels(*, directory: Path) -> dict[str, object]:
    """Replay exact UUID/name labels from retained official dictionary page bytes."""
    if (directory / "labels.json").stat().st_size > 64 * 1024 * 1024:
        raise CandidateCatalogError("native genre label artifact exceeds byte bound")
    raw = TypeAdapter(dict[str, object]).validate_json((directory / "labels.json").read_bytes())
    if raw.get("revision") != "local-musicbrainz-native-genre-labels-v1":
        raise CandidateCatalogError("unsupported native genre label artifact")
    if raw.get("output_sha256") != sha256_json(
        {k: v for k, v in raw.items() if k != "output_sha256"}
    ):
        raise CandidateCatalogError("native genre label artifact hash does not replay")
    if raw.get("public_export_authorized") is not False or raw.get("membership_claims_added") != 0:
        raise CandidateCatalogError("native labels cannot authorize membership or publication")
    expected_declarations = {
        "scope": "local_research_only",
        "identity_join": "exact_musicbrainz_genre_uuid_only",
        "source": "MusicBrainz",
        "license": "CC0-1.0",
        "license_scope": "native_genre_identity_and_name_core_metadata_only",
    }
    if any(raw.get(key) != value for key, value in expected_declarations.items()):
        raise CandidateCatalogError("native genre label source declarations do not replay")
    pages = TypeAdapter(list[dict[str, object]]).validate_python(raw.get("pages"))
    if not 1 <= len(pages) <= _MAX_GENRES // _PAGE_SIZE:
        raise CandidateCatalogError("native genre label pages exceed the bounded contract")
    genres = _replay_pages(directory, pages)
    if genres != raw.get("genres") or len(genres) != raw.get("genre_count"):
        raise CandidateCatalogError("native genre names do not replay from exact source bytes")
    return raw


def build_local_musicbrainz_genre_label_join(
    *, catalog_directory: Path, label_directory: Path, output_path: Path
) -> dict[str, object]:
    """Join direct genre UUIDs to native labels, retaining ambiguous/missing abstentions.

    Seed IDs are opaque; no historical name or position enters this join. Names
    are source display metadata and cannot add direct observations or memberships.
    """
    require_local_candidate_destination(output_path)
    catalog = verify_local_musicbrainz_candidate_catalog(directory=catalog_directory)
    labels = verify_native_musicbrainz_genre_labels(directory=label_directory)
    names = TypeAdapter(list[dict[str, object]]).validate_python(labels["genres"])
    by_uuid = {str(row["musicbrainz_genre_id"]): row for row in names}
    grouped: dict[str, list[str]] = {}
    database = catalog_directory / "catalog.sqlite"
    with closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        for seed_id, genre_id in connection.execute(
            "SELECT DISTINCT seed_id,musicbrainz_genre_id FROM direct_claim "
            "ORDER BY seed_id,musicbrainz_genre_id"
        ):
            grouped.setdefault(str(seed_id), []).append(str(genre_id))
    rows: list[dict[str, object]] = []
    for seed_id, genre_ids in grouped.items():
        matched = [by_uuid[genre_id] for genre_id in genre_ids if genre_id in by_uuid]
        status = "missing_native_label"
        display: object = None
        if len(matched) != len(genre_ids):
            status = "missing_native_label"
        elif len(genre_ids) != 1:
            status = "ambiguous_native_identity"
        elif matched[0]["display_name"] is None:
            status = "unusable_display"
        else:
            status = "resolved_source_label"
            display = matched[0]["display_name"]
        rows.append(
            {
                "seed_id": seed_id,
                "musicbrainz_genre_ids": genre_ids,
                "native_labels": matched,
                "display_name": display,
                "status": status,
            }
        )
    result: dict[str, object] = {
        "revision": "local-musicbrainz-native-genre-seed-label-join-v1",
        "scope": "local_research_only",
        "public_export_authorized": False,
        "membership_claims_added": 0,
        "historical_names_or_positions_read": False,
        "identity_join": "exact_musicbrainz_genre_uuid_only",
        "catalog_output_sha256": catalog.output_sha256,
        "catalog_direct_object_sha256": catalog.direct_object_sha256,
        "labels_output_sha256": labels["output_sha256"],
        "labels_byte_sha256": sha256_file(label_directory / "labels.json")[0],
        "seed_count": len(rows),
        "resolved_seed_count": sum(row["status"] == "resolved_source_label" for row in rows),
        "abstained_seed_count": sum(row["status"] != "resolved_source_label" for row in rows),
        "rows": rows,
    }
    result["output_sha256"] = sha256_json(result)
    payload = canonical_json(result) + b"\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        if output_path.read_bytes() != payload:
            raise CandidateCatalogError("refusing to replace a different native genre label join")
    else:
        with output_path.open("xb") as stream:
            stream.write(payload)
    return result
