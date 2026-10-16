"""Project only reviewed candidate IDs and historical listen counts from local FMA."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from opennoise.ingest.fma.corpus import project_row, source_rows, verify_sources
from opennoise.ml.fma_waveform_pipeline import candidate, digest, read, write

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

SOURCE_SHA = "cd46d53488e6892eed78b742814ef95e6531b18b6d69c8eb95688da075e6df99"
RAW_SHA = "b025dc407ed663c10a0e3fd03b7b98154674bab043dff3ed8883f255010f7147"


def select_counts(
    rows: Iterable[dict[str, str]], selected: list[dict[str, Any]]
) -> list[dict[str, int]]:
    """Consume the complete checked stream, retaining no free-form source fields."""
    expected = {row["track_id"]: row for row in selected}
    counts = {}
    for raw in rows:
        identity = raw.get("track_id", "")
        if not identity.isascii() or not identity.isdecimal() or int(identity) not in expected:
            continue
        track_id = int(identity)
        native = project_row("tracks", raw)
        target = expected[track_id]
        if native["artist_id"] != target["artist_id"] or sorted(
            native["genre_ids"] or []
        ) != sorted(target["genre_ids"]):
            raise ValueError("historical popularity identity association differs")
        count = raw.get("track_listens", "")
        if not count.isascii() or not count.isdecimal() or track_id in counts:
            raise ValueError("missing, invalid or duplicate historical popularity")
        counts[track_id] = int(count)
    if set(counts) != set(expected):
        raise ValueError("historical popularity cohort incomplete")
    return [{"track_id": key, "historical_track_listens": counts[key]} for key in sorted(counts)]


def project(source: Path, manifest: Path, output: Path) -> dict[str, Any]:
    """Verify captured range custody and full raw-member hash before writing projection."""
    receipt_body = read(source / "source-receipt.json", 200_000)
    if digest(receipt_body) != SOURCE_SHA:
        raise ValueError("historical source receipt differs")
    selected = candidate(manifest)
    receipt = verify_sources(source)
    rows, checked, handles = source_rows(source, receipt["members"]["fma_metadata/raw_tracks.csv"])
    try:
        counts = select_counts(rows, selected["tracks"])
        if not checked.complete or checked.sha256.hexdigest() != RAW_SHA:
            raise ValueError("historical raw tracks stream incomplete or hash differs")
    finally:
        for handle in handles:
            handle.close()
    result = {
        "revision": "fma-permitted55-historical-listens-v1",
        "metadata_source_receipt_sha256": SOURCE_SHA,
        "native_raw_tracks_sha256": RAW_SHA,
        "candidate_manifest_sha256": digest(read(manifest, 200_000)),
        "source_captured_at": json.loads(receipt_body)["captured_at"],
        "interpretation": (
            "Historical native track_listens, not current audience popularity or musical quality."
        ),
        "tracks": counts,
    }
    write(output, result)
    return result
