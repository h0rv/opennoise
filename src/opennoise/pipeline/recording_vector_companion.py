"""Verified native vector left joins, without changing the historical scalar companion."""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path
from typing import Any

from opennoise.ingest.acousticbrainz.vector_bank import digest, payload, safe_path, verify
from opennoise.pipeline.recording_feature_companion import _fact_observations
from opennoise.serving.metadata.recording_facts import verify_recording_fact_pack

REVISION = "exact-recording-vector-companion-v2"
MAX_ROWS = 1000
MAX_SOURCE_ENTRIES = 256
MAX_BYTES = 4_000_000
MEMBERS = {"observations.json", "report.json"}


def join(observation: dict[str, Any], row: dict[str, Any] | None, width: int) -> dict[str, Any]:
    """Require exact recording identity and complete concordant native credit sets."""
    state = "not_nominated"
    if row is not None:
        if row["recording_mbid"] != observation["recording_mbid"]:
            raise ValueError("Recording identity mismatch")
        state = "unavailable_source"
        if row["state"] == "available" and row["identity_state"] == "matched":
            state = "missing_companion_credit"
            fact = row["exact_credit"]["fact"]
            if fact is not None:
                if fact["recording_mbid"] != observation["recording_mbid"]:
                    raise ValueError("Credit identity mismatch")
                native_credits = observation["credited_artist_mbids"]
                state = "missing_observation_credit"
                if native_credits is not None:
                    state = "credit_conflict"
                    if observation["artist_mbid"] in native_credits and set(native_credits) == set(
                        fact["credited_artist_mbids"]
                    ):
                        state = "joined"
    numeric = list(row["values"]) if state == "joined" and row is not None else [None] * width
    if len(numeric) != width:
        raise ValueError("Vector width differs")
    return {
        **observation,
        "join_state": state,
        "values": numeric,
        "missing_mask": [v is None for v in numeric],
        "companion_evidence": None
        if row is None
        else {k: v for k, v in row.items() if k not in {"values", "missing_mask"}},
    }


def derive(observations: Path, source: Path, bank: Path) -> tuple[bytes, dict[str, Any]]:
    """Replay both independent source chains before constructing any joined rows."""
    for path in (observations, source, bank):
        safe_path(path)
    total = 0
    for entries, path in enumerate(observations.rglob("*"), start=1):
        safe_path(path)
        if entries > MAX_SOURCE_ENTRIES:
            raise ValueError("Observation inventory cap exceeded")
        if path.is_file():
            digest(path)
            total += path.stat().st_size
            if total > MAX_BYTES:
                raise ValueError("Observation source byte cap exceeded")
        elif not path.is_dir():
            raise ValueError("Invalid observation source entry")
    projection = verify_recording_fact_pack(observations)
    vector_bank = verify(source, bank)
    by_id = {r["recording_mbid"]: r for r in vector_bank["rows"]}
    rows = []
    for observation in _fact_observations(observations, projection):
        if len(rows) >= MAX_ROWS:
            raise ValueError("Observation cap exceeded")
        rows.append(
            join(observation, by_id.get(observation["recording_mbid"]), len(vector_bank["columns"]))
        )
    body = payload({"revision": REVISION, "columns": vector_bank["columns"], "rows": rows})
    states = Counter(r["join_state"] for r in rows)
    report = {
        "revision": REVISION,
        "implementation_sha256": digest(Path(__file__)),
        "inputs": {
            "observation_receipt_sha256": digest(observations / "receipt.json"),
            "native_receipt_sha256": digest(source / "receipt.json"),
            "bank_receipt_sha256": digest(bank / "receipt.json"),
            "bank_sha256": digest(bank / "bank.json"),
        },
        "observation_rows": len(rows),
        "unique_recordings": len({r["recording_mbid"] for r in rows}),
        "unique_artist_recording_pairs": len(
            {(r["artist_mbid"], r["recording_mbid"]) for r in rows}
        ),
        "joined_unique_recordings": len(
            {r["recording_mbid"] for r in rows if r["join_state"] == "joined"}
        ),
        "join_states": dict(sorted(states.items())),
        "source_states": dict(
            sorted(
                Counter(
                    "not_nominated"
                    if r["companion_evidence"] is None
                    else r["companion_evidence"]["state"]
                    for r in rows
                ).items()
            )
        ),
        "observed_rows_per_column": [
            sum(not r["missing_mask"][i] for r in rows) for i in range(len(vector_bank["columns"]))
        ],
        "files": {
            "observations.json": {"sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
        },
        "policy": {
            "license": "CC0-1.0",
            "model_fit": False,
            "audio": False,
            "selection_association_is_credit": False,
            "representative_sample": False,
            "missing_values": "null; no imputation",
            "row_unit": "source observation, not unique recording",
        },
    }
    return body, report


def build(observations: Path, source: Path, bank: Path, output: Path) -> dict[str, Any]:
    """Write a fresh bounded artifact, never inside an input pack."""
    safe_path(output)
    if any(output.resolve().is_relative_to(p.resolve()) for p in (observations, source, bank)):
        raise ValueError("Output overlaps source custody")
    body, report = derive(observations, source, bank)
    summary = payload(report)
    if len(body) + len(summary) > MAX_BYTES:
        raise ValueError("Output cap exceeded")
    output.mkdir(parents=True, exist_ok=False)
    (output / "observations.json").write_bytes(body)
    (output / "report.json").write_bytes(summary)
    return report


def replay(observations: Path, source: Path, bank: Path, output: Path) -> dict[str, Any]:
    """Compare all bytes against native replay, rejecting resealed altered outputs."""
    safe_path(output)
    if {p.name for p in output.iterdir()} != MEMBERS:
        raise ValueError("Output inventory differs")
    for name in MEMBERS:
        digest(output / name)
    if sum((output / name).stat().st_size for name in MEMBERS) > MAX_BYTES:
        raise ValueError("Output cap exceeded")
    body, report = derive(observations, source, bank)
    if (output / "observations.json").read_bytes() != body or (
        output / "report.json"
    ).read_bytes() != payload(report):
        raise ValueError("Output differs from source replay")
    return report
