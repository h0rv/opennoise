"""Write one fresh local-only merged discovery candidate from sealed local inputs."""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from opennoise.deployment.merged_public_direct_discovery import (
    build_merged_public_direct_discovery_candidate,
    merged_public_direct_discovery_json,
)
from opennoise.deployment.public_direct_static_discovery import SealedQidAdditiveStaticDiscovery


def _write_fresh_candidate(path: Path, payload: bytes) -> None:
    """Atomically create a local candidate and refuse any existing target."""
    if not path.parent.is_dir():
        raise ValueError(f"candidate parent directory does not exist: {path.parent}")
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing candidate: {path}")
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
            raise FileExistsError(f"refusing to overwrite existing candidate: {path}") from error
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    """Parse exact local inputs and atomically create a new inspectable candidate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-static-discovery", type=Path, required=True)
    parser.add_argument("--additive-sidecar", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    additive = SealedQidAdditiveStaticDiscovery.model_validate_json(
        arguments.additive_sidecar.read_bytes()
    )
    candidate = build_merged_public_direct_discovery_candidate(
        base_static_discovery=arguments.base_static_discovery,
        additive=additive,
    )
    _write_fresh_candidate(arguments.output, merged_public_direct_discovery_json(candidate))
    print(candidate.output_sha256)  # noqa: T201 - CLI reports the new local candidate identity.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
