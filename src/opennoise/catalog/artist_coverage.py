"""Exact MusicBrainz-ID coverage for a small electronic-artist audit cohort."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from opennoise.catalog.musicbrainz_genre_labels import verify_native_musicbrainz_genre_labels

# IDs are the join key. Names are display labels only; duplicate names such as
# Burial must never combine independent MusicBrainz identities.
ARTIST_COVERAGE_COHORT: Final[tuple[tuple[str, str], ...]] = (
    ("Aphex Twin", "f22942a1-6f70-4f48-866e-238cb2308fbd"),
    ("Four Tet", "3bcff06f-675a-451f-9075-99e8657047e8"),
    ("Boards of Canada", "69158f97-4c07-4c4e-baf8-4e4ab1ed666e"),
    ("Autechre", "410c9baf-5469-44f6-9852-826524b80c61"),
    ("Burial (UK dubstep)", "9ddce51c-2b75-4b3e-ac8c-1db09e7c89c6"),
    ("Squarepusher", "4d86ad4e-28d8-4e9f-8cf4-735c57060fdc"),
    ("Floating Points", "69d9c5ba-7bba-4cb7-ab32-8ccc48ad4f97"),
    ("Caribou", "735e3514-a8ae-401f-af3b-6300df1b8d2c"),
    ("Brian Eno", "ff95eb47-41c4-4f7f-a104-cdc30f02e872"),
    ("Jon Hopkins", "0b0c25f4-f31c-46a5-a4fb-ccbf53d663bd"),
)


@dataclass(frozen=True, slots=True)
class ArtistCoverage:
    """Direct source and rich model coverage for one exact native artist ID."""

    cohort_name: str
    artist_mbid: str
    display_name: str | None = None
    catalog_name: str | None = None
    name_status: str | None = None
    direct_claim_count: int | None = None
    direct_seed_count: int | None = None
    direct_genre_ids: tuple[str, ...] | None = None
    direct_genres: tuple[str, ...] | None = None
    open_tag_feature_count: int | None = None
    features: tuple[dict[str, Any], ...] | None = None
    assignment_state: str | None = None
    assignments: tuple[dict[str, Any], ...] | None = None


def _readonly(database: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)


def _target_rows(path: Path) -> dict[str, dict[str, Any]]:
    targets = {identity for _, identity in ARTIST_COVERAGE_COHORT}
    found: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise TypeError(f"{path}:{line_number}: expected JSON object")
            identity = row.get("artist_mbid")
            if not isinstance(identity, str):
                continue
            if identity not in targets:
                continue
            if identity in found:
                raise ValueError(f"{path}:{line_number}: duplicate exact artist ID {identity}")
            found[identity] = row
    return found


def _community_summaries(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    communities = payload.get("communities")
    if not isinstance(communities, list):
        raise TypeError(f"{path}: expected communities list")
    result = {}
    for community in communities:
        if not isinstance(community, dict) or not isinstance(community.get("id"), str):
            continue
        descriptors = [
            {
                "namespace": row.get("namespace"),
                "value": row.get("value"),
                "support_count": row.get("support_count"),
            }
            for row in community.get("descriptors", [])
            if isinstance(row, dict)
        ]
        result[community["id"]] = {
            "label": community.get("label"),
            "level": community.get("level"),
            "descriptors": descriptors,
        }
    return result


def audit_artist_coverage(  # noqa: C901, PLR0913
    catalog_database: Path | None = None,
    *,
    feature_database: Path | None = None,
    genre_label_directory: Path | None = None,
    feature_jsonl: Path | None = None,
    name_jsonl: Path | None = None,
    assignments_jsonl: Path | None = None,
    communities_json: Path | None = None,
) -> tuple[ArtistCoverage, ...]:
    """Audit exact native IDs from optional SQLite and/or portable JSONL artifacts.

    Rich artist features and inferred assignments are read by MusicBrainz UUID
    directly from JSONL. They do not require the local SQLite catalog.
    """
    artists: dict[str, tuple[str | None, str | None]] = {}
    claims: dict[str, list[str]] = defaultdict(list)
    claim_count: dict[str, int] = defaultdict(int)
    seed_counts: dict[str, int] = {}
    if catalog_database is not None:
        with closing(_readonly(Path(catalog_database))) as catalog:
            artists = {
                str(mbid): (name, status)
                for mbid, name, status in catalog.execute(
                    "SELECT artist_mbid,canonical_name,name_status FROM artist"
                )
            }
            for mbid, genre_id in catalog.execute(
                "SELECT artist_mbid,musicbrainz_genre_id FROM direct_claim "
                "ORDER BY artist_mbid,musicbrainz_genre_id"
            ):
                identity = str(mbid)
                claims[identity].append(str(genre_id))
                claim_count[identity] += 1
            seed_counts = {
                str(mbid): int(count)
                for mbid, count in catalog.execute(
                    "SELECT artist_mbid,COUNT(*) FROM seed_artist GROUP BY artist_mbid"
                )
            }

    feature_counts: dict[str, int] = {}
    if feature_database is not None:
        with closing(_readonly(Path(feature_database))) as features:
            feature_counts = {
                str(mbid): int(count)
                for mbid, count in features.execute(
                    "SELECT artist_id,COUNT(*) FROM artist_tag_features GROUP BY artist_id"
                )
            }

    genre_names: dict[str, str] | None = None
    if genre_label_directory is not None:
        labels = verify_native_musicbrainz_genre_labels(directory=Path(genre_label_directory))
        genre_rows = cast("list[dict[str, object]]", labels["genres"])
        genre_names = {
            str(row["musicbrainz_genre_id"]): str(row["display_name"])
            for row in genre_rows
            if row["display_name"] is not None
        }

    feature_rows = _target_rows(Path(feature_jsonl)) if feature_jsonl else {}
    name_rows = _target_rows(Path(name_jsonl)) if name_jsonl else {}
    assignment_rows = _target_rows(Path(assignments_jsonl)) if assignments_jsonl else {}
    community_map = _community_summaries(Path(communities_json) if communities_json else None)

    results = []
    for cohort_name, mbid in ARTIST_COVERAGE_COHORT:
        catalog_name, status = artists.get(mbid, (None, None))
        name_row = name_rows.get(mbid, {})
        feature_row = feature_rows.get(mbid)
        assignment_row = assignment_rows.get(mbid)
        memberships = assignment_row.get("memberships", []) if assignment_row else None
        if memberships is not None:
            if not isinstance(memberships, list):
                raise ValueError(f"assignment memberships for {mbid} must be a list")
            enriched_memberships = []
            for membership in memberships:
                if not isinstance(membership, dict):
                    raise TypeError(f"assignment membership for {mbid} must be an object")
                community_id = membership.get("community_id")
                enriched_memberships.append(
                    {
                        **membership,
                        "community": community_map.get(community_id),
                    }
                )
            memberships = enriched_memberships
        features = feature_row.get("features") if feature_row else None
        if features is not None and not isinstance(features, list):
            raise ValueError(f"feature list for {mbid} must be a list")
        results.append(
            ArtistCoverage(
                cohort_name=cohort_name,
                artist_mbid=mbid,
                display_name=(
                    str(name_row["name"]) if isinstance(name_row.get("name"), str) else catalog_name
                ),
                catalog_name=catalog_name,
                name_status=status,
                direct_claim_count=claim_count.get(mbid, 0) if catalog_database else None,
                direct_seed_count=seed_counts.get(mbid, 0) if catalog_database else None,
                direct_genre_ids=tuple(claims.get(mbid, ())) if catalog_database else None,
                direct_genres=(
                    tuple(
                        genre_names[identity]
                        for identity in claims.get(mbid, ())
                        if identity in genre_names
                    )
                    if genre_names is not None
                    else None
                ),
                open_tag_feature_count=(
                    feature_counts.get(mbid, 0) if feature_database is not None else None
                ),
                features=tuple(features) if features is not None else None,
                assignment_state=(str(assignment_row.get("state")) if assignment_row else None),
                assignments=tuple(memberships) if memberships is not None else None,
            )
        )
    return tuple(results)
