"""Auditable candidate build from a closed roster of already-public source bytes."""

from __future__ import annotations

import platform
import shutil
import tempfile
from importlib.metadata import version
from pathlib import Path
from typing import Any, TypedDict

from opennoise.pipeline import artist_network, catalog_demo

CONTRACT = "config/releases/retained-public-catalog-inputs-v1.json"
CONTRACT_SHA256 = "c2c749c5186abc42eb01ef73fb068915920cb86975729b5352277f0c87d902c8"
REVISION = "retained-public-catalog-candidate-v1"
MAX_FILES = 1100
MAX_BYTES = 80_000_000


class PayloadMember(TypedDict):
    """A finite static member's custody, not an allowed arbitrary source path."""

    sha256: str
    bytes: int


def _file(root: Path, relative: str) -> Path:
    path = root / relative
    if (
        Path(relative).is_absolute()
        or ".." in Path(relative).parts
        or not path.resolve().is_relative_to(root.resolve())
        or any(p.is_symlink() for p in (path, *path.parents))
        or not path.is_file()
    ):
        raise ValueError(f"Unsafe or missing candidate member: {relative}")
    return path


def inputs(root: Path) -> dict[str, Any]:
    """Check every allowlisted byte before source replay; never recover another input."""
    path = _file(root, CONTRACT)
    if catalog_demo.digest(path) != CONTRACT_SHA256:
        raise ValueError("Public candidate input contract differs")
    contract = catalog_demo.read(path)
    for source in contract["sources"]:
        for relative, expected in source["files"].items():
            member = _file(root, relative)
            if (
                member.stat().st_size != expected["bytes"]
                or catalog_demo.digest(member) != expected["sha256"]
            ):
                raise ValueError(f"Public candidate source differs: {relative}")
    return contract


def inventory(site: Path) -> dict[str, PayloadMember]:
    """Describe only the generated static site, never replay databases or research reports."""
    if not site.is_dir() or site.is_symlink():
        raise ValueError("Candidate payload must be a real directory")
    result: dict[str, PayloadMember] = {}
    for path in sorted(site.rglob("*")):
        if path.is_symlink():
            raise ValueError("Candidate payload cannot contain symlinks")
        if path.is_file():
            if path.suffix not in {".html", ".mjs", ".css", ".json"}:
                raise ValueError("Candidate payload contains a non-static member")
            result[path.relative_to(site).as_posix()] = {
                "sha256": catalog_demo.digest(path),
                "bytes": path.stat().st_size,
            }
    if (
        not result
        or len(result) > MAX_FILES
        or sum(v["bytes"] for v in result.values()) > MAX_BYTES
    ):
        raise ValueError("Candidate static payload exceeds its fixed bounds")
    return result


def implementation(root: Path) -> dict[str, str]:
    """Bind actual implementation bytes, including the delegated builder and migrations."""
    paths = {
        path.relative_to(root).as_posix()
        for prefix in ("src/opennoise", "scripts", "migrations")
        for path in (root / prefix).rglob("*")
        if path.is_file() and path.suffix in {".py", ".mjs", ".css", ".html", ".sql"}
    }
    paths.update(("pyproject.toml", "uv.lock"))
    return {name: catalog_demo.digest(_file(root, name)) for name in sorted(paths)}


def build(root: Path, output: Path) -> dict[str, Any]:
    """Build a fresh candidate; preserve the canonical deploy path and all release pins."""
    root, output = root.resolve(), output.absolute()
    if (
        output.exists()
        or not output.resolve().is_relative_to(root / ".cache")
        or any(p.is_symlink() for p in (output, *output.parents))
    ):
        raise ValueError("Candidate output must be fresh, local and below checkout .cache")
    contract = inputs(root)
    artist_network.inputs(root)
    output.mkdir(parents=True)
    try:
        result = catalog_demo.build(root, output / "replay")
        shutil.copytree(Path(result["site"]), output / "site")
        network = artist_network.build(root, output / "site")
        catalog_demo._standalone(output / "site")  # noqa: SLF001 -- Rebundle after the public extension.
        manifest = {
            "revision": REVISION,
            "publication_authorized": False,
            "legacy_release_reconstructed": False,
            "private_artifacts_consumed": False,
            "acquisitions": 0,
            "input_contract_sha256": CONTRACT_SHA256,
            "input_contract": contract,
            "counts": result["counts"],
            "artist_network": network,
            "runtime": {
                "python": platform.python_version(),
                "numpy": version("numpy"),
                "scipy": version("scipy"),
            },
            "implementation_sha256": implementation(root),
            "payload": inventory(output / "site"),
            "scope": (
                "Fresh replay of the fixed public CC0 metadata/descriptor cohorts; "
                "no private demo input, annotations, relevance benchmark or playback. "
                "Source graph and small unvalidated acoustic suggestions remain separate."
            ),
        }
        catalog_demo.write(output / "payload-manifest.json", manifest)
    except BaseException:
        shutil.rmtree(output)
        raise
    return manifest


def verify(root: Path, output: Path) -> dict[str, Any]:
    """Check closed payload custody and independently rebuild from the pinned public inputs."""
    root, output = root.resolve(), output.absolute()
    if not output.resolve().is_relative_to(root / ".cache") or any(
        p.is_symlink() for p in (output, *output.parents)
    ):
        raise ValueError("Candidate verification must remain below checkout .cache")
    manifest = catalog_demo.read(_file(output, "payload-manifest.json"))
    if manifest["revision"] != REVISION or manifest["input_contract"] != inputs(root):
        raise ValueError("Candidate manifest/input scope differs")
    if inventory(output / "site") != manifest["payload"]:
        raise ValueError("Candidate closed payload inventory differs")
    with tempfile.TemporaryDirectory(dir=root / ".cache", prefix="candidate-replay-") as temporary:
        replay = build(root, Path(temporary) / "candidate")
        if replay != manifest:
            raise ValueError("Candidate does not reproduce from the declared public inputs")
    return manifest
