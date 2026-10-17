"""Offline native recording vectors; no fitting, inferred credits or source-tag inputs."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any
from uuid import UUID

from opennoise.common import canonical_json
from opennoise.ingest.acousticbrainz.native_sonic import verify_native_sonic
from opennoise.ingest.acousticbrainz.projection import NUMERIC_PATHS, json_document

REVISION = "native-acousticbrainz-vector-bank-v1"
MAX_FILE_BYTES = 2_000_000
MAX_PACK_BYTES = 4_000_000
EXCLUDED_SCALARS = {
    "lowlevel.loudness_ebu128.integrated",
    "lowlevel.loudness_ebu128.loudness_range",
    "lowlevel.rms.mean",
}
SCALARS = tuple(p for p in NUMERIC_PATHS if p not in EXCLUDED_SCALARS)
VECTORS = (
    ("lowlevel.mfcc.mean", 13),
    ("lowlevel.gfcc.mean", 13),
    ("tonal.hpcp.mean", 36),
    ("tonal.hpcp.var", 36),
    ("lowlevel.spectral_contrast_coeffs.mean", 6),
    ("lowlevel.spectral_contrast_coeffs.var", 6),
    ("lowlevel.barkbands.mean", 27),
    ("lowlevel.barkbands.var", 27),
)
UNITS = {
    "rhythm.bpm": "beats/minute",
    "rhythm.bpm_histogram_first_peak_bpm.mean": "beats/minute",
    "rhythm.bpm_histogram_second_peak_bpm.mean": "beats/minute",
    "rhythm.beats_count": "count",
    "rhythm.onset_rate": "onsets/second",
    "lowlevel.spectral_centroid.mean": "Hz",
    "tonal.tuning_frequency": "Hz",
}


def columns() -> list[dict[str, Any]]:
    """Freeze literal source coordinate order; unspecified units are never guessed."""
    return [
        {
            "path": path,
            "index": index,
            "family": path.rsplit(".", 1)[0],
            "unit": UNITS.get(path, "source_native_unspecified"),
            "transformation": "none",
        }
        for path, width in [(p, 1) for p in SCALARS] + list(VECTORS)
        for index in ([None] if path in SCALARS else range(width))
    ]


def values(raw: dict[str, Any]) -> list[float | None]:
    """Read only allowlisted numeric leaves; missing is null, malformed fails closed."""
    result: list[float | None] = []
    for path, width in [(p, 1) for p in SCALARS] + list(VECTORS):
        value: Any = raw
        for key in path.split("."):
            if value is not None and not isinstance(value, dict):
                raise ValueError(f"Malformed native numeric branch: {path}")
            value = value.get(key) if isinstance(value, dict) else None
        if value is None:
            result.extend([None] * width)
            continue
        leaves = [value] if path in SCALARS else value
        if not isinstance(leaves, list) or len(leaves) != width:
            raise ValueError(f"Native vector shape differs: {path}")
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in leaves):
            raise ValueError(f"Invalid native numeric value: {path}")
        result.extend(float(v) for v in leaves)
    return result


def safe_path(path: Path) -> None:
    """Reject symbolic links in every supplied path component."""
    if any(part.is_symlink() for part in (path.absolute(), *path.absolute().parents)):
        raise ValueError("Symlinked bank or source path")


def digest(path: Path) -> str:
    """Hash one bounded artifact."""
    safe_path(path)
    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("Invalid bank artifact path or size")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def project(source: Path) -> dict[str, Any]:
    """Verify the entire native source before reading numeric arrays and credit evidence."""
    safe_path(source)
    source_projection = verify_native_sonic(source)
    manifest = json.loads((source / "manifest.json").read_bytes())
    captures = {r["recording_mbid"]: r for r in manifest["sonic_captures"]}
    rows = []
    for record in source_projection["records"]:
        row = {
            k: v for k, v in record.items() if k not in {"descriptors", "descriptor_missing_paths"}
        }
        capture = captures[record["recording_mbid"]]
        numeric = (
            values(json_document((source / capture["raw_path"]).read_bytes()))
            if record["state"] == "available"
            else [None] * len(columns())
        )
        row["values"] = numeric
        row["missing_mask"] = [v is None for v in numeric]
        rows.append(row)
    rows.sort(key=lambda r: r["recording_mbid"])
    return {
        "revision": REVISION,
        "license": "CC0-1.0 native AcousticBrainz data and MusicBrainz core credit facts",
        "source_receipt_sha256": digest(source / "receipt.json"),
        "columns": columns(),
        "excluded_scalar_paths": sorted(EXCLUDED_SCALARS),
        "rows": rows,
        "counts": {
            "nominated_recordings": len(rows),
            "available_recordings": sum(r["state"] == "available" for r in rows),
            "selection_artists": len({r["cohort_artist_mbid"] for r in rows}),
            "exact_credited_artists": len(
                {
                    a
                    for r in rows
                    if r["exact_credit"]["fact"]
                    for a in r["exact_credit"]["fact"]["credited_artist_mbids"]
                }
            ),
        },
        "scope": {
            "fit": False,
            "audio": False,
            "fma_join": False,
            "descriptive_tags_consumed": False,
            "global_coverage": False,
            "selection_association_is_credit": False,
            "missing_source_date_count": source_projection["missing_source_date_count"],
        },
    }


def payload(value: object) -> bytes:
    """Canonical bounded serialization before any output write."""
    body = canonical_json(value) + b"\n"
    if len(body) > MAX_FILE_BYTES:
        raise ValueError("Bank artifact exceeds byte cap")
    return body


def build(source: Path, output: Path) -> dict[str, Any]:
    """Build a new closed bank without changing source data."""
    safe_path(output)
    body = payload(project(source))
    receipt = {
        "revision": REVISION,
        "producer_sha256": digest(Path(__file__)),
        "source_receipt_sha256": digest(source / "receipt.json"),
        "files": {"bank.json": {"sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}},
    }
    receipt_body = payload(receipt)
    if len(body) + len(receipt_body) > MAX_PACK_BYTES:
        raise ValueError("Bank exceeds total byte cap")
    output.mkdir(parents=True, exist_ok=False)
    (output / "bank.json").write_bytes(body)
    (output / "receipt.json").write_bytes(receipt_body)
    return receipt


def verify(source: Path, output: Path) -> dict[str, Any]:
    """Replay all values from verified native input, not merely self-consistent hashes."""
    safe_path(output)
    if {p.name for p in output.iterdir()} != {"bank.json", "receipt.json"}:
        raise ValueError("Bank inventory differs")
    for name in ("bank.json", "receipt.json"):
        digest(output / name)
    if sum(p.stat().st_size for p in output.iterdir()) > MAX_PACK_BYTES:
        raise ValueError("Bank exceeds total byte cap")
    body = (output / "bank.json").read_bytes()
    receipt = json.loads((output / "receipt.json").read_bytes())
    expected = {
        "revision": REVISION,
        "producer_sha256": digest(Path(__file__)),
        "source_receipt_sha256": digest(source / "receipt.json"),
        "files": {"bank.json": {"sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}},
    }
    if receipt != expected or body != payload(project(source)):
        raise ValueError("Bank differs from native source replay")
    return json.loads(body)


def lookup(source: Path, output: Path, recording_mbid: str) -> dict[str, Any]:
    """Return one exact native ID, including explicit source absence outcomes."""
    if str(UUID(recording_mbid)) != recording_mbid:
        raise ValueError("Recording ID must be canonical")
    for row in verify(source, output)["rows"]:
        if row["recording_mbid"] == recording_mbid:
            return row
    raise ValueError("Recording ID was not nominated")
