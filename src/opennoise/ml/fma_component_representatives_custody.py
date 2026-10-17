"""Immutable protocol, saved experiment and bounded stage custody."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, BinaryIO

from opennoise.ml.fma_retrieval_loss_custody import (
    code as original_code,
)
from opennoise.ml.fma_retrieval_loss_custody import (
    digest,
    encoded,
    inventory,
    no_symlink,
    validate_original,
    versions,
)

PROTOCOL_SHA256 = "7ce59e1c4ef85e2f38f0e0224e8aa39a28a0186f73027a301ec1246a4ac3f949"
MAX_OUTPUT_BYTES = 100_000_000
FOLD_FILES = {"candidates.json", "predictions.jsonl.zst", "components.json"}


def code() -> dict[str, str]:
    """Bind every local implementation dependency used for verification or new ranking."""
    root = Path(__file__).resolve().parents[3]
    names = [
        "src/opennoise/ml/fma_component_representatives.py",
        "src/opennoise/ml/fma_component_representatives_stats.py",
        "src/opennoise/ml/fma_component_representatives_custody.py",
        "scripts/run_fma_component_representatives.py",
    ]
    return {**original_code(), **{name: digest(root / name) for name in names}}


def freeze(
    protocol: Path, original_seal: Path, source: Path, original_run: Path, output: Path
) -> dict[str, Any]:
    """Seal one reviewed design before any new retained-data neighborhoods are computed."""
    no_symlink(output)
    if output.exists() or digest(protocol) != PROTOCOL_SHA256:
        raise ValueError("Fresh seal and exact approved protocol required")
    bindings = validate_original(original_seal, source, original_run)
    result = {
        "revision": "fma-component-representatives-seal-v1",
        "protocol_text": protocol.read_text(),
        "protocol": json.loads(protocol.read_bytes()),
        "protocol_sha256": PROTOCOL_SHA256,
        "source": str(source.resolve()),
        "original_run": str(original_run.resolve()),
        "original_seal": str(original_seal.resolve()),
        "bindings": bindings,
        "code": code(),
        "versions": versions(),
    }
    with output.open("xb") as stream:
        stream.write(encoded(result))
    return result


def verify_seal(path: Path) -> dict[str, Any]:
    """Reject changed source, runtime, design or historical predictions."""
    no_symlink(path)
    result = json.loads(path.read_bytes())
    if (
        result["revision"] != "fma-component-representatives-seal-v1"
        or result["protocol_sha256"] != PROTOCOL_SHA256
        or hashlib.sha256(result["protocol_text"].encode()).hexdigest() != PROTOCOL_SHA256
        or json.loads(result["protocol_text"]) != result["protocol"]
        or result["code"] != code()
        or result["versions"] != versions()
    ):
        raise ValueError("Frozen protocol, code or runtime differs")
    actual = validate_original(
        Path(result["original_seal"]), Path(result["source"]), Path(result["original_run"])
    )
    if actual != result["bindings"]:
        raise ValueError("Historical artifact bindings differ")
    return result


def output_bytes(root: Path) -> int:
    """Count all stage bytes without following links."""
    no_symlink(root)
    total = 0
    for path in root.rglob("*"):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError("Nonregular output entry")
        if path.is_file():
            total += path.stat().st_size
    if total > MAX_OUTPUT_BYTES:
        raise ValueError("Combined output exceeds 100 MB")
    return total


class BoundedWriter:
    """Enforce remaining compressed-output space before every compressor write."""

    def __init__(self, stream: BinaryIO, allowance: int) -> None:
        """Reserve only the current stage's remaining compressed-byte allowance."""
        self.stream = stream
        self.remaining = allowance

    def write(self, value: bytes) -> int:
        """Reject an oversized write before mutating the stage."""
        if len(value) > self.remaining:
            raise ValueError("Combined output exceeds 100 MB")
        count = self.stream.write(value)
        self.remaining -= count
        return count

    def flush(self) -> None:
        """Flush only the current regular file."""
        self.stream.flush()


def write_json(root: Path, path: Path, value: object) -> None:
    """Create one fresh stage file within the unchanged combined bound."""
    no_symlink(path)
    payload = encoded(value)
    if output_bytes(root) + len(payload) > MAX_OUTPUT_BYTES:
        raise ValueError("Combined output exceeds 100 MB")
    with path.open("xb") as stream:
        stream.write(payload)


def receipt(root: Path, folder: Path, seal: Path, stage: str) -> None:
    """Close a deterministic stage inventory with no fitted-model claim."""
    write_json(
        root,
        folder / "receipt.json",
        {
            "revision": "fma-component-representatives-stage-v1",
            "stage": stage,
            "seal_sha256": digest(seal),
            "model_fit": False,
            "deploy_authorized": False,
            "files": inventory(folder),
        },
    )


def verify_stage(folder: Path, seal: Path, stage: str) -> dict[str, Any]:
    """Require every expected stage file, exact hashes and truthful scope flags."""
    actual = inventory(folder)
    required = {"results.json"} if stage == "summary" else FOLD_FILES
    result = json.loads((folder / "receipt.json").read_bytes())
    if (
        set(actual) != required | {"receipt.json"}
        or set(result)
        != {"revision", "stage", "seal_sha256", "model_fit", "deploy_authorized", "files"}
        or result["revision"] != "fma-component-representatives-stage-v1"
        or result["stage"] != stage
        or result["seal_sha256"] != digest(seal)
        or result["model_fit"] is not False
        or result["deploy_authorized"] is not False
        or result["files"] != {name: actual[name] for name in required}
    ):
        raise ValueError("Closed stage inventory or scope differs")
    return result
