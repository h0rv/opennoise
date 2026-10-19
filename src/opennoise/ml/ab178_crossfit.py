"""Exhaustive own-component-fold evaluation using unchanged exact-version routing."""

from __future__ import annotations

import shutil
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from opennoise.ml import ab178_artist_export as artists
from opennoise.ml import ab178_version_routing as routing

portable = routing.portable
REVISION = "native-ab178-crossfit-v1"
MAX_BYTES = 32_000_000
MAX_FILES = 256


def runtime() -> dict[str, Any]:
    """Bind the composition layer and unchanged underlying runtime independently."""
    return {"routing": routing.runtime(), "crossfit_sha256": portable.bank.digest(Path(__file__))}


def protocol(path: Path, pin: str) -> dict[str, Any]:
    """Require every immutable fold and identical declared contracts before computation."""
    body = portable.read(path, pin)
    plans = body["fold_plans"]
    if (
        body["revision"] != "native-ab178-crossfit-evaluation-plan-v1"
        or [p["fold"] for p in plans] != list(range(routing.engine.POLICY["folds"]))
        or any(body[k] is not False for k in ("network", "audio_extraction", "genre_inference"))
        or body["base_plan_sha256"] != plans[0]["plan_sha256"]
    ):
        raise ValueError("Crossfit protocol folds or source policy differ")
    base = plans[0]["plan"]
    for item in plans:
        plan = item["plan"]
        if (
            portable.hash_value(plan) != item["plan_sha256"]
            or plan["heldout_fold"] != item["fold"]
            or type(item["fold"]) is not int
            or plan["source_receipt_sha256"] != body["source_receipt_sha256"]
            or {k: v for k, v in plan.items() if k not in {"heldout_fold", "eligibility"}}
            != {k: v for k, v in base.items() if k not in {"heldout_fold", "eligibility"}}
        ):
            raise ValueError("Crossfit fold plan identity or contract policy differs")
    return body


def inventory(directory: Path) -> dict[str, str]:
    """Bound each closed file before hashing; include nested routing manifests."""
    files = {}
    total = 0
    for path in directory.rglob("*"):
        portable.bank.safe_path(path)
        if path.is_file() and path != directory / "manifest.json":
            total += path.stat().st_size
            if len(files) >= MAX_FILES or total > MAX_BYTES:
                raise ValueError("Crossfit inventory resource bound exceeded")
            files[path.relative_to(directory).as_posix()] = portable.bank.digest(path)
    return files


def cell_evidence(
    group: dict[str, Any], declared: dict[str, Any], directory: Path, fold: int
) -> dict[str, Any]:
    """Retain one cell, selecting only queries whose immutable component fold matches."""
    contract_pin = group["contract_sha256"]
    frame_pin = None
    if group["support"]["state"] == "fitted":
        body = portable.bundle(directory / contract_pin / "frame", declared["bundle_sha256"])
        frame_pin = portable.hash_value(body["frame"])
    else:
        intake = portable.read(directory / "intake.json")["rows"]
        body = {"roster": intake, "frame": {"heldout_fold": fold}}
    proof = {
        "contract_sha256": contract_pin,
        "heldout_fold": fold,
        "bundle_sha256": declared.get("bundle_sha256"),
        "frame_sha256": frame_pin,
    }
    rows = [r for r in group["inference_rows"] if r["fold"] == fold]
    if any(r["fit_member"] for r in rows):
        raise ValueError("Own-fold query was included in its fitted frame")
    rows = [{**r, **proof, "neighbors": [{**n, **proof} for n in r["neighbors"]]} for r in rows]
    evidence = artists.aggregate(body, {"rows": rows})
    evidence["artists"] = [a for a in evidence["artists"] if a["recording_mbids"]]
    evidence["counts"]["verified_credited_artists"] = len(evidence["artists"])
    for artist in evidence["artists"]:
        artist.update(proof)
        for neighbors in artist["neighbor_evidence"].values():
            for neighbor in neighbors:
                neighbor.update(proof)
                for observation in neighbor["observations"]:
                    observation.update(proof)
    return {
        **proof,
        "support": group["support"],
        "query_count": len(rows),
        "inference_rows": rows,
        **evidence,
    }


