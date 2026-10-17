"""Pinned native AB178 metadata queries and a single frozen component-isolated frame."""

from __future__ import annotations

import hashlib
import json
import math
import platform
import re
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np

from opennoise.ingest.acousticbrainz import vector_bank as bank
from opennoise.ml import recording_evaluation as engine

REVISION = "native-ab178-portable-v1"
CONTRACT_REVISION = "native-ab178-feature-contract-v1"
MAX_ROWS = 100
MAX_BYTES = 4_000_000
MAX_FILE_BYTES = 2_000_000
MAX_VERSION_LENGTH = 128
MAX_SAMPLE_RATE = 384_000
VERSION_KEYS = {"essentia", "essentia_git_sha", "essentia_build_sha", "extractor"}
CONFIG_KEYS = {"analysis_sample_rate", "downmix", "equal_loudness"}


def encoded(value: object) -> bytes:
    """Serialize finite deterministic artifacts."""
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def hash_value(value: object) -> str:
    """Bind exact canonical metadata or numeric values."""
    return hashlib.sha256(encoded(value)).hexdigest()


def read(path: Path, pin: str | None = None) -> dict[str, Any]:
    """Read only bounded regular JSON with an optional external SHA256 pin."""
    bank.safe_path(path)
    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("Artifact is not a bounded regular file")
    raw = path.read_bytes()
    if pin is not None and hashlib.sha256(raw).hexdigest() != pin:
        raise ValueError("Artifact differs from external pin")
    body = json.loads(raw)
    if not isinstance(body, dict) or encoded(body) != raw:
        raise ValueError("Artifact must be a canonical JSON object")
    return body


def contract(body: dict[str, Any]) -> dict[str, Any]:
    """Require an explicitly frozen clean extractor, full configuration and AB178 schema."""
    if (
        set(body) != {"revision", "schema_sha256", "version", "analysis"}
        or body["revision"] != CONTRACT_REVISION
        or body["schema_sha256"] != hash_value(bank.columns())
        or not isinstance(body["version"], dict)
        or set(body["version"]) != VERSION_KEYS
        or not isinstance(body["analysis"], dict)
        or set(body["analysis"]) != CONFIG_KEYS
    ):
        raise ValueError("Feature contract schema or required fields differ")
    version, analysis = body["version"], body["analysis"]
    if (
        any(
            not isinstance(v, str)
            or not 0 < len(v) <= MAX_VERSION_LENGTH
            or "dirty" in v.casefold()
            for v in version.values()
        )
        or re.fullmatch("[0-9a-f]{40}", version["essentia_build_sha"]) is None
        or type(analysis["analysis_sample_rate"]) is not int
        or not 1 <= analysis["analysis_sample_rate"] <= MAX_SAMPLE_RATE
        or analysis["downmix"] not in {"mix", "left", "right"}
        or type(analysis["equal_loudness"]) is not int
        or analysis["equal_loudness"] not in {0, 1}
    ):
        raise ValueError("Unknown or dirty extractor/configuration contract")
    return body


def runtime() -> dict[str, Any]:
    """Bind the deployed transform implementation and numerical runtime."""
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "code": {p.name: bank.digest(p) for p in (Path(__file__), Path(engine.__file__))},
    }


def destination(output: Path, sources: tuple[Path, ...]) -> None:
    """Require a fresh path outside all original inputs."""
    bank.safe_path(output)
    if output.exists() or any(output.resolve().is_relative_to(p.resolve()) for p in sources):
        raise ValueError("Output must be fresh and outside source custody")


def publish(output: Path, name: str, body: dict[str, Any]) -> str:
    """Publish one complete bounded artifact after all computation succeeds."""
    raw = encoded(body)
    if len(raw) > MAX_FILE_BYTES or len(raw) > MAX_BYTES:
        raise ValueError("Portable artifact byte cap exceeded")
    output.mkdir(parents=True, exist_ok=False)
    (output / name).write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def load(directory: Path, name: str, pin: str) -> dict[str, Any]:
    """Reject extra files, runtime drift and malformed revisions before inference."""
    bank.safe_path(directory)
    if {p.name for p in directory.iterdir()} != {name}:
        raise ValueError("Portable artifact inventory differs")
    body = read(directory / name, pin)
    if body["revision"] != REVISION:
        raise ValueError("Portable revision differs")
    return body


