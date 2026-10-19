"""Strict version routing over the existing native AB178 bank and frozen-frame engine."""

from __future__ import annotations

import json
import math
import shutil
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID

from opennoise.ingest.acousticbrainz import native_sonic, projection
from opennoise.ml import ab178_artist_export as artists
from opennoise.ml import ab178_portable as portable
from opennoise.ml import recording_evaluation as engine

REVISION = "native-ab178-version-routing-v1"
MAX_CONTRACTS = 8
MAX_FILES = 64
MAX_BYTES = 10_000_000


def runtime() -> dict[str, Any]:
    """Pin routing, ingestion, aggregation and the existing numerical implementation."""
    return {
        **portable.runtime(),
        "routing_code": {
            p.name: portable.bank.digest(p)
            for p in (
                Path(__file__),
                Path(artists.__file__),
                Path(portable.bank.__file__),
                Path(native_sonic.__file__),
                Path(projection.__file__),
            )
        },
    }


def plan(path: Path, pin: str) -> dict[str, Any]:
    """Validate the externally frozen cohort and exact contracts before any fit."""
    body = portable.read(path, pin)
    if (
        body["revision"] != "native-ab178-version-routing-plan-v1"
        or body["policy"] != engine.POLICY
        or type(body["heldout_fold"]) is not int
        or not 0 <= body["heldout_fold"] < engine.POLICY["folds"]
        or not 1 <= len(body["contracts"]) <= MAX_CONTRACTS
        or any(body[k] is not False for k in ("network", "audio_extraction", "genre_inference"))
    ):
        raise ValueError("Routing plan policy differs")
    pins, ids = set(), set()
    for group in body["contracts"]:
        contract_pin = group["contract_sha256"]
        cohort = group["recording_mbids"]
        if (
            portable.hash_value(portable.contract(group["contract"])) != contract_pin
            or contract_pin in pins
            or not cohort
            or cohort != sorted(set(cohort))
            or any(str(UUID(i)) != i or i in ids for i in cohort)
        ):
            raise ValueError("Routing plan contracts or cohorts differ")
        pins.add(contract_pin)
        ids.update(cohort)
    if len(ids) > portable.MAX_ROWS:
        raise ValueError("Routing plan cohort bound exceeded")
    return body