def replay(directory: Path, index: dict[str, Any]) -> dict[str, Any]:
    """Verify frozen per-fold runs and assemble exactly one out-of-fit row per nomination."""
    frozen = protocol(directory / "protocol.json", index["protocol_sha256"])
    cells, rows = [], []
    ledger = intake = source_abstentions = None
    for item, run in zip(frozen["fold_plans"], index["runs"], strict=True):
        fold = item["fold"]
        path = directory / f"fold-{fold}"
        if run["fold"] != fold:
            raise ValueError("Crossfit run order differs")
        if (
            portable.read(directory / f"plans/fold-{fold}.json", item["plan_sha256"])
            != item["plan"]
        ):
            raise ValueError("Crossfit fold plan differs")
        result = routing.verify(path, run["manifest_sha256"])
        registry = portable.read(path / "registry.json")
        current_intake = portable.read(path / "intake.json")
        if (
            registry["plan_sha256"] != item["plan_sha256"]
            or registry["source_receipt_sha256"] != frozen["source_receipt_sha256"]
        ):
            raise ValueError("Crossfit nested run source or plan binding differs")
        if fold == 0:
            ledger, intake, source_abstentions = (
                registry["ledger"],
                current_intake,
                result["unrouted"],
            )
        elif (
            ledger != registry["ledger"]
            or intake != current_intake
            or source_abstentions != result["unrouted"]
        ):
            raise ValueError("Crossfit global source identity changed across folds")
        for group, declared in zip(result["groups"], registry["groups"], strict=True):
            cell = cell_evidence(group, declared, path, fold)
            cells.append(cell)
            rows.extend(cell["recordings"])
    if ledger is None or source_abstentions is None:
        raise ValueError("Crossfit has no source ledger")
    rows.extend(
        {
            **r,
            "heldout_fold": r["fold"],
            "bundle_sha256": None,
            "frame_sha256": None,
            "query_role": "source_abstention",
        }
        for r in source_abstentions
    )
    rows.sort(key=lambda r: r["recording_mbid"])
    if [r["recording_mbid"] for r in rows] != [r["recording_mbid"] for r in ledger] or any(
        r["fit_member"] or r["fold"] != r["heldout_fold"] for r in rows
    ):
        raise ValueError("Crossfit final query identity or own-fold isolation differs")
    return {
        "revision": REVISION,
        "protocol_sha256": index["protocol_sha256"],
        "source_receipt_sha256": frozen["source_receipt_sha256"],
        "scope": (
            "CC0 historical native metadata; own-fold queries only; "
            "no calibration, genre, listener relevance or fresh confirmation established; "
            "no cross-cell score pooling"
        ),
        "cells": cells,
        "recordings": rows,
        "counts": {
            "nominated_recordings": len(rows),
            "compatible_recordings": sum(r["contract_sha256"] is not None for r in rows),
            "cells": len(cells),
            "fitted_cells": sum(c["support"]["state"] == "fitted" for c in cells),
            "recording_outcomes": dict(Counter(r["outcome"] for r in rows)),
            "emitted_by_fold": {
                str(f): sum(r["outcome"] == "emitted" and r["fold"] == f for r in rows)
                for f in range(routing.engine.POLICY["folds"])
            },
            "recording_edges": sum(len(r["neighbors"]) for r in rows),
        },
    }


def verify(directory: Path, pin: str) -> dict[str, Any]:
    """Check the closed envelope and exact source-free, no-refit evidence replay."""
    manifest = portable.read(directory / "manifest.json", pin)
    if (
        manifest["revision"] != REVISION
        or manifest["runtime"] != runtime()
        or manifest["files"] != inventory(directory)
    ):
        raise ValueError("Crossfit inventory or runtime differs")
    index = portable.read(directory / "index.json")
    result = replay(directory, index)
    expected = {"protocol.json", "index.json", "evidence.json"}
    for fold in range(routing.engine.POLICY["folds"]):
        expected.add(f"plans/fold-{fold}.json")
        nested = portable.read(directory / f"fold-{fold}/manifest.json")
        expected.add(f"fold-{fold}/manifest.json")
        expected.update(f"fold-{fold}/{name}" for name in nested["files"])
    actual_dirs = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_dir()}
    expected_dirs = {str(p) for name in expected for p in Path(name).parents if str(p) != "."}
    if (
        set(manifest["files"]) != expected
        or actual_dirs != expected_dirs
        or result != portable.read(directory / "evidence.json")
    ):
        raise ValueError("Crossfit closed inventory or evidence differs")
    return result


def build(
    source: Path, source_pin: str, protocol_path: Path, protocol_pin: str, output: Path
) -> str:
    """Stage all predeclared fold runs and atomically publish an exhaustive evaluation."""
    portable.destination(output, (source, protocol_path))
    if any(p.resolve().is_relative_to(output.resolve()) for p in (source, protocol_path)):
        raise ValueError("Crossfit output overlaps input custody")
    frozen = protocol(protocol_path, protocol_pin)
    if source_pin != frozen["source_receipt_sha256"]:
        raise ValueError("Crossfit source differs from frozen protocol")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".ab178-crossfit-", dir=output.parent) as temporary:
        stage = Path(temporary) / "result"
        stage.mkdir()
        shutil.copyfile(protocol_path, stage / "protocol.json")
        index = {"protocol_sha256": protocol_pin, "runs": []}
        for item in frozen["fold_plans"]:
            fold = item["fold"]
            plan_path = stage / f"plans/fold-{fold}.json"
            routing.write(plan_path, item["plan"])
            routing.plan(plan_path, item["plan_sha256"])
            pin = routing.build(
                source, source_pin, plan_path, item["plan_sha256"], stage / f"fold-{fold}"
            )
            index["runs"].append({"fold": fold, "manifest_sha256": pin})
        routing.write(stage / "index.json", index)
        routing.write(stage / "evidence.json", replay(stage, index))
        routing.write(
            stage / "manifest.json",
            {"revision": REVISION, "runtime": runtime(), "files": inventory(stage)},
        )
        pin = portable.bank.digest(stage / "manifest.json")
        verify(stage, pin)
        stage.rename(output)
    return pin
