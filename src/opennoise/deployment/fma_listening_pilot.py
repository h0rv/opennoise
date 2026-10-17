"""Local method-blind pilot using only the reviewed permitted55 candidate."""

# ruff: noqa: PLR2004, E501 -- protocol constants and neutral fixed A/B labels.
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from opennoise.common import canonical_json

REVISION = "fma-permitted55-listening-v1"
SEED = "opennoise-permitted55-listening-20261016-v1"
MAX_CONTROL = 2_000_000
MAX_RESPONSE = 200_000
MAX_CLIP = 2_000_000
MAX_AUDIO = 64_000_000
DESIGN_SHA256 = "aa458a99bda9a71e6ffe036447710b086bf7ab36370b0e11ff2de70fb75ce513"
CHOICES = {None, "A", "B", "tie", "neither", "unsure", "playback_failure"}
FAMILIARITY = {None, "none", "query", "candidate", "both", "unsure"}
RESPONSE_FIELDS = {
    "item_id",
    "choice",
    "heard_query",
    "heard_A",
    "heard_B",
    "familiarity",
    "conflict",
    "notes",
}
CREDIT_FIELDS = {
    "track_id",
    "artist_id",
    "audio_sha256",
    "audio_bytes",
    "duration_seconds",
    "title",
    "artist_name",
    "license_title",
    "license_url",
    "source_url",
    "attribution",
    "composer",
    "copyright_c",
    "copyright_p",
    "embedded_notices",
    "embedded_source_urls",
    "embedded_curators",
    "audio_path",
    "license_evidence",
    "embedded_extra_text_present",
}
PAGE = Path(__file__).parents[1] / "static" / "fma-listening-pilot.html"


def read(path: Path, cap: int = MAX_CONTROL) -> bytes:
    """Read one bounded nonsymlinked local input."""
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Symlinked pilot input")
    if not path.is_file() or not 0 < path.stat().st_size <= cap:
        raise ValueError("Missing or oversized pilot input")
    return path.read_bytes()


def sha(body: bytes) -> str:
    """Digest exact immutable bytes."""
    return hashlib.sha256(body).hexdigest()


def write(path: Path, value: object) -> None:
    """Write a bounded JSON artifact without overwriting."""
    body = canonical_json(value) + b"\n"
    if len(body) > MAX_CONTROL:
        raise ValueError("Pilot control exceeds byte budget")
    with path.open("xb") as stream:
        stream.write(body)


def order(values: list[int | str], scope: str) -> list[Any]:
    """Order neutral assignments by the prespecified seed."""
    return sorted(values, key=lambda x: sha(f"{SEED}\0{scope}\0{x}".encode()))


