"""Package a source-verified native FMA listening site for standalone local use."""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import zstandard

from opennoise.common import canonical_json, sha256_file
from opennoise.deployment.fma_genre_discovery import ASSETS, genre_index
from opennoise.deployment.fma_listening_home import collection_keys
from opennoise.deployment.local_listening_server import (
    MAX_FILE_BYTES,
    REVISION,
    inventory,
    verify,
)

README = """OpenNoise — local listening

Extract the complete ZIP. From this OpenNoise folder run:

    python3 serve.py

Python 3.9 or newer is sufficient; no dependencies or repository are needed.
Open the printed local URL. Ctrl+C stops the server. Use --port 8001 to change
ports or --check-only to verify all files without starting a server.

Playback starts only when you press Play. Queue saves stay in this browser.
Source credits and licenses appear beside each excerpt. FMA tags and numerical
descriptor suggestions are not validated musical judgments. This is a local
research bundle; public deployment is not authorized.

MANIFEST.json records every file's SHA-256 and size. These hashes detect changes
relative to this bundle's inventory; they are not an external signature. Keep the
separately supplied archive SHA-256 for checking the downloaded ZIP.
"""


def _verify_site(root: Path) -> None:
    """Replay source bindings and each closed static export before packaging."""
    observed = inventory(root)
    expected = {"collections.html", "collections.json", "genre-discovery.json", "index.html"}
    expected.update(ASSETS[1:])
    if json.loads((root / "genre-discovery.json").read_bytes()) != genre_index(root):
        raise ValueError("discovery index differs from retained source bindings")
    for key in collection_keys(root):
        base = root / key / "explorer"
        receipt = json.loads((base / "static-receipt.json").read_bytes())
        if (
            receipt["revision"] != "fma-source-static-v1"
            or receipt["deploy_authorized"] is not False
        ):
            raise ValueError("unsupported local catalog scope")
        binding = receipt["files_manifest"]
        if binding["path"] != "files-manifest.json.zst" or sha256_file(base / binding["path"]) != (
            binding["sha256"],
            binding["bytes"],
        ):
            raise ValueError("static inventory hash differs")
        with zstandard.ZstdDecompressor().stream_reader(
            io.BytesIO((base / binding["path"]).read_bytes())
        ) as reader:
            decoded = reader.read(MAX_FILE_BYTES + 1)
        if len(decoded) > MAX_FILE_BYTES:
            raise ValueError("static inventory exceeds decode limit")
        files = json.loads(decoded)
        for relative, record in files.items():
            name = f"{key}/explorer/{relative}"
            if observed.get(name) != record:
                raise ValueError("static file differs from source-bound inventory")
            expected.add(name)
        expected.update(
            f"{key}/explorer/{name}" for name in ("static-receipt.json", "files-manifest.json.zst")
        )
        expected.update(
            path.relative_to(root).as_posix() for path in (root / key / "audio").iterdir()
        )
    if set(observed) != expected:
        raise ValueError("unexpected or missing listening site files")


def build_listening_bundle(site: Path, output: Path) -> dict[str, Any]:
    """Create a new reproducible ZIP containing verified site bytes and a local launcher."""
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing to replace a listening bundle")
    _verify_site(site)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fma-bundle-", dir=output.parent) as name:
        root = Path(name) / "OpenNoise"
        shutil.copytree(site, root / "site")
        _verify_site(root / "site")
        shutil.copyfile(Path(__file__).with_name("local_listening_server.py"), root / "serve.py")
        (root / "README.txt").write_text(README)
        manifest = {
            "revision": REVISION,
            "public_deployment_authorized": False,
            "files": inventory(root),
        }
        (root / "MANIFEST.json").write_bytes(canonical_json(manifest) + b"\n")
        verify(root)
        with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    info = zipfile.ZipInfo("OpenNoise/" + path.relative_to(root).as_posix())
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o100644 << 16
                    archive.writestr(info, path.read_bytes())
        with zipfile.ZipFile(output) as archive:
            if archive.testzip() is not None:
                raise ValueError("bundle ZIP CRC verification failed")
    digest, size = sha256_file(output)
    return {
        "path": str(output),
        "bytes": size,
        "sha256": digest,
        "files": len(manifest["files"]),
        "revision": REVISION,
        "public_deployment_authorized": False,
    }