def topology(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep all known co-credit components, including incompatible source rows."""
    return [
        {k: row[k] for k in ("recording_mbid", "component_id", "fold")}
        for row in engine.component_ledger(rows)["records"]
    ]


def contract_rows(intake: list[dict[str, Any]], group: dict[str, Any]) -> list[dict[str, Any]]:
    """Project exact intake contracts without changing native identity evidence."""
    rows = []
    for row in intake:
        current = dict(row)
        if current["join_state"] == "unplanned_contract":
            current["join_state"] = "joined"
        if current["join_state"] == "joined" and row["version"] != group["contract"]["version"]:
            current.update(
                join_state="extractor_version_mismatch",
                values=[None] * len(portable.bank.columns()),
                missing_mask=[True] * len(portable.bank.columns()),
            )
        elif current["join_state"] == "joined" and row["analysis"] != group["contract"]["analysis"]:
            current.update(
                join_state="analysis_configuration_mismatch",
                values=[None] * len(portable.bank.columns()),
                missing_mask=[True] * len(portable.bank.columns()),
            )
        rows.append(current)
    return rows


def support(rows: list[dict[str, Any]], fold: int) -> dict[str, Any]:
    """Declare only expected minimum-support and heldout eligibility outcomes."""
    ledger = {r["recording_mbid"]: r for r in engine.component_ledger(rows)["records"]}
    joined = [ledger[r["recording_mbid"]] for r in rows if r["join_state"] == "joined"]
    train = [r for r in joined if r["fold"] != fold]
    heldout = [r for r in joined if r["fold"] == fold]
    training_rows = [
        r
        for r in rows
        if r["join_state"] == "joined" and ledger[r["recording_mbid"]]["fold"] != fold
    ]
    selected = [
        i
        for i in range(len(portable.bank.columns()))
        if (
            sum(r["values"][i] is not None and math.isfinite(r["values"][i]) for r in training_rows)
            >= max(
                engine.POLICY["minimum_column_observations"],
                len(training_rows) * engine.POLICY["minimum_column_fraction"],
            )
        )
    ]
    complete = [
        r
        for r in training_rows
        if all(r["values"][i] is not None and math.isfinite(r["values"][i]) for i in selected)
    ]
    variable = any(len({r["values"][i] for r in complete}) > 1 for i in selected)
    reason = None
    if (
        not selected
        or len(complete) < engine.POLICY["minimum_complete_training_recordings"]
        or not variable
    ):
        reason = "insufficient_training_support"
    elif not any(q["component_id"] != c["component_id"] for q in heldout for c in train):
        reason = "no_compatible_cross_component_heldout_query"
    return {
        "training_recordings": len(train),
        "training_components": len({r["component_id"] for r in train}),
        "heldout_recordings": len(heldout),
        "heldout_components": len({r["component_id"] for r in heldout}),
        "state": reason or "fitted",
    }


def write(path: Path, value: dict[str, Any]) -> None:
    """Write canonical bounded JSON inside an unpublished staging directory."""
    raw = portable.encoded(value)
    if len(raw) > portable.MAX_FILE_BYTES:
        raise ValueError("Routing file byte bound exceeded")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def validate_intake(
    directory: Path, intake: list[dict[str, Any]], registry: dict[str, Any]
) -> None:
    """Bind routed identity, source evidence and numeric values to the verified native bank."""
    native = json.loads((directory / "bank/bank.json").read_bytes())
    receipt = json.loads((directory / "bank/receipt.json").read_bytes())
    if (
        portable.bank.digest(directory / "bank/receipt.json") != registry["bank_receipt_sha256"]
        or portable.bank.payload(native) != (directory / "bank/bank.json").read_bytes()
        or portable.bank.payload(receipt) != (directory / "bank/receipt.json").read_bytes()
    ):
        raise ValueError("Routing bank encoding or receipt differs")
    if (
        native["source_receipt_sha256"] != registry["source_receipt_sha256"]
        or receipt["source_receipt_sha256"] != registry["source_receipt_sha256"]
        or native["columns"] != portable.bank.columns()
        or receipt["files"]["bank.json"]["sha256"]
        != portable.bank.digest(directory / "bank/bank.json")
        or len(intake) != len(native["rows"])
    ):
        raise ValueError("Routing native bank custody differs")
    for row, original in zip(intake, native["rows"], strict=True):
        expected_evidence = {
            k: v for k, v in original.items() if k not in {"values", "missing_mask"}
        }
        fact = original["exact_credit"]["fact"]
        if (
            row["evidence"] != expected_evidence
            or row["recording_mbid"] != original["recording_mbid"]
            or row["companion"] != {"credit_fact": fact}
            or row["credited_artist_mbids"] != (fact["credited_artist_mbids"] if fact else None)
            or (
                row["join_state"] == "joined"
                and (
                    row["values"] != original["values"]
                    or row["missing_mask"] != original["missing_mask"]
                )
            )
        ):
            raise ValueError("Routing intake identity or numeric join differs")


def evidence(  # noqa: C901 - one closed replay boundary.
    directory: Path, registry: dict[str, Any]
) -> dict[str, Any]:
    """Replay all queries without source access or refitting, keeping each frame separate."""
    frozen_plan = plan(directory / "plan.json", registry["plan_sha256"])
    intake = portable.read(directory / "intake.json")["rows"]
    validate_intake(directory, intake, registry)
    if not 1 <= len(intake) <= portable.MAX_ROWS or len(
        {r["recording_mbid"] for r in intake}
    ) != len(intake):
        raise ValueError("Routing intake cardinality differs")
    ledger = topology(intake)
    if (
        ledger != registry["ledger"]
        or frozen_plan["source_receipt_sha256"] != registry["source_receipt_sha256"]
    ):
        raise ValueError("Routing global ledger or source binding differs")
    meta = {r["recording_mbid"]: r for r in ledger}
    assigned = set()
    output = []
    for group, declared in zip(frozen_plan["contracts"], registry["groups"], strict=True):
        pin = group["contract_sha256"]
        rows = contract_rows(intake, group)
        ids = [r["recording_mbid"] for r in rows if r["join_state"] == "joined"]
        counts = support(rows, frozen_plan["heldout_fold"])
        if (
            sorted(ids) != group["recording_mbids"]
            or declared["contract_sha256"] != pin
            or declared["support"] != counts
        ):
            raise ValueError("Routing contract cohort or support differs")
        assigned.update(ids)
        if counts["state"] == "fitted":
            bundle_path, queries = directory / pin / "frame", directory / pin / "queries"
            body = portable.bundle(bundle_path, declared["bundle_sha256"])
            if (
                body["roster"] != rows
                or topology(body["roster"]) != ledger
                or body["contract_sha256"] != pin
                or body["frame"]["heldout_fold"] != frozen_plan["heldout_fold"]
                or body["source_receipt_sha256"] != registry["source_receipt_sha256"]
                or body["bank_receipt_sha256"] != registry["bank_receipt_sha256"]
            ):
                raise ValueError("Routing frozen frame binding differs")
            result = portable.infer(
                bundle_path, declared["bundle_sha256"], queries, declared["query_sha256"]
            )
            if [r["recording_mbid"] for r in result["rows"]] != ids:
                raise ValueError("Routing query cohort differs")
        else:
            body = {"roster": rows, "frame": {"heldout_fold": frozen_plan["heldout_fold"]}}
            result = {
                "rows": [
                    {
                        "recording_mbid": i,
                        "outcome": counts["state"],
                        "vector": [],
                        "neighbors": [],
                        "fit_member": False,
                        **{k: meta[i][k] for k in ("component_id", "fold")},
                    }
                    for i in ids
                ]
            }
        body = {**body, "roster": [r for r in rows if r["recording_mbid"] in ids]}
        output.append(
            {
                "contract_sha256": pin,
                "support": counts,
                "inference_rows": result["rows"],
                **artists.aggregate(body, result),
            }
        )
    unrouted = []
    for row in intake:
        i = row["recording_mbid"]
        if i not in assigned:
            if row["join_state"] == "joined":
                raise ValueError("Clean contract absent from frozen plan")
            unrouted.append(
                {
                    "recording_mbid": i,
                    "contract_sha256": None,
                    "outcome": row["join_state"],
                    "credited_artist_mbids": row["credited_artist_mbids"],
                    **{k: meta[i][k] for k in ("component_id", "fold")},
                    "neighbors": [],
                    "fit_member": False,
                }
            )
    return {
        "revision": REVISION,
        "plan_sha256": registry["plan_sha256"],
        "source_receipt_sha256": registry["source_receipt_sha256"],
        "scope": (
            "CC0 native metadata comparison only; separate exact-contract frames; "
            "no calibration, genre or listener relevance established"
        ),
        "groups": output,
        "unrouted": unrouted,
        "counts": {
            "nominated_recordings": len(intake),
            "routed_recordings": len(assigned),
            "unrouted_outcomes": dict(Counter(r["outcome"] for r in unrouted)),
        },
    }


def inventory(directory: Path) -> dict[str, str]:
    """Hash a closed bounded regular-file inventory."""
    result = {}
    total = 0
    for path in directory.rglob("*"):
        portable.bank.safe_path(path)
        if path.is_file() and path != directory / "manifest.json":
            total += path.stat().st_size
            result[path.relative_to(directory).as_posix()] = portable.bank.digest(path)
    if total > MAX_BYTES or len(result) > MAX_FILES:
        raise ValueError("Routing total byte bound exceeded")
    return result


def verify(directory: Path, pin: str) -> dict[str, Any]:
    """Verify closed custody and reproduce all outcomes offline without fitting."""
    manifest = portable.read(directory / "manifest.json", pin)
    if (
        manifest["revision"] != REVISION
        or manifest["runtime"] != runtime()
        or manifest["files"] != inventory(directory)
    ):
        raise ValueError("Routing inventory or runtime differs")
    registry = portable.read(directory / "registry.json")
    expected = {
        "plan.json",
        "intake.json",
        "bank/bank.json",
        "bank/receipt.json",
        "registry.json",
        "evidence.json",
    }
    for group in registry["groups"]:
        if group["support"]["state"] == "fitted":
            expected.update(
                f"{group['contract_sha256']}/{name}"
                for name in ("contract.json", "frame/bundle.json", "queries/queries.json")
            )
    if set(manifest["files"]) != expected:
        raise ValueError("Routing closed file inventory differs")
    actual_dirs = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_dir()}
    expected_dirs = {str(p) for name in expected for p in Path(name).parents if str(p) != "."}
    if actual_dirs != expected_dirs:
        raise ValueError("Routing closed directory inventory differs")
    result = evidence(directory, registry)
    if result != portable.read(directory / "evidence.json"):
        raise ValueError("Routing evidence replay differs")
    return result


def build(source: Path, source_pin: str, plan_path: Path, plan_pin: str, output: Path) -> str:
    """Verify native sources, build independent frozen frames and atomically publish evidence."""
    portable.destination(output, (source, plan_path))
    if any(p.resolve().is_relative_to(output.resolve()) for p in (source, plan_path)):
        raise ValueError("Output overlaps input custody")
    frozen_plan = plan(plan_path, plan_pin)
    if (
        source_pin != frozen_plan["source_receipt_sha256"]
        or portable.bank.digest(source / "receipt.json") != source_pin
    ):
        raise ValueError("Routing source differs from frozen plan")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".ab178-routing-", dir=output.parent) as temporary:
        stage = Path(temporary) / "result"
        stage.mkdir()
        shutil.copyfile(plan_path, stage / "plan.json")
        portable.bank.build(source, stage / "bank")
        projected = portable.bank.verify(source, stage / "bank")
        all_rows = [
            portable.source_rows(source, g["contract"], projected) for g in frozen_plan["contracts"]
        ]
        intake = [
            dict(
                next(
                    (rows[n] for rows in all_rows if rows[n]["join_state"] == "joined"),
                    all_rows[0][n],
                )
            )
            for n in range(len(all_rows[0]))
        ]
        for row in intake:
            if row["join_state"] in {
                "extractor_version_mismatch",
                "analysis_configuration_mismatch",
            }:
                row["join_state"] = "unplanned_contract"
        write(stage / "intake.json", {"rows": intake})
        registry = {
            "source_receipt_sha256": source_pin,
            "plan_sha256": plan_pin,
            "bank_receipt_sha256": portable.bank.digest(stage / "bank/receipt.json"),
            "ledger": topology(intake),
            "groups": [],
        }
        for group, rows in zip(frozen_plan["contracts"], all_rows, strict=True):
            pin = group["contract_sha256"]
            ids = [r["recording_mbid"] for r in rows if r["join_state"] == "joined"]
            if sorted(ids) != group["recording_mbids"] or rows != contract_rows(intake, group):
                raise ValueError("Verified source differs from frozen contract cohort")
            counts = support(rows, frozen_plan["heldout_fold"])
            entry = {"contract_sha256": pin, "support": counts}
            if counts["state"] == "fitted":
                path = stage / pin
                write(path / "contract.json", group["contract"])
                bundle_pin = portable.export_bundle(
                    source,
                    source_pin,
                    stage / "bank",
                    registry["bank_receipt_sha256"],
                    path / "contract.json",
                    pin,
                    frozen_plan["heldout_fold"],
                    path / "frame",
                )
                query_pin = portable.export_queries(
                    path / "frame", bundle_pin, source, source_pin, ids, path / "queries"
                )
                entry.update(bundle_sha256=bundle_pin, query_sha256=query_pin)
            registry["groups"].append(entry)
        write(stage / "registry.json", registry)
        write(stage / "evidence.json", evidence(stage, registry))
        write(
            stage / "manifest.json",
            {"revision": REVISION, "runtime": runtime(), "files": inventory(stage)},
        )
        pin = portable.bank.digest(stage / "manifest.json")
        verify(stage, pin)
        stage.rename(output)
    return pin
