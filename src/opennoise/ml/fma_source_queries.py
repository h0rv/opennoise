"""Stream a verified native CSV to a small portable query pack, without a feature bank."""

from __future__ import annotations

import bz2
import csv
import io
import math
import struct
from typing import TYPE_CHECKING, Any

import numpy as np

from opennoise.ingest.fma.corpus import CheckedCSV
from opennoise.ingest.fma_features import (
    MAX_ROWS,
    MAX_SOURCE_BYTES,
    MEMBER_NAME,
    selected_feature_positions,
    verify_feature_source,
)
from opennoise.ingest.fma_native_bank import COLUMNS, MAX_METADATA_BYTES, STAGE_LIMITS
from opennoise.ml.fma_encoder_bundle import (
    MAX_QUERIES,
    QUERY_BYTES,
    QUERY_REVISION,
    load_bundle,
    sha,
    write_manifest,
)
from opennoise.ml.fma_encoder_export import fresh_destination

if TYPE_CHECKING:
    from pathlib import Path


def source_preflight(source: Path, receipt_sha256: str) -> dict[str, Any]:
    """Bound consumed files before the existing ZIP/range custody verifier reads them."""
    for name in (
        "README.md",
        "central-directory.range",
        "declaration.json",
        "source-receipt.json",
        "feature-local-header.range",
        "feature-compressed.range",
    ):
        path = source / name
        limit = MAX_SOURCE_BYTES if name == "feature-compressed.range" else MAX_METADATA_BYTES
        if (
            any(part.is_symlink() for part in (path, *path.parents))
            or not path.is_file()
            or path.stat().st_size > limit
        ):
            raise ValueError("Native source input is not a bounded regular file")
    if sha(source / "source-receipt.json") != receipt_sha256:
        raise ValueError("Native source receipt differs from external pin")
    receipt = verify_feature_source(source)
    if receipt["member"].get("payload_path") != "feature-compressed.range":
        raise ValueError("Native source payload must be the verified compressed range")
    return receipt


def scan_rows(
    source: Path,
    member: dict[str, Any],
    track_ids: list[int],
    columns: list[list[Any]],
    native_sha256: str,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Validate every row and complete EOF; retain only explicitly requested float32 rows."""
    lookup = {identity: index for index, identity in enumerate(track_ids)}
    features = np.full((len(track_ids), len(columns)), np.nan, dtype="<f4")
    present = np.zeros(len(track_ids), dtype=bool)
    seen: set[int] = set()
    float_row = struct.Struct("<" + "f" * len(COLUMNS))
    with (source / member["payload_path"]).open("rb") as raw:
        if raw.read(len(MEMBER_NAME)) != MEMBER_NAME.encode():
            raise ValueError("Native feature local filename differs")
        raw.seek(member["payload_prefix_bytes"])
        checked = CheckedCSV(bz2.BZ2File(raw), member)
        with io.TextIOWrapper(io.BufferedReader(checked), encoding="utf-8", newline="") as text:
            reader = csv.reader(text)
            native_columns, _ = selected_feature_positions([next(reader) for _ in range(3)])
            if tuple(native_columns) != COLUMNS:
                raise ValueError("Full native feature column order differs")
            positions = [native_columns.index(tuple(column)) for column in columns]
            index = next(reader)
            if len(index) != len(COLUMNS) + 1 or index[0] != "track_id" or any(index[1:]):
                raise ValueError("Native track index header differs")
            for row in reader:
                if len(row) != len(COLUMNS) + 1 or not row[0].isascii() or not row[0].isdecimal():
                    raise ValueError("Native feature row or identity differs")
                identity = int(row[0])
                if not 0 < identity < 2**32 or identity in seen or len(seen) >= MAX_ROWS:
                    raise ValueError("Native feature ID is invalid, duplicate or exceeds row cap")
                seen.add(identity)
                values = [float(cell) if cell else math.nan for cell in row[1:]]
                values = [value if math.isfinite(value) else math.nan for value in values]
                # Match the native bank's float32 conversion, including overflow rejection.
                packed = float_row.pack(*values)
                if identity in lookup:
                    features[lookup[identity]] = np.frombuffer(packed, dtype="<f4")[positions]
                    present[lookup[identity]] = True
        if not checked.complete or checked.sha256.hexdigest() != native_sha256:
            raise ValueError("Native source EOF or full CSV SHA256 differs from bundle")
    return (
        features,
        present,
        {
            "native_rows": len(seen),
            "native_uncompressed_bytes": checked.length,
            "native_zip_crc32_verified": f"{checked.crc:08x}",
        },
    )


def export_source_queries(  # noqa: PLR0913, PLR0917 - two explicitly pinned inputs.
    bundle: Path,
    bundle_sha256: str,
    source: Path,
    source_receipt_sha256: str,
    track_ids: list[int],
    output: Path,
) -> str:
    """Publish only after complete source verification; no query labels or model fitting."""
    fresh_destination(output, (bundle, source))
    if (
        not 1 <= len(track_ids) <= MAX_QUERIES
        or len(set(track_ids)) != len(track_ids)
        or any(type(identity) is not int or not 0 < identity < 2**32 for identity in track_ids)
    ):
        raise ValueError("Request requires 1..256 unique positive native uint32 IDs")
    body, *_ = load_bundle(bundle, bundle_sha256)
    source_receipt = source_preflight(source, source_receipt_sha256)
    features, present, observed = scan_rows(
        source,
        source_receipt["member"],
        track_ids,
        body["columns"],
        body["native_observed_sha256"],
    )
    output.mkdir(parents=True, exist_ok=False)
    np.savez(
        output / "queries.npz",
        ids=np.array(track_ids, dtype=np.int64),
        features=features,
        feature_present=present,
    )
    return write_manifest(
        output,
        {
            "revision": QUERY_REVISION,
            "mode": "native-source",
            "namespace": body["namespace"],
            "columns": body["columns"],
            "bundle_sha256": bundle_sha256,
            "source_receipt_sha256": source_receipt_sha256,
            "native_observed_sha256": body["native_observed_sha256"],
            "license": body["license"],
            "attribution": body["attribution"],
            "query_labels_consumed": False,
            "audio_downloaded": False,
            "full_archive_sha1_verified": False,
            "stage_limits": STAGE_LIMITS,
            "rows": len(track_ids),
            **observed,
        },
        QUERY_BYTES,
    )
