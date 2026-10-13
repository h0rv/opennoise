"""Strictly offline, source-bound two-listener pilot; never creates musical judgments."""

# ruff: noqa: E501, PLR2004 -- frozen pilot sizes and human-readable protocol text.

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from opennoise.common import canonical_json
from opennoise.deployment.fma_genre_discovery import genre_index
from opennoise.ingest.fma.corpus import project_row, source_rows, verify_sources
from opennoise.serving.metadata.fma_listening import LICENSES

type Record = dict[str, Any]

REVISION = "fma-independent-audition-reconstruction-v1"
SEED = "opennoise-independent-audition-20261013-v1"
MAX_CONTROL = 2_000_000
MAX_CLIP = 2_000_000
MAX_SLOT_AUDIO = 64_000_000
CREDIT_FIELDS = (
    "track_id",
    "title",
    "artist_id",
    "artist_name",
    "attribution",
    "composer",
    "copyright_c",
    "copyright_p",
    "license_title",
    "license_url",
    "source_url",
    "duration_seconds",
    "audio_sha256",
    "audio_bytes",
)
ANSWER_FIELDS = (
    "item_id",
    "reviewer_slot",
    "reviewer_id",
    "review_date",
    "region",
    "familiarity_0_4",
    "conflict_description",
    "heard_all_exact_clips",
    "playback_failure",
    "unsure",
    "unsupported",
    "fit_1_5",
    "introduction_useful_1_5",
    "diversity_limits",
    "sonic_preference",
    "cultural_preference",
    "confidence_1_5",
    "notes",
)
RULES = {
    "reviewers_per_item": 2,
    "operational_complete": "Both listeners supply access and rating-or-unsure responses on at least 10/12 items in each task; otherwise incomplete.",
    "identity_error": "Quarantine known wrong identity or credits; retain denominator and original response.",
    "genre_positive": "Both fit and introduction usefulness >=4, exact listening, no unsure/unsupported/conflict; retain other outcomes separately.",
    "neighbors": "Separate sonic and cultural preferences; retain tie, neither, unsure, unsupported and disagreement. Identical candidates are nondiscriminating.",
    "promotion": "None; no quality score, significance, global coverage or musical acceptance claim.",
    "uncertainty": "Descriptive counts only; future uncertainty must cluster native artist/leakage component. Never pool repeated judgments as independent votes.",
    "adjudication": "Preserve original answers; any adjudication is a separate record.",
}


def _body(path: Path, limit: int = MAX_CONTROL) -> bytes:
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("symlinked audition input")
    if not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise ValueError("missing or oversized audition input")
    return path.read_bytes()


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _write(path: Path, value: object) -> None:
    with path.open("xb") as stream:
        stream.write(canonical_json(value) + b"\n")


def _order(values: list[Any], scope: str) -> list[Any]:
    return sorted(values, key=lambda value: _sha(f"{SEED}:{scope}:{value}".encode()))


def _inputs(site: Path, source: Path) -> tuple[Record, Record, Record, dict[int, int], Record]:  # noqa: C901, PLR0912 -- source and byte custody domains.
    index = json.loads(_body(site / "genre-discovery.json"))
    if genre_index(site) != index:
        raise ValueError("audition discovery index differs from verified export")
    receipt = verify_sources(source)
    source_sha = _sha(_body(source / "source-receipt.json"))
    bindings = {"genre-discovery.json": _sha(_body(site / "genre-discovery.json"))}
    audio, packs = {}, {}
    for key in ("original", "expanded"):
        config = index["collections"][key]
        neighbor = config.get("playable_neighbors")
        if not neighbor:
            raise ValueError("audition requires both verified suggestion packs")
        for relative, expected in (
            (config["manifest"], config["manifest_sha256"]),
            (neighbor["manifest_path"], neighbor["manifest_sha256"]),
        ):
            body = _body(site / relative)
            if _sha(body) != expected:
                raise ValueError("audition bound input changed")
            bindings[relative] = expected
        audio[key] = json.loads(_body(site / config["manifest"]))
        packs[key] = json.loads(_body(site / neighbor["manifest_path"]))
        static = json.loads(_body(site / key / "explorer/static-receipt.json"))
        if static["source_receipt_sha256"] != source_sha:
            raise ValueError("popularity metadata source differs from catalog")
    rows, checked, handles = source_rows(source, receipt["members"]["fma_metadata/raw_tracks.csv"])
    listens = {}
    try:
        for raw in rows:
            track = index["tracks"].get(raw["track_id"])
            if track is None:
                continue
            native = project_row("tracks", raw)
            if any(
                native[field] != track[field] for field in ("track_id", "artist_id", "genre_ids")
            ):
                raise ValueError("audition native track association differs")
            credit_fields = {
                "license_url": "license_url",
                "license_title": "license_title",
                "title": "track_title",
                "artist_name": "artist_name",
                "source_url": "track_url",
                "composer": "track_composer",
                "copyright_c": "track_copyright_c",
                "copyright_p": "track_copyright_p",
            }
            for collection in audio.values():
                attached = collection["tracks"].get(raw["track_id"])
                if attached is not None and any(
                    attached[field] != raw.get(native_field, "")
                    for field, native_field in credit_fields.items()
                ):
                    raise ValueError("audition native license or credit differs from audio")
            value = raw["track_listens"]
            if not value.isdecimal():
                raise ValueError("missing historical popularity; no substitution")
            listens[int(raw["track_id"])] = int(value)
        if not checked.complete or len(listens) != len(index["tracks"]):
            raise ValueError("incomplete audition source stream")
        bindings["native_raw_tracks_csv"] = checked.sha256.hexdigest()
    finally:
        for handle in handles:
            handle.close()
    bindings["metadata_source_receipt"] = source_sha
    return index, audio, packs, listens, bindings


