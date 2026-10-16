"""Audio-free view of the exact reviewed55 manifest and unchanged descriptor packs."""

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from opennoise.deployment import fma_profile_site as original
from opennoise.deployment.fma_public_candidate import REVIEWED_MANIFEST_SHA256
from opennoise.ml import fma_waveform_pipeline as waveform

REVISION = "fma-permitted55-audio-free-profile-site-v1"
BASE_PAGE_SHA256 = "bfef9e74ca4c5b4055bd590ffaa195585cf117357aee218ec047d38aef6cb96c"


def _replace(text: str, before: str, after: str) -> str:
    if text.count(before) != 1:
        raise ValueError("Reviewed page substitution differs")
    return text.replace(before, after, 1)


def audio_free_page() -> bytes:
    """Derive a small availability variant without modifying the frozen playback page."""
    body = original.PAGE_PATH.read_bytes()
    if hashlib.sha256(body).hexdigest() != BASE_PAGE_SHA256:
        raise ValueError("Playback template differs from reviewed derivation input")
    text = body.decode()
    section = next(line for line in text.splitlines() if line.startswith('<section id="player"'))
    text = _replace(
        text,
        section,
        '<p id="availability">No excerpt available. This view includes metadata and recording '
        "profiles only; no audio files are included.</p>",
    )
    text = _replace(
        text,
        "const q=selector=>document.querySelector(selector), audio=q('audio');",
        "const q=selector=>document.querySelector(selector);",
    )
    text = _replace(text, "playbackVersion=0,", "")
    start, end = text.index("function play(row){"), text.index("function list(){")
    replacement = """function playButton(){return node('small','No excerpt available');}
function trackCredits(row){
  const section=node('section','');section.setAttribute('aria-label','Recording credits');
  section.id='recording-credits';
  section.append(node('p',row.attribution));external(section,'License',row.license_url);
  if(row.source_url)external(section,'Native source',row.source_url);
  else section.append(node('small','Native source URL unknown.'));
  for(const url of row.embedded_source_urls)
    if(url!==row.source_url)external(section,'Supplied embedded source',url);
  for(const key of ['composer','copyright_c','copyright_p'])
    if(row[key])section.append(node('small',key+': '+row[key]));
  for(const [key,value] of Object.entries(row.embedded_notices))
    section.append(node('small',key+': '+value));
  if(row.embedded_curators.length)
    section.append(node('small','Supplied curators: '+row.embedded_curators.join('; ')));
  if(row.embedded_extra_text_present)section.append(node('small',
    'The source recording contains additional embedded text; '+
    'neither that text nor audio is included here.'));
  return section;
}
"""
    text = _replace(text, text[start:end], replacement)
    stop = next(line for line in text.splitlines() if line.startswith("q('#stop').onclick="))
    text = _replace(text, stop, "")
    for before, after in (
        ("node('p',row.attribution));", "trackCredits(row));"),
        ("fetch('candidate/manifest.json')", "fetch('metadata/manifest.json')"),
        (
            "Original audio bytes remain unchanged.",
            (
                "No audio files are included. Saved descriptors and recording profiles "
                "are reused unchanged."
            ),
        ),
        (
            '<a href="candidate/index.html">List-only interface</a>',
            '<a href="#tracks">Complete track list</a>',
        ),
        ("All artist excerpts remain playable.", "All artist records remain available."),
        ("anchor('Hear shared excerpts',", "anchor('View shared recordings',"),
    ):
        # Attribution also appears in the newly added credit helper: target the original detail row.
        if before == "node('p',row.attribution));":
            text = _replace(
                text,
                "playButton(row),node('p',row.attribution));",
                "playButton(row),trackCredits(row));",
            )
        else:
            text = _replace(text, before, after)
    return text.encode()


