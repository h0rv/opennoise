"""Replay all native FMA acoustic bytes/cells and raw-versus-feature denominators."""

from __future__ import annotations

import argparse
import bz2
import csv
import hashlib
import json
import math
import struct
import zlib
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from opennoise.common import canonical_json, sha256_file
from scripts.audit_fma_native_source import projection_rows

if TYPE_CHECKING:
    from collections.abc import Iterator


def audit(source: Path, features: Path, metadata: Path) -> dict[str, object]:  # noqa: C901, PLR0912, PLR0915 - independent native stream and identity audit.
    """Validate source hashes, exact projected cells and independently recomputed duplicates."""
    receipt = json.loads((source / "source-receipt.json").read_bytes())
    projected = json.loads((features / "projection-receipt.json").read_bytes())
    if (
        receipt["member"]["name"] != "fma_metadata/features.csv"
        or receipt["license"] != "CC-BY-4.0"
        or receipt["audio_downloaded"] is not False
        or receipt["excluded"] != ["EchoNest", "pickle", "audio"]
        or projected["audio_downloaded"] is not False
        or projected["echo_nest_consumed"] is not False
        or projected["source_receipt_sha256"] != sha256_file(source / "source-receipt.json")[0]
    ):
        raise ValueError("acoustic source role or licensing contract differs")
    if sha256_file(source / "declaration.json")[0] != receipt["declaration_sha256"]:
        raise ValueError("acoustic declaration identity differs")
    for row in receipt["ranges"]:
        if sha256_file(source / row["path"]) != (row["sha256"], row["bytes"]):
            raise ValueError("captured acoustic range hash or length differs")
    for name, facts in projected["files"].items():
        if sha256_file(features / name) != (facts["sha256"], facts["bytes"]):
            raise ValueError("projected acoustic file hash or length differs")
    member = receipt["member"]
    columns = [tuple(row) for row in projected["columns"]]
    pack = struct.Struct("<" + "f" * len(columns))
    identity_pack = struct.Struct("<I")
    native_signature_groups: dict[bytes, list[int]] = defaultdict(list)
    projected_signature_groups: dict[bytes, list[int]] = defaultdict(list)
    identities: set[int] = set()
    length = crc = rows = missing = 0
    digest = hashlib.sha256()
    with (source / member["payload_path"]).open("rb") as raw:
        raw.seek(member["payload_prefix_bytes"])
        with bz2.BZ2File(raw) as native:

            def lines() -> Iterator[str]:
                nonlocal length, crc
                for line in native:
                    length += len(line)
                    crc = zlib.crc32(line, crc)
                    digest.update(line)
                    yield line.decode("utf-8")

            reader = csv.reader(lines())
            headers = [next(reader) for _row in range(3)]
            native_columns = [
                (headers[0][i], headers[1][i], int(headers[2][i]))
                for i in range(1, len(headers[0]))
            ]
            positions = [native_columns.index(column) + 1 for column in columns]
            if next(reader)[0] != "track_id":
                raise ValueError("native acoustic track index differs")
            with (
                (features / "features.float32").open("rb") as vectors,
                (features / "track_ids.uint32").open("rb") as ids,
            ):
                for row in reader:
                    identity = int(row[0])
                    if identity in identities or len(row) != len(native_columns) + 1:
                        raise ValueError("native acoustic identity duplicate or width differs")
                    identities.add(identity)
                    if ids.read(identity_pack.size) != identity_pack.pack(identity):
                        raise ValueError("native acoustic identity projection differs")
                    values = [
                        float(row[position]) if row[position] else math.nan
                        for position in positions
                    ]
                    missing += sum(not math.isfinite(value) for value in values)
                    values = [value if math.isfinite(value) else math.nan for value in values]
                    encoded = pack.pack(*values)
                    if vectors.read(pack.size) != encoded:
                        raise ValueError("native-to-float32 acoustic cell projection differs")
                    # Independent equivalence hash; source float strings retain their identities.
                    signature = hashlib.sha256(json.dumps(row[1:]).encode()).digest()
                    native_signature_groups[signature].append(identity)
                    projected_signature_groups[hashlib.sha256(encoded).digest()].append(identity)
                    rows += 1
                if ids.read(1) or vectors.read(1):
                    raise ValueError("projection adds native acoustic rows")
    if (
        length != member["uncompressed_bytes"]
        or crc != member["crc32"]
        or digest.hexdigest() != projected["native_observed_sha256"]
        or rows != projected["rows"]
    ):
        raise ValueError("full native acoustic byte, CRC, SHA or row denominator differs")
    duplicate_groups = sorted(
        sorted(group) for group in native_signature_groups.values() if len(group) > 1
    )
    if duplicate_groups != json.loads(
        (features / "duplicate-native-feature-cells.json").read_bytes()
    ):
        raise ValueError("independent full-native duplicate groups differ")
    metadata_rows = {int(str(row["track_id"])): row for row in projection_rows(metadata)}
    raw_ids = set(metadata_rows)
    intersection = raw_ids & identities
    stats: Counter[str] = Counter()
    observed_labels: set[int] = set()
    label_adapter = TypeAdapter(list[int])
    for identity, row in metadata_rows.items():
        labels = label_adapter.validate_python(row["genre_ids"] or [])
        status = "feature_present" if identity in identities else "feature_missing"
        stats[status + ":tracks"] += 1
        stats[status + ":positive_pairs"] += len(labels)
        stats[status + ":unlabeled_tracks"] += not labels
        if identity in intersection:
            observed_labels.update(labels)
            stats["intersection:" + str(row["artist_id_status"]) + ":tracks"] += 1
            stats["intersection:" + str(row["artist_id_status"]) + ":positive_pairs"] += len(labels)
    return {
        "revision": "independent-fma-acoustic-source-audit-v1",
        "source_receipt_sha256": sha256_file(source / "source-receipt.json")[0],
        "projection_receipt_sha256": sha256_file(features / "projection-receipt.json")[0],
        "metadata_tracks_sha256": sha256_file(metadata)[0],
        "native_crc32": f"{crc:08x}",
        "native_uncompressed_bytes": length,
        "native_observed_sha256": digest.hexdigest(),
        "native_feature_columns": len(native_columns),
        "projected_feature_columns": len(columns),
        "projected_cells_verified": rows * len(columns),
        "feature_rows": rows,
        "metadata_track_rows": len(raw_ids),
        "feature_metadata_intersection": len(intersection),
        "feature_rows_without_raw_metadata": len(identities - raw_ids),
        "metadata_tracks_without_features": len(raw_ids - identities),
        "quality": stats,
        "observed_native_genres_in_feature_intersection": len(observed_labels),
        "missing_selected_feature_cells": missing,
        "exact_full_native_feature_duplicate_groups": len(duplicate_groups),
        "tracks_in_exact_full_native_feature_duplicate_groups": sum(map(len, duplicate_groups)),
        "exact_projected_44_feature_duplicate_groups": sum(
            len(v) > 1 for v in projected_signature_groups.values()
        ),
        "exact_duplicate_group_ids_sha256": sha256_file(
            features / "duplicate-native-feature-cells.json"
        )[0],
        "recording_or_artist_identity_bridge_from_duplicate_features": False,
        "independent_musical_relevance": "not_measured",
        "code_sha256": sha256_file(Path(__file__))[0],
    }


def main() -> None:
    """Write a fresh independent audit with no source or model artifact mutations."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--features", required=True, type=Path)
    parser.add_argument("--metadata-tracks", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.source, args.features, args.metadata_tracks)
    with args.output.open("xb") as stream:
        stream.write(canonical_json(result) + b"\n")
    print(json.dumps(result, indent=2))  # noqa: T201 - independent audit evidence.


if __name__ == "__main__":
    main()