def select_items(
    index: Record, packs: Record, listens: dict[int, int]
) -> tuple[list[Record], list[Record], Record]:
    """Freeze all denominators, including unavailable genres and unsupported queries."""
    strata: dict[str, list[int]] = {}
    for genre in index["genres"]:
        if genre["track_ids"]:
            cell = (
                ("single" if len(genre["track_ids"]) == 1 else "multiple")
                + "/"
                + ("root" if genre["parent_id"] is None else "child")
            )
            strata.setdefault(cell, []).append(genre["genre_id"])
    cells = ("multiple/child", "multiple/root", "single/child", "single/root")
    if any(len(strata.get(cell, [])) < 3 for cell in cells):
        raise ValueError("insufficient frozen genre stratum; no replacement")
    genres, queries, frame = [], [], []
    native = {g["genre_id"]: g for g in index["genres"]}
    for cell in cells:
        for identity in _order(strata[cell], "genre/" + cell)[:3]:
            row = native[identity]
            genres.append(
                {
                    "item_id": f"G{len(genres) + 1:02}",
                    "kind": "genre",
                    "title": row["title"],
                    "track_ids": row["starting_ids"][:1],
                    "genre_id": identity,
                    "stratum": cell,
                }
            )
    for collection in ("original", "expanded"):
        pack = packs[collection]
        rows = {r["track_id"]: r for r in pack["rows"]}
        defaults = [i for i in rows if index["tracks"][str(i)]["collection"] == collection]
        if len(defaults) < 6:
            raise ValueError("insufficient query stratum; no replacement")
        frame.extend(
            {"track_id": i, "collection": collection, "reason": rows[i]["reason"]}
            for i in sorted(defaults)
        )
        for identity in _order(defaults, "query/" + collection)[:6]:
            row = rows[identity]
            eligible = sorted(
                i
                for i in rows
                if rows[i]["reason"] is None
                and pack["components"][str(i)] != pack["components"][str(identity)]
            )
            supported = row["reason"] is None and bool(eligible)
            model = row["neighbor_ids"][0] if supported else None
            baseline = min(eligible, key=lambda i: (-listens[i], i)) if supported else None
            if supported and model not in eligible:
                raise ValueError("descriptor candidate outside baseline pool")
            queries.append(
                {
                    "item_id": f"N{len(queries) + 1:02}",
                    "kind": "neighbor",
                    "query": identity,
                    "descriptor": model,
                    "popularity": baseline,
                    "collection": collection,
                    "reason": row["reason"] if not supported else None,
                    "identical_candidates": supported and model == baseline,
                    "eligible_ids": eligible,
                }
            )
    return (
        genres,
        queries,
        {
            "all_genres": index["genres"],
            "genre_strata": {k: len(v) for k, v in strata.items()},
            "default_queries": frame,
            "historical_track_listens": listens,
        },
    )


