"""Cache-only named musical values with separately typed source and inferred cohorts."""

from __future__ import annotations

import errno
import hashlib
import json
import math
import os
import re
import resource
import shutil
import sqlite3
import tempfile
import time
import zlib
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import numpy as np
from scipy import sparse

from opennoise.analysis.emergent_topic_holdout import musical_value
from opennoise.catalog.musicbrainz_candidate import require_local_candidate_destination
from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.deployment.community_preview import (
    validate_feature_proposals,
    verified_receipt,
    verify_feature_lineage,
)
from opennoise.deployment.style_artist_maps import (
    MIN_STYLE_SUPPORT,
    ArtistMapContext,
    map_context,
    style_artist_map,
)
from opennoise.ml.artist_feature_enrichment import EnrichmentModel, load_enrichment
from opennoise.ml.layout_lenses import build_weighted_spectral_coordinates
from opennoise.ml.semantic_layout.atlas import AtlasPoint, build_rectangular_atlas

ROLES = (
    "observed_artist_feature",
    "credited_release_context",
    "inferred_feature_proposal",
)
PAGE_SIZE = 100
MAX_ARTISTS = 250_000
MAX_VALUES = 50_000
RESOURCE_GUARD_REVISION = "named-style-resource-v2"
MAX_FEATURES = 5_000_000
MAX_ROW_VALUES = 512
MAX_PAIR_OBSERVATIONS = 50_000_000
MAX_PROPOSAL_SHARD_BYTES = 64 * 1024 * 1024
NEIGHBORS = 12
MINIMUM_JOINT_SUPPORT = 2
DEFAULT_BROWSE_SUPPORT = 5
DISPLAY_RECIPE_REVISION = "named-style-display-v4"
REVIEWED_NONSTYLE_LABELS = frozenset(
    {
        "27 club",
        "covid-19",
        "death by murder",
        "fixme",
        "model",
        "records",
        "komponist",
        "violinist",
        "violinists",
        "pianist",
        "pianists",
        "drummer",
        "drummers",
        "guitarist",
        "guitarists",
        "bassist",
        "bassists",
        "vocalist",
        "vocalists",
        "composer",
        "composers",
        "instrumentalist",
        "instrumentalists",
        "organist",
        "organists",
        "jazz musicians",
        "recording engineer",
        "recording engineers",
        "audio engineer",
        "audio engineers",
        "record producer",
        "record producers",
        "actor",
        "actress",
        "photographer",
        "american",
        "british",
        "canadian",
        "chinese",
        "czech",
        "dutch",
        "english",
        "french",
        "german",
        "greek",
        "hungarian",
        "irish",
        "israeli",
        "italian",
        "japanese",
        "korean",
        "lithuanian",
        "norwegian",
        "polish",
        "portuguese",
        "romanian",
        "russian",
        "spanish",
        "swedish",
        "swiss",
        "turkish",
        "welsh",
    }
)
type NamespaceSupport = dict[str, Counter[str]]


def style_id(value: str) -> str:
    """Bind stable routes to canonical source musical values, never display names."""
    return "style-" + hashlib.sha256(value.encode()).hexdigest()[:24]


def evidence_tier(value: str, support: int, native_ids: list[str]) -> str:
    """Choose a display tier; repeat support never validates a genre taxonomy."""
    if display_suppression_reason(value):
        return "raw_source_candidate"
    if native_ids:
        return "dictionary_named_style"
    raw_label = (
        any(mark in value for mark in ('"', "!", "http://", "https://", "[", "]"))
        or (value.startswith("'") and value.endswith("'"))
        or re.match(r"^(?:my |my:|i |our |favorite |favourite |seen live)", value) is not None
    )
    return (
        "repeated_source_candidate"
        if support >= DEFAULT_BROWSE_SUPPORT and not raw_label
        else "raw_source_candidate"
    )


def display_suppression_reason(value: str) -> str | None:
    """Suppress clear metadata labels from the default view without changing atoms."""
    if value in REVIEWED_NONSTYLE_LABELS:
        return "reviewed_nonstyle_label"
    if re.match(r"^top\s*\d+\b", value):
        return "ranking_label"
    if value.endswith((" records", " record label")):
        return "record_label_name"
    if (
        re.search(r"(?:^|\s)(?:sxsw|south by southwest|southbysouthwest)(?:\s|$)", value)
        or value in {"festival", "festivals", "music festival", "music festivals"}
        or re.search(r"\bfestivals?(?: \d{4})?$", value)
    ):
        return "event_or_festival_label"
    if re.search(r"\b(?:actor|actress|screenwriter|cinematographer|photographer)\b", value):
        return "biographical_role_label"
    return (
        "biographical_death_cause_label"
        if re.match(r"^death (?:by|from|due to)\s+\S", value)
        else None
    )


