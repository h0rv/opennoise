"""Local full-catalog demonstration from the fixed public CC0 source packs."""

# ruff: noqa: PLR0912, PLR0915, C901 -- Fixed, bounded source projection.
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from opennoise.ml import ab178_crossfit as acoustic
from opennoise.pipeline import cultural_catalog as catalog
from opennoise.pipeline.full_input_indexes import normalize_name

if TYPE_CHECKING:
    from pathlib import Path

CORE = (
    "data/release/musicbrainz-credit-catalog-v1/objects/musicbrainz-credit-catalog/sha256/"
    "13921b94a5a0c77c625713b5e272d40d081c67de3eb5b1299c8c1c48baf6d6ba.json"
)
ACOUSTIC_SOURCE_PIN = "13e21e5296989e148e0efc2f6956675d2d391326552fe4a1a3b67df56e1494cb"
ACOUSTIC_PLAN_PIN = "4fefa8bfc2ac9ac7985b86e4a27db92443188031c3dcab2e455b9b08cb25dda6"
ACOUSTIC_OUTPUT_PIN = "f24b2306e0ab997db68e79483ccae993357bb3b4dc3c66d2b04cd3d5f3b8c6e7"
ASSETS = (
    "full-foundation.html",
    "full-foundation.mjs",
    "full-foundation.css",
    "full-foundation-normalization.mjs",
    "listening-list.mjs",
    "map-atlas.mjs",
    "pipeline-demo.mjs",
    "pipeline-demo.css",
)


def digest(path: Path) -> str:
    """Bind actual local bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> Any:  # noqa: ANN401 -- Existing source verifiers validate these files.
    """Read a verified source or generated payload."""
    return json.loads(path.read_bytes())


def write(path: Path, value: object) -> None:
    """Write finite static data, never executable source text."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")


