"""Bounded Wikidata artist-context claims joined by exact MusicBrainz IDs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final
from urllib.parse import urlparse
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field

ENDPOINT: Final = "https://query.wikidata.org/sparql"
PROPERTY_IDS: Final = {"P136", "P495", "P740", "P135"}
_MAX_ARTISTS: Final = 50
_MAX_RESPONSE_BYTES: Final = 2_000_000
_MAX_BINDINGS: Final = 1_000
_UUID_LENGTH: Final = 36


class CulturalClaim(BaseModel):
    """One direct Wikidata statement, retaining its independent property identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    musicbrainz_artist_id: str
    wikidata_artist_id: str
    property_id: str
    value_qid: str
    value_label: str | None = None
    source: str = ENDPOINT
    license: str = "CC0"


class CulturalArtistEvidence(BaseModel):
    """Claims for an exact MusicBrainz artist; no name-based identity resolution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    musicbrainz_artist_id: str
    wikidata_artist_id: str
    label: str | None = None
    claims: tuple[CulturalClaim, ...] = Field(max_length=200)


def build_query(musicbrainz_artist_ids: tuple[str, ...]) -> str:
    """Build a bounded query over exact MBIDs and four explicit context properties."""
    if not musicbrainz_artist_ids or len(musicbrainz_artist_ids) > _MAX_ARTISTS:
        raise ValueError("artist ID batch must contain between 1 and 50 IDs")
    if len(set(musicbrainz_artist_ids)) != len(musicbrainz_artist_ids):
        raise ValueError("artist ID batch must not contain duplicates")
    if any(not _is_uuid(value) for value in musicbrainz_artist_ids):
        raise ValueError("artist IDs must be canonical MusicBrainz UUIDs")
    values = " ".join(f'"{value}"' for value in sorted(musicbrainz_artist_ids))
    return f"""PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?mbid ?artist ?label ?property ?value ?valueLabel WHERE {{
  VALUES ?mbid {{ {values} }}
  ?artist wdt:P434 ?mbid.
  OPTIONAL {{ ?artist rdfs:label ?label. FILTER(LANG(?label) = "en") }}
  VALUES ?property {{ wdt:P136 wdt:P495 wdt:P740 wdt:P135 }}
  OPTIONAL {{
    ?artist ?property ?value.
    OPTIONAL {{ ?value rdfs:label ?valueLabel. FILTER(LANG(?valueLabel) = "en") }}
  }}
}}
LIMIT 1000"""


def capture_raw_response(
    musicbrainz_artist_ids: tuple[str, ...], *, client: httpx.Client | None = None
) -> tuple[str, bytes, int]:
    """Fetch one response, preserving its exact bytes under a hard 2 MB cap."""
    query = build_query(musicbrainz_artist_ids)
    owns_client = client is None
    session = client or httpx.Client(
        timeout=20.0,
        headers={
            "User-Agent": "OpenNoise/0.1 (open cultural metadata research)",
            "Accept": "application/sparql-results+json",
        },
    )
    try:
        with session.stream("GET", ENDPOINT, params={"query": query}) as response:
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_bytes(chunk_size=65_536):
                if len(body) + len(chunk) > _MAX_RESPONSE_BYTES:
                    raise ValueError("Wikidata response exceeds 2 MB cap")
                body.extend(chunk)
            status_code = response.status_code
    finally:
        if owns_client:
            session.close()
    return query, bytes(body), status_code


def fetch_artist_context(
    musicbrainz_artist_ids: tuple[str, ...], *, client: httpx.Client | None = None
) -> tuple[CulturalArtistEvidence, ...]:
    """Fetch at most 50 exact-ID artists; reject oversized or malformed responses."""
    _, body, _ = capture_raw_response(musicbrainz_artist_ids, client=client)
    payload = httpx.Response(200, content=body).json()
    return parse_bindings(payload, set(musicbrainz_artist_ids))


def parse_bindings(
    payload: Mapping[str, object], requested_ids: set[str]
) -> tuple[CulturalArtistEvidence, ...]:
    """Validate SPARQL rows and collapse them into stable claim records."""
    results = payload.get("results")
    if not isinstance(results, Mapping):
        raise TypeError("invalid SPARQL results structure")
    bindings = results.get("bindings")
    if not isinstance(bindings, list) or len(bindings) >= _MAX_BINDINGS:
        raise ValueError("SPARQL response reached the 1000-row cap; results may be truncated")
    labels: dict[tuple[str, str], str | None] = {}
    claims_by_artist: dict[tuple[str, str], set[tuple[str, str, str | None]]] = {}
    for binding in bindings:
        if not isinstance(binding, Mapping):
            raise TypeError("SPARQL binding must be an object")
        parsed = _parse_binding(binding, requested_ids)
        if parsed is None:
            continue
        mbid, artist_id, label, prop, value, value_label = parsed
        key = (mbid, artist_id)
        labels.setdefault(key, None)
        claims_by_artist.setdefault(key, set())
        if label is not None:
            labels[key] = label
        if prop is not None and value is not None:
            claims_by_artist[key].add((prop, value, value_label))
    return tuple(
        CulturalArtistEvidence(
            musicbrainz_artist_id=mbid,
            wikidata_artist_id=artist_id,
            label=labels[(mbid, artist_id)],
            claims=tuple(
                CulturalClaim(
                    musicbrainz_artist_id=mbid,
                    wikidata_artist_id=artist_id,
                    property_id=prop,
                    value_qid=value,
                    value_label=value_label,
                )
                for prop, value, value_label in sorted(claim_set)
            ),
        )
        for (mbid, artist_id), claim_set in sorted(claims_by_artist.items())
    )


def _parse_binding(
    binding: Mapping[str, object], requested_ids: set[str]
) -> tuple[str, str, str | None, str | None, str | None, str | None] | None:
    """Validate one SPARQL row and enforce requested identity and property bounds."""
    mbid = _literal(binding, "mbid")
    if mbid not in requested_ids:
        raise ValueError("response included an unrequested MusicBrainz ID")
    artist_id = _qid(binding, "artist")
    if artist_id is None:
        raise ValueError("SPARQL artist URI cannot be empty")
    label_binding = binding.get("label")
    label = None
    if isinstance(label_binding, Mapping) and label_binding.get("xml:lang") == "en":
        candidate_label = label_binding.get("value")
        if isinstance(candidate_label, str):
            label = candidate_label
    prop = _property(binding)
    value = _qid(binding, "value", optional=True)
    value_label_binding = binding.get("valueLabel")
    value_label = None
    if isinstance(value_label_binding, Mapping) and value_label_binding.get("xml:lang") == "en":
        candidate_label = value_label_binding.get("value")
        if isinstance(candidate_label, str):
            value_label = candidate_label
    return mbid, artist_id, label, prop, value, value_label


def _is_uuid(value: str) -> bool:
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _literal(binding: Mapping[str, object], key: str) -> str:
    value = binding.get(key)
    if not isinstance(value, Mapping) or not isinstance(value.get("value"), str):
        raise TypeError(f"SPARQL binding lacks {key}")
    return str(value["value"])


def _qid(binding: Mapping[str, object], key: str, *, optional: bool = False) -> str | None:
    value = binding.get(key)
    if value is None and optional:
        return None
    if not isinstance(value, Mapping) or not isinstance(value.get("value"), str):
        raise TypeError(f"SPARQL binding lacks {key} QID")
    parsed = urlparse(str(value["value"]))
    qid = parsed.path.rsplit("/", 1)[-1]
    if parsed.netloc != "www.wikidata.org" or parsed.path != f"/entity/{qid}" or not _is_qid(qid):
        raise ValueError(f"invalid Wikidata entity URI in {key}")
    return qid


def _is_qid(value: str) -> bool:
    return len(value) > 1 and value[0] == "Q" and value[1:].isdigit()


def _property(binding: Mapping[str, object]) -> str | None:
    value = binding.get("property")
    if not isinstance(value, Mapping) or not isinstance(value.get("value"), str):
        return None
    property_uri = str(value["value"])
    if not property_uri.startswith("http://www.wikidata.org/prop/direct/"):
        raise ValueError("response included a non-Wikidata property URI")
    prop = property_uri.rsplit("/", 1)[-1]
    if prop not in PROPERTY_IDS:
        raise ValueError("response included a property outside the requested set")
    return prop
