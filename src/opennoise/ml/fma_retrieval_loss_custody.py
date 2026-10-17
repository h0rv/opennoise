"""Closed artifact and source custody for a read-only frozen prediction diagnostic."""

from __future__ import annotations

import hashlib
import json
import platform
from importlib.metadata import version
from pathlib import Path
from typing import Any

PROTOCOL_SHA256 = "e9b3d7a63b28f0ea87365f2f2a89cd5269db5befe7c865f17cc9d7affeae1018"
ORIGINAL_SEAL_SHA256 = "e4351cfa8fb0f89d69c6984d63d7456510c78d39a2ba84aaa90c01134b5975e9"
MANIFEST_SHA256 = "4344e609efd7442bf2c598fefb9d1f5abb08884b59f922a53a05643c60d0a323"
ORIGINAL_SUMMARY_SHA256 = "ccf1b98b3e4ca7602f253484f5025964cadefab0e792a98968661f3d490f65e4"
MAX_OUTPUT_BYTES = 10_000_000
FOLD_FILES = {
    "embedding.npz",
    "recording_gaussian.npz",
    "balanced_gaussian.npz",
    "statistics.npz",
    "candidates.json",
    "ranks.jsonl.zst",
}


def digest(path: Path) -> str:
    """Hash a file without reading it into memory."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def encoded(value: object) -> bytes:
    """Serialize deterministic finite JSON."""
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def no_symlink(path: Path) -> None:
    """Reject ambiguous input or output locations."""
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("Symlink path is not allowed")


def inventory(root: Path) -> dict[str, Any]:
    """Bind every regular file, rejecting symlinks and special files."""
    no_symlink(root)
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ValueError("Nonregular artifact entry")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = {
                "bytes": path.stat().st_size,
                "sha256": digest(path),
            }
    return result


def versions() -> dict[str, str]:
    """Bind runtime versions without relaxing existing source guards."""
    return {
        "python": platform.python_version(),
        **{name: version(name) for name in ("numpy", "scipy", "zstandard")},
    }


def code() -> dict[str, str]:
    """Pin the diagnostic and verified loader's existing dependencies."""
    root = Path(__file__).resolve().parents[3]
    names = [
        "src/opennoise/ml/fma_retrieval_loss.py",
        "src/opennoise/ml/fma_retrieval_loss_custody.py",
        "scripts/run_fma_retrieval_loss.py",
        "src/opennoise/ml/fma_component_balanced.py",
        "src/opennoise/ml/fma_component_balanced_metrics.py",
        "src/opennoise/ml/fma_acoustic_baseline.py",
        "src/opennoise/ml/fma_split_audit.py",
    ]
    return {name: digest(root / name) for name in names}


def validate_original(  # noqa: C901 - closed source and five original stage bindings.
    original_seal: Path, source: Path, run: Path
) -> dict[str, Any]:
    """Check original fixed inputs and all six closed output stage inventories."""
    no_symlink(original_seal)
    if (
        digest(original_seal) != ORIGINAL_SEAL_SHA256
        or digest(source / "MANIFEST.json") != MANIFEST_SHA256
    ):
        raise ValueError("Original seal or numeric manifest differs")
    original = json.loads(original_seal.read_bytes())
    if original["versions"] != versions():
        raise ValueError("Original runtime versions differ")
    for name, value in code().items():
        if name in original["code"] and original["code"][name] != value:
            raise ValueError("Verified loader source differs from original execution")
    inputs = inventory(source)
    declared = json.loads((source / "MANIFEST.json").read_bytes())["files"]
    if set(inputs) != set(declared) | {"MANIFEST.json"} or any(
        inputs[name] != binding for name, binding in declared.items()
    ):
        raise ValueError("Closed numeric source inventory differs")
    files = inventory(run)
    if {p.name for p in run.iterdir()} != {"summary", *(f"fold-{fold}" for fold in range(5))}:
        raise ValueError("Original run stage inventory differs")
    if digest(run / "summary/results.json") != ORIGINAL_SUMMARY_SHA256:
        raise ValueError("Original summary pin differs")
    summary = json.loads((run / "summary/results.json").read_bytes())
    expected = {}
    for name in [*(f"fold-{fold}" for fold in range(5)), "summary"]:
        receipt = json.loads((run / name / "receipt.json").read_bytes())
        required = {"results.json"} if name == "summary" else FOLD_FILES
        if set(receipt["files"]) != required or receipt["seal_sha256"] != ORIGINAL_SEAL_SHA256:
            raise ValueError("Original stage receipt differs")
        if name != "summary" and (
            receipt["fold"] != int(name[-1])
            or digest(run / name / "receipt.json") != summary["fold_receipts"][name[-1]]
        ):
            raise ValueError("Original receipt fold or pinned summary binding differs")
        expected.update({f"{name}/{path}": binding for path, binding in receipt["files"].items()})
        expected[f"{name}/receipt.json"] = files[f"{name}/receipt.json"]
    if files != expected:
        raise ValueError("Original closed files or receipt hashes differ")
    return {"source": inputs, "run": files}


def write_outputs(output: Path, values: dict[str, Any]) -> None:
    """Check the complete new-output budget before creating any output file."""
    no_symlink(output)
    if output.exists():
        raise FileExistsError("Fresh output required")
    payloads = {name: encoded(value) for name, value in values.items()}
    if sum(map(len, payloads.values())) > MAX_OUTPUT_BYTES:
        raise ValueError("Diagnostic output exceeds 10 MB")
    output.mkdir(parents=True)
    for name, payload in payloads.items():
        (output / name).write_bytes(payload)


def freeze(
    protocol: Path, original_seal: Path, source: Path, run: Path, output: Path
) -> dict[str, Any]:
    """Bind exact already-frozen predictions before running their loss decomposition."""
    no_symlink(output)
    if output.exists() or digest(protocol) != PROTOCOL_SHA256:
        raise ValueError("Fresh seal and approved protocol required")
    bindings = validate_original(original_seal, source, run)
    result = {
        "revision": "fma-retrieval-loss-seal-v1",
        "protocol": json.loads(protocol.read_bytes()),
        "protocol_text": protocol.read_text(),
        "protocol_sha256": PROTOCOL_SHA256,
        "original_seal": str(original_seal.resolve()),
        "source": str(source.resolve()),
        "run": str(run.resolve()),
        "bindings": bindings,
        "code": code(),
        "versions": versions(),
    }
    payload = encoded(result)
    if len(payload) > MAX_OUTPUT_BYTES:
        raise ValueError("Seal exceeds output budget")
    with output.open("xb") as stream:
        stream.write(payload)
    return result


def verify_seal(path: Path) -> dict[str, Any]:
    """Fail closed on policy, code, runtime, source or saved-prediction changes."""
    no_symlink(path)
    result = json.loads(path.read_bytes())
    if (
        result["revision"] != "fma-retrieval-loss-seal-v1"
        or result["protocol_sha256"] != PROTOCOL_SHA256
        or hashlib.sha256(result["protocol_text"].encode()).hexdigest() != PROTOCOL_SHA256
        or json.loads(result["protocol_text"]) != result["protocol"]
        or result["code"] != code()
        or result["versions"] != versions()
    ):
        raise ValueError("Diagnostic seal policy or implementation differs")
    actual = validate_original(
        Path(result["original_seal"]), Path(result["source"]), Path(result["run"])
    )
    if actual != result["bindings"]:
        raise ValueError("Saved diagnostic input bindings differ")
    return result