def source_memberships(row: dict[str, Any]) -> tuple[list[dict[str, Any]], set[str]]:
    """Keep direct source features and credited release context in separate roles."""
    memberships: dict[tuple[str, str], dict[str, Any]] = {}
    values = set()
    for feature in row["features"]:
        weight = feature.get("weight", 1)
        refs = feature.get("evidence_refs")
        if (
            isinstance(weight, bool)
            or not isinstance(weight, (int, float))
            or not math.isfinite(weight)
            or weight <= 0
            or not isinstance(refs, list)
            or not refs
            or any(not isinstance(ref, str) or not ref for ref in refs)
        ):
            raise ValueError("source features require finite positive weights and references")
        value = musical_value(feature)
        if value is None:
            continue
        values.add(value)
        role = (
            "credited_release_context"
            if feature["namespace"].startswith("release_")
            else "observed_artist_feature"
        )
        key = (value, role)
        membership = memberships.setdefault(
            key,
            {
                "style_id": style_id(value),
                "value": value,
                "role": role,
                "native_fact": False,
                "source_features": [],
            },
        )
        membership["source_features"].append(feature)
    if len(values) > MAX_ROW_VALUES:
        raise ValueError("artist exceeds bounded source musical values")
    return [memberships[key] for key in sorted(memberships)], values


def _require_pair_bound(matrix: sparse.csr_matrix) -> None:
    degrees = np.diff(matrix.indptr).astype(np.int64)
    if int(np.sum(degrees * degrees)) > MAX_PAIR_OBSERVATIONS:
        raise ValueError("source cooccurrence pair bound exceeded")


def source_positions(
    values: list[str],
    matrix: sparse.csr_matrix,
) -> tuple[dict[str, tuple[float, float]], list[dict[str, Any]], set[str]]:
    """Embed sparse source cooccurrence; identical support columns cannot separate."""
    _require_pair_bound(matrix)
    columns = matrix.tocsc()
    classes = defaultdict(list)
    support = np.asarray(matrix.sum(axis=0)).ravel()
    for column, value in enumerate(values):
        start, end = columns.indptr[column : column + 2]
        if end > start:
            classes[columns.indices[start:end].tobytes()].append(value)
    duplicates = {value for group in classes.values() if len(group) > 1 for value in group}
    joint = (matrix.T @ matrix).tocsr()
    weights: dict[tuple[str, str], float] = {}
    edges = {}
    for left, value in enumerate(values):
        if value in duplicates:
            continue
        start, end = joint.indptr[left : left + 2]
        ranked = []
        for right, count in zip(joint.indices[start:end], joint.data[start:end], strict=True):
            other = values[right]
            if left == right or other in duplicates or count < MINIMUM_JOINT_SUPPORT:
                continue
            score = float(count / np.sqrt(support[left] * support[right]))
            if 0 < score < 1 - 1e-10:
                ranked.append((score, other, int(count)))
        for score, other, count in sorted(ranked, key=lambda item: (-item[0], item[1]))[:NEIGHBORS]:
            left_id, right_id = sorted((style_id(value), style_id(other)))
            pair = (left_id, right_id)
            weights[pair] = score
            edges[pair] = {
                "style_ids": list(pair),
                "source_joint_artist_support": count,
                "weight": score,
                "role": "source_musical_cooccurrence",
            }
    connected = tuple(sorted({key for pair in weights for key in pair}))
    positions = {}
    if connected:
        coordinates = build_weighted_spectral_coordinates(connected, weights)
        atlas = build_rectangular_atlas(
            tuple(
                AtlasPoint(point.genre_id, float(point.x), float(point.y), str(point.component))
                for point in coordinates
            )
        )
        positions = {key: (round(x, 10), round(y, 10)) for key, (x, y) in atlas.positions.items()}
    return positions, [edges[pair] for pair in sorted(edges)], duplicates


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(value) + b"\n")


def _clone_file(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination)
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
        shutil.copyfile(source, destination)


def _pack(value: object) -> bytes:
    return zlib.compress(canonical_json(value))