def build_audition(site: Path, source: Path, output: Path) -> Record:
    """Create a NEW pilot, never silently reconstruct the historical PR18 assignments."""
    if output.exists() or any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError("audition destination must be fresh")
    index, audio, packs, listens, bindings = _inputs(site, source)
    genres, queries, denominator = select_items(index, packs, listens)
    output.mkdir(parents=True)
    coordinator = output / "coordinator"
    coordinator.mkdir()
    key, manifests = {}, {}
    template = _body(Path(__file__).parents[1] / "static/fma-audition.html")
    for slot in (1, 2):
        dest = output / f"listener-{slot}"
        (dest / "audio").mkdir(parents=True)
        items = [{k: row[k] for k in ("item_id", "kind", "title", "track_ids")} for row in genres]
        key[str(slot)] = {}
        for query in queries:
            methods = _order(["descriptor", "popularity"], f"assignment/{slot}/{query['item_id']}")
            key[str(slot)][query["item_id"]] = dict(zip(("A", "B"), methods, strict=True))
            items.append(
                {
                    "item_id": query["item_id"],
                    "kind": "neighbor",
                    "query": query["query"],
                    "A": query[methods[0]],
                    "B": query[methods[1]],
                    "unsupported": query["descriptor"] is None,
                }
            )
        by_id = {r["item_id"]: r for r in items}
        ids = _order([r["item_id"] for r in items[:12]], f"genre-order/{slot}") + _order(
            [r["item_id"] for r in items[12:]], f"neighbor-order/{slot}"
        )
        items = [by_id[i] for i in ids]
        used = sorted(
            {
                t
                for row in items
                for t in (
                    row["track_ids"]
                    if row["kind"] == "genre"
                    else [row["query"], row["A"], row["B"]]
                )
                if t is not None
            }
        )
        credit_rows, total = {}, 0
        for identity in used:
            collection = index["tracks"][str(identity)]["collection"]
            row = audio[collection]["tracks"][str(identity)]
            body = _body(site / collection / "audio" / row["audio_path"], MAX_CLIP)
            if (
                row["license_url"] not in LICENSES
                or row["decode"]["full_decode"] is not True
                or _sha(body) != row["audio_sha256"]
                or len(body) != row["audio_bytes"]
            ):
                raise ValueError("audition audio license/hash/decode differs")
            total += len(body)
            if total > MAX_SLOT_AUDIO:
                raise ValueError("audition slot audio exceeds 64 MB")
            (dest / "audio" / f"{identity}.mp3").write_bytes(body)
            credit_rows[str(identity)] = {k: row[k] for k in CREDIT_FIELDS} | {
                "audio_path": f"audio/{identity}.mp3"
            }
        _write(dest / "items.json", {"reviewer_slot": slot, "items": items})
        _write(dest / "credits.json", credit_rows)
        with (dest / "review-form.csv").open("x", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=ANSWER_FIELDS)
            writer.writeheader()
            writer.writerows({"item_id": row["item_id"], "reviewer_slot": slot} for row in items)
        (dest / "index.html").write_bytes(template)
        (dest / "README.txt").write_text(
            "Run python3 serve.py (Python 3.11+). Complete independently; never consult coordinator or other listener. Blank means unanswered. Ratings 1=poor, 3=mixed, 5=strong; familiarity 0=none to4=very familiar. Record conflicts, date/region and playback failures. Preserve unsure, unsupported and disagreements. One short excerpt cannot establish full work or genre diversity. Historical source license claims and metadata CC-BY-4.0; missing credits remain unknown. No musical-quality promotion. Download answers before closing.\n"
        )
        (dest / "serve.py").write_text(
            f"""from pathlib import Path

import hashlib
import json
import http.server
import os


p = Path(__file__).resolve().parent

for n, r in json.loads((p / 'MANIFEST.json').read_text()).items():
    f = p / n
    assert (
        f.stat().st_size == r['bytes']
        and hashlib.sha256(f.read_bytes()).hexdigest() == r['sha256']
    ), n

os.chdir(p)
print('Open http://127.0.0.1:887{slot}/')
http.server.HTTPServer(
    ('127.0.0.1', 887{slot}),
    http.server.SimpleHTTPRequestHandler,
).serve_forever()
"""
        )
        inventory = {
            str(p.relative_to(dest)): {"bytes": p.stat().st_size, "sha256": _sha(p.read_bytes())}
            for p in sorted(dest.rglob("*"))
            if p.is_file()
        }
        _write(dest / "MANIFEST.json", inventory)
        manifests[str(slot)] = _sha((dest / "MANIFEST.json").read_bytes())
    _write(coordinator / "assignment-key.json", key)
    _write(coordinator / "roster.json", {"genres": genres, "neighbors": queries})
    _write(coordinator / "denominators.json", denominator)
    declaration = {
        "revision": REVISION,
        "seed": SEED,
        "inputs": bindings,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "listener_template_sha256": _sha(template),
        "neighbor_provenance": {k: p["provenance"] for k, p in packs.items()},
        "listener_manifest_sha256": manifests,
        "coordinator_files_sha256": {
            name: _sha((coordinator / name).read_bytes())
            for name in ("assignment-key.json", "roster.json", "denominators.json")
        },
        "rules": RULES,
        "sampling": "Lowest seeded SHA256 per cell: three single/multiple x root/child genres; six default queries per collection, unsupported retained. Genre uses frozen first starter. No replacements.",
        "baseline": "Highest historical native track_listens in same supported collection excluding whole query component; native-ID ties. Identical candidates retained.",
        "scope_limits": [
            "New protocol/seed, not historical PR18 reconstruction",
            "Availability conditioned; unequal inclusion probabilities",
            "Region/language/era unknown; no broad/sub/micro equivalence",
            "No balanced cold/heldout sampling or quality inference; model training scope remains the attached pack provenance",
            "No full-catalog, membership, map or global acceptance claim",
        ],
        "judgments_recorded": 0,
        "public_deployment_authorized": False,
    }
    _write(coordinator / "declaration.json", declaration)
    return declaration
