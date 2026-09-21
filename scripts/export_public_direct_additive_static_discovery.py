"""Write one fresh local-only additive static-discovery sidecar."""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from opennoise.checkpoints.sealed_qid_direct_bridge import SealedQidDirectBridge
from opennoise.deployment.public_direct_static_discovery import (
    build_sealed_qid_additive_static_discovery,
    sealed_qid_additive_static_discovery_json,
)


def _write_fresh_output(path: Path, payload: bytes) -> None:
    """Atomically create a sidecar without replacing an existing file or symlink."""
    if not path.parent.is_dir():
        raise ValueError(f"output parent directory does not exist: {path.parent}")
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing output: {path}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise FileExistsError(f"refusing to overwrite existing output: {path}") from error
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    """Parse pinned local inputs and create one fresh sidecar."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-database", type=Path, required=True)
    parser.add_argument("--base-static-discovery", type=Path, required=True)
    parser.add_argument("--bridge-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    bridge = SealedQidDirectBridge.model_validate_json(arguments.bridge_receipt.read_bytes())
    payload = build_sealed_qid_additive_static_discovery(
        database=arguments.public_database,
        base_static_discovery=arguments.base_static_discovery,
        bridge=bridge,
    )
    _write_fresh_output(arguments.output, sealed_qid_additive_static_discovery_json(payload))
    print(payload.output_sha256)  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