def _unpack(value: bytes | None) -> list[dict[str, Any]]:
    return json.loads(zlib.decompress(value)) if value else []


def _prediction_receipt(directory: Path, digest: str) -> tuple[dict[str, Any], EnrichmentModel]:
    receipt = verified_receipt(directory, "prediction-receipt.json")
    if (
        receipt["scope"] not in {"local_research_only", "local_noncommercial_research"}
        or receipt["public_export_authorized"]
        or receipt["role"] != "inferred_feature_proposals"
        or receipt["training_sha256"] != digest
        or receipt["training_input_sha256"] != digest
        or any(
            receipt[key] is not False
            for key in ("audio_used", "historical_inputs_used", "native_fact", "scores_calibrated")
        )
        or "model/receipt.json" not in receipt["files"]
    ):
        raise ValueError("style proposals violate source-only inference boundary")
    model = load_enrichment(directory / "model")
    if model.training_sha256 != digest or model.model_sha256 != receipt["model_sha256"]:
        raise ValueError("style proposal model identity differs")
    return receipt, model


def _ingest(
    features: Path,
    database: sqlite3.Connection,
) -> tuple[list[str], sparse.csr_matrix, Counter[str], dict[str, set[str]], NamespaceSupport]:
    vocabulary: dict[str, int] = {}
    rows, columns = [], []
    totals: Counter[str] = Counter()
    labels: dict[str, set[str]] = defaultdict(set)
    namespace_support: NamespaceSupport = defaultdict(Counter)
    with features.open(encoding="utf-8") as stream:
        for index, line in enumerate(stream):
            row = json.loads(line)
            artist = row["artist_mbid"]
            if str(UUID(artist)) != artist or index >= MAX_ARTISTS:
                raise ValueError("invalid or excessive artist identities")
            memberships, values = source_memberships(row)
            totals["feature_observations"] += len(row["features"])
            totals["artists"] += 1
            if totals["feature_observations"] > MAX_FEATURES:
                raise ValueError("feature observation bound exceeded")
            database.execute(
                "INSERT INTO artists(mbid, source, proposals) VALUES (?, ?, NULL)",
                (artist, _pack(memberships)),
            )
            for membership in memberships:
                value = membership["value"]
                namespaces = set()
                for feature in membership["source_features"]:
                    labels[value].add(feature["value"])
                    namespaces.add(feature["namespace"])
                for namespace in namespaces:
                    namespace_support[value][namespace] += 1
                database.execute(
                    "INSERT INTO members VALUES (?, ?, ?, NULL)",
                    (style_id(value), membership["role"], artist),
                )
                totals[membership["role"]] += 1
            for value in sorted(values):
                if value not in vocabulary:
                    vocabulary[value] = len(vocabulary)
                rows.append(index)
                columns.append(vocabulary[value])
            if len(vocabulary) > MAX_VALUES:
                raise ValueError("source vocabulary bound exceeded")
    database.commit()
    values = sorted(vocabulary)
    matrix = sparse.csr_matrix(
        (np.ones(len(rows)), (rows, columns)), shape=(totals["artists"], len(values))
    )
    ordered = cast("sparse.csr_matrix", matrix[:, [vocabulary[value] for value in values]].tocsr())
    return values, ordered, totals, labels, namespace_support


def _proposal_support(
    proposal: dict[str, Any],
    memberships: list[dict[str, Any]],
    model: EnrichmentModel,
) -> None:
    column = model.value_index.get(proposal["value"])
    if column is None or model.target_support[column] <= 0:
        raise ValueError("proposal target lacks source musical support")
    if proposal["training_target_artist_support"] != int(model.target_support[column]):
        raise ValueError("proposal target support differs from bound model")
    for cue in proposal["evidence"]:
        cue_memberships = [
            membership for membership in memberships if membership["value"] == cue["value"]
        ]
        refs = {
            feature_ref
            for membership in cue_memberships
            for feature in membership["source_features"]
            for feature_ref in feature["evidence_refs"]
        }
        proper_cue_present = any(
            feature["namespace"] == "artist_genre"
            for membership in cue_memberships
            for feature in membership["source_features"]
        )
        cue_index = model.cue_index.get((cue["cue_role"], cue["value"]))
        if (
            cue_index is None
            or (cue["cue_role"] == "proper_genre" and not proper_cue_present)
            or cue["training_joint_artist_support"] != int(model.joint_support[cue_index, column])
            or cue["training_cue_artist_support"] != int(model.cue_support[cue_index])
            or not set(cue["query_evidence_refs"]).issubset(refs)
        ):
            raise ValueError("proposal cue differs from bound source/model")