def assignments(queries: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """No selection by outcome: retain the six frozen queries, including missing arms."""
    ids = [r["track_id"] for r in queries]
    if len(ids) != 6 or len(set(ids)) != 6 or any(type(i) is not int or i <= 0 for i in ids):
        raise ValueError("Pilot requires exactly six unique native test queries")
    by_id = {r["track_id"]: r for r in queries}
    shuffled = order(ids, "assignment")
    identifiers = order(ids, "item-identifiers")
    packets: dict[str, Any] = {}
    key: dict[str, Any] = {}
    for slot in (1, 2):
        items, mapping = {}, {}
        for number, identity in enumerate(shuffled):
            row = by_id[identity]
            if set(row) != {"track_id", "component_id", "raw", "simple", "reason"}:
                raise ValueError("Unexpected comparison fields")
            if type(row["component_id"]) is not int or row["component_id"] <= 0:
                raise ValueError("Invalid query component")
            for method in ("raw", "simple"):
                if row[method] is not None and (type(row[method]) is not int or row[method] <= 0):
                    raise ValueError("Invalid comparison candidate")
            item = f"T{identifiers.index(identity) + 1:02}"
            raw_a = (number < 3) == (slot == 1)
            methods = {"A": "raw" if raw_a else "simple", "B": "simple" if raw_a else "raw"}
            items[item] = {
                "item_id": item,
                "query": identity,
                "A": row[methods["A"]],
                "B": row[methods["B"]],
                "unsupported": row["raw"] is None or row["simple"] is None,
                "identical_candidates": row["raw"] is not None and row["raw"] == row["simple"],
            }
            mapping[item] = {"query": identity, "component_id": row["component_id"], **methods}
        packets[str(slot)] = [items[i] for i in order(list(items), f"item-order/{slot}")]
        key[str(slot)] = mapping
    return packets, key


def inventory(directory: Path) -> dict[str, Any]:
    """Inventory a flat controlled participant or coordinator root."""
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("Symlinked participant member")
        name = path.relative_to(directory).as_posix()
        if path.is_dir():
            if name != "audio":
                raise ValueError("Unexpected participant directory")
        elif path.is_file():
            if name != "inventory.json":
                body = read(path, MAX_CLIP if name.startswith("audio/") else MAX_CONTROL)
                result[name] = {"bytes": len(body), "sha256": sha(body)}
        else:
            raise ValueError("Unsupported participant member")
    return result


def validate_packet(directory: Path, inventory_sha256: str) -> dict[str, Any]:  # noqa: C901, PLR0912 -- explicit closed custody gates.
    """Validate a separated participant root; no coordinator content may be present."""
    raw = read(directory / "inventory.json")
    if sha(raw) != inventory_sha256 or json.loads(raw) != inventory(directory):
        raise ValueError("Participant inventory differs from external pin")
    packet = json.loads(read(directory / "packet.json"))
    if (
        set(packet) != {"revision", "slot", "items", "tracks", "metadata_attribution"}
        or packet["revision"] != REVISION
        or type(packet["slot"]) is not int
        or packet["slot"] not in (1, 2)
        or len(packet["items"]) != 6
    ):
        raise ValueError("Invalid participant scope")
    expected = {"packet.json", "index.html", "README.txt", "serve.py"}
    used, seen = set(), set()
    for item in packet["items"]:
        if set(item) != {"item_id", "query", "A", "B", "unsupported", "identical_candidates"}:
            raise ValueError("Participant method or unexpected field present")
        if item["item_id"] in seen or item["item_id"] not in {f"T{i:02}" for i in range(1, 7)}:
            raise ValueError("Duplicate or unknown trial")
        seen.add(item["item_id"])
        for role in ("query", "A", "B"):
            identity = item[role]
            if identity is None and role != "query":
                continue
            if type(identity) is not int or identity <= 0:
                raise ValueError("Invalid participant identity")
            used.add(str(identity))
        if item["unsupported"] is not (item["A"] is None or item["B"] is None) or item[
            "identical_candidates"
        ] is not (item["A"] is not None and item["A"] == item["B"]):
            raise ValueError("Invalid nondiscriminating trial marker")
    if set(packet["tracks"]) != used:
        raise ValueError("Participant credit roster differs")
    total = 0
    for identity, row in packet["tracks"].items():
        name = f"audio/{identity}.mp3"
        body = read(directory / name, MAX_CLIP)
        if (
            set(row) != CREDIT_FIELDS
            or row["track_id"] != int(identity)
            or row["audio_path"] != name
            or row["audio_sha256"] != sha(body)
            or row["audio_bytes"] != len(body)
            or "genre_ids" in row
        ):
            raise ValueError("Participant audio/credit binding differs")
        expected.add(name)
        total += len(body)
    if total > MAX_AUDIO or set(json.loads(raw)) != expected:
        raise ValueError("Participant inventory or audio budget differs")
    if read(directory / "index.html") != read(PAGE):
        raise ValueError("Participant interface differs")
    return packet


def response(packet: dict[str, Any], packet_sha256: str, value: dict[str, Any]) -> dict[str, Any]:
    """Preserve raw answers; missing listening is not quietly treated as a valid preference."""
    if (
        not isinstance(value, dict)
        or set(value) != {"revision", "packet_sha256", "slot", "items"}
        or value["revision"] != REVISION
        or value["packet_sha256"] != packet_sha256
        or type(value["slot"]) is not int
        or value["slot"] != packet["slot"]
        or not isinstance(value["items"], list)
        or len(value["items"]) != 6
    ):
        raise ValueError("Response binding or denominator differs")
    expected = {r["item_id"] for r in packet["items"]}
    seen = set()
    for row in value["items"]:
        if not isinstance(row, dict) or set(row) != RESPONSE_FIELDS:
            raise ValueError("Unexpected response fields")
        if (
            not isinstance(row["item_id"], str)
            or row["item_id"] in seen
            or row["item_id"] not in expected
        ):
            raise ValueError("Duplicate or unknown response item")
        seen.add(row["item_id"])
        if (
            (row["choice"] is not None and not isinstance(row["choice"], str))
            or (row["familiarity"] is not None and not isinstance(row["familiarity"], str))
            or row["choice"] not in CHOICES
            or row["familiarity"] not in FAMILIARITY
        ):
            raise ValueError("Unknown response choice")
        for field in ("heard_query", "heard_A", "heard_B", "conflict"):
            if row[field] is not None and type(row[field]) is not bool:
                raise ValueError("Listening/conflict response must be nullable boolean")
        if not isinstance(row["notes"], str) or len(row["notes"]) > 1000:
            raise ValueError("Invalid response notes")
    return value


def summarize(  # noqa: C901 -- retain each prespecified exclusion independently.
    coordinator: dict[str, Any],
    packets: dict[str, dict[str, Any]],
    responses: list[dict[str, Any]],
    *,
    distinct_participants_confirmed: bool = False,
) -> dict[str, Any]:
    """Describe two correlated slots per query; never invent responses or acceptance."""
    if type(distinct_participants_confirmed) is not bool:
        raise ValueError("Distinct participant confirmation must be explicit boolean")
    supplied = {}
    for value in responses:
        slot = str(value.get("slot"))
        if slot not in packets or slot in supplied:
            raise ValueError("Unknown or duplicate listener slot")
        supplied[slot] = response(packets[slot], coordinator["packet_sha256"][slot], value)
    rows, counts, eligible = [], Counter(), Counter()
    for item in sorted(coordinator["key"]["1"]):
        cluster = coordinator["key"]["1"][item]
        observations = []
        for slot in ("1", "2"):
            trial = next(r for r in packets[slot]["items"] if r["item_id"] == item)
            raw = next(
                (r for r in supplied.get(slot, {}).get("items", []) if r["item_id"] == item), None
            )
            choice = raw["choice"] if raw else None
            counts[choice or "missing"] += 1
            exclusions = []
            if choice is None:
                exclusions.append("missing_response")
            elif choice in {"unsure", "playback_failure"}:
                exclusions.append("nonpreference_outcome")
            if trial["unsupported"]:
                exclusions.append("unsupported")
            if trial["identical_candidates"]:
                exclusions.append("identical_candidates")
            if raw is None or any(raw[f"heard_{role}"] is not True for role in ("query", "A", "B")):
                exclusions.append("incomplete_listening_self_report")
            if raw is None or raw["conflict"] is not False:
                exclusions.append("conflict_or_unreported_conflict")
            mapped = coordinator["key"][slot][item].get(choice, choice) if choice else None
            if not exclusions:
                eligible[mapped] += 1
            observations.append(
                {
                    "slot": int(slot),
                    "response": raw,
                    "mapped_choice": mapped,
                    "exclusions": exclusions,
                }
            )
        rows.append(
            {
                "item_id": item,
                "query": cluster["query"],
                "component_id": cluster["component_id"],
                "observations": observations,
                "disagreement": observations[0]["mapped_choice"] != observations[1]["mapped_choice"]
                if all(o["mapped_choice"] is not None and not o["exclusions"] for o in observations)
                else None,
            }
        )
    return {
        "revision": REVISION,
        "planned_responses": 12,
        "queries": rows,
        "query_components": len({r["component_id"] for r in rows}),
        "submitted_slots": sorted(int(s) for s in supplied),
        "distinct_participants_confirmed": distinct_participants_confirmed,
        "outcome_counts": {
            str(k): counts[k]
            for k in ("missing", "A", "B", "tie", "neither", "unsure", "playback_failure")
        },
        "eligible_outcome_counts": dict(sorted(eligible.items())),
        "musical_quality_validated": False,
        "public_deployment_authorized": False,
        "limitations": "Descriptive six-query pilot of previously inspected test data. Two slots do not prove independent people. No significance, population inference or serving promotion. Listening flags are self-reports. Original responses retained; cluster by query/component.",
    }


def _evaluations(pack: Path, candidate_manifest: Path, pin: str) -> dict[str, Any]:
    from opennoise.ml.fma_waveform_evaluation import validate_evaluation_pack  # noqa: PLC0415

    return validate_evaluation_pack(pack, candidate_manifest, pin)


def _candidate(candidate: Path) -> dict[str, Any]:
    from opennoise.deployment.fma_public_candidate import (  # noqa: PLC0415
        REVIEWED_MANIFEST_SHA256,
        validate_candidate,
    )

    result = validate_candidate(candidate, REVIEWED_MANIFEST_SHA256)
    if len(result["tracks"]) != 55:
        raise ValueError("Pilot input must be the reviewed55 candidate")
    return result


def _seal(candidate: Path, baseline: Path, pin: str) -> dict[str, Any]:
    _candidate(candidate)
    _evaluations(baseline, candidate / "manifest.json", pin)
    return {
        "revision": REVISION,
        "design_sha256": DESIGN_SHA256,
        "candidate_manifest_sha256": sha(read(candidate / "manifest.json")),
        "baseline_inventory_sha256": pin,
        "baseline_evaluation_sha256": sha(read(baseline / "evaluation.json")),
        "builder_sha256": sha(read(Path(__file__))),
        "page_sha256": sha(read(PAGE)),
        "seed": SEED,
        "actual_judgments": 0,
        "public_deployment_authorized": False,
    }


def freeze_pilot(
    candidate: Path, baseline: Path, pin: str, design: Path, output: Path
) -> dict[str, Any]:
    """Create a separate execution seal for reviewer approval before building any packet."""
    if sha(read(design)) != DESIGN_SHA256:
        raise ValueError("Listening design differs from the frozen reviewed protocol")
    result = _seal(candidate, baseline, pin)
    write(output, result)
    return result


def _server(slot: int) -> str:
    return f'''"""Serve only this participant folder on loopback; never serve its parent."""
import argparse
import hashlib
import http.server
import json
from pathlib import Path

root = Path(__file__).resolve().parent
expected = json.loads((root / "inventory.json").read_bytes())
actual = {{p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}}
if actual != set(expected) | {{"inventory.json"}} or any(p.is_symlink() for p in root.rglob("*")):
    raise SystemExit("Participant inventory differs")
for name, record in expected.items():
    path = root / name
    if path.stat().st_size != record["bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
        raise SystemExit("Participant bytes differ: " + name)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--port", type=int, default={8870 + slot})
args = parser.parse_args()
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *values, **kwargs):
        super().__init__(*values, directory=str(root), **kwargs)
print(f"Open http://127.0.0.1:{{args.port}}/", flush=True)
http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
'''


def build_pilot(
    candidate: Path,
    baseline: Path,
    seal_path: Path,
    seal_sha256: str,
    output: Path,
) -> dict[str, Any]:
    """Materialize two closed, method-blind participant roots after seal approval."""
    body = read(seal_path)
    if sha(body) != seal_sha256:
        raise ValueError("Execution seal differs from independently supplied pin")
    seal = json.loads(body)
    if seal != _seal(candidate, baseline, seal["baseline_inventory_sha256"]):
        raise ValueError("Execution inputs or implementation changed after seal")
    manifest = _candidate(candidate)
    evaluation = _evaluations(
        baseline, candidate / "manifest.json", seal["baseline_inventory_sha256"]
    )
    queries = []
    for row in evaluation["queries"]:
        if row["fold"] == 2:
            queries.append(  # noqa: PERF401 -- preserve explicit fold filtering and arm selection.
                {
                    "track_id": row["track_id"],
                    "component_id": row["component_id"],
                    "raw": next(iter(row["arms"]["raw"]["ranking"]), None),
                    "simple": next(iter(row["arms"]["simple4"]["ranking"]), None),
                    "reason": row["reason"],
                }
            )
    items, key = assignments(queries)
    tracks = {r["track_id"]: r for r in manifest["tracks"]}
    if output.exists() or any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError("Pilot output must be fresh and nonsymlinked")
    output.mkdir(parents=True)
    coordinator = {
        "revision": REVISION,
        "build_seal": seal,
        "build_seal_sha256": seal_sha256,
        "key": key,
        "queries": queries,
        "packet_sha256": {},
        "inventory_sha256": {},
        "actual_judgments": 0,
        "public_deployment_authorized": False,
    }
    for slot in (1, 2):
        dest = output / f"listener-{slot}"
        (dest / "audio").mkdir(parents=True)
        used = sorted(
            {
                r[role]
                for r in items[str(slot)]
                for role in ("query", "A", "B")
                if r[role] is not None
            }
        )
        credit_rows, total = {}, 0
        for identity in used:
            row = tracks[identity]
            audio = read(candidate / row["audio_path"], MAX_CLIP)
            if len(audio) != row["audio_bytes"] or sha(audio) != row["audio_sha256"]:
                raise ValueError("Audio changed during snapshot")
            total += len(audio)
            if total > MAX_AUDIO:
                raise ValueError("Participant audio budget exceeded")
            (dest / row["audio_path"]).write_bytes(audio)
            credit_rows[str(identity)] = {k: v for k, v in row.items() if k != "genre_ids"}
        packet = {
            "revision": REVISION,
            "slot": slot,
            "items": items[str(slot)],
            "tracks": credit_rows,
            "metadata_attribution": manifest["metadata_attribution"],
        }
        write(dest / "packet.json", packet)
        (dest / "index.html").write_bytes(read(PAGE))
        (dest / "README.txt").write_text(
            "Local method-blind listening pilot. Run python3 serve.py inside this folder, then open the loopback URL. "
            "Serve ONLY this listener folder; never the parent/coordinator folder. Work independently without looking "
            "at another slot or coordinator files. Names and required credits remain visible: this is not identity blinding. "
            "Listen to the full query, A and B when available, then record your own judgment. Listening flags are self-reports. "
            "Blank means unanswered. Identical and unavailable candidates stay in the denominator. "
            "Download answers before closing/reloading, then use Restore saved answers to continue with this same packet and slot. Nothing is saved automatically or transmitted. "
            "No musical-quality conclusion, deployment authorization or rights warranty follows from this pilot.\n"
        )
        (dest / "serve.py").write_text(_server(slot))
        write(dest / "inventory.json", inventory(dest))
        pin = sha(read(dest / "inventory.json"))
        validate_packet(dest, pin)
        coordinator["inventory_sha256"][str(slot)] = pin
        coordinator["packet_sha256"][str(slot)] = sha(read(dest / "packet.json"))
    (output / "coordinator").mkdir()
    write(output / "coordinator" / "mapping.json", coordinator)
    (output / "coordinator" / "build-seal.json").write_bytes(body)
    write(output / "coordinator" / "inventory.json", inventory(output / "coordinator"))
    return coordinator


def summarize_files(
    root: Path,
    mapping_sha256: str,
    responses: list[Path],
    output: Path,
    *,
    distinct_participants_confirmed: bool = False,
) -> dict[str, Any]:
    """Validate pinned packets and supplied local answers, then write descriptive counts."""
    raw = read(root / "coordinator" / "mapping.json")
    if sha(raw) != mapping_sha256:
        raise ValueError("Coordinator mapping differs from external pin")
    coordinator = json.loads(raw)
    if (
        {p.name for p in (root / "coordinator").iterdir()}
        != {"mapping.json", "build-seal.json", "inventory.json"}
        or json.loads(read(root / "coordinator" / "inventory.json"))
        != inventory(root / "coordinator")
        or sha(read(root / "coordinator" / "build-seal.json")) != coordinator["build_seal_sha256"]
        or json.loads(read(root / "coordinator" / "build-seal.json")) != coordinator["build_seal"]
    ):
        raise ValueError("Coordinator closed inventory or seal differs")
    packets = {}
    for slot in ("1", "2"):
        directory = root / f"listener-{slot}"
        packets[slot] = validate_packet(directory, coordinator["inventory_sha256"][slot])
        if sha(read(directory / "packet.json")) != coordinator["packet_sha256"][slot]:
            raise ValueError("Coordinator packet binding differs")
    if len(responses) > 2:
        raise ValueError("At most two response files; duplicate slots are not merged")
    result = summarize(
        coordinator,
        packets,
        [json.loads(read(p, MAX_RESPONSE)) for p in responses],
        distinct_participants_confirmed=distinct_participants_confirmed,
    )
    result["mapping_sha256"] = mapping_sha256
    result["response_sha256"] = [sha(read(p, MAX_RESPONSE)) for p in responses]
    write(output, result)
    return result
