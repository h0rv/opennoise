"""Package the frozen eight-clip listening pilot without hidden source observations."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import sys
import zipfile
from pathlib import Path
from typing import Any

PILOT_SIZE = 8
REVIEWER_ROWS = 16
UPLOAD_LIMIT = 10 * 1024 * 1024


def digest(path: Path) -> str:
    """Hash without loading media into memory."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _read_packet(packet: Path, audio_pack: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Require a frozen eight-item cohort and still-blank independent reviewer slots."""
    cohort = json.loads((packet / "cohort.json").read_bytes())
    native = json.loads((audio_pack / "listening.json").read_bytes())
    items = cohort["items"]
    if len(items) != PILOT_SIZE or len({row["item_id"] for row in items}) != PILOT_SIZE:
        raise ValueError("pilot needs eight distinct frozen items")
    with (packet / "review-form.csv").open(newline="") as source:
        forms = list(csv.DictReader(source))
    if len(forms) != REVIEWER_ROWS or any(
        value
        for row in forms
        for field, value in row.items()
        if field not in {"item_id", "reviewer_slot"}
    ):
        raise ValueError("pilot must preserve blank, uncompleted reviewer forms")
    assignments = json.loads((packet / "reviewer-assignments.json").read_bytes())
    if any(row["reviewer_id"] or row["status"] != "unassigned" for row in assignments):
        raise ValueError("pilot does not invent or discard reviewer assignments")
    return cohort, native


def _copy_media(
    cohort: dict[str, Any], native: dict[str, Any], audio_pack: Path, output: Path
) -> None:
    """Bind unchanged MP3 bytes, exact native IDs and individual license declarations."""
    items = cohort["items"]
    native_tracks = {str(row["track_id"]): row for row in native["tracks"]}
    audio = output / "fma-listening"
    audio.mkdir()
    for item in items:
        track = native_tracks[str(item["native_track_id"])]
        source = audio_pack / track["audio_path"]
        if source.is_symlink() or source.name != f"{item['native_track_id']}.mp3":
            raise ValueError("native audio path must be a regular exact-ID file")
        if (
            digest(source) != item["clip_sha256"]
            or item["clip_sha256"] != track["audio_sha256"]
            or source.stat().st_size != item["clip_bytes"]
            or item["audio_license_url"] != track["license_url"]
            or item["attribution"] != track["attribution"]
            or not item["genre_tags_hidden"]
        ):
            raise ValueError("pilot media identity, license or attribution differs")
        os.link(source, audio / source.name)
        item["playback_url"] = f"fma-listening/{source.name}"


