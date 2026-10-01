"""Measure retained-reference coverage without turning missing evidence into parity."""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from opennoise.adapters.everynoise import QUINT_SOURCE, adapt_quint_html
from opennoise.catalog.musicbrainz_candidate import require_local_candidate_destination
from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.deployment.direct_artist_shards import PAGE_SIZE, PREFIX_LENGTH

if TYPE_CHECKING:
    from collections.abc import Iterable


def normalized_name(name: str) -> str:
    """Match only Unicode-normalized casefolded whole names, never fuzzy aliases."""
    return " ".join(unicodedata.normalize("NFC", name).casefold().split())


def compare_genre_names(reference: Iterable[str], candidate: Iterable[str]) -> dict[str, object]:
    """Keep missing names and candidate extras explicit; name matches are not identities."""
    reference_names = {normalized_name(name): name for name in reference}
    candidate_names = {normalized_name(name): name for name in candidate}
    matched = sorted(reference_names.keys() & candidate_names.keys())
    return {
        "method": "exact_nfc_casefold_whitespace_name_diagnostic_not_identity_bridge",
        "reference_distinct_names": len(reference_names),
        "candidate_distinct_names": len(candidate_names),
        "matched_reference_names": len(matched),
        "reference_name_coverage": len(matched) / len(reference_names) if reference_names else None,
        "missing_reference_names": [
            reference_names[key] for key in sorted(reference_names.keys() - candidate_names.keys())
        ],
        "candidate_only_names": [
            candidate_names[key] for key in sorted(candidate_names.keys() - reference_names.keys())
        ],
    }


def verify_preview_files(directory: Path) -> dict[str, object]:
    """Verify every receipt-bound static response before measuring a preview."""
    receipt = TypeAdapter(dict[str, object]).validate_json(
        (directory / "preview-receipt.json").read_bytes()
    )
    unsigned = dict(receipt)
    digest = unsigned.pop("output_sha256", None)
    if digest != sha256_json(unsigned):
        raise ValueError("preview receipt hash mismatch")
    if (
        receipt.get("scope") != "local_research_only"
        or receipt.get("public_export_authorized") is not False
    ):
        raise ValueError("parity evaluation requires an explicit local research artifact")
    files = receipt["files"]
    if not isinstance(files, dict):
        raise TypeError("invalid preview file ledger")
    required = {
        "data.json",
        "index.html",
        "direct-custody-preview.js",
        "direct-custody-preview.css",
    }
    if not required <= files.keys():
        raise ValueError("preview receipt omits mandatory entry points")
    actual_files = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and path.name != "preview-receipt.json"
    }
    if actual_files != files.keys():
        raise ValueError("preview receipt does not bind every static response")
    for relative, metadata in files.items():
        path = directory / relative
        if Path(relative).is_absolute() or ".." in Path(relative).parts or path.is_symlink():
            raise ValueError("unsafe preview receipt path")
        if not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError("preview file escapes artifact")
        digest, size = sha256_file(path)
        if digest != metadata["sha256"] or size != metadata["bytes"]:
            raise ValueError(f"preview file hash mismatch: {relative}")
    return receipt


