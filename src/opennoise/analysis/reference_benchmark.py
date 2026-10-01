"""Independent, eval-only Every Noise reference projections and coverage metrics."""

from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from typing import Any, override

from opennoise.adapters.everynoise import (
    adapt_quint_historical_representatives,
    adapt_quint_html,
)
from opennoise.analysis.everynoise_parity import normalized_name
from opennoise.common import sha256_json

ARTIST_ID = re.compile(
    r"(?:spotify:artist:|open\.spotify\.com/artist/)([A-Za-z0-9]{22})(?:[/?#\"']|$)"
)
VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
MAX_NEIGHBORS = 50
MAX_PAGE_BYTES = 2_000_000


class _ArtistParser(HTMLParser):
    """Read visible scanme names and artist IDs; never retain media attributes."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[dict[str, str]] = []
        self.active: dict[str, str] | None = None
        self.depth = 0
        self.parts: list[str] = []

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if self.active is not None:
            if tag not in VOID_TAGS:
                self.depth += 1
            return
        if tag == "div" and "scanme" in (attributes.get("class") or "").split():
            identifier = ARTIST_ID.search(attributes.get("onclick") or "")
            if identifier:
                self.active = {"source_artist_id": identifier.group(1)}
                self.parts = []
                self.depth = 0

    @override
    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Ignore self-closing nested markup without changing depth."""

    @override
    def handle_data(self, data: str) -> None:
        if self.active is not None and self.depth == 0:
            self.parts.append(data)

    @override
    def handle_endtag(self, tag: str) -> None:
        if self.active is None:
            return
        if self.depth:
            self.depth -= 1
        elif tag == "div":
            name = " ".join("".join(self.parts).split())
            if name:
                self.rows.append({**self.active, "artist_name": name})
            self.active = None


def parse_archived_artist_page(raw: bytes, *, genre_name: str) -> dict[str, Any]:
    """Extract bounded positive observations, without claiming complete membership."""
    if len(raw) > MAX_PAGE_BYTES:
        raise ValueError("archived artist page exceeds 2 MB bound")
    parser = _ArtistParser()
    parser.feed(raw.decode("utf-8", errors="strict"))
    parser.close()
    rows = {row["source_artist_id"]: row for row in parser.rows}
    if len(rows) != len(parser.rows):
        raise ValueError("duplicate artist identifiers in archived page")
    return {
        "genre_name": genre_name,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "members": list(rows.values()),
        "membership_completeness": "unverified_bounded_positive_observations",
        "rank_semantics": "document_order_not_representative_ranking",
    }


def build_reference_contract(raw: bytes, *, neighbor_count: int = 10) -> dict[str, Any]:
    """Bind pinned genre and representative observations outside construction inputs."""
    if not 1 <= neighbor_count <= MAX_NEIGHBORS:
        raise ValueError("neighbor count must be between 1 and 50")
    adaptation = adapt_quint_html(raw)
    representatives = adapt_quint_historical_representatives(raw)
    if adaptation.quarantine:
        raise ValueError("reference genre quarantine prevents evaluation")
    points = [(row.catalog.name, row.layout.x_px, row.layout.y_px) for row in adaptation.records]
    neighbors = {}
    for name, x, y in points:
        nearby = sorted(
            ((other, (x - ox) ** 2 + (y - oy) ** 2) for other, ox, oy in points if other != name),
            key=lambda row: (row[1], row[0]),
        )
        neighbors[name] = [row[0] for row in nearby[:neighbor_count]]
    genre_names = {row.catalog.external_id: row.catalog.name for row in adaptation.records}
    return {
        "revision": "everynoise-independent-reference-v1",
        "role": "evaluation_only_no_construction_or_training",
        "source_sha256": adaptation.source.sha256,
        "source_snapshot": adaptation.source.snapshot,
        "source_data_date": "2023-11-19",
        "live_site_verified": False,
        "genres": [point[0] for point in points],
        "geometry_neighbors": neighbors,
        "neighbor_semantics": "nearest_display_coordinates_not_editorial_similarity",
        "representatives": [
            {
                "genre_name": genre_names[row.genre_external_id],
                "artist_name": row.artist_name,
                "track_title": row.track_title,
                "recording_source_id": row.recording_source_id,
            }
            for row in representatives.records
        ],
        "representative_quarantine_count": len(representatives.quarantine),
        "memberships": [],
        "membership_completeness": "unavailable_pinned_map_is_not_membership_census",
    }


