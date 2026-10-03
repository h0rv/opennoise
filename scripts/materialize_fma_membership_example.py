"""Reconstruct the exact FMA source-membership example from its text recipe."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, cast

RECIPE = Path(__file__).resolve().parents[1] / "data/recipes/fma-source-memberships-v1"
EXPECTED_FILES = {
    "calibration-memberships.jsonl.zst": ("calibration-memberships.jsonl.zst.base64.txt", "base64"),
    "confirmation-memberships.jsonl.zst": (
        "confirmation-memberships.jsonl.zst.base64.txt",
        "base64",
    ),
    "declaration.json": ("declaration.json", "utf-8"),
    "evaluation.json": ("evaluation.json", "utf-8"),
    "fma_memberships.py": ("fma_memberships.py.source", "utf-8"),
    "pack-receipt.json": ("pack-receipt.json", "utf-8"),
    "README.md": ("README.md.source", "utf-8"),
    "test_diagnostic-memberships.jsonl.zst": (
        "test_diagnostic-memberships.jsonl.zst.base64.txt",
        "base64",
    ),
    "thresholds.json": ("thresholds.json", "utf-8"),
}
MANIFEST_FIELDS = {"revision", "license", "attribution", "interpretation", "sources"}
SOURCE_FIELDS = {"payload", "encoding", "bytes", "sha256"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _decode_payload(payload: bytes, encoding: str, original: str) -> bytes:
    if encoding == "utf-8":
        payload.decode("utf-8", errors="strict")
        return payload
    if encoding != "base64":
        raise ValueError(f"unsupported encoding for {original}: {encoding!r}")
    try:
        text = payload.decode("ascii", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError(f"base64 payload is not ASCII for {original}") from exc
    if not text.endswith("\n") or "\n" in text[:-1] or "\r" in text:
        raise ValueError(f"base64 payload must be one ASCII line for {original}")
    try:
        return base64.b64decode(text[:-1], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"invalid strict base64 payload for {original}") from exc


def _read_manifest(recipe: Path) -> dict[str, object]:
    manifest_path = recipe / "recipe-manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError("recipe manifest is missing or is not a regular file")
    try:
        manifest: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("recipe manifest is not valid UTF-8 JSON") from exc
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_FIELDS:
        raise ValueError("recipe manifest fields differ from the expected schema")
    if manifest["revision"] != "fma-source-memberships-text-recipe-v1":
        raise ValueError("recipe revision differs")
    if manifest["license"] != "CC-BY-4.0":
        raise ValueError("recipe license differs")
    sources = manifest["sources"]
    if not isinstance(sources, dict) or set(sources) != set(EXPECTED_FILES):
        raise ValueError("recipe source inventory differs from the known nine files")
    return {name: sources[name] for name in EXPECTED_FILES}


def _read_source(recipe: Path, original: str, record: object) -> bytes:
    """Decode and check one manifest-bound source payload."""
    expected_payload, expected_encoding = EXPECTED_FILES[original]
    if not isinstance(record, dict) or set(record) != SOURCE_FIELDS:
        raise ValueError(f"manifest binding fields differ for {original}")
    record = cast("dict[str, object]", record)
    if record["payload"] != expected_payload or record["encoding"] != expected_encoding:
        raise ValueError(f"manifest payload mapping differs for {original}")
    payload_path = recipe / expected_payload
    if not payload_path.is_file() or payload_path.is_symlink():
        raise ValueError(f"payload is missing or not a regular file: {expected_payload}")
    source_bytes = _decode_payload(payload_path.read_bytes(), expected_encoding, original)
    digest = hashlib.sha256(source_bytes).hexdigest()
    if (
        not isinstance(record["bytes"], int)
        or isinstance(record["bytes"], bool)
        or record["bytes"] != len(source_bytes)
    ):
        raise ValueError(f"decoded byte count differs for {original}")
    if not isinstance(record["sha256"], str) or not SHA256_RE.fullmatch(record["sha256"]):
        raise ValueError(f"invalid SHA-256 manifest value for {original}")
    if record["sha256"] != digest:
        raise ValueError(f"decoded SHA-256 differs for {original}")
    return source_bytes


def _check_payload_inventory(recipe: Path) -> None:
    expected_payloads = {"recipe-manifest.json", "README.md"}
    expected_payloads.update(mapping[0] for mapping in EXPECTED_FILES.values())
    actual_payloads = set()
    for child in recipe.iterdir():
        if child.is_symlink() or not child.is_file():
            raise ValueError(f"unexpected non-file recipe entry: {child.name}")
        actual_payloads.add(child.name)
    if actual_payloads != expected_payloads:
        raise ValueError("recipe payload inventory differs from manifest")
    (recipe / "README.md").read_bytes().decode("utf-8", errors="strict")


def validate_recipe(recipe: Path = RECIPE) -> dict[str, bytes]:
    """Return exact source bytes after validating inventory and every binding."""
    sources = _read_manifest(recipe)
    decoded = {name: _read_source(recipe, name, sources[name]) for name in EXPECTED_FILES}
    _check_payload_inventory(recipe)
    return decoded


def materialize(recipe: Path, output: Path) -> dict[str, Any]:
    """Write validated source bytes into a new directory that cannot be overwritten."""
    files = validate_recipe(recipe)
    # mkdir without exist_ok makes the requested output a fresh, exclusive path.
    output.mkdir(parents=False, exist_ok=False)
    for name, content in files.items():
        (output / name).write_bytes(content)
    return {
        "output": str(output),
        "files_written": len(files),
        "total_bytes": sum(map(len, files.values())),
        "license": "CC-BY-4.0",
    }


def main() -> None:
    """Parse command-line arguments and materialize the recipe."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="new output directory that does not already exist",
    )
    parser.add_argument("--recipe", type=Path, default=RECIPE, help="text recipe directory")
    args = parser.parse_args()
    sys.stdout.write(json.dumps(materialize(args.recipe, args.output), ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