def verify_complete_artist_navigation(directory: Path) -> tuple[int, int]:  # noqa: C901, PLR0912, PLR0915 - all static projections must agree before claiming reachability.
    """Replay declared browser routes and reconcile pages, search, and profiles."""
    receipt = verify_preview_files(directory)
    payload = json.loads((directory / "data.json").read_bytes())
    catalog = payload["artist_catalog"]
    if (
        catalog["revision"] != "direct-source-artist-shards-v1"
        or catalog["page_size"] != PAGE_SIZE
        or catalog["prefix_length"] != PREFIX_LENGTH
        or catalog["profile_path_template"] != "artists/{prefix}.json"
        or catalog["genre_pages_path_template"] != "genre-artists/{genre_id}/{page}.json"
        or catalog["search_path"] != "artist-search.json"
    ):
        raise ValueError("unsupported complete artist routing contract")
    genres = {row["id"]: row for row in payload["genres"]}
    if (
        len(genres) != len(payload["genres"])
        or genres.keys() != catalog["genre_page_counts"].keys()
    ):
        raise ValueError("artist navigation genre identities differ")
    profiles = {}
    expected_profile_paths = set()
    for file in sorted((directory / "artists").glob("*.json")):
        artists = json.loads(file.read_bytes())["artists"]
        if any(artist[:PREFIX_LENGTH] != file.stem or artist in profiles for artist in artists):
            raise ValueError("artist profile routed to wrong or duplicate shard")
        profiles.update(artists)
        expected_profile_paths.add(file.relative_to(directory).as_posix())
    if len(expected_profile_paths) != catalog["profile_shard_count"]:
        raise ValueError("incomplete artist profile shards")
    search = json.loads((directory / "artist-search.json").read_bytes())["artists"]
    if len(search) != len(profiles) or {row[0] for row in search} != profiles.keys():
        raise ValueError("artist search identity projection differs")
    for artist, name, status in search:
        if (name, status) != (profiles[artist]["name"], profiles[artist]["name_status"]):
            raise ValueError("artist search display projection differs")
    pairs = set()
    expected_page_paths = set()
    for genre, row in genres.items():
        count = row["observed_artist_count"]
        pages = (count + catalog["page_size"] - 1) // catalog["page_size"]
        if pages != catalog["genre_page_counts"][genre] or pages != row["direct_artist_page_count"]:
            raise ValueError("genre page count differs from source count")
        for number in range(pages):
            relative = f"genre-artists/{genre}/{number}.json"
            expected_page_paths.add(relative)
            page = json.loads((directory / relative).read_bytes())
            if (page["genre_id"], page["page"], page["total_count"], page["role"]) != (
                genre,
                number,
                count,
                "direct_source_observation",
            ):
                raise ValueError("source artist page route metadata differs")
            if len(page["artists"]) != min(
                catalog["page_size"], count - number * catalog["page_size"]
            ):
                raise ValueError("source artist page size differs")
            for artist in page["artists"]:
                identity = artist["id"]
                profile = {key: value for key, value in artist.items() if key != "id"}
                if (
                    profiles.get(identity) != profile
                    or genre not in profile["genre_ids"]
                    or (genre, identity) in pairs
                ):
                    raise ValueError("source artist page and profile differ")
                pairs.add((genre, identity))
    profile_pairs = {
        (genre, artist) for artist, profile in profiles.items() for genre in profile["genre_ids"]
    }
    if (
        profile_pairs != pairs
        or len(pairs) != catalog["direct_pair_count"]
        or len(profiles) != catalog["artist_count"]
    ):
        raise ValueError("incomplete static source navigation")
    files = receipt["files"]
    if not isinstance(files, dict):
        raise TypeError("invalid preview file ledger")
    declared_pages = {path for path in files if path.startswith("genre-artists/")}
    declared_profiles = {path for path in files if path.startswith("artists/")}
    if declared_pages != expected_page_paths or declared_profiles != expected_profile_paths:
        raise ValueError("declared routes differ from artist navigation contract")
    _verify_lazy_genre_details(directory, profiles)
    return len(profiles), len(pairs)


