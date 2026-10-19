"""Optional component-representative comparison against proven frozen nearest-five results."""

from __future__ import annotations

import math
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from opennoise.ml import ab178_crossfit as crossfit

portable = crossfit.portable
REVISION = "native-ab178-component-neighbors-v1"
MAX_BYTES = 4_000_000
POLICIES = ("nearest_recording", "nearest_component")
FILES = {"protocol.json", "comparison.json", "manifest.json"}


def runtime() -> dict[str, Any]:
    """Pin only the new comparison and unchanged frozen inference dependencies."""
    return {
        "crossfit": crossfit.runtime(),
        "comparison_sha256": portable.bank.digest(Path(__file__)),
    }


def protocol(path: Path, pin: str) -> dict[str, Any]:
    """Require the fixed optional policy, baseline proof and unchanged resource/gate controls."""
    body = portable.read(path, pin)
    if (
        body["revision"] != "native-ab178-component-neighbors-plan-v1"
        or body["policies"] != list(POLICIES)
        or body["default_existing_policy"] != POLICIES[0]
        or type(body["neighbor_count"]) is not int
        or body["neighbor_count"] != crossfit.routing.engine.POLICY["neighbors"]
        or any(
            body[k] is not False
            for k in ("network", "audio_extraction", "genre_inference", "refitting")
        )
    ):
        raise ValueError("Component comparison protocol differs")
    return body


