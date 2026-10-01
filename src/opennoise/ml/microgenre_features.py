"""Build source-preserving, normalized artist features for microgenre discovery.

This module creates an offline candidate cache only.  It preserves facets and
evidence references, and intentionally has no access to historical placements.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

_NAMESPACES = {"artist_genre", "artist_tag", "release_genre", "release_tag", "area", "decade"}
_MIN_LABEL_LENGTH = 2
_LATEST_ABBREVIATED_DECADE = 20
_PURE_PLACE_TAGS = frozenset(
    {
        "uk",
        "u.k.",
        "united kingdom",
        "great britain",
        "british",
        "america",
        "american",
        "usa",
        "u.s.a.",
        "united states",
        "canada",
        "canadian",
        "new zealand",
        "new zealanders",
        "australia",
        "australian",
        "france",
        "french",
        "germany",
        "german",
        "japan",
        "japanese",
        "italy",
        "italian",
        "sweden",
        "swedish",
        "norway",
        "norwegian",
        "finland",
        "finnish",
        "romania",
        "romanian",
        "brazil",
        "brazilian",
        "mexico",
        "mexican",
        "spain",
        "spanish",
        "ireland",
        "irish",
        "scotland",
        "scottish",
        "wales",
        "welsh",
        "netherlands",
        "dutch",
        "belgium",
        "belgian",
        "poland",
        "polish",
        "russia",
        "russian",
        "china",
        "chinese",
        "south korea",
        "korean",
        "india",
        "indian",
        "argentina",
        "argentinian",
        "cuba",
        "cuban",
        "jamaica",
        "jamaican",
        "turkey",
        "turkish",
        "switzerland",
        "swiss",
        "greece",
        "greek",
        "portugal",
        "portuguese",
        "denmark",
        "danish",
        "iceland",
        "icelandic",
    }
)
_MUSICAL_COMPOUND_HEADS = frozenset(
    {
        "ambient",
        "bass",
        "blues",
        "breakbeat",
        "dance",
        "disco",
        "drum and bass",
        "dub",
        "electronica",
        "folk",
        "funk",
        "garage",
        "gospel",
        "hardcore",
        "hip hop",
        "house",
        "jazz",
        "metal",
        "noise",
        "pop",
        "punk",
        "r&b",
        "rap",
        "reggae",
        "rock",
        "soul",
        "techno",
        "trance",
        "wave",
    }
)
_MBID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_REJECT_PATTERNS = (
    re.compile(r"^(favorites?|favourites?|owned|wishlist|wantlist|loved tracks?)$"),
    re.compile(r"\b(last\.fm|spotify|scrobbl|tagging|musicbrainz|allmusic|rateyourmusic)\b"),
    re.compile(r"\b(male|female|woman|women|man|men|gay|lesbian|transgender|lgbtq?)\b"),
    re.compile(
        r"^(vocalist|singer|songwriter|producer|music producer|composer|dj|band|solo artist|"
        r"violinist|guitarist|pianist|drummer|bassist|cellist|saxophonist|trumpeter|"
        r"actor|actress|baritone|writer|arranger)$"
    ),
    re.compile(r"^(album|albums|track|tracks|song|songs|artist|artists|music)$"),
    re.compile(r"^(awesome|best|good|great|cool|beautiful|favorite|favourite)$"),
    re.compile(r"\b(private|personal|my collection|my tags)\b"),
    re.compile(r"^(white|vegan)$"),
    re.compile(r"\b(tiktok|youtube|youtuber|twitch|streamer|influencer|social media)\b"),
    re.compile(r"\b(debut|universal fire|fire victim)\b"),
)


def normalize_value(value: str) -> str:
    """Return the stable identity form required by the feature contract."""
    return " ".join(unicodedata.normalize("NFC", value).split()).casefold()


def _display(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _weight(count: object) -> float:
    """Dampen vote/count volume so duplicate or huge source counts cannot dominate."""
    if isinstance(count, bool) or not isinstance(count, (float, int)) or count <= 0:
        return 1.0
    return round(min(5.0, 1.0 + math.log1p(float(count)) / 4.0), 6)


def tag_rejection_reason(value: str) -> str | None:  # noqa: PLR0911
    """Return an explicit rejection code for nonmusical or junk tag values."""
    normalized = normalize_value(value)
    if normalized.startswith("_"):
        return "technical_private_metadata_tag"
    if len(normalized) < _MIN_LABEL_LENGTH:
        return "too_short"
    if not any(char.isalpha() for char in normalized):
        return "no_letters"
    if any(pattern.search(normalized) for pattern in _REJECT_PATTERNS):
        return "nonmusical_or_technical_tag"
    parts = normalized.split()
    if (
        len(parts) > 1
        and parts[0] in _PURE_PLACE_TAGS
        and parts[-1]
        in {
            "singer",
            "vocalist",
            "violinist",
            "guitarist",
            "pianist",
            "drummer",
            "bassist",
            "composer",
        }
    ):
        return "nonmusical_or_technical_tag"
    if "seen live" in normalized:
        return "nonmusical_or_technical_tag"
    if _decade_value(normalized):
        return "year_like_tag_use_decade_facet"
    return None


def _decade_value(normalized: str) -> str | None:
    if re.fullmatch(r"(?:19|20)\d0s", normalized):
        return normalized
    if match := re.fullmatch(r"(40|50|60|70|80|90|00|10|20)s", normalized):
        year = int(match.group(1))
        century = 2000 if year <= _LATEST_ABBREVIATED_DECADE else 1900
        return f"{century + year}s"
    return None


def _ref(value: object, fallback: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else fallback


def _source_ref(row: Mapping[str, Any], fallback: str) -> str:
    """Bind a feature to its source page and exact response bytes when known."""
    parts: list[str] = []
    for key in ("source_document", "source_request_url", "source_response_sha256"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return "|".join(parts) if parts else _ref(row.get("source_evidence_ref"), fallback)


def _make_feature(
    namespace: str, value: str, count: object, ref: str | list[str]
) -> dict[str, Any]:
    evidence_refs = [ref] if isinstance(ref, str) else ref
    return {
        "namespace": namespace,
        "value": normalize_value(value),
        "weight": _weight(count),
        "evidence_refs": sorted({item.strip() for item in evidence_refs if item.strip()}),
    }


def _add_tag(
    artist: str,
    raw: object,
    namespace: str,
    ref: str | list[str],
    rejected: list[dict[str, str]],
) -> dict[str, Any] | None:
    if isinstance(raw, str):
        label, count = raw, None
    elif isinstance(raw, Mapping):
        label, count = raw.get("name"), raw.get("count", raw.get("votes"))
    else:
        label, count = None, None
    if not isinstance(label, str) or not label.strip():
        rejected.append(
            {
                "artist_mbid": artist,
                "namespace": namespace,
                "raw_value": str(raw),
                "reason": "missing_label",
            }
        )
        return None
    if isinstance(count, (int, float)) and not isinstance(count, bool) and count <= 0:
        rejected.append(
            {
                "artist_mbid": artist,
                "namespace": namespace,
                "raw_value": _display(label),
                "reason": "nonpositive_source_count",
            }
        )
        return None
    reason = tag_rejection_reason(label)
    if reason:
        rejected.append(
            {
                "artist_mbid": artist,
                "namespace": namespace,
                "raw_value": _display(label),
                "reason": reason,
            }
        )
        return None
    return _make_feature(namespace, label, count, ref)


def _tag_label(raw: object) -> str | None:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, Mapping):
        label = raw.get("name")
        if isinstance(label, str):
            return label
    return None


def _add_label(
    artist: str,
    raw: object,
    namespace: str,
    ref: str | list[str],
    rejected: list[dict[str, str]],
) -> dict[str, Any] | None:
    if isinstance(raw, str):
        label, count = raw, None
    elif isinstance(raw, Mapping):
        label, count = raw.get("name", raw.get("label")), raw.get("count", raw.get("votes"))
    else:
        label, count = None, None
    if not isinstance(label, str) or not label.strip():
        rejected.append(
            {
                "artist_mbid": artist,
                "namespace": namespace,
                "raw_value": str(raw),
                "reason": "missing_label",
            }
        )
        return None
    if isinstance(count, (int, float)) and not isinstance(count, bool) and count <= 0:
        rejected.append(
            {
                "artist_mbid": artist,
                "namespace": namespace,
                "raw_value": _display(label),
                "reason": "nonpositive_source_count",
            }
        )
        return None
    return _make_feature(namespace, label, count, ref)


def _merge_feature(store: dict[tuple[str, str], dict[str, Any]], feature: dict[str, Any]) -> None:
    key = feature["namespace"], feature["value"]
    if key not in store:
        store[key] = feature
        return
    current = store[key]
    current["weight"] = max(current["weight"], feature["weight"])
    current["evidence_refs"] = sorted(set(current["evidence_refs"]) | set(feature["evidence_refs"]))


def build_microgenre_features(  # noqa: C901, PLR0912, PLR0915
    artist_records: Iterable[Mapping[str, Any]],
    *,
    release_records: Iterable[Mapping[str, Any]] = (),
    proper_genre_claims: Iterable[Any] = (),
    genre_labels: Mapping[str, str] | None = None,
    known_artist_names: Iterable[str] = (),
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Normalize artist, release, place, and decade facts into JSONL-ready rows.

    ``artist_records`` accepts the parity acquisition schema.  Verified genre
    IDs are converted to readable labels only through ``genre_labels``.
    Release records are facet-scoped and must name their credited artist MBID.
    """
    # Keeping source-specific filters, facet handling, and audit rejections in
    # one pass makes the resulting feature and rejection streams reproducible.
    artist_records = list(artist_records)
    labels = genre_labels or {}
    pure_place_tags = set(_PURE_PLACE_TAGS)
    for row in artist_records:
        for field in ("area", "begin_area"):
            area = row.get(field)
            if isinstance(area, Mapping) and isinstance(area.get("name"), str):
                pure_place_tags.add(normalize_value(area["name"]))
        country = row.get("country")
        if isinstance(country, str) and country.strip():
            pure_place_tags.add(normalize_value(country))
    artist_names = {
        row["artist_mbid"]: normalize_value(name)
        for row in artist_records
        if isinstance(row.get("artist_mbid"), str)
        and isinstance(
            name := row.get("name", row.get("artist_name", row.get("canonical_name"))), str
        )
        and name.strip()
    }
    global_artist_names = set(artist_names.values())
    global_artist_names.update(
        normalize_value(name)
        for name in known_artist_names
        if isinstance(name, str) and name.strip()
    )
    verified_genre_values = {normalize_value(label) for label in labels.values()}
    for row in artist_records:
        genres = row.get("genres")
        if isinstance(genres, list):
            for genre in genres:
                label = genre.get("name") if isinstance(genre, Mapping) else genre
                if isinstance(label, str) and label.strip():
                    verified_genre_values.add(normalize_value(label))
    features_by_artist: dict[str, dict[tuple[str, str], dict[str, Any]]] = defaultdict(dict)
    rejected: list[dict[str, str]] = []
    for index, row in enumerate(artist_records):
        artist = row.get("artist_mbid")
        if not isinstance(artist, str) or not _MBID.fullmatch(artist):
            rejected.append(
                {
                    "artist_mbid": str(artist or ""),
                    "namespace": "artist",
                    "raw_value": str(index),
                    "reason": "invalid_artist_mbid",
                }
            )
            continue
        fallback = f"native-artist:{artist}"
        source_ref = _source_ref(row, fallback)
        store = features_by_artist[artist]
        for raw in row.get("genres", []) if isinstance(row.get("genres", []), list) else []:
            feature = None
            if isinstance(raw, Mapping) and isinstance(raw.get("id"), str):
                label = labels.get(raw["id"], raw.get("name"))
                if isinstance(label, str) and label:
                    feature = _add_label(
                        artist,
                        {"name": label, "count": raw.get("count", raw.get("votes"))},
                        "artist_genre",
                        source_ref,
                        rejected,
                    )
                else:
                    rejected.append(
                        {
                            "artist_mbid": artist,
                            "namespace": "artist_genre",
                            "raw_value": raw["id"],
                            "reason": "unverified_genre_label_missing",
                        }
                    )
            else:
                feature = _add_label(artist, raw, "artist_genre", source_ref, rejected)
            if feature:
                _merge_feature(store, feature)
        for raw in row.get("tags", []) if isinstance(row.get("tags", []), list) else []:
            tag = _tag_label(raw)
            decade = _decade_value(normalize_value(tag)) if tag else None
            if decade:
                count = raw.get("count", raw.get("votes")) if isinstance(raw, Mapping) else None
                if isinstance(count, (int, float)) and not isinstance(count, bool) and count <= 0:
                    rejected.append(
                        {
                            "artist_mbid": artist,
                            "namespace": "decade",
                            "raw_value": _display(tag or ""),
                            "reason": "nonpositive_source_count",
                        }
                    )
                else:
                    _merge_feature(store, _make_feature("decade", decade, count, source_ref))
                continue
            if tag and normalize_value(tag) in pure_place_tags:
                rejected.append(
                    {
                        "artist_mbid": artist,
                        "namespace": "artist_tag",
                        "raw_value": _display(tag),
                        "reason": "place_or_nationality_tag_use_context_facet",
                    }
                )
                continue
            if tag and normalize_value(tag) == artist_names.get(artist):
                rejected.append(
                    {
                        "artist_mbid": artist,
                        "namespace": "artist_tag",
                        "raw_value": _display(tag),
                        "reason": "exact_artist_name_tag",
                    }
                )
                continue
            normalized_tag = normalize_value(tag) if tag else ""
            referenced_name = normalized_tag.removeprefix("otherartistname ")
            has_musical_head = any(
                referenced_name.endswith(f" {head}") or referenced_name.startswith(f"{head} ")
                for head in _MUSICAL_COMPOUND_HEADS
            )
            if (
                referenced_name in global_artist_names
                and normalized_tag not in verified_genre_values
                and not has_musical_head
            ):
                rejected.append(
                    {
                        "artist_mbid": artist,
                        "namespace": "artist_tag",
                        "raw_value": _display(tag or ""),
                        "reason": "artist_name_reference_tag",
                    }
                )
                continue
            feature = _add_tag(artist, raw, "artist_tag", source_ref, rejected)
            if feature:
                _merge_feature(store, feature)
        area = row.get("area")
        if isinstance(area, Mapping) and isinstance(area.get("name"), str):
            feature = _add_label(artist, area["name"], "area", source_ref, rejected)
            if feature:
                _merge_feature(store, feature)
        life = row.get("life_span", row.get("life-span"))
        begin = life.get("begin") if isinstance(life, Mapping) else None
        if isinstance(begin, str) and re.match(r"^\d{4}", begin):
            decade = f"{int(begin[:4]) // 10 * 10}s"
            _merge_feature(store, _make_feature("decade", decade, None, source_ref))

    for index, row in enumerate(release_records):
        artist_value = row.get("artist_mbid", row.get("artist_mbids"))
        artists = artist_value if isinstance(artist_value, list) else [artist_value]
        fallback = _ref(
            row.get("release_group_mbid"),
            _ref(row.get("release_group_id"), f"release-record:{index}"),
        )
        release_refs = row.get("evidence_refs")
        refs = (
            [value for value in release_refs if isinstance(value, str) and value.strip()]
            if isinstance(release_refs, list)
            else []
        )
        if not refs and isinstance(row.get("evidence_ref"), str):
            refs = [row["evidence_ref"]]
        sources = row.get("sources")
        if isinstance(sources, list):
            for source in sources:
                if isinstance(source, Mapping):
                    document = source.get("source_document")
                    digest = source.get("source_response_sha256")
                    if isinstance(document, str) and document.strip():
                        refs.append(document)
                    if isinstance(digest, str) and digest.strip():
                        refs.append(digest)
        if not refs:
            refs = [fallback]
        refs = sorted(set(refs))
        for artist in artists:
            if not isinstance(artist, str) or not _MBID.fullmatch(artist):
                rejected.append(
                    {
                        "artist_mbid": str(artist or ""),
                        "namespace": "release",
                        "raw_value": fallback,
                        "reason": "invalid_credit_artist_mbid",
                    }
                )
                continue
            store = features_by_artist[artist]
            first_release_date = row.get("first_release_date")
            if isinstance(first_release_date, str) and re.match(r"^\d{4}", first_release_date):
                release_decade = f"{int(first_release_date[:4]) // 10 * 10}s"
                _merge_feature(store, _make_feature("decade", release_decade, None, refs))
            for field, namespace in (("genres", "release_genre"), ("tags", "release_tag")):
                values = row.get(field, [])
                for raw in values if isinstance(values, list) else []:
                    feature_raw = raw
                    tag = _tag_label(raw)
                    decade = _decade_value(normalize_value(tag)) if tag else None
                    if namespace == "release_tag" and decade:
                        count = (
                            raw.get("count", raw.get("votes")) if isinstance(raw, Mapping) else None
                        )
                        if (
                            isinstance(count, (int, float))
                            and not isinstance(count, bool)
                            and count <= 0
                        ):
                            rejected.append(
                                {
                                    "artist_mbid": artist,
                                    "namespace": "decade",
                                    "raw_value": _display(tag or ""),
                                    "reason": "nonpositive_source_count",
                                }
                            )
                        else:
                            _merge_feature(store, _make_feature("decade", decade, count, refs))
                        continue
                    if (
                        namespace == "release_tag"
                        and tag
                        and normalize_value(tag) in pure_place_tags
                    ):
                        rejected.append(
                            {
                                "artist_mbid": artist,
                                "namespace": namespace,
                                "raw_value": _display(tag or ""),
                                "reason": "place_or_nationality_tag_use_context_facet",
                            }
                        )
                        continue
                    if namespace == "release_genre" and isinstance(raw, Mapping):
                        genre_id = raw.get("id", raw.get("musicbrainz_genre_id"))
                        if isinstance(genre_id, str):
                            label = labels.get(genre_id)
                            if not label:
                                rejected.append(
                                    {
                                        "artist_mbid": artist,
                                        "namespace": namespace,
                                        "raw_value": genre_id,
                                        "reason": "unverified_genre_label_missing",
                                    }
                                )
                                continue
                            feature_raw = {
                                "name": label,
                                "count": raw.get("count", raw.get("votes")),
                            }
                    tag = _tag_label(raw)
                    if (
                        namespace == "release_tag"
                        and tag
                        and normalize_value(tag) == artist_names.get(artist)
                    ):
                        rejected.append(
                            {
                                "artist_mbid": artist,
                                "namespace": namespace,
                                "raw_value": _display(tag),
                                "reason": "exact_artist_name_tag",
                            }
                        )
                        continue
                    normalized_tag = normalize_value(tag) if tag else ""
                    referenced_name = normalized_tag.removeprefix("otherartistname ")
                    has_musical_head = any(
                        referenced_name.endswith(f" {head}")
                        or referenced_name.startswith(f"{head} ")
                        for head in _MUSICAL_COMPOUND_HEADS
                    )
                    if (
                        namespace == "release_tag"
                        and referenced_name in global_artist_names
                        and normalized_tag not in verified_genre_values
                        and not has_musical_head
                    ):
                        rejected.append(
                            {
                                "artist_mbid": artist,
                                "namespace": namespace,
                                "raw_value": _display(tag or ""),
                                "reason": "artist_name_reference_tag",
                            }
                        )
                        continue
                    feature = (
                        _add_label(artist, feature_raw, namespace, refs, rejected)
                        if namespace == "release_genre"
                        else _add_tag(artist, feature_raw, namespace, refs, rejected)
                    )
                    if feature:
                        _merge_feature(store, feature)

    # Portable direct claims are supplied only after their custody verifier has
    # checked the source object.  The label dictionary is separately verified
    # by its caller and keeps opaque genre UUIDs out of model features.
    for index, raw_claim in enumerate(proper_genre_claims):
        claim = raw_claim
        if not isinstance(claim, Mapping) and callable(getattr(claim, "model_dump", None)):
            claim = claim.model_dump(mode="json")
        if not isinstance(claim, Mapping):
            rejected.append(
                {
                    "artist_mbid": "",
                    "namespace": "artist_genre",
                    "raw_value": str(index),
                    "reason": "malformed_verified_claim",
                }
            )
            continue
        artist = claim.get("artist_mbid")
        genre_id = claim.get("musicbrainz_genre_id", claim.get("genre_id"))
        if not isinstance(artist, str) or not _MBID.fullmatch(artist):
            rejected.append(
                {
                    "artist_mbid": str(artist or ""),
                    "namespace": "artist_genre",
                    "raw_value": str(index),
                    "reason": "invalid_verified_claim_artist_mbid",
                }
            )
            continue
        store = features_by_artist[artist]
        if not isinstance(genre_id, str) or genre_id not in labels:
            rejected.append(
                {
                    "artist_mbid": artist,
                    "namespace": "artist_genre",
                    "raw_value": str(genre_id or ""),
                    "reason": "unverified_genre_label_missing",
                }
            )
            continue
        ref = _ref(
            claim.get("source_evidence_ref"),
            _ref(claim.get("evidence_ref"), f"verified-proper-genre:{index}"),
        )
        feature = _add_label(artist, labels[genre_id], "artist_genre", ref, rejected)
        if feature:
            _merge_feature(store, feature)

    result = [
        {
            "artist_mbid": artist,
            "features": sorted(store.values(), key=lambda item: (item["namespace"], item["value"])),
        }
        for artist, store in sorted(features_by_artist.items())
    ]
    return result, rejected