def _write_documents(packet: Path, cohort: dict[str, Any], output: Path) -> None:
    """Hide source observations and make local playback and pilot limits explicit."""
    items = cohort["items"]
    for name in ("review-form.csv", "reviewer-assignments.json"):
        (output / name).write_bytes((packet / name).read_bytes())
    declaration = json.loads((packet / "declaration.json").read_bytes())
    declaration["revision"] = "fma-permitted-listening-description-pilot-v1"
    declaration["candidate_presented"] = False
    declaration["fit_1_5_instruction"] = "Leave blank: this pilot presents no candidate fit object."
    declaration["review_thresholds"] = {
        "fit_summary": "Not applicable: no candidate fit object is presented.",
        "description_confidence": "1 low to 5 high; confidence in your own description only.",
        "judgments_recorded": 0,
    }
    for name, data in [("cohort.json", cohort), ("declaration.json", declaration)]:
        (output / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    markup = (
        (packet / "listen.html").read_text().replace('src="/fma-listening/', 'src="fma-listening/')
    )
    markup = markup.replace(
        "<main>", '<a class="skip" href="#main">Skip to excerpts</a><main id="main" tabindex="-1">'
    )
    markup = markup.replace(
        "</style>",
        ".skip:focus{outline:3px solid #174c91}button:focus-visible,a:focu"
        "s-visible,audio:focus-visible{outline:3px solid #174c91}</style>",
    )
    for item in items:
        markup = markup.replace(
            f'src="{html.escape(item["playback_url"])}"',
            f'data-track-id="{item["native_track_id"]}" src="{html.escape(item["playback_url"])}"',
        )
    markup = markup.replace(
        "</main>",
        "<p>No candidate is presented. Leave fit_1_5 blank; put your indep"
        "endent description and possible genres in notes.</p></main><scrip"
        't>document.querySelector(".skip").addEventListener("click",event='
        '>{event.preventDefault();document.querySelector("main").focus();}'
        ");</script>",
    )
    (output / "listen.html").write_text(markup)
    request = (
        "Two independent listeners wanted: eight licensed 30-second excerpts, "
        "about 10 minutes each. Extract the ZIP and open listen.html. "
        "Independently record playback or identity problems, "
        "familiarity/conflicts, your own musical description or possible "
        "genres, and uncertainty. No candidate is presented: leave fit_1_5 "
        "blank. Do not infer a full recording from its excerpt unless you "
        "independently know that recording. Do not discuss answers before "
        "submitting separate completed CSVs; keep disagreement.\n"
    )
    (output / "listener-request.txt").write_text(request)
    (output / "README.md").write_text("""# Eight-clip independent listening pilot

Extract this ZIP into a new directory, keeping the `fma-listening` directory next to
`listen.html`. Open `listen.html` in a browser. All eight clips use relative local paths; no
account, external player or server is required. Files are unchanged native FMA small 30-second
excerpts. Each clip has its own source-declared Creative Commons license and exact attribution
beside the player and in `cohort.json` (CC BY 3.0, CC BY 4.0, CC BY-SA 4.0 or CC0). Follow
each individual license; the ZIP does not replace them. Metadata is from FMA contributors,
Defferrard et al., ISMIR 2017 (CC BY 4.0).

Two independent listeners each review all eight excerpts, about 10 minutes per person. Use one
reviewer slot consistently and your own short reviewer identifier. Listen before consulting
source pages or file tags; source genre observations and model methods are deliberately absent
from the review documents. Do not discuss answers until both forms are complete. No people or
judgments have been supplied.

Fill your eight rows in a separate copy of `review-form.csv`:

- `heard_exact_clip`: yes/no; describe any wrong clip, title mismatch or playback problem in
  `playback_failure` or `notes`.
- `familiarity_0_4`: 0 unfamiliar to 4 very familiar. Declare relevant conflicts; none is a
  valid answer.
- `notes`: your own musical description and possible genres, with uncertainty. These are
  independent descriptions, not a requested label confirmation.
- `confidence_1_5`: 1 low to 5 high, confidence in your own description. Use `unsure` when the
  excerpt does not support a judgment.
- **Leave `fit_1_5` and `unsupported` blank. No candidate fit object or model proposal is
  presented in this pilot.**
- `clip_seems_representative_of_full_recording`: leave blank or unsure unless you
  independently know the full recording. If you do, explain that familiarity and your reason
  in `notes`. A 30-second excerpt cannot establish representativeness by itself.

Return the two separately completed CSVs. Keep independent answers and disagreements; do not
average them into invented consensus. Do not edit the frozen cohort or declaration. This
eight-item access and description pilot does not satisfy the larger frozen musical-review
cohort, calibrated genre membership, representative-recording or full Every Noise acceptance
gates.

`SHA256SUMS` checks every packaged document and MP3. A coordinator can run `sha256sum -c
SHA256SUMS` inside the extracted directory; checking hashes is not required to listen.
Original project sources, original review packet and recovery artifacts remain unchanged.""")


def _seal(output: Path) -> dict[str, str]:
    """Inventory the exact documents and media without coordinator keys or raw labels."""
    files = sorted(path for path in output.rglob("*") if path.is_file())
    inventory = {path.relative_to(output).as_posix(): digest(path) for path in files}
    (output / "SHA256SUMS").write_text(
        "".join(f"{value}  {name}\n" for name, value in inventory.items())
    )
    return inventory


def _archive(output: Path, inventory: dict[str, str]) -> Path:
    """Write and fully read back every member in a fresh upload-sized ZIP."""
    archive = output.with_suffix(".zip")
    if archive.exists():
        raise ValueError("pilot ZIP output must be fresh")
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_STORED) as target:
        for path in sorted(p for p in output.rglob("*") if p.is_file()):
            target.write(path, path.relative_to(output).as_posix())
    if archive.stat().st_size >= UPLOAD_LIMIT:
        raise ValueError("pilot exceeds Pages upload limit")
    with zipfile.ZipFile(archive) as target:
        if target.testzip():
            raise ValueError("pilot ZIP CRC verification failed")
        for name, expected in inventory.items():
            with target.open(name) as stream:
                hasher = hashlib.sha256()
                while block := stream.read(65536):
                    hasher.update(block)
                if hasher.hexdigest() != expected:
                    raise ValueError("pilot ZIP member readback differs")
    return archive


def build(packet: Path, audio_pack: Path, output: Path) -> dict[str, object]:
    """Preserve inputs and write a fresh independently readable pilot directory."""
    cohort, native = _read_packet(packet, audio_pack)
    output.mkdir(parents=True, exist_ok=False)
    _copy_media(cohort, native, audio_pack, output)
    _write_documents(packet, cohort, output)
    inventory = _seal(output)
    archive = _archive(output, inventory)
    return {
        "revision": "opennoise-listener-pilot-zip-v1",
        "output": str(output),
        "zip": str(archive),
        "zip_bytes": archive.stat().st_size,
        "zip_sha256": digest(archive),
        "items": 8,
        "reviewer_rows": 16,
        "candidate_presented": False,
        "judgments": 0,
        "member_hashes": inventory,
        "readback_verified": True,
    }


def main() -> None:
    """Build a separate pilot; never overwrite sources or old packets."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--audio-pack", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    sys.stdout.write(json.dumps(build(args.packet, args.audio_pack, args.output), indent=2) + "\n")


if __name__ == "__main__":
    main()
