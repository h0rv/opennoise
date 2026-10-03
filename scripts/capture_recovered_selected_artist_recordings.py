"""Freeze or replay the full-pagination recipe. HTTP requires a separately reviewed worker."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import zstandard

from opennoise.ingest.musicbrainz.compressed_catalog_custody import replay_and_verify
from opennoise.serving.metadata.recovered_recording_catalog import (
    LIMITS,
    REVISION,
    artist_summary,
    page_binding,
    project_page,
    read_ledger,
    request_plan,
    verify_inherited_sources,
    verify_ledger_order,
    verify_source_prefix,
)
from opennoise.serving.metadata.selected_recording_catalog import (
    canonical_json,
    sha256_file,
    verify_frozen_roster,
)

HTTP_OK = 200
BASELINE_AUDITOR = Path("/dev/shm/opennoise-selected150-recording-catalog-v3-baseline-auditor.py")  # noqa: S108 - exact immutable SHA-checked recovery source, copied into freeze.
BASELINE_AUDITOR_SHA256 = "37cb4722153cc378489171698ae20a0e70a45bf9fd5f25066dc64ea54e53b334"
IMPLEMENTATIONS = (
    str(BASELINE_AUDITOR),
    "scripts/launch_recovered_recording_capture.py",
    "scripts/capture_recovered_selected_artist_recordings.py",
    "scripts/capture_full_selected_artist_recordings.py",
    "src/opennoise/ingest/musicbrainz/recovered_catalog_capture.py",
    "src/opennoise/serving/metadata/recovered_recording_catalog.py",
    "src/opennoise/serving/metadata/full_recording_catalog.py",
    "src/opennoise/ingest/musicbrainz/compressed_catalog_custody.py",
    "src/opennoise/ingest/musicbrainz/full_catalog_capture.py",
    "src/opennoise/serving/metadata/recording_facts.py",
    "src/opennoise/serving/metadata/selected_recording_catalog.py",
)


def write_new(path: Path, value: object) -> None:
    """Never replace an earlier artifact."""
    with path.open("xb") as stream:
        stream.write(canonical_json(value))


def inventory(directory: Path) -> dict[str, dict[str, Any]]:
    """Bind every regular file, with no symlinks or out-of-directory source aliases."""
    files = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("source pack cannot contain symlinks")
        if path.is_file() and path != directory / "receipt.json":
            digest, length = sha256_file(path)
            files[str(path.relative_to(directory))] = {"sha256": digest, "bytes": length}
    return files


def freeze(output: Path, baseline: Path, root: Path, prefix_proof: Path) -> dict[str, object]:
    """Verify the old native counts, then seal identities, policy and code before HTTP."""
    if sys.flags.optimize or sha256_file(BASELINE_AUDITOR)[0] != BASELINE_AUDITOR_SHA256:
        raise ValueError("native auditor requires exact reviewed source and active assertions")
    baseline_report = output.with_name(output.name + "-baseline-native-replay.json")
    baseline_argv = [
        sys.executable,
        str(BASELINE_AUDITOR),
        str(baseline),
        str(root),
        str(baseline_report),
    ]
    checked = subprocess.run(  # noqa: S603 - fixed interpreter/code, native paths only.
        baseline_argv,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONOPTIMIZE": "0"},
    )
    baseline_replay = json.loads(checked.stdout)
    peak_bytes = int(baseline_replay["resource"]["process_peak_rss_since_exec"].split()[0]) * 1024
    if (
        not baseline_replay["actual_sealed_artifact_valid"]
        or peak_bytes >= LIMITS["max_process_rss_bytes"]
    ):
        raise ValueError("separate native baseline replay exceeded process memory budget")
    report_pin = baseline_replay["report_binding"]
    if sha256_file(baseline_report) != (report_pin["sha256"], report_pin["bytes"]):
        raise ValueError("actual native auditor report bytes differ")
    source_reuse = verify_source_prefix(prefix_proof)
    selection = verify_frozen_roster(baseline, root)
    candidates = json.loads((baseline / "candidates.json").read_bytes())
    # The old verifier predates global stage closure. Enforce its actual stage/order here.
    old = json.loads((baseline / "captures.json").read_bytes())
    if not isinstance(old, list):
        raise TypeError("baseline captures must be an ordered list")
    browse = [c for c in old if c.get("stage") == "browse"]
    lookup = [c for c in old if c.get("stage") == "lookup"]
    if old != browse + lookup or len(browse) != len(selection["artists"]):
        raise ValueError("baseline has extra, unknown or reordered stages")
    if [[c["artist_mbid"], c["recording_mbid"]] for c in lookup] != candidates["pairs"]:
        raise ValueError("baseline exact lookup order differs")
    plan = request_plan(selection, candidates)
    output.mkdir(exist_ok=False)
    (output / "implementation").mkdir()
    snapshots = {}
    for index, relative in enumerate(IMPLEMENTATIONS):
        source = root / relative
        copied = output / "implementation" / f"{index:02d}-{source.name}"
        with copied.open("xb") as stream:
            stream.write(source.read_bytes())
        digest, length = sha256_file(copied)
        snapshots[relative] = {
            "path": str(copied.relative_to(output)),
            "sha256": digest,
            "bytes": length,
        }
    write_new(
        output / "baseline-replay.json",
        {
            "argv": baseline_argv,
            "environment_overrides": {"PYTHONOPTIMIZE": "0"},
            "result": baseline_replay,
        },
    )
    with (output / "baseline-native-replay.json").open("xb") as stream:
        stream.write(baseline_report.read_bytes())
    write_new(output / "source-reuse.json", source_reuse)
    write_new(output / "selection.json", selection)
    write_new(output / "plan.json", plan)
    write_new(
        output / "pre-http-freeze.json",
        {
            "revision": REVISION,
            "frozen_at": datetime.now(UTC).isoformat(),
            "argv": sys.argv,
            "baseline_path": str(baseline),
            "baseline_receipt_sha256": sha256_file(baseline / "receipt.json")[0],
            "baseline_candidates_sha256": sha256_file(baseline / "candidates.json")[0],
            "baseline_native_replay_sha256": sha256_file(output / "baseline-native-replay.json")[0],
            "selection_sha256": sha256_file(output / "selection.json")[0],
            "plan_sha256": sha256_file(output / "plan.json")[0],
            "source_reuse_sha256": sha256_file(output / "source-reuse.json")[0],
            "implementation": snapshots,
            "source_pins": selection["source_pins"],
            "source_field_scope": {
                "license_url": "https://musicbrainz.org/doc/About/Data_License",
                "approved": "Core recording fields and exact native credits only.",
                "envelope": ["recording-count", "recording-offset", "recordings"],
                "supplementary_rows": "Raw custody only; entire mixed page excluded from facts.",
                "recording_projector": "Unchanged project_recording_fact for every row.",
            },
            "seed_policy": "No random selection or fitting; baseline counts prescribe pagination.",
        },
    )
    return {
        "requests": len(plan["requests"]),
        "freeze_sha256": sha256_file(output / "pre-http-freeze.json")[0],
    }


def verify_freeze(directory: Path, root: Path) -> dict[str, object]:  # noqa: C901
    """Check the captured implementation before any source replay or HTTP."""
    frozen = json.loads((directory / "pre-http-freeze.json").read_bytes())
    if (
        sha256_file(directory / "baseline-native-replay.json")[0]
        != frozen["baseline_native_replay_sha256"]
    ):
        raise ValueError("frozen native baseline replay evidence changed")
    if sha256_file(directory / "source-reuse.json")[0] != frozen["source_reuse_sha256"]:
        raise ValueError("frozen native source reuse declaration changed")
    reuse = json.loads((directory / "source-reuse.json").read_bytes())
    if verify_source_prefix(Path(reuse["source_proof_path"])) != reuse:
        raise ValueError("original source prefix cannot be replayed exactly")
    baseline = Path(frozen["baseline_path"])
    if (
        sha256_file(baseline / "receipt.json")[0] != frozen["baseline_receipt_sha256"]
        or sha256_file(baseline / "candidates.json")[0] != frozen["baseline_candidates_sha256"]
    ):
        raise ValueError("independently replayed baseline changed")
    selection = json.loads((directory / "selection.json").read_bytes())
    candidates = json.loads((baseline / "candidates.json").read_bytes())
    if selection != json.loads((baseline / "selection.json").read_bytes()):
        raise ValueError("pre-HTTP artist roster differs from verified native baseline")
    if request_plan(selection, candidates) != json.loads((directory / "plan.json").read_bytes()):
        raise ValueError("frozen pages cannot be rederived from exact native baseline counts")
    for filename, key in [("selection.json", "selection_sha256"), ("plan.json", "plan_sha256")]:
        if sha256_file(directory / filename)[0] != frozen[key]:
            raise ValueError("pre-HTTP identity or policy bytes changed")
    if set(frozen["implementation"]) != set(IMPLEMENTATIONS):
        raise ValueError("pre-HTTP implementation closure differs")
    for relative, pin in frozen["implementation"].items():
        expected = (pin["sha256"], pin["bytes"])
        if (
            sha256_file(directory / pin["path"]) != expected
            or sha256_file(root / relative) != expected
        ):
            raise ValueError("construction implementation changed after pre-HTTP freeze")
    return cast("dict[str, object]", frozen)


def replay(directory: Path, root: Path) -> dict[str, object]:  # noqa: C901, PLR0912
    """Reconstruct all page outcomes from lossless source bytes, bounded by one artist."""
    actual_files = inventory(directory)
    verify_freeze(directory, root)
    receipt = json.loads((directory / "receipt.json").read_bytes())
    if set(receipt) != {"revision", "files"} or receipt["revision"] != REVISION:
        raise ValueError("closed source receipt schema differs")
    if receipt.get("files") != actual_files:
        raise ValueError("closed source inventory differs")
    verify_inherited_sources(directory)
    logical = (
        sum(int(row["bytes"]) for row in actual_files.values())
        + (directory / "receipt.json").stat().st_size
    )
    if logical > LIMITS["logical_pack_bytes"]:
        raise ValueError("entire source pack exceeds logical byte cap")
    metadata_bytes = (
        sum(
            int(pin["bytes"])
            for name, pin in actual_files.items()
            if not name.startswith("custody/")
        )
        + (directory / "receipt.json").stat().st_size
    )
    if metadata_bytes > LIMITS["metadata_reserve_bytes"]:
        raise ValueError("closed metadata exceeds frozen reserved byte budget")
    plan = json.loads((directory / "plan.json").read_bytes())
    captures = read_ledger(directory, plan)
    verify_ledger_order(plan, captures)
    summaries, requests, pages = [], [], []
    current = None
    for request, capture in zip(plan["requests"], captures, strict=True):
        if current is not None and current != request["artist_mbid"]:
            summaries.append(artist_summary(current, requests, pages))
            requests, pages = [], []
        current = request["artist_mbid"]
        projected = None
        custody = capture.get("custody")
        if custody and custody.get("path") is not None:
            path = directory / custody["path"]
            if (
                path.parent != directory / "custody"
                or path.name != f"{len(summaries):03d}-{len(requests):04d}.json.zst"
            ):
                raise ValueError("native custody path differs from prescribed request position")
            replay_and_verify(path, custody)
            if (
                capture["status_code"] == HTTP_OK
                and custody["complete_body"]
                and capture["headers"].get("content-encoding", "identity") == "identity"
                and capture["header_scope"]["approved"]
            ):
                with path.open("rb") as stream:
                    body = (
                        zstandard.ZstdDecompressor(max_window_size=1_048_576)
                        .stream_reader(stream)
                        .read(LIMITS["response_bytes"] + 1)
                    )
                try:
                    projected = project_page(body, request)
                except (ValueError, TypeError, KeyError):
                    projected = None
        if page_binding(projected) != capture.get("projection"):
            raise ValueError("saved catalog projection differs from native bytes")
        requests.append(request)
        if projected is not None:
            projected.pop("facts")
        pages.append(projected)
    if current is not None:
        summaries.append(artist_summary(current, requests, pages))
    if summaries != json.loads((directory / "artists.json").read_bytes()):
        raise ValueError("saved artist closure differs from complete native page replay")
    return {
        "verified": True,
        "artists": len(summaries),
        "logical_bytes": logical,
        "statuses": {
            status: sum(r["status"] == status for r in summaries)
            for status in ["observed_window_complete", "partial", "inconsistent", "unknown"]
        },
    }


def main() -> None:
    """Run one immutable freeze or independent bounded replay process."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["freeze", "capture", "verify"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--prefix-proof", type=Path)
    args = parser.parse_args()
    if args.command == "freeze":
        if args.baseline is None or args.prefix_proof is None:
            parser.error("freeze requires --baseline and --prefix-proof")
        result = freeze(args.output, args.baseline, args.root, args.prefix_proof)
    elif args.command == "capture":
        verify_freeze(args.output, args.root)
        from opennoise.ingest.musicbrainz.recovered_catalog_capture import capture  # noqa: PLC0415

        result = capture(args.output)
        write_new(args.output / "capture-result.json", result)
        files = inventory(args.output)
        write_new(args.output / "receipt.json", {"revision": REVISION, "files": files})
    else:
        result = replay(args.output, args.root)
    print(json.dumps(result, sort_keys=True))  # noqa: T201 - machine receipt.


if __name__ == "__main__":
    main()
