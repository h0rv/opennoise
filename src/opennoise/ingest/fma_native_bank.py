"""Explicitly bounded, offline full-statistics FMA feature bank."""

from __future__ import annotations

import json
import re
import shutil
from typing import TYPE_CHECKING, Any

from opennoise.common import canonical_json, sha256_file
from opennoise.ingest.fma_features import CHANNELS, MAX_ROWS, _project_features

if TYPE_CHECKING:
    from pathlib import Path

MAX_METADATA_BYTES = 200_000
REVISION = "fma-native-feature-bank-v1"
MAX_BANK_BYTES = 240_000_000
STAGE_LIMITS = {"cpu_seconds": 300, "wall_seconds": 360, "memory_bytes": 1_000_000_000}
NATIVE_CHANNELS = {
    **{("zcr" if key == "zero_crossing_rate" else key): value for key, value in CHANNELS.items()},
    "chroma_cqt": 12,
    "chroma_stft": 12,
    "tonnetz": 6,
}
STATISTICS = ("kurtosis", "max", "mean", "median", "min", "skew", "std")
COLUMNS = tuple(
    (name, statistic, number)
    for name, count in sorted(NATIVE_CHANNELS.items())
    for statistic in STATISTICS
    for number in range(1, count + 1)
)


def _metadata(path: Path) -> bytes:
    """Bound metadata before parsing and reject filesystem indirection."""
    if (
        any(part.is_symlink() for part in (path, *path.parents))
        or not path.is_file()
        or path.stat().st_size > MAX_METADATA_BYTES
    ):
        raise ValueError("native bank metadata file exceeds bound or is not regular")
    return path.read_bytes()


def project_native_bank(source: Path, output: Path, declaration: Path) -> dict[str, Any]:
    """Require a separately sealed budget/source declaration before projecting all columns."""
    body = _metadata(declaration)
    declared = json.loads(body)
    expected = {
        "revision": REVISION,
        "max_bank_bytes": MAX_BANK_BYTES,
        "max_rows": MAX_ROWS,
        "stage_limits": STAGE_LIMITS,
        "columns": [list(column) for column in COLUMNS],
        "source_receipt_sha256": sha256_file(source / "source-receipt.json")[0],
    }
    if any(declared.get(key) != value for key, value in expected.items()):
        raise ValueError("native bank differs from frozen declaration")
    native_sha = declared.get("native_observed_sha256")
    if not isinstance(native_sha, str) or re.fullmatch(r"[0-9a-f]{64}", native_sha) is None:
        raise ValueError("native bank requires prior verified native SHA256")
    if shutil.disk_usage(output.parent).free < MAX_BANK_BYTES + 100_000_000:
        raise ValueError("insufficient free space for native bank")
    receipt = _project_features(
        source,
        output,
        selected=COLUMNS,
        max_bytes=MAX_BANK_BYTES,
        revision=REVISION,
        write_receipt=False,
    )
    # Only publish the completion receipt after all source and output checks.
    if receipt["native_observed_sha256"] != native_sha:
        raise ValueError("native bank source differs from prior verified native SHA256")
    (output / "bank-declaration.json").write_bytes(body)
    receipt.pop("conceptual_channels")
    receipt.pop("explicit_native_channel_aliases")
    receipt.update(
        native_channels=NATIVE_CHANNELS,
        statistics=STATISTICS,
        max_bank_bytes=MAX_BANK_BYTES,
        bank_declaration_sha256=sha256_file(declaration)[0],
    )
    receipt["files"]["bank-declaration.json"] = {
        "sha256": sha256_file(output / "bank-declaration.json")[0],
        "bytes": len(body),
    }
    encoded = canonical_json(receipt) + b"\n"
    if sum(row["bytes"] for row in receipt["files"].values()) + len(encoded) > MAX_BANK_BYTES:
        raise ValueError("native bank complete artifact exceeds declared budget")
    (output / "projection-receipt.json").write_bytes(encoded)
    return receipt


def verify_native_bank(directory: Path) -> dict[str, Any]:
    """Verify completed bank inventory, shape, schema, and source declaration binding."""
    receipt = json.loads(_metadata(directory / "projection-receipt.json"))
    if (
        receipt["revision"] != REVISION
        or receipt["columns"] != [list(column) for column in COLUMNS]
        or type(receipt["rows"]) is not int
        or not 0 < receipt["rows"] <= MAX_ROWS
        or any(part.is_symlink() for part in (directory, *directory.parents))
        or receipt["native_channels"] != NATIVE_CHANNELS
        or receipt["statistics"] != list(STATISTICS)
        or re.fullmatch(r"[0-9a-f]{64}", receipt["native_observed_sha256"]) is None
        or receipt["dtype"] != "little-endian float32 with explicit NaN missingness"
        or receipt["track_id_dtype"] != "little-endian uint32"
        or receipt["native_column_count"] != len(COLUMNS)
        or receipt["license"] != "CC-BY-4.0"
        or receipt["audio_downloaded"] is not False
        or receipt["echo_nest_consumed"] is not False
        or receipt["full_archive_sha1_verified"] is not False
        or receipt["max_bank_bytes"] != MAX_BANK_BYTES
        or set(receipt["files"])
        != {
            "features.float32",
            "track_ids.uint32",
            "duplicate-native-feature-cells.json",
            "bank-declaration.json",
        }
    ):
        raise ValueError("native bank schema or inventory differs")
    if {path.name for path in directory.iterdir()} != {
        *receipt["files"],
        "projection-receipt.json",
    }:
        raise ValueError("native bank directory inventory differs")
    total = (directory / "projection-receipt.json").stat().st_size
    for name, row in receipt["files"].items():
        path = directory / name
        if (
            path.is_symlink()
            or not path.is_file()
            or sha256_file(path) != (row["sha256"], row["bytes"])
        ):
            raise ValueError("native bank artifact hash or length differs")
        total += row["bytes"]
    declaration = json.loads(_metadata(directory / "bank-declaration.json"))
    if (
        declaration["revision"] != REVISION
        or declaration["columns"] != [list(column) for column in COLUMNS]
        or declaration["max_rows"] != MAX_ROWS
        or declaration["max_bank_bytes"] != MAX_BANK_BYTES
        or declaration["stage_limits"] != STAGE_LIMITS
        or total > MAX_BANK_BYTES
        or receipt["files"]["features.float32"]["bytes"] != receipt["rows"] * len(COLUMNS) * 4
        or receipt["files"]["track_ids.uint32"]["bytes"] != receipt["rows"] * 4
        or receipt["bank_declaration_sha256"] != receipt["files"]["bank-declaration.json"]["sha256"]
        or declaration["source_receipt_sha256"] != receipt["source_receipt_sha256"]
        or declaration["native_observed_sha256"] != receipt["native_observed_sha256"]
    ):
        raise ValueError("native bank shape, budget, or source binding differs")
    return receipt