def _inputs(
    manifest: Path, model: Path, discovery: Path, model_pin: str, discovery_pin: str
) -> None:
    original._pin(model, model_pin)  # noqa: SLF001 - unchanged reviewed pack boundary.
    original._pin(discovery, discovery_pin)  # noqa: SLF001
    waveform.candidate(manifest)
    waveform.validate_waveform_pack(model, manifest)
    original._discovery(discovery, manifest, model, discovery_pin)  # noqa: SLF001


def validate_audio_free_site(directory: Path, model_pin: str, discovery_pin: str) -> dict[str, Any]:
    """Verify exact metadata-only inventory, unchanged packs, page and external pins."""
    path = directory / "site-receipt.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > original.MAX_RECEIPT_BYTES:
        raise ValueError("Invalid audio-free site receipt")
    receipt = json.loads(path.read_bytes())
    expected = {
        "revision",
        "candidate_manifest_sha256",
        "model_inventory_sha256",
        "discovery_inventory_sha256",
        "base_page_sha256",
        "audio_available",
        "public_deployment_authorized",
        "musical_quality_validated",
        "files",
    }
    if (
        not isinstance(receipt, dict)
        or set(receipt) != expected
        or receipt["revision"] != REVISION
        or receipt["candidate_manifest_sha256"] != REVIEWED_MANIFEST_SHA256
        or receipt["model_inventory_sha256"] != model_pin
        or receipt["discovery_inventory_sha256"] != discovery_pin
        or receipt["base_page_sha256"] != BASE_PAGE_SHA256
        or receipt["audio_available"] is not False
        or receipt["public_deployment_authorized"] is not False
        or receipt["musical_quality_validated"] is not False
        or receipt["files"] != original._inventory(directory, site=True)  # noqa: SLF001
        or {p.name for p in directory.iterdir()}
        != {"metadata", "model", "discovery", "index.html", "site-receipt.json"}
        or {p.name for p in (directory / "metadata").iterdir()} != {"manifest.json"}
        or (directory / "index.html").read_bytes() != audio_free_page()
    ):
        raise ValueError("Audio-free site custody or availability differs")
    _inputs(
        directory / "metadata/manifest.json",
        directory / "model",
        directory / "discovery",
        model_pin,
        discovery_pin,
    )
    return receipt


def build_audio_free_site(  # noqa: PLR0913, PLR0917 - three independently pinned sources.
    manifest: Path, model: Path, discovery: Path, output: Path, model_pin: str, discovery_pin: str
) -> dict[str, Any]:
    """Read a manifest file, never its audio directory, and copy only reviewed numeric packs."""
    _inputs(manifest, model, discovery, model_pin, discovery_pin)
    page = audio_free_page()
    inventories = [original._inventory(p) for p in (model, discovery)]  # noqa: SLF001
    if (
        sum(len(i) for i in inventories) + 3 > original.MAX_FILES
        or sum(r["bytes"] for i in inventories for r in i.values())
        + manifest.stat().st_size
        + len(page)
        + original.MAX_RECEIPT_BYTES
        > original.MAX_SITE_BYTES
    ):
        raise ValueError("Audio-free site exceeds unchanged export limits")
    if output.exists() or output.is_symlink() or any(p.is_symlink() for p in output.parents):
        raise ValueError("Output must be fresh and nonsymlinked")
    output.mkdir(parents=True)
    (output / "metadata").mkdir()
    (output / "metadata/manifest.json").write_bytes(waveform.read(manifest, 200000))
    for name, source in (("model", model), ("discovery", discovery)):
        shutil.copytree(source, output / name)
    (output / "index.html").write_bytes(page)
    receipt = {
        "revision": REVISION,
        "candidate_manifest_sha256": REVIEWED_MANIFEST_SHA256,
        "model_inventory_sha256": model_pin,
        "discovery_inventory_sha256": discovery_pin,
        "base_page_sha256": BASE_PAGE_SHA256,
        "audio_available": False,
        "public_deployment_authorized": False,
        "musical_quality_validated": False,
        "files": original._inventory(output, site=True),  # noqa: SLF001
    }
    (output / "site-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return validate_audio_free_site(output, model_pin, discovery_pin)