def _proposals(
    directory: Path,
    receipt: dict[str, Any],
    model: EnrichmentModel,
    database: sqlite3.Connection,
    totals: Counter[str],
) -> None:
    seen = set()
    for relative in sorted(receipt["files"]):
        if not relative.startswith("feature-proposals/") or not relative.endswith(".json"):
            continue
        if receipt["files"][relative]["bytes"] > MAX_PROPOSAL_SHARD_BYTES:
            raise ValueError("proposal shard exceeds bounded parser size")
        records = json.loads((directory / relative).read_bytes())["artists"]
        for artist, record in records.items():
            source = database.execute(
                "SELECT source FROM artists WHERE mbid=?", (artist,)
            ).fetchone()
            if source is None or artist in seen:
                raise ValueError("proposal artist differs from exact feature corpus")
            seen.add(artist)
            memberships = _unpack(source[0])
            known = {membership["value"] for membership in memberships}
            if set(record["observed_music_values"]) != known:
                raise ValueError("proposal observed values differ from exact source features")
            validate_feature_proposals(record, model.training_sha256, model.model_sha256)
            for proposal in record["feature_proposals"]:
                value = proposal["value"]
                _proposal_support(proposal, memberships, model)
                database.execute(
                    "INSERT INTO members VALUES (?, ?, ?, ?)",
                    (style_id(value), ROLES[2], artist, proposal["score"]),
                )
                totals[ROLES[2]] += 1
            database.execute(
                "UPDATE artists SET proposals=? WHERE mbid=?",
                (_pack(record["feature_proposals"]), artist),
            )
        database.commit()
    if len(seen) != totals["artists"]:
        raise ValueError("proposal projection omits exact source artists")


def _profiles(
    source: Path,
    receipt: dict[str, Any],
    output: Path,
    database: sqlite3.Connection,
    fallbacks: dict[str, dict[str, Any]],
) -> None:
    for (prefix,) in database.execute("SELECT DISTINCT substr(mbid,1,3) FROM artists ORDER BY 1"):
        relative = f"artists/{prefix}.json"
        if relative not in receipt["files"]:
            raise ValueError("artist name shard lacks source binding")
        profiles = json.loads((source / relative).read_bytes())["artists"]
        result = {}
        for artist, memberships, proposals in database.execute(
            "SELECT mbid, source, proposals FROM artists WHERE mbid>=? AND mbid<? ORDER BY mbid",
            (prefix, prefix + "~"),
        ):
            if artist not in profiles:
                raise ValueError("exact feature artist lacks verified source profile")
            profile = {**profiles[artist]}
            if profile["name_status"] == "unresolved" and artist in fallbacks:
                profile.update(
                    name=fallbacks[artist]["name"],
                    name_status="exact_verified_bulk_name_fallback",
                    name_evidence_ref=fallbacks[artist]["evidence_ref"],
                )
            database.execute("UPDATE artists SET name=? WHERE mbid=?", (profile["name"], artist))
            database.execute(
                "INSERT INTO artist_names VALUES (?, ?, ?)",
                (artist, profile["name"], profile["name_status"]),
            )
            inferred = [
                {**proposal, "style_id": style_id(proposal["value"])}
                for proposal in _unpack(proposals)
            ]
            result[artist] = {
                **profile,
                "artist_mbid": artist,
                "style_memberships": _unpack(memberships) + inferred,
            }
        _write(output / relative, {"artists": result})
        database.commit()


