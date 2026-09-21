"""Write one fresh, hash-declared local receipt for the production bridge contract."""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from opennoise.checkpoints.public_direct_bridge_candidate import CandidateInputs
from opennoise.checkpoints.public_direct_production_bridge import (
    _CANDIDATE_SHA256,
    _PRIMARY_SELECTION_SHA256,
    build_public_direct_production_bridge,
)
from opennoise.common import sha256_file


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-database", type=Path, required=True)
    parser.add_argument("--public-database-sha256", required=True)
    parser.add_argument("--static-discovery", type=Path, required=True)
    parser.add_argument("--static-discovery-sha256", required=True)
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--reconciliation-sha256", required=True)
    parser.add_argument("--canonical-layout", type=Path, required=True)
    parser.add_argument("--canonical-layout-sha256", required=True)
    parser.add_argument("--public-direct-candidate-sha256", required=True)
    parser.add_argument("--primary-selection-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _require_declared_hash(path: Path, declared: str, label: str) -> None:
    actual, _ = sha256_file(path)
    if actual != declared:
        raise ValueError(f"{label} SHA-256 does not match its declared input hash")


def _require_pinned_declaration(declared: str, expected: str, label: str) -> None:
    if declared != expected:
        raise ValueError(f"{label} SHA-256 does not match the production bridge pin")


def _write_fresh_receipt(path: Path, payload: bytes) -> None:
    """Atomically create one receipt and reject an existing target, including a symlink."""
    if not path.parent.is_dir():
        raise ValueError(f"receipt parent directory does not exist: {path.parent}")
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing receipt: {path}")
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
            raise FileExistsError(f"refusing to overwrite existing receipt: {path}") from error
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    """Verify explicit inputs, build the receipt, and create exactly one local output."""
    arguments = _arguments()
    _require_declared_hash(
        arguments.public_database, arguments.public_database_sha256, "public database"
    )
    _require_declared_hash(
        arguments.static_discovery, arguments.static_discovery_sha256, "static discovery"
    )
    _require_declared_hash(
        arguments.reconciliation, arguments.reconciliation_sha256, "reconciliation"
    )
    _require_declared_hash(
        arguments.canonical_layout, arguments.canonical_layout_sha256, "canonical layout"
    )
    _require_pinned_declaration(
        arguments.public_direct_candidate_sha256,
        _CANDIDATE_SHA256,
        "public direct candidate",
    )
    _require_pinned_declaration(
        arguments.primary_selection_sha256,
        _PRIMARY_SELECTION_SHA256,
        "primary selection",
    )
    receipt = build_public_direct_production_bridge(
        CandidateInputs(
            public_database=arguments.public_database,
            static_discovery=arguments.static_discovery,
            reconciliation=arguments.reconciliation,
            canonical_layout=arguments.canonical_layout,
        )
    )
    _write_fresh_receipt(arguments.output, receipt.model_dump_json(indent=2).encode() + b"\n")
    print(receipt.output_sha256)  # noqa: T201 - CLI reports the created receipt identity.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
