"""Freeze, export, load and replay a bounded target-free recording comparison."""

from __future__ import annotations

import gzip
import hashlib
import json
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opennoise.common import sha256_file
from opennoise.ml import recording_evaluation as engine
from opennoise.pipeline.recording_feature_companion import replay_companion

MAX_OBSERVATIONS = 250_000
MAX_DECODED_BYTES = 128_000_000
MAX_LINE_BYTES = 1_000_000
MAX_OUTPUT_BYTES = 20_000_000
MAX_DISTANCE_PAIRS = 2_000_000
MEMBERS = {"declaration.json", "ledger.json", "frames.json", "queries.jsonl.gz", "report.json"}


@dataclass(frozen=True)
class Inputs:
    """Native custody is required for every run, including offline replay."""

    observations: Path
    sonic: Path
    companion: Path
    native_source: Path | None = None
    root: Path | None = None


def canonical(value: object) -> bytes:
    """Encode reproducible finite JSON without paths, clock values or pickle."""
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def binding(path: Path) -> dict[str, object]:
    """Bind bytes for portable artifacts; no trust is inferred from a self-sealed hash."""
    digest, size = sha256_file(path)
    return {"sha256": digest, "bytes": size}


def _destination(inputs: Inputs, destination: Path) -> None:
    if any(path.is_symlink() for path in (destination, *destination.parents)):
        raise ValueError("evaluation destination has a symlink ancestor")
    for source in (inputs.observations, inputs.sonic, inputs.companion, inputs.native_source):
        if source is not None and destination.resolve().is_relative_to(source.resolve()):
            raise ValueError("evaluation destination must remain outside source custody")


