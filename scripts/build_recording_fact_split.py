"""Replay native CC0 recording credits into a bounded identity-isolation example."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from opennoise.analysis.connected_split import TrackIdentity, build_split
from opennoise.ingest.acousticbrainz.native_sonic import verify_native_sonic
from opennoise.serving.metadata.recording_facts import verify_recording_fact_pack


def _verified_recordings(
    directory: Path, kind: str
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    if kind == "native-sonic":
        pack = verify_native_sonic(directory)
        return (
            pack,
            [row["exact_credit"]["fact"] for row in pack["records"] if row["artist_join_allowed"]],
            "projection.json",
        )
    pack = verify_recording_fact_pack(directory)
    return (
        pack,
        [recording for artist in pack["artists"] for recording in artist["recordings"]],
        "recording-facts.json",
    )


def main() -> int:
    """Verify raw source custody before constructing a fresh connected split artifact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path)
    parser.add_argument(
        "--pack-kind", choices=("recording-facts", "native-sonic"), default="recording-facts"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", default="opennoise-recording-facts-v1")
    args = parser.parse_args()
    directory = args.pack or Path("data/examples") / args.pack_kind
    pack, facts, projection = _verified_recordings(directory, args.pack_kind)
    records: dict[str, TrackIdentity] = {}
    for recording in facts:
        identity = "musicbrainz:recording:" + recording["recording_mbid"]
        row = TrackIdentity(
            track_id=identity,
            artist_ids=tuple(
                "musicbrainz:artist:" + value for value in recording["credited_artist_mbids"]
            ),
            recording_ids=(identity,),
        )
        if identity in records and records[identity] != row:
            raise ValueError("conflicting credits for a canonical recording")
        records[identity] = row
    report = build_split(list(records.values()), seed=args.seed)
    report["source"] = {
        "license": pack["license"],
        "pack_kind": args.pack_kind,
        "receipt_sha256": hashlib.sha256((directory / "receipt.json").read_bytes()).hexdigest(),
        "projection_sha256": hashlib.sha256((directory / projection).read_bytes()).hexdigest(),
        "native_source_replay_passed": True,
        "verified_exact_credit_records": len(facts),
        "selected_source_records": pack.get("selected_recordings", len(facts)),
    }
    report["evaluation_ready"] = False
    report["evaluation_blockers"] = [
        "The recording-credit projection supplies neither album membership nor duplicate groups.",
        "No independent musical relevance labels are supplied; no model is fitted.",
        "Known identity isolation is a structural example, not a performance evaluation.",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