def write_feature_artifacts(  # noqa: PLR0913
    rows: list[dict[str, Any]],
    rejected: list[dict[str, str]],
    *,
    inputs: Mapping[str, Path],
    output: Path,
    rejection_output: Path,
    receipt_output: Path,
) -> dict[str, Any]:
    """Write deterministic feature and rejection streams with an input-bound receipt."""
    output.parent.mkdir(parents=True, exist_ok=True)
    rejection_output.parent.mkdir(parents=True, exist_ok=True)
    receipt_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    rejection_output.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rejected
        ),
        encoding="utf-8",
    )
    receipt = {
        "revision": "microgenre-feature-cache-v1",
        "policy": "offline_candidate_only_no_historical_assignments_or_audio",
        "inputs": {
            name: {"path": str(path), "sha256": _sha256(path)}
            for name, path in sorted(inputs.items())
        },
        "artists": len(rows),
        "features": sum(len(row["features"]) for row in rows),
        "rejected_observations": len(rejected),
        "feature_sha256": _sha256(output),
        "rejections_sha256": _sha256(rejection_output),
    }
    receipt_output.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return receipt


def build_artist_name_overlay(
    artist_records: Iterable[Mapping[str, Any]],
    artist_ids: Iterable[str],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Keep readable display names outside model feature rows and report gaps."""
    selected = set(artist_ids)
    names: dict[str, dict[str, str]] = {}
    for row in artist_records:
        artist = row.get("artist_mbid")
        name = row.get("name", row.get("artist_name", row.get("canonical_name")))
        if (
            isinstance(artist, str)
            and artist in selected
            and isinstance(name, str)
            and name.strip()
        ):
            candidate = {
                "artist_mbid": artist,
                "name": _display(name),
                "evidence_ref": _source_ref(row, "artist-metadata"),
            }
            previous = names.get(artist)
            # Stable conflict handling: exact repeated names coalesce; distinct
            # source names are sorted and the lexical first is the deterministic
            # display choice, while every evidence reference remains recorded.
            if previous is None:
                names[artist] = candidate
            elif normalize_value(previous["name"]) == normalize_value(candidate["name"]):
                previous["evidence_ref"] = ",".join(
                    sorted(set(previous["evidence_ref"].split(",")) | {candidate["evidence_ref"]})
                )
            else:
                variants = sorted(
                    (previous["name"], candidate["name"]),
                    key=lambda value: (normalize_value(value), value),
                )
                refs = sorted(
                    set(previous["evidence_ref"].split(",")) | {candidate["evidence_ref"]}
                )
                names[artist] = {
                    "artist_mbid": artist,
                    "name": variants[0],
                    "evidence_ref": ",".join(refs),
                }
    found = [names[key] for key in sorted(names)]
    missing = [
        {"artist_mbid": artist, "reason": "no_verified_display_name_in_metadata_overlay"}
        for artist in sorted(selected - names.keys())
    ]
    return found, missing