def positions(
    ids: list[str], edges: list[dict[str, Any]], *, place_unlinked: bool = False
) -> dict[str, list[float]]:
    """Arrange linked components and unlinked names; these are not acoustic coordinates."""
    adjacency: dict[str, set[str]] = {identity: set() for identity in ids}
    for edge in edges:
        adjacency[edge["source"]].add(edge["target"])
        adjacency[edge["target"]].add(edge["source"])
    linked = sorted(identity for identity in ids if adjacency[identity])
    result: dict[str, list[float]] = {}
    for index, identity in enumerate(linked):
        angle = 2 * math.pi * index / len(linked)
        result[identity] = [math.cos(angle) * 300, math.sin(angle) * 300]
    # Deterministic graph drawing only. No features, labels, thresholds or acoustic
    # distances enter these forces; the preserved edges are the sole input.
    for iteration in range(240):
        force = {identity: [0.0, 0.0] for identity in linked}
        for index, left in enumerate(linked):
            for right in linked[index + 1 :]:
                dx, dy = (result[left][d] - result[right][d] for d in (0, 1))
                distance = max(math.hypot(dx, dy), 0.1)
                strength = 6400 / distance
                for d, delta in enumerate((dx, dy)):
                    force[left][d] += delta / distance * strength
                    force[right][d] -= delta / distance * strength
        for left in linked:
            for right in sorted(adjacency[left]):
                dx, dy = (result[left][d] - result[right][d] for d in (0, 1))
                distance = max(math.hypot(dx, dy), 0.1)
                for d, delta in enumerate((dx, dy)):
                    force[left][d] -= delta * distance / 160
        temperature = 20 * (1 - iteration / 240) + 0.05
        for identity in linked:
            dx, dy = force[identity]
            length = max(math.hypot(dx, dy), 0.1)
            for d, delta in enumerate((dx, dy)):
                result[identity][d] += delta / length * min(length, temperature)
    isolated = [identity for identity in ids if not adjacency[identity]]
    if place_unlinked:
        below = max((p[1] for p in result.values()), default=0) + 100
        for i, identity in enumerate(isolated):
            result[identity] = [float(i % 8 * 80), float(below + i // 8 * 60)]
    return result


def _acoustic(root: Path, output: Path) -> dict[str, Any]:
    path = output / "acoustic-replay"
    acoustic.build(
        root / "data/examples/native-sonic",
        ACOUSTIC_SOURCE_PIN,
        root / "data/recipes/ab178-crossfit/protocol.json",
        ACOUSTIC_PLAN_PIN,
        path,
    )
    if digest(path / "manifest.json") != ACOUSTIC_OUTPUT_PIN:
        raise ValueError("Replayed acoustic pipeline differs from the frozen public recipe")
    evidence = acoustic.verify(path, ACOUSTIC_OUTPUT_PIN)
    bank = read(path / "fold-0/bank/bank.json")
    return {"evidence": evidence, "bank": bank}


def _standalone(site: Path) -> None:
    """Bundle existing plain modules and data for offline file opening; no framework."""

    def module(name: str, exports: str) -> str:
        source = (site / name).read_text()
        source = re.sub(r"^import .*?;\n", "", source, flags=re.MULTILINE)
        source = re.sub(r"\bexport (?=(?:async )?function|const|let)", "", source)
        return "(()=>{\n" + source + "\nreturn {" + exports + "};\n})()"

    files = {p.relative_to(site).as_posix(): read(p) for p in sorted(site.rglob("*.json"))}
    data = json.dumps(files, ensure_ascii=True, allow_nan=False).replace("<", "\\u003c")
    main = (site / "full-foundation.mjs").read_text()
    main = re.sub(r"^import .*?;\n", "", main, flags=re.MULTILINE)
    script = (
        "globalThis.OPENNOISE_LOCAL_FILES=" + data + ";\n"
        "const {normalizeName}="
        + module("full-foundation-normalization.mjs", "normalizeName")
        + ";\n"
        "const {mountListeningList}=" + module("listening-list.mjs", "mountListeningList") + ";\n"
        "const {fitCamera,zoomAtCenter}="
        + module("map-atlas.mjs", "fitCamera,zoomAtCenter")
        + ";\n"
        "globalThis.OPENNOISE_PIPELINE_DEMO="
        + module("pipeline-demo.mjs", "renderMap,appendArtistEvidence")
        + ";\n"
        + main
    )
    if "</script" in script.lower():
        raise ValueError("Unexpected HTML script boundary in bundled modules")
    html = (site / "index.html").read_text()
    html = re.sub(
        r'<link rel="stylesheet" href="([^"]+)">',
        lambda match: "<style>" + (site / match[1]).read_text() + "</style>",
        html,
    )
    html = html.replace(
        '<script type="module" src="full-foundation.mjs"></script>',
        '<script type="module">' + script + "</script>",
    )
    (site / "OpenNoise.html").write_text(html)


def build(root: Path, output: Path) -> dict[str, Any]:
    """Replay public sources and export the existing app to a local-only fresh directory."""
    root, output = root.resolve(), output.absolute()
    if output.exists() or not output.resolve().is_relative_to(root / ".cache"):
        raise ValueError("Demo output must be fresh and under this checkout's .cache")
    if any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError("Demo output cannot traverse symlinks")
    output.mkdir(parents=True)
    result = catalog.build(
        root / CORE,
        catalog.CORE_SHA,
        root / "data/examples/cultural-context",
        catalog.PACKS[0][1],
        root / "data/examples/independent-cultural-context",
        catalog.PACKS[1][1],
        output / "catalog-replay",
        register_core_custody=True,
    )
    sonic = _acoustic(root, output)
    facts = result["orders"]["musicbrainz-first"]
    artists: dict[str, dict[str, Any]] = {
        identity: {
            "id": identity,
            "name": row["name"],
            "name_status": row["name_status"],
            "catalog": True,
            "genres": [],
            "recordings": [],
        }
        for identity, row in facts["neighbors"].items()
    }
    names: dict[str, str] = {}
    titles: dict[str, str] = {}
    source = root / "data/examples/native-sonic"
    # Source verification above binds these exact public credit bytes before display.
    for path in sorted((source / "raw/credits").glob("*.json")):
        body = read(path)
        titles[body["id"]] = body["title"]
        for credit in body["artist-credit"]:
            if isinstance(credit, dict):
                artist = credit["artist"]
                names.setdefault(artist["id"], artist["name"])
    for identity, name in names.items():
        artists.setdefault(
            identity,
            {
                "id": identity,
                "name": name,
                "name_status": "source_name",
                "catalog": False,
                "genres": [],
                "recordings": [],
            },
        )
    metadata = read(output / "catalog-replay/musicbrainz-first.approved-input.json")
    genre_names = {
        g["genre_id"].split(":")[-1]: g["name"] for g in metadata["public_model_input"]["genres"]
    }
    claims: dict[str, set[str]] = defaultdict(set)
    for artist, genre, *_ in facts["graph"]["claims"]:
        claims[artist].add(genre)
    for artist, genres in claims.items():
        artists[artist]["genres"] = sorted(genres)
    recordings = {}
    hydration = read(output / "catalog-replay/core-hydration.json")
    for release in hydration["releases"]:
        for medium in release["media"]:
            for track in medium["tracks"]:
                identity = track["recording_id"]
                recordings.setdefault(
                    identity,
                    {
                        "id": identity,
                        "title": track["title"],
                        "artists": [],
                        "url": f"https://musicbrainz.org/recording/{identity}",
                    },
                )
    core_recording_count = len(recordings)
    for credit in read(output / "catalog-replay/core-credits.json")["credits"]:
        if credit["entity_kind"] == "recording":
            recordings[credit["entity_id"]]["artists"] = [m["artist_id"] for m in credit["members"]]
    outcomes = {row["recording_mbid"]: row for row in sonic["evidence"]["recordings"]}
    feature_rows = []
    for row in sonic["bank"]["rows"]:
        identity = row["recording_mbid"]
        fact = row["exact_credit"]["fact"]
        feature_rows.append(
            {
                "id": identity,
                "title": titles.get(identity),
                "values": row["values"],
                "artists": fact["credited_artist_mbids"] if fact else [],
                "outcome": outcomes[identity]["outcome"],
                "contract": outcomes[identity]["contract_sha256"],
                "fold": outcomes[identity]["heldout_fold"],
                "source_url": row["source_url"],
                "source_sha256": row["source_sha256"],
            }
        )
        if fact:
            recordings.setdefault(
                identity,
                {
                    "id": identity,
                    "title": fact["title"],
                    "artists": fact["credited_artist_mbids"],
                    "url": fact["url"],
                },
            )
    for row in recordings.values():
        for artist in row["artists"]:
            artists[artist]["recordings"].append(row["id"])
    edges = [
        {
            "source": artist,
            "target": other,
            "kind": "shared_source_genre",
            "genres": sorted(claims[artist] & claims[other]),
        }
        for artist, item in facts["neighbors"].items()
        for other in item["neighbors"]
        if artist < other
    ]
    acoustic_edges = [
        {
            "source": artist["artist_mbid"],
            "target": neighbor["artist_mbid"],
            "kind": "suggested_from_descriptors",
            "contract": cell["contract_sha256"],
            "fold": cell["heldout_fold"],
            "observations": neighbor["observations"],
        }
        for cell in sonic["evidence"]["cells"]
        for artist in cell["artists"]
        for neighbor in artist["neighbor_evidence"]["heldout"]
    ]
    ordered = sorted(artists.values(), key=lambda a: (normalize_name(a["name"]), a["id"]))
    source_positions = positions([a["id"] for a in ordered], edges)
    audio_positions = positions(sorted(names), acoustic_edges, place_unlinked=True)
    counts = {
        "artists": len(artists),
        "catalog_artists": len(facts["neighbors"]),
        "artists_with_direct_genres": len(claims),
        "recordings": len(recordings),
        "core_recordings": core_recording_count,
        "acoustic_artists": len(names),
        "acoustic_nominations": len(feature_rows),
        "descriptor_recordings": sonic["bank"]["counts"]["available_recordings"],
        "compatible_recordings": sonic["evidence"]["counts"]["compatible_recordings"],
        "compatible_artists": len(
            {
                artist
                for row in outcomes.values()
                if row["contract_sha256"] is not None
                for artist in row["credited_artist_mbids"]
            }
        ),
        "supported_query_recordings": sum(row["outcome"] == "emitted" for row in outcomes.values()),
        "supported_query_artists": len(
            {
                artist
                for row in outcomes.values()
                if row["outcome"] == "emitted"
                for artist in row["credited_artist_mbids"]
            }
        ),
        "genres": len(genre_names),
    }
    site = output / "site"
    site.mkdir()
    for asset in ASSETS:
        shutil.copyfile(
            root / "src/opennoise/static" / asset,
            site / ("index.html" if asset == "full-foundation.html" else asset),
        )
    html = (
        (site / "index.html")
        .read_text()
        .replace("</head>", '<link rel="stylesheet" href="pipeline-demo.css"></head>')
    )
    (site / "index.html").write_text(html)
    public_genres = [
        {
            "genre_id": g,
            "name": name,
            "artists": [[a["id"], a["name"]] for a in ordered if g in a["genres"]],
        }
        for g, name in sorted(genre_names.items(), key=lambda x: (normalize_name(x[1]), x[0]))
    ]
    write(site / "genres.json", public_genres)
    write(
        site / "profile.json",
        {
            "revision": "retained-cc0-pipeline-demo-v1",
            "counts": counts,
            "pipeline_demo": {"path": "pipeline.json"},
            "browse_page_size": 500,
        },
    )
    pairs = [[a["id"], a["name"]] for a in ordered]
    write(site / "browse/000000.json", pairs)
    write(
        site / "search/index.json",
        {"pages": [[normalize_name(pairs[0][1]), normalize_name(pairs[-1][1]), len(pairs)]]},
    )
    for number in range(256):
        prefix = f"{number:02x}"
        write(
            site / f"artists/identity-{prefix}.json", [a for a in pairs if a[0].startswith(prefix)]
        )
    for artist in ordered:
        write(
            site / f"details/{artist['id']}.json",
            {
                "direct_genres": artist["genres"],
                "recordings": [recordings[i] for i in sorted(set(artist["recordings"]))],
                "sources": [f"https://musicbrainz.org/artist/{artist['id']}"],
            },
        )
    pipeline = {
        "revision": "retained-cc0-pipeline-demo-v1",
        "counts": counts,
        "artists": [
            {
                **a,
                "position": source_positions.get(a["id"]),
                "acoustic_position": audio_positions.get(a["id"]),
            }
            for a in ordered
        ],
        "genres": genre_names,
        "source_edges": edges,
        "acoustic_edges": acoustic_edges,
        "features": feature_rows,
        "columns": sonic["bank"]["columns"],
        "recordings": recordings,
        "source_missingness": read(output / "catalog-replay/missingness.json"),
        "scope": (
            "Local provisional demonstration; graph layout arranges links, "
            "never perceptual distance"
        ),
        "source_pins": {
            "core": catalog.CORE_SHA,
            "cultural": catalog.PACKS[0][1],
            "independent_cultural": catalog.PACKS[1][1],
            "sonic": ACOUSTIC_SOURCE_PIN,
            "frozen_acoustic_replay": ACOUSTIC_OUTPUT_PIN,
        },
    }
    write(site / "pipeline.json", pipeline)
    receipt = {
        "revision": "retained-cc0-pipeline-demo-v1",
        "counts": counts,
        "source_pins": pipeline["source_pins"],
        "implementation_sha256": {
            "catalog_demo.py": digest(root / "src/opennoise/pipeline/catalog_demo.py"),
            "build_retained_catalog_demo.py": digest(
                root / "scripts/build_retained_catalog_demo.py"
            ),
        },
        "license": "CC0-1.0 source metadata; MIT code",
        "delivery": "candidate receipt; production authority: separate opennoise-release.json",
        "perceptual_similarity_validated": False,
        "audio_playback_verified": False,
        "private_annotations_or_benchmark_inputs": False,
        "limitations": (
            "Broad source catalog; acoustic coverage is an electronic/ambient-heavy "
            "17-artist subset. No EveryNoise parity or quality gain is established."
        ),
        "files": {
            p.relative_to(site).as_posix(): digest(p) for p in site.rglob("*") if p.is_file()
        },
    }
    write(site / "receipt.json", receipt)
    _standalone(site)
    return {
        "counts": counts,
        "site": str(site),
        "standalone": str(site / "OpenNoise.html"),
        "standalone_sha256": digest(site / "OpenNoise.html"),
    }
