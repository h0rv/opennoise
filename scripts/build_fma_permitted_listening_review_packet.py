"""Create a rights-bound 8-clip FMA listening review packet without ratings."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import sys
from pathlib import Path
from typing import Any

CLIP_COUNT = 8


def sha(path: Path) -> str:
    """Hash the exact source audio or generated packet file by streaming."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build(source_pack: Path, output: Path, route_prefix: str = "/fma-listening/") -> dict[str, Any]:
    """Freeze the eight permitted exact excerpts with blank listener forms."""
    source_file = source_pack / "listening.json"
    pack = json.loads(source_file.read_text(encoding="utf-8"))
    tracks = pack["tracks"]
    if len(tracks) != CLIP_COUNT:
        raise ValueError("Expected the frozen eight-track permitted FMA excerpt pack")
    items = []
    for i, t in enumerate(sorted(tracks, key=lambda x: int(x["track_id"])), 1):
        audio = source_pack / t["audio_path"]
        actual = sha(audio)
        if actual != t["audio_sha256"] or audio.stat().st_size != t["audio_bytes"]:
            raise ValueError(f"Audio custody mismatch for native FMA track {t['track_id']}")
        items.append(
            {
                "item_id": f"L{i:02d}",
                "native_track_id": int(t["track_id"]),
                "native_artist_id": int(t["artist_id"]),
                "identity_namespace": "FMA native only; no MusicBrainz recording identity implied",
                "artist_name": t["artist_name"],
                "track_title": t["track_title"],
                "region": "unknown",
                "language": "unknown",
                "era": "unknown",
                "source_track_page": t["track_url"],
                "audio_license_title": t["license_title"],
                "audio_license_url": t["license_url"],
                "attribution": t["attribution"],
                "clip_scope": t["clip_scope"],
                "clip_sha256": actual,
                "clip_bytes": audio.stat().st_size,
                "playback_url": route_prefix.rstrip("/") + "/" + audio.name,
                "provider_region": "not_recorded",
                "availability_status": (
                    "local_clip_in_open_build; external/provider availability not assessed"
                ),
                "musical_representativeness": "not_judged",
                "genre_tags_hidden": True,
            }
        )
    declaration = {
        "revision": "fma-permitted-excerpt-independent-review-v1",
        "denominator": 8,
        "cohort_scope": (
            "separate exact-native-ID listening-access cohort; not the full FMA "
            "sample and not selected for musical representativeness"
        ),
        "source_pack_revision": pack["revision"],
        "source_pack_sha256": sha(source_file),
        "rights": (
            "Each included 30-second excerpt has an explicit source-declared "
            "Creative Commons license in its item record. Metadata and audio "
            "rights are distinct. Attribution is required where the license "
            "requires it. No additional rights to full recording, derivative "
            "audio, or external provider playback are asserted."
        ),
        "listening_behavior": (
            "Use the supplied clip only for this review, do not infer full-track "
            "properties from a 30-second excerpt, do not download/embed elsewhere "
            "or redistribute outside the declared license scope, and record "
            "whether the exact clip was heard successfully."
        ),
        "reviewers_per_item": 2,
        "review_thresholds": {
            "fit_scale": {
                "1": "does not fit",
                "2": "mostly does not fit",
                "3": "mixed or uncertain fit",
                "4": "good fit",
                "5": "very strong fit",
            },
            "fit_summary": (
                "retain both ratings; do not replace disagreement with consensus; "
                "unsure and access failure are separate outcomes"
            ),
        },
        "limits": [
            (
                "These excerpts were selected by source/license availability, not for "
                "genre or quality representativeness."
            ),
            (
                "A clip cannot establish an artist's full discography, era, or "
                "defining-recording status."
            ),
            "No independent listening or musical judgments have yet been recorded.",
            "Provider region and external availability are unknown.",
            "Native FMA IDs are not MusicBrainz IDs.",
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "declaration.json").write_text(
        json.dumps(declaration, indent=2, sort_keys=True) + "\n"
    )
    (output / "cohort.json").write_text(
        json.dumps({"items": items}, indent=2, sort_keys=True) + "\n"
    )
    slots = [
        {"item_id": x["item_id"], "reviewer_slot": s, "reviewer_id": "", "status": "unassigned"}
        for x in items
        for s in (1, 2)
    ]
    (output / "reviewer-assignments.json").write_text(json.dumps(slots, indent=2) + "\n")
    with (output / "review-form.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "item_id",
                "reviewer_slot",
                "reviewer_id",
                "familiarity_0_4",
                "conflict_description",
                "heard_exact_clip",
                "playback_failure",
                "fit_1_5",
                "confidence_1_5",
                "unsure",
                "unsupported",
                "clip_seems_representative_of_full_recording",
                "notes",
            ],
        )
        w.writeheader()
        for x in items:
            for slot in (1, 2):
                w.writerow(
                    {
                        "item_id": x["item_id"],
                        "reviewer_slot": slot,
                        "reviewer_id": "",
                        "familiarity_0_4": "",
                        "conflict_description": "",
                        "heard_exact_clip": "",
                        "playback_failure": "",
                        "fit_1_5": "",
                        "confidence_1_5": "",
                        "unsure": "",
                        "unsupported": "",
                        "clip_seems_representative_of_full_recording": "",
                        "notes": "",
                    }
                )
    req = (
        "We need two independent listeners for each of these eight exact "
        "native FMA excerpts. Each item is a 30-second clip with its "
        "source-declared per-track Creative Commons license, attribution text, "
        "and a local static playback link. These eight were selected for an "
        "explicit listening permission path, not as a representative genre "
        "cohort. Please record whether you heard the exact clip, report "
        "playback failures, declare familiarity/conflicts, and rate only what "
        "this excerpt supports. Do not infer the full recording or artist "
        "discography from this short excerpt; use unsure when it is not "
        "enough. Keep both independent answers and disagreements. Provider "
        "region and wider availability remain unknown."
    )
    (output / "listener-request.txt").write_text(req + "\n")
    rows = []
    rows.extend(
        (
            f"<article><h2>{html.escape(x['artist_name'])} — "
            f"{html.escape(x['track_title'])}</h2><p>FMA track {x['native_track_id']} "
            f"· 30-second excerpt · {html.escape(x['audio_license_title'])}</p>"
            '<audio controls preload="none" '
            f'src="{html.escape(x["playback_url"], quote=True)}">'
            "Audio playback is unavailable in this browser.</audio><p><a "
            f'href="{html.escape(x["source_track_page"], quote=True)}">'
            "Source track page</a> · <a "
            f'href="{html.escape(x["audio_license_url"], quote=True)}">License</a></p>'
            f"<p>{html.escape(x['attribution'])}</p></article>"
        )
        for x in items
    )
    page = (
        (
            '<!doctype html><html lang="en"><meta charset="utf-8"><meta '
            'name="viewport" content="width=device-width, '
            'initial-scale=1"><title>FMA permitted excerpt '
            "review</title><style>body{font:16px/1.5 "
            "system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 "
            "1rem;color:#202124}article{border-top:1px solid #bbb;padding:1rem "
            "0}audio{width:100%}small{color:#555}</style><main><h1>Permitted FMA "
            "excerpt review</h1><p>Eight 30-second excerpts selected by explicit "
            "source license. This is a listening-access cohort, not a "
            "representative music sample. Record judgments in the blank CSV; each "
            "item has two independent reviewer rows. Do not infer full-track "
            "quality from a short clip.</p>"
        )
        + "".join(rows)
        + "</main></html>\n"
    )
    (output / "listen.html").write_text(page, encoding="utf-8")
    files = {
        p.name: sha(p)
        for p in sorted(output.iterdir())
        if p.is_file() and p.name != "manifest.json"
    }
    (output / "manifest.json").write_text(
        json.dumps({"sha256": files}, indent=2, sort_keys=True) + "\n"
    )
    return {
        "clips": len(items),
        "reviewer_slots": len(slots),
        "source_pack_sha256": declaration["source_pack_sha256"],
        "licensed_clip_ids": [x["native_track_id"] for x in items],
    }


def main() -> int:
    """Build a packet from a pinned licensed excerpt source pack."""
    p = argparse.ArgumentParser()
    p.add_argument("--source-pack", type=Path, required=True)
    p.add_argument(
        "--output",
        type=Path,
        default=Path("docs/foundation/musical-review-packet/fma-permitted-listening"),
    )
    p.add_argument("--route-prefix", default="/fma-listening/")
    a = p.parse_args()
    sys.stdout.write(
        json.dumps(build(a.source_pack, a.output, a.route_prefix), sort_keys=True) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