def _cohorts(output: Path, database: sqlite3.Connection, styles: list[dict[str, Any]]) -> None:
    database.create_function("CASEFOLD", 1, str.casefold, deterministic=True)
    for style in styles:
        cohorts = {}
        for role in ROLES:
            count = database.execute(
                "SELECT count(*) FROM members WHERE style=? AND role=?", (style["id"], role)
            ).fetchone()[0]
            pages = []
            cursor = database.execute(
                "SELECT m.artist, a.name, m.score FROM members m JOIN artists a ON a.mbid=m.artist "
                "WHERE m.style=? AND m.role=? ORDER BY CASEFOLD(a.name), m.artist",
                (style["id"], role),
            )
            while batch := cursor.fetchmany(PAGE_SIZE):
                relative = f"cohorts/{style['id']}/{role}/{len(pages)}.json"
                pages.append(relative)
                _write(
                    output / relative,
                    {
                        "style_id": style["id"],
                        "role": role,
                        "native_fact": False,
                        "page": len(pages) - 1,
                        "artist_count": count,
                        "artists": [
                            {
                                "artist_mbid": artist,
                                "name": name,
                                "score": score,
                                "profile_path": f"artists/{artist[:3]}.json",
                            }
                            for artist, name, score in batch
                        ],
                    },
                )
            cohorts[role] = {"artist_count": count, "pages": pages}
        style["counts"] = {role: cohorts[role]["artist_count"] for role in ROLES}
        style["source_artist_support"] = database.execute(
            "SELECT count(DISTINCT artist) FROM members WHERE style=? AND role!=?",
            (style["id"], ROLES[2]),
        ).fetchone()[0]
        style["evidence_tier"] = evidence_tier(
            style["name"],
            style["source_artist_support"],
            style.get("native_genre_ids", []),
        )
        style["default_visible"] = style["evidence_tier"] != "raw_source_candidate"
        style["display_recipe_revision"] = DISPLAY_RECIPE_REVISION
        style["display_suppression_reason"] = display_suppression_reason(style["name"])
        style["detail_path"] = f"styles/{style['id']}.json"
        _write(output / style["detail_path"], {**style, "cohorts": cohorts})


def _assets(
    source: Path, receipt: dict[str, Any], output: Path, database: sqlite3.Connection
) -> None:
    relative = "artist-search.json"
    if relative not in receipt["files"]:
        raise ValueError("artist search lacks verified source binding")
    search = json.loads((source / relative).read_bytes())["artists"]
    expected = {row[0] for row in database.execute("SELECT mbid FROM artists")}
    if len(search) != len(expected) or {row[0] for row in search} != expected:
        raise ValueError("source artist search differs from exact feature corpus")
    names = {
        row[0]: row[1:] for row in database.execute("SELECT mbid,name,status FROM artist_names")
    }
    projected = [[row[0], *names[row[0]]] for row in search]
    projected.sort(key=lambda row: (row[1].casefold(), row[0]))
    _write(output / relative, {"artists": projected})
    static = Path(__file__).resolve().parents[1] / "static"
    for suffix in ("html", "css", "js"):
        name = f"style-atlas.{suffix}"
        shutil.copyfile(static / name, output / ("index.html" if suffix == "html" else name))


def _missing_name_ids(
    features: Path, receipt: dict[str, Any], known: set[str], named: set[str]
) -> set[str]:
    missing_overlay = features.parent / "missing-artist-names.jsonl"
    if sha256_file(missing_overlay)[0] != receipt["missing_names_sha256"]:
        raise ValueError("missing artist name overlay differs from feature receipt")
    missing: set[str] = set()
    with missing_overlay.open(encoding="utf-8") as stream:
        for line in stream:
            artist = json.loads(line)["artist_mbid"]
            if artist not in known or artist in named or artist in missing:
                raise ValueError("missing name overlay does not match exact source corpus")
            missing.add(artist)
    return missing