def _verify_lazy_genre_details(  # noqa: C901 - detail, overview, and source profiles must agree.
    directory: Path, profiles: dict[str, object]
) -> None:
    """Verify the lazy genre gate required before the browser exposes source pages."""
    payload = json.loads((directory / "data.json").read_bytes())
    revision = payload.get("genre_details_revision")
    if revision is None:
        return
    if revision != "direct-source-genre-details-v1":
        raise ValueError("unsupported lazy genre routing contract")
    known_genres = {row["id"] for row in payload["genres"]}
    for genre in payload["genres"]:
        relative = f"genre-details/{genre['id']}.json"
        if genre["detail_path"] != relative:
            raise ValueError("lazy genre detail route differs")
        detail = json.loads((directory / relative).read_bytes())
        for key in (
            "id",
            "name",
            "x",
            "y",
            "observed_artist_count",
            "direct_artist_page_count",
            "direct_artist_page_size",
        ):
            if detail[key] != genre[key]:
                raise ValueError("lazy genre detail and overview differ")
        if len(detail["peers"]) != genre["modeled_neighbor_count"]:
            raise ValueError("lazy genre peer count differs")
        if any(peer["seed_id"] not in known_genres for peer in detail["peers"]):
            raise ValueError("lazy genre peer identity differs")
        selected = set(detail["direct_artist_ids"]) | {
            proposal["artist_mbid"] for proposal in detail["proposals"]
        }
        if selected != detail["artist_profiles"].keys():
            raise ValueError("lazy genre embedded profile identities differ")
        if any(
            profiles.get(artist) != profile for artist, profile in detail["artist_profiles"].items()
        ):
            raise ValueError("lazy genre embedded profile projection differs")
        for artist in detail["direct_artist_ids"]:
            profile = detail["artist_profiles"][artist]
            if genre["id"] not in profile["genre_ids"]:
                raise ValueError("lazy genre example is not a direct source member")


def build_everynoise_parity_report(
    *, reference: Path, preview: Path, output: Path
) -> dict[str, object]:
    """Bind a dated H2 oracle and an independently built source explorer for evaluation."""
    require_local_candidate_destination(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing to replace a parity report")
    historical = adapt_quint_html(reference.read_bytes())
    if historical.quarantine:
        raise ValueError("reference genre quarantine prevents complete reference measurement")
    receipt = verify_preview_files(preview)
    payload = json.loads((preview / "data.json").read_bytes())
    genres = payload["genres"]
    name_diagnostic = compare_genre_names(
        (record.catalog.name for record in historical.records), (row["name"] for row in genres)
    )
    complete_artist_projection: dict[str, object] = {"status": "unavailable"}
    if payload.get("artist_catalog"):
        artists, pairs = verify_complete_artist_navigation(preview)
        complete_artist_projection = {
            "status": "verified_complete_for_declared_source_not_every_noise",
            "reachable_source_artists": artists,
            "reachable_direct_source_pairs": pairs,
            "reference_membership_recall": None,
            "reference_membership_recall_status": (
                "unavailable_no_complete_reference_membership_or_identity_bridge"
            ),
        }
    report: dict[str, object] = {
        "revision": "everynoise-parity-evaluation-v1",
        "scope": "local_evaluation_only",
        "reference_source_sha256": QUINT_SOURCE.sha256,
        "reference_snapshot": QUINT_SOURCE.snapshot,
        "reference_data_date": "2023-11-19",
        "live_site_verified": False,
        "preview_receipt_output_sha256": receipt["output_sha256"],
        "reference_genre_count": len(historical.records),
        "candidate_genre_count": len(genres),
        "placed_candidate_genres": sum(
            row["x"] is not None and row["y"] is not None for row in genres
        ),
        "genre_name_diagnostic": name_diagnostic,
        "complete_artist_projection": complete_artist_projection,
        "audio_playback": {"status": "excluded_by_existing_metadata_only_policy", "parity": False},
        "artist_map_geometry": {
            "status": "bounded_source_overlap_maps_not_reference_geometry"
            if receipt.get("artist_maps")
            else "not_implemented",
            "parity": None if receipt.get("artist_maps") else False,
            "quality_evaluated": False,
            "source_map_counts": receipt.get("artist_maps"),
        },
        "reference_artist_rankings": {"status": "unavailable", "parity": None},
        "playlist_and_release_exploration": {
            "release_metadata_status": "bounded_retained_credit_context"
            if receipt.get("release_contexts")
            else "not_integrated",
            "playlist_status": "unavailable_in_retained_inputs",
            "parity": False,
        },
        "overall_parity": False,
        "overall_percentage": None,
        "overall_percentage_reason": (
            "coverage, interaction, geometry, and listening are independent criteria; "
            "unknown criteria cannot count as passed"
        ),
        "historical_data_role": "evaluation_only_no_construction_or_training",
        "evaluator_sha256": sha256_file(Path(__file__))[0],
    }
    report["output_sha256"] = sha256_json(report)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_json(report) + b"\n")
    return report