def ranked_candidates(
    query: dict[str, Any], candidates: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[dict[str, Any]]:
    """Reconstruct every eligible frozen Euclidean distance with native-recording ties."""
    identity = query["recording_mbid"]
    component = metadata[identity]["component_id"]
    if component is None or query["fit_member"]:
        raise ValueError("Emitted query lacks an isolated known credit component")
    distances = []
    for candidate in candidates:
        target = candidate["recording_mbid"]
        known_component = metadata[target]["component_id"]
        if target == identity or known_component == component:
            continue
        if known_component is None:
            raise ValueError("Frozen candidate has no known credit component")
        distance = math.dist(query["vector"], candidate["vector"])
        if not math.isfinite(distance):
            raise ValueError("Frozen candidate distance is not finite")
        distances.append((distance, target))
    return [{"recording_mbid": i, "distance": d} for d, i in sorted(distances)]


def representatives(ranked: list[dict[str, Any]], metadata: dict[str, Any]) -> list[dict[str, Any]]:
    """Take the nearest recording of each component in the existing distance/MBID order."""
    seen = set()
    selected = []
    for neighbor in ranked:
        component = metadata[neighbor["recording_mbid"]]["component_id"]
        if component is None:
            raise ValueError("Representative has no known credit component")
        if component not in seen:
            selected.append(neighbor)
            seen.add(component)
    return selected[: crossfit.routing.engine.POLICY["neighbors"]]


def coverage(
    neighbors: list[dict[str, Any]], metadata: dict[str, Any], roster: dict[str, Any]
) -> dict[str, Any]:
    """Count only exact native credits of selected recordings, never component-wide credits."""
    return {
        "recording_edges": len(neighbors),
        "component_ids": sorted({metadata[n["recording_mbid"]]["component_id"] for n in neighbors}),
        "artist_mbids": sorted(
            {
                a
                for n in neighbors
                for a in roster[n["recording_mbid"]]["credited_artist_mbids"] or []
            }
        ),
    }


def query_comparison(
    row: dict[str, Any],
    ranked: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    metadata: dict[str, Any],
    roster: dict[str, Any],
) -> dict[str, Any]:
    """Keep both coverage gains and losses for every emitted or abstained query."""
    baseline = coverage(row["neighbors"], metadata, roster)
    alternative = coverage(selected, metadata, roster)
    return {
        "recording_mbid": row["recording_mbid"],
        "outcome": row["outcome"],
        "retrieval_attempted": row["outcome"] == "emitted",
        "eligible_recordings": len(ranked),
        "eligible_component_ids": coverage(ranked, metadata, roster)["component_ids"],
        POLICIES[0]: baseline,
        POLICIES[1]: alternative,
        "components_gained": sorted(
            set(alternative["component_ids"]) - set(baseline["component_ids"])
        ),
        "components_lost": sorted(
            set(baseline["component_ids"]) - set(alternative["component_ids"])
        ),
        "artists_gained": sorted(set(alternative["artist_mbids"]) - set(baseline["artist_mbids"])),
        "artists_lost": sorted(set(baseline["artist_mbids"]) - set(alternative["artist_mbids"])),
    }


def summarize(queries: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate structural counts and native unions without pooling distances or frames."""
    return {
        "queries": len(queries),
        "retrieval_attempted_queries": sum(q["retrieval_attempted"] for q in queries),
        "eligible_component_count_sum": sum(len(q["eligible_component_ids"]) for q in queries),
        "queries_gaining_components": sum(bool(q["components_gained"]) for q in queries),
        "queries_losing_components": sum(bool(q["components_lost"]) for q in queries),
        "queries_gaining_artists": sum(bool(q["artists_gained"]) for q in queries),
        "queries_losing_artists": sum(bool(q["artists_lost"]) for q in queries),
        "policies": {
            policy: {
                "recording_edges": sum(q[policy]["recording_edges"] for q in queries),
                "returned_component_count_sum": sum(
                    len(q[policy]["component_ids"]) for q in queries
                ),
                "exact_artist_count_sum": sum(len(q[policy]["artist_mbids"]) for q in queries),
                "component_union_ids": sorted(
                    {i for q in queries for i in q[policy]["component_ids"]}
                ),
                "exact_artist_union_mbids": sorted(
                    {i for q in queries for i in q[policy]["artist_mbids"]}
                ),
            }
            for policy in POLICIES
        },
    }


def compare(  # noqa: C901 - prove and retain each cell at one boundary.
    source: Path, source_pin: str, protocol_path: Path, protocol_pin: str
) -> dict[str, Any]:
    """Prove original rankings, then compare a fixed representative policy without refitting."""
    frozen = protocol(protocol_path, protocol_pin)
    original = crossfit.verify(source, source_pin)
    if (
        original["protocol_sha256"] != frozen["evaluation_protocol_sha256"]
        or original["source_receipt_sha256"] != frozen["source_receipt_sha256"]
    ):
        raise ValueError("Component comparison source evaluation differs")
    cells, comparisons = [], {}
    selected_rows = {}
    for cell in original["cells"]:
        fold, contract = cell["heldout_fold"], cell["contract_sha256"]
        directory = source / f"fold-{fold}"
        intake = portable.read(directory / "intake.json")["rows"]
        roster = {r["recording_mbid"]: r for r in intake}
        metadata = {
            r["recording_mbid"]: r for r in portable.read(directory / "registry.json")["ledger"]
        }
        body = (
            portable.bundle(directory / contract / "frame", cell["bundle_sha256"])
            if cell["bundle_sha256"] is not None
            else None
        )
        queries, alternative_rows = [], []
        for row in cell["inference_rows"]:
            ranked, selected = [], []
            if row["outcome"] == "emitted":
                if body is None:
                    raise ValueError("Emitted query has no frozen frame")
                ranked = ranked_candidates(row, body["candidates"], metadata)
                expected = [
                    {k: n[k] for k in ("recording_mbid", "distance")} for n in row["neighbors"]
                ]
                if ranked[: frozen["neighbor_count"]] != expected:
                    raise ValueError("Reconstructed nearest-five differs from frozen baseline")
                selected = representatives(ranked, metadata)
            elif row["neighbors"]:
                raise ValueError("Abstained query has neighbor evidence")
            comparison = query_comparison(row, ranked, selected, metadata, roster)
            queries.append(comparison)
            comparisons[row["recording_mbid"]] = comparison
            alternative_rows.append({**row, "neighbors": selected})
        alternative = crossfit.cell_evidence(
            {**cell, "inference_rows": alternative_rows},
            {"bundle_sha256": cell["bundle_sha256"]},
            directory,
            fold,
        )
        for row in alternative["recordings"]:
            selected_rows[row["recording_mbid"]] = row
        cells.append(
            {
                **{
                    k: cell[k]
                    for k in (
                        "contract_sha256",
                        "heldout_fold",
                        "bundle_sha256",
                        "frame_sha256",
                        "support",
                        "query_count",
                    )
                },
                "summary": summarize(queries),
                "policies": {
                    POLICIES[0]: {k: cell[k] for k in ("recordings", "artists", "counts")},
                    POLICIES[1]: {k: alternative[k] for k in ("recordings", "artists", "counts")},
                },
            }
        )
    rows = []
    for row in original["recordings"]:
        identity = row["recording_mbid"]
        if identity not in comparisons:
            comparisons[identity] = query_comparison(row, [], [], {}, {})
        rows.append(
            {
                **row,
                "component_neighbors": selected_rows.get(identity, {}).get("neighbors", []),
                "comparison": comparisons[identity],
            }
        )
    return {
        "revision": REVISION,
        "crossfit_manifest_sha256": source_pin,
        "protocol_sha256": protocol_pin,
        "source_receipt_sha256": original["source_receipt_sha256"],
        "default_policy": POLICIES[0],
        "scope": (
            "CC0 historical structural comparison only; exact selected-recording credits; "
            "no relevance, genre, calibration or quality claim"
        ),
        "recordings": rows,
        "cells": cells,
        "summary": summarize(list(comparisons.values())),
    }


def inventory(directory: Path) -> dict[str, str]:
    """Accept exactly the bounded comparison files, without copying the input pipeline."""
    portable.bank.safe_path(directory)
    if {p.name for p in directory.iterdir()} != FILES:
        raise ValueError("Component comparison inventory differs")
    total = 0
    hashes: dict[str, str] = {}
    for name in FILES:
        path = directory / name
        portable.bank.safe_path(path)
        if not path.is_file():
            raise ValueError("Component comparison file is not regular")
        total += path.stat().st_size
        if total > MAX_BYTES:
            raise ValueError("Component comparison byte bound exceeded")
        if name != "manifest.json":
            hashes[name] = portable.bank.digest(path)
    return hashes


def verify(source: Path, source_pin: str, output: Path, output_pin: str) -> dict[str, Any]:
    """Verify custody and reproduce the comparison from only a relocated frozen evaluation."""
    manifest = portable.read(output / "manifest.json", output_pin)
    if (
        manifest["revision"] != REVISION
        or manifest["runtime"] != runtime()
        or manifest["crossfit_manifest_sha256"] != source_pin
        or manifest["files"] != inventory(output)
    ):
        raise ValueError("Component comparison runtime, input or output differs")
    result = compare(source, source_pin, output / "protocol.json", manifest["protocol_sha256"])
    if result != portable.read(output / "comparison.json"):
        raise ValueError("Component comparison evidence replay differs")
    return result


def build(
    source: Path, source_pin: str, protocol_path: Path, protocol_pin: str, output: Path
) -> str:
    """Atomically publish only the explicit optional comparison and its pinned protocol."""
    portable.destination(output, (source, protocol_path))
    if any(p.resolve().is_relative_to(output.resolve()) for p in (source, protocol_path)):
        raise ValueError("Component comparison output overlaps input custody")
    result = compare(source, source_pin, protocol_path, protocol_pin)
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".ab178-components-", dir=output.parent) as temporary:
        stage = Path(temporary) / "result"
        stage.mkdir()
        shutil.copyfile(protocol_path, stage / "protocol.json")
        crossfit.routing.write(stage / "comparison.json", result)
        crossfit.routing.write(
            stage / "manifest.json",
            {
                "revision": REVISION,
                "runtime": runtime(),
                "crossfit_manifest_sha256": source_pin,
                "protocol_sha256": protocol_pin,
                "files": {
                    name: portable.bank.digest(stage / name)
                    for name in ("protocol.json", "comparison.json")
                },
            },
        )
        pin = portable.bank.digest(stage / "manifest.json")
        verify(source, source_pin, stage, pin)
        stage.rename(output)
    return pin
