"""Verify and custody the qualified public release without rebuilding it."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from opennoise.pipeline.public_release_custody import (
    PublicReleaseCustodySettings,
    custody_public_release,
)

_CACHE_SHA256 = "282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866"
_CACHE_BYTE_SIZE = 153_231_360


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_path(name: str, fallback: Path) -> Path:
    return Path(os.environ.get(name, str(fallback)))


def main() -> int:
    """Run one offline custody operation and print its atomic receipt."""
    root = _default_path("OPENNOISE_PUBLIC_RELEASE_ROOT", _project_root())
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--release-directory",
        type=Path,
        default=_default_path(
            "OPENNOISE_PUBLIC_RELEASE_DIRECTORY", root / "config/releases/phase3-public-20260831"
        ),
    )
    parser.add_argument(
        "--cache-database",
        type=Path,
        default=_default_path(
            "OPENNOISE_PUBLIC_RELEASE_CACHE",
            root / ".worktrees/phase3-public-evidence/data/phase3-public-qualified.sqlite",
        ),
    )
    parser.add_argument(
        "--source-vault",
        type=Path,
        default=_default_path(
            "OPENNOISE_PUBLIC_RELEASE_SOURCE_VAULT",
            root / ".worktrees/phase3-public-evidence/data/phase3-final-vault",
        ),
    )
    parser.add_argument(
        "--evidence-directory",
        type=Path,
        default=_default_path(
            "OPENNOISE_PUBLIC_RELEASE_EVIDENCE",
            root / ".cache/public-release-evidence",
        ),
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=_default_path(
            "OPENNOISE_PUBLIC_RELEASE_CUSTODY_OUTPUT", root / ".cache/public-release-custody"
        ),
    )
    parser.add_argument(
        "--objective-gates-directory",
        type=Path,
        default=_default_path(
            "OPENNOISE_PUBLIC_RELEASE_OBJECTIVE_GATES", root / ".cache/objective-gates"
        ),
    )
    parser.add_argument("--skip-objective-gates", action="store_true")
    parser.add_argument("--source-mode", choices=("copy", "reference"), default="copy")
    parser.add_argument("--expected-cache-sha256", default=_CACHE_SHA256)
    parser.add_argument("--expected-cache-byte-size", type=int, default=_CACHE_BYTE_SIZE)
    arguments = parser.parse_args()
    settings = PublicReleaseCustodySettings(
        release_directory=arguments.release_directory,
        cache_database=arguments.cache_database,
        source_vault=arguments.source_vault,
        evidence_directory=arguments.evidence_directory,
        output_directory=arguments.output_directory,
        objective_gates_directory=(
            None if arguments.skip_objective_gates else arguments.objective_gates_directory
        ),
        source_mode=arguments.source_mode,
        expected_cache_sha256=arguments.expected_cache_sha256,
        expected_cache_byte_size=arguments.expected_cache_byte_size,
    )
    receipt = custody_public_release(settings, rebuild_command=tuple(sys.argv))
    sys.stdout.write(f"{receipt.model_dump_json(indent=2)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
