"""Small local landing page for independently bounded, verified listening collections."""

# ruff: noqa: E501 -- self-contained HTML template.
from __future__ import annotations

import hashlib
import html
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from opennoise.common import canonical_json, sha256_file
from opennoise.deployment.fma_playback import (
    COLLECTION_REVISION,
    REVISION,
    validate_playback_export,
)


def build_listening_home(root: Path) -> dict[str, Any]:  # noqa: C901 -- cross-collection source and coverage gates.
    """Bind two complete exports and report overlap instead of summing duplicate audio."""
    if root.is_symlink() or (root / "index.html").exists() or (root / "collections.json").exists():
        raise ValueError("listening landing destination must be new")
    collections: list[dict[str, Any]] = []
    domains = []
    original_audio = validate_playback_export(root / "original" / "audio")
    expanded_audio = validate_playback_export(root / "expanded" / "audio")
    origin = expanded_audio.get("sources", {}).get("original", {})
    if (
        original_audio["revision"] != REVISION
        or expanded_audio["revision"] != COLLECTION_REVISION
        or origin.get("manifest_sha256")
        != sha256_file(root / "original" / "audio" / "manifest.json")[0]
        or origin.get("capture_sha256") != original_audio.get("source_pack_sha256")
        or set(origin.get("tracks", {})) != set(original_audio["tracks"])
    ):
        raise ValueError("collection sibling source association differs")
    for identity, row in original_audio["tracks"].items():
        if (
            origin["tracks"][identity]["record_sha256"]
            != hashlib.sha256(canonical_json(row)).hexdigest()
        ):
            raise ValueError("collection original source inventory differs")
    for key in ("original", "expanded"):
        audio = original_audio if key == "original" else expanded_audio
        catalog_path = root / key / "explorer" / "catalog.json"
        catalog = json.loads(catalog_path.read_bytes())
        playback = catalog["playback"]
        if playback["manifest_sha256"] != sha256_file(root / key / "audio" / "manifest.json")[0]:
            raise ValueError("collection catalog audio binding differs")
        index = {row["track_id"]: row for row in playback["tracks"]}
        if len(index) != len(playback["tracks"]) or set(index) != set(map(int, audio["tracks"])):
            raise ValueError("collection catalog native IDs differ")
        inventory = {**origin["tracks"], **expanded_audio["sources"]["expanded"]["tracks"]}
        for identity, row in index.items():
            expected = inventory[str(identity)]
            if (
                row["artist_id"] != audio["tracks"][str(identity)]["artist_id"]
                or row["artist_id"] != expected["artist_id"]
                or row["genre_ids"] != expected["genre_ids"]
            ):
                raise ValueError("collection catalog source annotations differ")
        ids = set(index)
        genres = {genre for row in index.values() for genre in row["genre_ids"]}
        names = {row["genre_id"]: row["title"] for row in catalog["genres"]}
        domains.append((ids, genres, names))
        collections.append(
            {
                "key": key,
                "label": catalog["collection"]["label"],
                "path": f"{key}/explorer/index.html#listen",
                "clips": len(ids),
                "artists": len({row["artist_id"] for row in index.values()}),
                "direct_genres": len(genres),
                "audio_manifest_sha256": playback["manifest_sha256"],
                "catalog_sha256": sha256_file(catalog_path)[0],
                "metadata_receipt_sha256": catalog["source_receipt_sha256"]
                if "source_receipt_sha256" in catalog
                else json.loads((catalog_path.parent / "static-receipt.json").read_bytes())[
                    "source_receipt_sha256"
                ],
            }
        )
    if collections[0]["metadata_receipt_sha256"] != collections[1]["metadata_receipt_sha256"]:
        raise ValueError("collection native metadata differs")
    if collections[0]["metadata_receipt_sha256"] != origin["metadata_source_receipt_sha256"]:
        raise ValueError("collection metadata source association differs")
    original, expanded = domains
    added = sorted(expanded[1] - original[1], key=lambda g: (expanded[2][g].casefold(), g))
    result = {
        "revision": "fma-local-listening-collections-v1",
        "public_deployment_authorized": False,
        "collections": collections,
        "distinct_clips": len(original[0] | expanded[0]),
        "shared_clips": len(original[0] & expanded[0]),
        "new_clips": len(expanded[0] - original[0]),
        "distinct_direct_genres": len(original[1] | expanded[1]),
        "new_direct_genre_ids": added,
        "musical_representativeness": "not_judged",
    }
    links = "".join(
        f'<li><a href="{row["path"]}">{html.escape(row["label"])}</a>'
        f" — {row['clips']} excerpts · {row['artists']} artists · "
        f"{row['direct_genres']} direct genre annotations</li>"
        for row in collections
    )
    genre_links = "".join(
        f'<li><a href="expanded/explorer/index.html#listen&amp;genre={genre}">'
        f"{html.escape(expanded[2][genre])}</a></li>"
        for genre in added
    )
    page = f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenNoise · listening collections</title>
<style>body{{font:16px system-ui,sans-serif;max-width:64rem;margin:2rem auto;padding:0 1rem;line-height:1.5;color:#222}}a{{color:#154d94}}li{{margin:.6rem 0}}.genres{{columns:3 14rem}}:focus-visible{{outline:3px solid #a34800;outline-offset:3px}}</style>
<main><h1>OpenNoise · listen</h1><p>Choose a collection, then play an excerpt or explore its artists and source genres.</p>
<ul>{links}</ul><p>{result["distinct_clips"]} distinct excerpts across both collections; {result["shared_clips"]} appear in both. Switching collections stops the current player.</p>
<h2>New genre annotations to explore</h2><p>{result["new_clips"]} new recordings add {len(added)} direct source genre annotations. These are overlapping track labels, not independently validated representative examples.</p>
<ul class="genres">{genre_links}</ul><p>Each collection stays within the existing 64-excerpt limit. The complete native catalog remains searchable in both.</p>
<p>Local playback only. Artist attribution and each recording's license appear beside the player. Nothing starts automatically.</p>
<details><summary>Sources and coverage</summary><p>FMA native metadata · CC BY 4.0. The original capture and the separately approved larger-archive capture retain separate custody. No full-archive checksum or musical-quality claim is made.</p><a href="collections.json">Collection receipt</a></details></main></html>"""
    (root / "index.html").write_text(page)
    (root / "collections.json").write_bytes(canonical_json(result) + b"\n")
    return result