def _fallback_names(
    source: Path, features: Path, receipt: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    if "name_overlay_sha256" not in receipt:
        return {}
    overlay = features.parent / "artist-names.jsonl"
    if sha256_file(overlay)[0] != receipt["name_overlay_sha256"]:
        raise ValueError("artist name fallback overlay differs from feature receipt")
    search = json.loads((source / "artist-search.json").read_bytes())["artists"]
    known = {row[0] for row in search}
    unresolved = {row[0] for row in search if row[2] == "unresolved"}
    seen = set()
    result = {}
    with overlay.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            artist = row["artist_mbid"]
            if artist not in known or artist in seen:
                raise ValueError("name overlay does not match exact source corpus")
            seen.add(artist)
            if artist in unresolved and row.get("name"):
                if not re.search(r"mbdump/artist:row:\d+:sha256:[0-9a-f]{64}", row["evidence_ref"]):
                    raise ValueError("bulk fallback name lacks exact artist-row provenance")
                result[artist] = row
    if seen | _missing_name_ids(features, receipt, known, seen) != known:
        raise ValueError("name overlays omit source corpus identities")
    return result


def _artist_maps(
    output: Path,
    database: sqlite3.Connection,
    styles: list[dict[str, Any]],
    context: ArtistMapContext,
    bindings: dict[str, str],
) -> dict[str, Any]:
    totals: Counter[str] = Counter()
    for style in styles:
        style["artist_map_status"] = "not_default_source_supported_style"
        if style["default_visible"] and style["source_artist_support"] >= MIN_STYLE_SUPPORT:
            members = defaultdict(list)
            for artist, role in database.execute(
                "SELECT artist,role FROM members WHERE style=? AND role!=? ORDER BY artist,role",
                (style["id"], ROLES[2]),
            ):
                members[artist].append(role)
            payload = style_artist_map(context, style["id"], dict(members))
            payload.update(bindings)
            for row in payload["artists"]:
                name, status = database.execute(
                    "SELECT name,status FROM artist_names WHERE mbid=?", (row["artist_mbid"],)
                ).fetchone()
                row.update(name=name, name_status=status)
            style["artist_map_path"] = f"style-artist-maps/{style['id']}.json"
            style["artist_map_status"] = "ready" if payload["positioned_count"] else "abstained"
            _write(output / style["artist_map_path"], payload)
            totals["map_count"] += 1
            for key in (
                "selected_count",
                "positioned_count",
                "abstained_count",
                "layout_edge_count",
            ):
                totals[key] += payload[key]
        detail_path = output / style["detail_path"]
        detail = json.loads(detail_path.read_bytes())
        detail.update(style)
        _write(detail_path, detail)
    return {
        "role": "inferred_source_artist_profile_maps",
        "scope": "local_research_only",
        "usable_canonical_music_values": len(context.vocabulary),
        **totals,
    }


def build_style_atlas(
    *,
    source: Path,
    features: Path,
    enrichment_directory: Path,
    output: Path,
    artist_maps: bool = False,
) -> dict[str, Any]:
    """Fit and export a fresh complete local candidate style atlas from verified caches."""
    require_local_candidate_destination(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing to replace a named style atlas")
    started = time.monotonic()
    feature_receipt = verify_feature_lineage(features)
    source_receipt = verified_receipt(source, "preview-receipt.json")
    if (
        source_receipt["scope"] != "local_research_only"
        or source_receipt["public_export_authorized"]
    ):
        raise ValueError("unsupported source profile boundary")
    prediction, model = _prediction_receipt(enrichment_directory, feature_receipt["feature_sha256"])
    fallbacks = _fallback_names(source, features, feature_receipt)
    map_summary = None
    output.parent.mkdir(parents=True, exist_ok=True)
    with (
        tempfile.TemporaryDirectory(dir=output.parent, prefix="style-atlas-work-") as temporary,
        closing(sqlite3.connect(Path(temporary) / "stage.sqlite")) as database,
    ):
        database.executescript(
            "CREATE TABLE artists(mbid TEXT PRIMARY KEY, source TEXT, "
            "proposals TEXT, name TEXT);"
            "CREATE TABLE artist_names(mbid TEXT PRIMARY KEY,name TEXT,status TEXT);"
            "CREATE TABLE members(style TEXT, role TEXT, artist TEXT, score REAL, "
            "PRIMARY KEY(style, role, artist));"
        )
        values, matrix, totals, labels, namespace_support = _ingest(features, database)
        if (
            totals["artists"] != feature_receipt["artists"]
            or totals["feature_observations"] != feature_receipt["features"]
        ):
            raise ValueError("source feature receipt counts differ")
        if tuple(values) != model.vocabulary:
            raise ValueError("bound model vocabulary differs from clean source values")
        _proposals(enrichment_directory, prediction, model, database, totals)
        positions, edges, duplicates = source_positions(values, matrix)
        dictionary_path = (
            Path(__file__).resolve().parents[3] / feature_receipt["inputs"]["genre_labels"]["path"]
        )
        dictionary = json.loads(dictionary_path.read_bytes())
        native = defaultdict(list)
        for genre in dictionary["genres"]:
            native[genre["canonical_name"]].append(genre["musicbrainz_genre_id"])
        styles = []
        for value in values:
            key = style_id(value)
            x, y = positions.get(key, (None, None))
            styles.append(
                {
                    "id": key,
                    "name": value,
                    "aliases": sorted(labels[value]),
                    "x": x,
                    "y": y,
                    "role": "candidate_named_style",
                    "native_fact": False,
                    "layout_status": "positioned_source_musical_cooccurrence"
                    if key in positions
                    else (
                        "abstained_identical_source_support"
                        if value in duplicates
                        else "abstained_no_distinct_supported_neighbors"
                    ),
                    "native_genre_ids": sorted(native.get(value, [])),
                    "native_dictionary_join": "exact_canonical_name_only",
                    "source_namespace_artist_support": dict(namespace_support[value]),
                }
            )
        output.mkdir()
        _profiles(source, source_receipt, output, database, fallbacks)
        _cohorts(output, database, styles)
        if artist_maps:
            artist_ids = tuple(
                row[0] for row in database.execute("SELECT mbid FROM artists ORDER BY rowid")
            )
            context = map_context(artist_ids, values, matrix)
            map_summary = _artist_maps(
                output,
                database,
                styles,
                context,
                {
                    "features_sha256": feature_receipt["feature_sha256"],
                    "source_model_sha256": model.model_sha256,
                },
            )
        _assets(source, source_receipt, output, database)
        totals["named_artists"] = database.execute(
            "SELECT count(*) FROM artist_names WHERE status!='unresolved'"
        ).fetchone()[0]
        totals["unresolved_artist_names"] = totals["artists"] - totals["named_artists"]
        totals["bulk_name_fallbacks"] = len(fallbacks)
    _write(
        output / "source-geometry.json",
        {
            "style_ids": [style["id"] for style in styles],
            "edges": edges,
            "features_sha256": feature_receipt["feature_sha256"],
            "minimum_joint_artist_support": MINIMUM_JOINT_SUPPORT,
            "neighbors_per_style": NEIGHBORS,
            "proposed_memberships_used_for_geometry": False,
        },
    )
    coverage: dict[str, Any] = {
        **totals,
        "styles": len(styles),
        "positioned_styles": len(positions),
        "unpositioned_styles": len(styles) - len(positions),
        "geometry_edges": len(edges),
        "evidence_tier_counts": dict(Counter(style["evidence_tier"] for style in styles)),
        "default_visible_styles": sum(1 for style in styles if style["default_visible"]),
        "default_positioned_styles": sum(
            1 for style in styles if style["default_visible"] and style["id"] in positions
        ),
    }
    _write(
        output / "data.json",
        {
            "revision": "named-source-style-atlas-v1",
            "scope": "local_research_only",
            "public_export_authorized": False,
            "role": "candidate_named_styles",
            "native_fact": False,
            "styles": styles,
            "coverage": coverage,
            "layout_method": "source_musical_cooccurrence_cosine_spectral_rectangular_atlas",
            "artist_order": "display_name_casefold_then_exact_mbid_not_relevance",
            "page_size": PAGE_SIZE,
            "artist_shard_prefix_length": 3,
            "artist_search_path": "artist-search.json",
            "artist_maps": map_summary,
            "default_browse_source_artist_support": DEFAULT_BROWSE_SUPPORT,
            "display_recipe_revision": DISPLAY_RECIPE_REVISION,
            "evidence_tier_semantics": {
                "dictionary_named_style": "Exact dictionary name only; no artist fact promotion",
                "repeated_source_candidate": "At least 5 distinct source artists; unreviewed label",
                "raw_source_candidate": "Rare or raw source label; no genre validation",
            },
        },
    )
    receipt = {
        "revision": "named-source-style-atlas-v1",
        "scope": "local_research_only",
        "public_export_authorized": False,
        "serving_authorized": False,
        "features_sha256": feature_receipt["feature_sha256"],
        "feature_receipt_sha256": sha256_file(features.parent / "receipt.json")[0],
        "source_preview_output_sha256": source_receipt["output_sha256"],
        "prediction_output_sha256": prediction["output_sha256"],
        "model_sha256": model.model_sha256,
        "builder_sha256": sha256_file(Path(__file__))[0],
        "native_dictionary_sha256": feature_receipt["inputs"]["genre_labels"]["sha256"],
        "name_overlay_sha256": feature_receipt.get("name_overlay_sha256"),
        "artist_maps": map_summary,
        "stage_storage": "zlib_compressed_source_and_proposal_json_in_sqlite",
        "code_bindings": {
            relative: sha256_file(Path(__file__).resolve().parents[3] / relative)[0]
            for relative in (
                "src/opennoise/deployment/style_atlas.py",
                "src/opennoise/deployment/style_artist_maps.py",
                "src/opennoise/deployment/community_preview.py",
                "src/opennoise/analysis/emergent_topic_holdout.py",
                "src/opennoise/ml/emergent_topics.py",
                "src/opennoise/ml/artist_feature_enrichment.py",
                "src/opennoise/ml/layout_lenses.py",
                "src/opennoise/ml/semantic_layout/atlas.py",
                "src/opennoise/common/hashing.py",
            )
        },
        "resources": {
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "maximum_source_pair_observations": MAX_PAIR_OBSERVATIONS,
            "maximum_proposal_shard_bytes": MAX_PROPOSAL_SHARD_BYTES,
            "maximum_source_values": MAX_VALUES,
            "resource_guard_revision": RESOURCE_GUARD_REVISION,
        },
        "native_genre_memberships_added": 0,
        "artist_names_used_for_construction": False,
        "audio_inputs_used": False,
        "historical_inputs_used": False,
        "external_gold_used": False,
        "source_licenses": {
            "core": feature_receipt["musicbrainz_core_metadata_license"],
            "tags": feature_receipt["musicbrainz_open_tags_license"],
        },
        "derived_output_obligations": feature_receipt["derived_output_obligations"],
        "coverage": coverage,
        "files": {
            path.relative_to(output).as_posix(): {
                "sha256": sha256_file(path)[0],
                "bytes": path.stat().st_size,
            }
            for path in sorted(output.rglob("*"))
            if path.is_file()
        },
    }
    receipt["output_sha256"] = sha256_json(receipt)
    _write(output / "receipt.json", receipt)
    return receipt


def refresh_style_atlas_display(*, source: Path, output: Path) -> dict[str, Any]:
    """Clone a verified atlas and rebind only versioned display tiers and UI assets."""
    require_local_candidate_destination(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing to replace a named style atlas")
    prior = verified_receipt(source, "receipt.json")
    if prior["scope"] != "local_research_only" or prior["public_export_authorized"]:
        raise ValueError("unsupported display refresh source")
    output.mkdir(parents=True)
    for relative in prior["files"]:
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        _clone_file(source / relative, destination)
    data = json.loads((output / "data.json").read_bytes())
    for style in data["styles"]:
        style["evidence_tier"] = evidence_tier(
            style["name"], style["source_artist_support"], style["native_genre_ids"]
        )
        style["default_visible"] = style["evidence_tier"] != "raw_source_candidate"
        style["display_recipe_revision"] = DISPLAY_RECIPE_REVISION
        style["display_suppression_reason"] = display_suppression_reason(style["name"])
        detail_path = output / style["detail_path"]
        detail = json.loads(detail_path.read_bytes())
        detail.update(style)
        temporary = detail_path.with_suffix(".tmp")
        _write(temporary, detail)
        temporary.replace(detail_path)
    coverage = data["coverage"]
    coverage.update(
        {
            "evidence_tier_counts": dict(
                Counter(style["evidence_tier"] for style in data["styles"])
            ),
            "default_visible_styles": sum(
                1 for style in data["styles"] if style["default_visible"]
            ),
            "default_positioned_styles": sum(
                1 for style in data["styles"] if style["default_visible"] and style["x"] is not None
            ),
        }
    )
    data["display_recipe_revision"] = DISPLAY_RECIPE_REVISION
    _write(output / "data.tmp", data)
    (output / "data.tmp").replace(output / "data.json")
    static = Path(__file__).resolve().parents[1] / "static"
    for suffix in ("html", "css", "js"):
        name = f"style-atlas.{suffix}"
        destination = output / ("index.html" if suffix == "html" else name)
        temporary = destination.with_suffix(".tmp")
        shutil.copyfile(static / name, temporary)
        temporary.replace(destination)
    receipt = {
        **prior,
        "coverage": coverage,
        "display_recipe_revision": DISPLAY_RECIPE_REVISION,
        "source_atlas_output_sha256": prior["output_sha256"],
        "source_atlas_builder_sha256": prior["builder_sha256"],
        "source_atlas_code_bindings": prior["code_bindings"],
        "builder_sha256": sha256_file(Path(__file__))[0],
        "derivation_method": "verified_clone_with_display_only_changes",
        "clone_storage": "hardlinks_with_cross_device_copy_fallback_and_atomic_replacements",
    }
    receipt["code_bindings"] = {
        relative: sha256_file(Path(__file__).resolve().parents[3] / relative)[0]
        for relative in prior["code_bindings"]
    }
    receipt["files"] = {
        path.relative_to(output).as_posix(): {
            "sha256": sha256_file(path)[0],
            "bytes": path.stat().st_size,
        }
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }
    receipt.pop("output_sha256")
    receipt["output_sha256"] = sha256_json(receipt)
    _write(output / "receipt.json", receipt)
    return receipt
