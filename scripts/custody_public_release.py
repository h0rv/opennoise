"""Verify and custody the qualified public release without rebuilding it."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from musix.pipeline.public_release_custody import (
    PublicReleaseCustodySettings,
    custody_public_release,
)

_CACHE_SHA256 = "282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866"
_CACHE_BYTE_SIZE = 153_231_360


def main() -> int:
    """Run one offline custody operation and print its atomic receipt."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--release-directory", type=Path, default=Path("config/releases/phase3-public-20260831")
    )
    parser.add_argument(
        "--cache-database",
        type=Path,
        default=Path("../phase3-public-evidence/data/phase3-public-qualified.sqlite"),
    )
    parser.add_argument(
        "--source-vault",
        type=Path,
        default=Path("../phase3-public-evidence/data/phase3-final-vault"),
    )
    parser.add_argument(
        "--evidence-directory",
        type=Path,
        default=Path("../final-integration/.cache/release-certify"),
    )
    parser.add_argument(
        "--output-directory", type=Path, default=Path("../../.cache/public-release-custody")
    )
    parser.add_argument("--expected-cache-sha256", default=_CACHE_SHA256)
    parser.add_argument("--expected-cache-byte-size", type=int, default=_CACHE_BYTE_SIZE)
    arguments = parser.parse_args()
    settings = PublicReleaseCustodySettings(
        release_directory=arguments.release_directory,
        cache_database=arguments.cache_database,
        source_vault=arguments.source_vault,
        evidence_directory=arguments.evidence_directory,
        output_directory=arguments.output_directory,
        expected_cache_sha256=arguments.expected_cache_sha256,
        expected_cache_byte_size=arguments.expected_cache_byte_size,
    )
    receipt = custody_public_release(settings, rebuild_command=tuple(sys.argv))
    sys.stdout.write(f"{receipt.model_dump_json(indent=2)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