def verified_rows(inputs: Inputs) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Replay native inputs, then bound decoded material before loading the observation roster."""
    report = replay_companion(
        inputs.observations,
        inputs.sonic,
        inputs.companion,
        native_source=inputs.native_source,
        root=inputs.root,
    )
    if report["observation_rows"] > MAX_OBSERVATIONS or report["decoded_bytes"] > MAX_DECODED_BYTES:
        raise ValueError("evaluation input exceeds declared memory budget")
    rows = []
    decoded = 0
    with gzip.open(inputs.companion / "features.jsonl.gz", "rb") as stream:
        while line := stream.readline(MAX_LINE_BYTES + 1):
            decoded += len(line)
            if (
                len(line) > MAX_LINE_BYTES
                or decoded > MAX_DECODED_BYTES
                or len(rows) >= MAX_OBSERVATIONS
            ):
                raise ValueError("evaluation decoded input budget exceeded")
            rows.append(json.loads(line))
    if len(rows) != report["observation_rows"] or decoded != report["decoded_bytes"]:
        raise ValueError("evaluation source denominator changed after replay")
    return rows, report


def _declaration(inputs: Inputs, ledger: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[3]
    implementation = (
        "src/opennoise/ml/recording_evaluation.py",
        "src/opennoise/pipeline/recording_evaluation.py",
        "scripts/evaluate_recording_companion.py",
    )
    return {
        "revision": engine.REVISION,
        "policy": engine.POLICY,
        "companion_report": binding(inputs.companion / "report.json"),
        "features": binding(inputs.companion / "features.jsonl.gz"),
        "numeric_paths": source["numeric_paths"],
        "ledger_sha256": hashlib.sha256(canonical(ledger)).hexdigest(),
        "implementation": {name: binding(root / name) for name in implementation},
        "queries": "every source observation in its component-held-out fold; no sampling",
        "duplicate_observations": "one training recording; retain all observation query outcomes",
        "partial_duplicate_join_policy": (
            "any non-joined observation quarantines the training identity"
        ),
        "baseline": "fixed SHA256 order on same supported training candidates as numeric arm",
        "selection": "fixed support rules; fitted columns and moments use training recordings only",
        "targets": "none; all relevance metrics unavailable",
        "confirmation": "previously inspected small selected sources; no fresh confirmation",
        "isolation": ledger["isolation"],
        "limits": {
            "observations": MAX_OBSERVATIONS,
            "decoded_bytes": MAX_DECODED_BYTES,
            "output_bytes": MAX_OUTPUT_BYTES,
            "distance_pairs": MAX_DISTANCE_PAIRS,
        },
    }


def freeze(inputs: Inputs, destination: Path) -> dict[str, Any]:
    """Persist fixed rules and source/code bindings before any transform or ranking is fitted."""
    _destination(inputs, destination)
    if destination.exists():
        raise ValueError("evaluation declaration must be fresh")
    rows, source = verified_rows(inputs)
    declaration = _declaration(inputs, engine.component_ledger(rows), source)
    with destination.open("xb") as stream:
        stream.write(canonical(declaration))
    return declaration


def _write(output: Path, name: str, value: object) -> None:
    body = canonical(value)
    if len(body) + sum(path.stat().st_size for path in output.iterdir()) > MAX_OUTPUT_BYTES:
        raise ValueError("evaluation output byte budget exceeded")
    (output / name).write_bytes(body)


def _write_queries(output: Path, queries: list[dict[str, Any]]) -> None:
    with (output / "queries.jsonl.gz").open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as stream:
            for query in queries:
                stream.write(canonical(query))
                if raw.tell() > MAX_OUTPUT_BYTES:
                    raise ValueError("evaluation query byte budget exceeded")
        if raw.tell() > MAX_OUTPUT_BYTES:
            raise ValueError("evaluation query byte budget exceeded")


def run(inputs: Inputs, declaration_path: Path, output: Path) -> dict[str, Any]:
    """Refuse policy/source drift, fit each training fold, and score all declared observations."""
    _destination(inputs, output)
    if output.exists():
        raise ValueError("evaluation output must be fresh")
    rows, source = verified_rows(inputs)
    ledger = engine.component_ledger(rows)
    declaration = _declaration(inputs, ledger, source)
    if declaration_path.is_symlink() or declaration_path.read_bytes() != canonical(declaration):
        raise ValueError("frozen evaluation declaration differs from source, code or fixed policy")
    eligible = sum(row["training_identity_state"] == "eligible" for row in ledger["records"])
    if eligible * eligible > MAX_DISTANCE_PAIRS:
        raise ValueError("evaluation distance-pair budget exceeded")
    frames = [
        engine.fit_frame(rows, ledger, fold, source["numeric_paths"])
        for fold in range(engine.POLICY["folds"])
    ]
    # Exercise the portable JSON load contract before computing exported results.
    frames = json.loads(canonical(frames))
    queries, summary = engine.compare_recordings(rows, ledger, frames)
    output.mkdir(parents=True)
    _write(output, "declaration.json", declaration)
    _write(output, "ledger.json", ledger)
    _write(output, "frames.json", frames)
    _write_queries(output, queries)
    report = {
        "revision": engine.REVISION,
        "files": {path.name: binding(path) for path in sorted(output.iterdir())},
        "summary": summary,
        "source_artist_coverage": source["inputs"]["source_artist_coverage"],
        "artist_observation_outcomes": {
            artist: dict(Counter(row["outcome"] for row in queries if row["artist_mbid"] == artist))
            for artist in source["artist_join_states"]
        },
        "isolation": ledger["isolation"],
        "model_scope": "train-only metadata comparison; no relevance or genre probabilities",
    }
    _write(output, "report.json", report)
    return report


def load_frames(output: Path) -> list[dict[str, Any]]:
    """Load hash-bound JSON transforms; native custody still requires replay, not just this load."""
    if {path.name for path in output.iterdir()} != MEMBERS or any(
        path.is_symlink() or not path.is_file() for path in output.iterdir()
    ):
        raise ValueError("evaluation artifact file set differs")
    if sum(path.stat().st_size for path in output.iterdir()) > MAX_OUTPUT_BYTES:
        raise ValueError("evaluation artifact byte budget exceeded")
    report = json.loads((output / "report.json").read_bytes())
    if report["revision"] != engine.REVISION or set(report["files"]) != MEMBERS - {"report.json"}:
        raise ValueError("evaluation artifact contract differs")
    if any(binding(output / name) != pin for name, pin in report["files"].items()):
        raise ValueError("evaluation artifact binding differs")
    return json.loads((output / "frames.json").read_bytes())


def replay(inputs: Inputs, declaration_path: Path, output: Path) -> dict[str, Any]:
    """Refit from native inputs and reproduce every loaded-frame query and artifact."""
    _destination(inputs, output)
    frames = load_frames(output)
    with tempfile.TemporaryDirectory(prefix="opennoise-evaluation-replay-") as temporary:
        rebuilt = Path(temporary) / "rebuilt"
        report = run(inputs, declaration_path, rebuilt)
        if any(sha256_file(output / name) != sha256_file(rebuilt / name) for name in MEMBERS):
            raise ValueError("evaluation differs from independently refitted native replay")
        if frames != load_frames(rebuilt):
            raise ValueError("loaded evaluation frames differ")
    return report