def _validate_projection(payload: dict[str, Any], *, reference: bool) -> None:
    """Reject malformed evaluation boundaries before computing denominators."""
    if not isinstance(payload, dict):
        raise TypeError("projection must be an object")
    genres = payload.get("genres")
    if not isinstance(genres, list) or any(
        not isinstance(name, str) or not name.strip() for name in genres
    ):
        raise ValueError("genres must be a list of nonempty names")
    neighbors = payload.get("geometry_neighbors", {})
    if not isinstance(neighbors, dict) or any(
        not isinstance(name, str)
        or not isinstance(values, list)
        or any(not isinstance(other, str) or not other.strip() for other in values)
        for name, values in neighbors.items()
    ):
        raise ValueError("geometry_neighbors must map names to lists of names")
    for field in ("memberships", "representatives"):
        rows = payload.get(field, [])
        if not isinstance(rows, list) or any(
            not isinstance(row, dict)
            or any(
                not isinstance(row.get(key), str) or not row[key].strip()
                for key in ("genre_name", "artist_name")
            )
            or (
                "recording_source_id" in row
                and (
                    not isinstance(row["recording_source_id"], str)
                    or re.fullmatch(r"[A-Za-z0-9]{22}", row["recording_source_id"]) is None
                )
            )
            for row in rows
        ):
            raise ValueError(f"{field} must contain named genre/artist observations")
    if reference:
        if not {"geometry_neighbors", "representatives"} <= payload.keys():
            raise ValueError("reference must declare neighbor and representative projections")
        digest = payload.get("source_sha256")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("reference must bind a valid source hash")


def evaluate_reference_contract(
    reference: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    """Report distinct coverage criteria; absence of reference evidence stays unknown."""
    _validate_projection(reference, reference=True)
    _validate_projection(candidate, reference=False)
    if reference.get("role") != "evaluation_only_no_construction_or_training":
        raise ValueError("reference must declare evaluation-only custody")
    genres = {normalized_name(name) for name in reference["genres"]}
    actual = {normalized_name(name) for name in candidate["genres"]}
    membership = _pair_metric(reference.get("memberships", []), candidate.get("memberships", []))
    representatives = _pair_metric(
        reference["representatives"], candidate.get("representatives", [])
    )
    recording_reference = {
        (normalized_name(row["genre_name"]), row["recording_source_id"])
        for row in reference["representatives"]
        if row.get("recording_source_id")
    }
    recording_candidate = {
        (normalized_name(row["genre_name"]), row["recording_source_id"])
        for row in candidate.get("representatives", [])
        if row.get("recording_source_id")
    }
    reference_neighbors = reference["geometry_neighbors"]
    candidate_neighbors = {
        normalized_name(name): {normalized_name(other) for other in values}
        for name, values in candidate.get("geometry_neighbors", {}).items()
    }
    expected_edges = sum(len(values) for values in reference_neighbors.values())
    matched_edges = sum(
        len(
            {normalized_name(other) for other in values}
            & candidate_neighbors.get(normalized_name(name), set())
        )
        for name, values in reference_neighbors.items()
    )
    return {
        "revision": "everynoise-independent-benchmark-v1",
        "scope": "local_evaluation_only",
        "reference_source_sha256": reference["source_sha256"],
        "reference_contract_sha256": sha256_json(reference),
        "candidate_projection_sha256": sha256_json(candidate),
        "genre_coverage": {
            "matched": len(genres & actual),
            "reference": len(genres),
            "recall": len(genres & actual) / len(genres) if genres else None,
        },
        "membership_positive_recovery": membership,
        "representative_artist_recovery": representatives,
        "representative_recording_recovery": {
            "matched": len(recording_reference & recording_candidate),
            "reference": len(recording_reference),
            "recall": len(recording_reference & recording_candidate) / len(recording_reference)
            if recording_reference
            else None,
        },
        "display_neighbor_recovery": {
            "matched": matched_edges,
            "reference": expected_edges,
            "recall": matched_edges / expected_edges if expected_edges else None,
        },
        "identity_method": "exact_normalized_name_diagnostic_not_identity_bridge",
        "overall_parity": False,
        "overall_percentage": None,
        "unknowns": ["complete_artist_memberships", "editorial_rankings", "listening_parity"],
    }


def _pair_metric(
    reference: list[dict[str, str]], candidate: list[dict[str, str]]
) -> dict[str, Any]:
    expected = {
        (normalized_name(row["genre_name"]), normalized_name(row["artist_name"]))
        for row in reference
    }
    actual = {
        (normalized_name(row["genre_name"]), normalized_name(row["artist_name"]))
        for row in candidate
    }
    return {
        "matched": len(expected & actual),
        "reference": len(expected),
        "recall": len(expected & actual) / len(expected) if expected else None,
        "status": "measured_positive_only" if expected else "unavailable",
    }