def source_rows(
    source: Path, feature_contract: dict[str, Any], projected: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Reuse verified native custody, values and credits; retain every source outcome."""
    data = bank.project(source) if projected is None else projected
    if not 1 <= len(data["rows"]) <= MAX_ROWS or data["columns"] != bank.columns():
        raise ValueError("Native AB178 row or column cap differs")
    rows = []
    for record in data["rows"]:
        identity = record["recording_mbid"]
        version: Any = None
        analysis: Any = None
        fact = record["exact_credit"]["fact"]
        state = record["state"]
        if state == "available":
            # Source replay already binds these exact raw bytes and embedded native ID.
            raw = json.loads((source / f"raw/sonic/{identity}.json").read_bytes())
            metadata = raw.get("metadata", {})
            version = metadata.get("version")
            properties = metadata.get("audio_properties", {})
            analysis = {key: properties.get(key) for key in sorted(CONFIG_KEYS)}
            state = "joined"
            if record["identity_state"] != "matched" or fact is None:
                state = "unverified_identity"
            elif not isinstance(version, dict) or set(version) != VERSION_KEYS:
                state = "unknown_extractor"
            elif any("dirty" in str(v).casefold() for v in version.values()):
                state = "dirty_extractor"
            elif encoded(version) != encoded(feature_contract["version"]):
                state = "extractor_version_mismatch"
            elif encoded(analysis) != encoded(feature_contract["analysis"]):
                state = "analysis_configuration_mismatch"
        artist_credits = fact["credited_artist_mbids"] if fact is not None else None
        rows.append(
            {
                "recording_mbid": identity,
                "credited_artist_mbids": artist_credits,
                "join_state": state,
                "values": record["values"] if state == "joined" else [None] * len(bank.columns()),
                "missing_mask": record["missing_mask"]
                if state == "joined"
                else [True] * len(bank.columns()),
                "version": version,
                "analysis": analysis,
                "companion": {"credit_fact": fact},
                "evidence": {
                    k: v for k, v in record.items() if k not in {"values", "missing_mask"}
                },
            }
        )
    return rows


def export_bundle(  # noqa: PLR0913, PLR0917 - independently pinned native inputs.
    source: Path,
    source_pin: str,
    native_bank: Path,
    bank_pin: str,
    contract_path: Path,
    contract_pin: str,
    fold: int,
    output: Path,
) -> str:
    """Fit one explicit train-only metadata frame; preserve all source identity components."""
    destination(output, (source, native_bank, contract_path))
    feature_contract = contract(read(contract_path, contract_pin))
    if (
        bank.digest(source / "receipt.json") != source_pin
        or bank.digest(native_bank / "receipt.json") != bank_pin
    ):
        raise ValueError("Native input receipt differs from external pin")
    rows = source_rows(source, feature_contract, bank.verify(source, native_bank))
    ledger = engine.component_ledger(rows)
    columns = [f"{c['path']}[{c['index']}]" for c in bank.columns()]
    frame = engine.fit_frame(rows, ledger, fold, columns)
    if frame["state"] != "fitted":
        raise ValueError("Explicit fold has insufficient compatible training support")
    identities = {r["recording_mbid"]: r for r in ledger["records"]}
    candidates = []
    for row in rows:
        if row["recording_mbid"] in frame["fitted_recordings"]:
            vector, reason = engine.transform(row, frame)
            if reason is None:
                candidates.append({"recording_mbid": row["recording_mbid"], "vector": vector})
    if not candidates or not any(
        r["join_state"] == "joined"
        and identities[r["recording_mbid"]]["fold"] == fold
        and any(
            identities[c["recording_mbid"]]["component_id"]
            != identities[r["recording_mbid"]]["component_id"]
            for c in candidates
        )
        for r in rows
    ):
        raise ValueError("Explicit fold has no compatible cross-component held-out query")
    return publish(
        output,
        "bundle.json",
        {
            "revision": REVISION,
            "runtime": runtime(),
            "contract": feature_contract,
            "contract_sha256": contract_pin,
            "columns": bank.columns(),
            "source_receipt_sha256": source_pin,
            "bank_receipt_sha256": bank_pin,
            "ledger": ledger,
            "frame": frame,
            "candidates": candidates,
            "roster": rows,
            "policy": engine.POLICY,
            "scope": "native metadata comparison; no audio extraction or relevance labels",
        },
    )


def bundle(directory: Path, pin: str) -> dict[str, Any]:
    """Load the frozen frame without reading any original source, bank or fit paths."""
    body = load(directory, "bundle.json", pin)
    if (
        body["runtime"] != runtime()
        or body["columns"] != bank.columns()
        or body["policy"] != engine.POLICY
        or contract(body["contract"]) != body["contract"]
        or body["contract_sha256"] != hash_value(body["contract"])
        or not 1 <= len(body["roster"]) <= MAX_ROWS
        or body["ledger"] != engine.component_ledger(body["roster"])
    ):
        raise ValueError("Frozen runtime, schema or identity ledger differs")
    validate_frame(body)
    return body


def validate_frame(body: dict[str, Any]) -> None:
    """Validate bounded frozen dimensions and replay candidates without refitting moments."""
    frame = body["frame"]
    rows = {r["recording_mbid"]: r for r in body["roster"]}
    if len(rows) != len(body["roster"]) or any(str(UUID(i)) != i for i in rows):
        raise ValueError("Frozen roster identities differ")
    training = [
        r["recording_mbid"]
        for r in body["ledger"]["records"]
        if r["fold"] != frame["heldout_fold"] and r["training_identity_state"] == "eligible"
    ]
    width = len(frame["columns"])
    if (
        frame["state"] != "fitted"
        or type(frame["heldout_fold"]) is not int
        or not 0 <= frame["heldout_fold"] < engine.POLICY["folds"]
        or frame["training_recordings"] != training
        or frame["input_columns"] != [f"{c['path']}[{c['index']}]" for c in bank.columns()]
        or not 1 <= width <= len(bank.columns())
        or len(set(frame["columns"])) != width
        or any(type(i) is not int or not 0 <= i < len(bank.columns()) for i in frame["columns"])
        or len(frame["center"]) != width
        or len(frame["scale"]) != width
        or any(type(v) not in (int, float) or not math.isfinite(v) for v in frame["center"])
        or any(
            type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in frame["scale"]
        )
        or len(frame["fitted_recordings"]) < engine.POLICY["minimum_complete_training_recordings"]
        or len(set(frame["fitted_recordings"])) != len(frame["fitted_recordings"])
        or not set(frame["fitted_recordings"]).issubset(training)
        or not 1 <= len(body["candidates"]) <= MAX_ROWS
    ):
        raise ValueError("Frozen frame dimensions or training isolation differ")
    expected = []
    for identity in sorted(frame["fitted_recordings"]):
        vector, reason = engine.transform(rows[identity], frame)
        if reason is None:
            expected.append({"recording_mbid": identity, "vector": vector})
    if body["candidates"] != expected:
        raise ValueError("Frozen candidates differ from fixed-frame transforms")


def export_queries(  # noqa: PLR0913, PLR0917 - two independently pinned packs.
    bundle_path: Path,
    bundle_pin: str,
    source: Path,
    source_pin: str,
    identities: list[str],
    output: Path,
) -> str:
    """Export exact requested native rows with full extractor and credit evidence."""
    destination(output, (bundle_path, source))
    if (
        not 1 <= len(identities) <= MAX_ROWS
        or len(set(identities)) != len(identities)
        or any(str(UUID(identity)) != identity for identity in identities)
    ):
        raise ValueError("Request requires 1..100 unique canonical recording MBIDs")
    body = bundle(bundle_path, bundle_pin)
    if (
        source_pin != body["source_receipt_sha256"]
        or bank.digest(source / "receipt.json") != source_pin
    ):
        raise ValueError("Native source receipt differs from frozen capture pin")
    by_id = {r["recording_mbid"]: r for r in source_rows(source, body["contract"])}
    frozen = {r["recording_mbid"]: r for r in body["roster"]}
    if by_id != frozen:
        raise ValueError("Native query rows differ from frozen source roster")
    rows = [
        by_id.get(identity, {"recording_mbid": identity, "join_state": "not_nominated"})
        for identity in identities
    ]
    return publish(
        output,
        "queries.json",
        {
            "revision": REVISION,
            "bundle_sha256": bundle_pin,
            "source_receipt_sha256": source_pin,
            "contract_sha256": body["contract_sha256"],
            "rows": rows,
        },
    )


def infer(bundle_path: Path, bundle_pin: str, queries: Path, query_pin: str) -> dict[str, Any]:
    """Transform only frozen compatible rows; exclude self and every known credit component."""
    body = bundle(bundle_path, bundle_pin)
    query = load(queries, "queries.json", query_pin)
    if (
        query["bundle_sha256"] != bundle_pin
        or query["source_receipt_sha256"] != body["source_receipt_sha256"]
        or query["contract_sha256"] != body["contract_sha256"]
        or not 1 <= len(query["rows"]) <= MAX_ROWS
    ):
        raise ValueError("Query schema or capture binding differs")
    roster = {r["recording_mbid"]: r for r in body["roster"]}
    metadata = {r["recording_mbid"]: r for r in body["ledger"]["records"]}
    ids = [r["recording_mbid"] for r in query["rows"]]
    if len(ids) != len(set(ids)) or any(str(UUID(i)) != i for i in ids):
        raise ValueError("Query identities are duplicate or noncanonical")
    results = []
    for row in query["rows"]:
        identity = row["recording_mbid"]
        if row != roster.get(identity, {"recording_mbid": identity, "join_state": "not_nominated"}):
            raise ValueError("Query feature, extractor or exact credit evidence differs")
        vector: list[float] = []
        reason = row["join_state"]
        neighbors = []
        if identity in metadata:
            vector, reason = engine.transform(row, body["frame"])
            if reason is None:
                component = metadata[identity]["component_id"]
                distances = [
                    (math.dist(vector, c["vector"]), c["recording_mbid"])
                    for c in body["candidates"]
                    if c["recording_mbid"] != identity
                    and metadata[c["recording_mbid"]]["component_id"] != component
                ]
                neighbors = [
                    {"recording_mbid": i, "distance": distance}
                    for distance, i in sorted(distances)[: engine.POLICY["neighbors"]]
                ]
                if not neighbors:
                    reason = "no_supported_cross_component_candidates"
        results.append(
            {
                "recording_mbid": identity,
                "outcome": reason or "emitted",
                "vector": vector,
                "neighbors": neighbors,
                "fit_member": identity in body["frame"]["fitted_recordings"],
                "component_id": metadata[identity]["component_id"]
                if identity in metadata
                else None,
                "fold": metadata[identity]["fold"] if identity in metadata else None,
            }
        )
    return {
        "revision": REVISION,
        "bundle_sha256": bundle_pin,
        "query_sha256": query_pin,
        "rows": results,
    }
