"""Deterministic standalone view of an externally pinned, validated audio-free site."""

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from opennoise.deployment.fma_audio_free_site import validate_audio_free_site

REVISION = "fma-reviewed55-audio-free-standalone-v1"
MAX_HTML_BYTES = 512 * 1024
DATA_FILES = ("metadata/manifest.json", "model/layout.json", "discovery/discovery.json")
RECEIPTS = ("model/receipt.json", "discovery/receipt.json")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _replace(text: str, before: str, after: str) -> str:
    if text.count(before) != 1:
        raise ValueError("Standalone derivation boundary differs")
    return text.replace(before, after, 1)


def standalone_bytes(source: Path, model_pin: str, discovery_pin: str) -> bytes:
    """Validate the original closed site, then embed only its exact five view inputs."""
    validate_audio_free_site(source, model_pin, discovery_pin)
    original = (source / "index.html").read_bytes()
    files = {name: (source / name).read_bytes() for name in (*DATA_FILES, *RECEIPTS)}
    provenance = {
        "revision": REVISION,
        "source_page_sha256": _sha(original),
        "source_site_receipt_sha256": _sha((source / "site-receipt.json").read_bytes()),
        "model_inventory_sha256": model_pin,
        "discovery_inventory_sha256": discovery_pin,
        "embedded_sources": {
            name: {"bytes": len(content), "sha256": _sha(content)}
            for name, content in files.items()
        },
        "audio_available": False,
        "public_deployment_authorized": False,
        "musical_quality_validated": False,
    }
    text = original.decode("utf-8")
    blocks = []
    for i, name in enumerate(DATA_FILES):
        # JSON stays inert even when supplied credits contain an HTML closing-script token.
        content = files[name].decode("utf-8").replace("<", "\\u003c")
        blocks.append(
            f'<script type="application/json" id="standalone-data-{i}">{content}</script>'
        )
        text = _replace(text, f"fetch('{name}')", f"embeddedResponse('standalone-data-{i}')")
    binding = json.dumps(provenance, sort_keys=True, separators=(",", ":")).replace("<", "\\u003c")
    blocks.append(f'<script type="application/json" id="standalone-provenance">{binding}</script>')
    # Preserve the strict-mode directive as the first statement of the executable script.
    before = "<script>\n'use strict';"
    helper = """\nfunction embeddedResponse(id){
  const block=document.getElementById(id);
  if(!block)return Promise.reject(new Error('Embedded source unavailable'));
  return Promise.resolve({ok:true,text:async()=>block.textContent});
}
"""
    text = _replace(text, before, "\n".join(blocks) + "\n" + before + helper)
    for name in RECEIPTS:
        encoded = base64.b64encode(files[name]).decode("ascii")
        download = name.replace("/", "-")
        text = _replace(
            text,
            f'href="{name}"',
            f'download="{download}" href="data:application/json;base64,{encoded}"',
        )
    result = text.encode("utf-8")
    if len(result) > MAX_HTML_BYTES:
        raise ValueError("Standalone HTML exceeds512KiB")
    return result


def verify_standalone(
    source: Path, html: Path, model_pin: str, discovery_pin: str
) -> dict[str, Any]:
    """Reconstruct exact expected bytes; embedded claims alone never authorize content."""
    if html.is_symlink() or not html.is_file() or html.stat().st_size > MAX_HTML_BYTES:
        raise ValueError("Invalid bounded standalone file")
    expected = standalone_bytes(source, model_pin, discovery_pin)
    if html.read_bytes() != expected:
        raise ValueError("Standalone content differs from validated source")
    return {"revision": REVISION, "bytes": len(expected), "sha256": _sha(expected)}


def build_standalone(
    source: Path, output: Path, model_pin: str, discovery_pin: str
) -> dict[str, Any]:
    """Write one fresh HTML file; preserve the source and every historical exporter."""
    if output.exists() or output.is_symlink() or any(p.is_symlink() for p in output.parents):
        raise ValueError("Fresh standalone output path required")
    content = standalone_bytes(source, model_pin, discovery_pin)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(content)
    return {"revision": REVISION, "bytes": len(content), "sha256": _sha(content)}
