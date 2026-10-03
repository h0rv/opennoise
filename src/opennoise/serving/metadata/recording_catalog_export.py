"""A bounded selected-artist recording view; native catalog coverage is not musical review."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import zstandard

from opennoise.serving.metadata.recovered_recording_catalog import (
    LIMITS,
    page_binding,
    project_page,
)
from opennoise.serving.metadata.selected_recording_catalog import canonical_json, sha256_file

if TYPE_CHECKING:
    from collections.abc import Iterator

REVISION = "selected150-native-recording-catalog-static-v1"
PAGE_SIZE = 500
MAX_OUTPUT_BYTES = 50_000_000
SOURCE_RECEIPT_SHA256 = "682e0e963a63c574f9f8729b4c74f8b42aa5bfcd35e41b1a21eeb1bd11b68f9d"
SOURCE_REPLAY_SCRIPT = "scripts/capture_recovered_selected_artist_recordings.py"
SCOPE = {
    "selection": "selected150_exact_artist_ids",
    "atomic_snapshot": False,
    "representative_judgments": 0,
    "musical_relevance": "not_assessed",
    "media_requested": False,
    "listening_permission": "Native metadata does not grant audio permissions.",
}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise TypeError("recording view control must be a JSON object")
    return cast("dict[str, Any]", value)


def _rows(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError("recording summary must contain JSON object rows")
    return cast("list[dict[str, Any]]", value)


def _peak_bytes() -> int:
    return (
        int(
            next(
                line.split()[1]
                for line in Path("/proc/self/status").read_text().splitlines()
                if line.startswith("VmHWM:")
            )
        )
        * 1024
    )


def _check_memory() -> int:
    peak = _peak_bytes()
    if peak >= LIMITS["max_process_rss_bytes"]:
        raise ValueError(
            "recording view process exceeded40MB; preserve candidate without promotion"
        )
    return peak


def verify_source(source: Path, root: Path) -> dict[str, object]:
    """Replay the exact frozen source/code/origin contract before projecting any rows."""
    if sha256_file(source / "receipt.json")[0] != SOURCE_RECEIPT_SHA256:
        raise ValueError("recording view requires the explicitly pinned native catalog")
    spec = importlib.util.spec_from_file_location(
        "catalog_native_replay", root / SOURCE_REPLAY_SCRIPT
    )
    if spec is None or spec.loader is None:
        raise ValueError("native recording replay implementation is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.replay(source, root)
    if not isinstance(result, dict) or result.get("verified") is not True:
        raise ValueError("native recording source replay did not verify")
    return cast("dict[str, object]", result)


def _observations(source: Path) -> Iterator[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Stream admitted nonprobe facts, preserving exact capture and source-row provenance."""
    with (source / "request-ledger.jsonl").open("rb") as stream:
        for raw in stream:
            event = json.loads(raw)
            if event["event"] != "outcome":
                continue
            capture = event["capture"]
            request = capture["request"]
            if request["stage"] == "closing" or capture["outcome"] != "native_core_page":
                continue
            custody = capture["custody"]
            with (source / custody["path"]).open("rb") as compressed:
                body = (
                    zstandard.ZstdDecompressor(max_window_size=1_048_576)
                    .stream_reader(compressed)
                    .read(LIMITS["response_bytes"] + 1)
                )
            if (
                len(body) != custody["decoded_bytes"]
                or hashlib.sha256(body).hexdigest() != custody["decoded_sha256"]
            ):
                raise ValueError("native page bytes changed after closed source replay")
            page = project_page(body, request)
            if page_binding(page) != capture["projection"] or page["rejected_rows"]:
                raise ValueError("native fact projection changed or contains unapproved rows")
            for row_index, fact in enumerate(page["facts"]):
                yield (
                    request["artist_mbid"],
                    {
                        key: fact[key]
                        for key in ["recording_mbid", "title", "length_ms", "credited_artist_mbids"]
                    }
                    | {
                        "source": {
                            "capture_sequence": event["sequence"],
                            "row_index": row_index,
                        },
                    },
                    {
                        "capture_sequence": event["sequence"],
                        "page_sha256": custody["decoded_sha256"],
                        "fetched_at": capture["fetched_at"],
                        "url": request["url"],
                    },
                )


def _inventory(output: Path) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for path in sorted(output.rglob("*")):
        if path.is_symlink():
            raise ValueError("recording view contains a source alias")
        if path.is_file() and path != output / "receipt.json":
            digest, count = sha256_file(path)
            result[path.relative_to(output).as_posix()] = {"sha256": digest, "bytes": count}
    return result


def _write(output: Path, relative: str, value: object, budget: list[int]) -> None:
    data = canonical_json(value)
    if budget[0] + len(data) > MAX_OUTPUT_BYTES:
        raise ValueError("recording view exceeded its independently declared output byte cap")
    path = output / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
    budget[0] += len(data)
    _check_memory()


def export_catalog(source: Path, root: Path, output: Path) -> dict[str, object]:
    """Write a fresh separately named addon without modifying the source or older product."""
    native_replay = verify_source(source, root)
    _check_memory()
    output.mkdir(exist_ok=False)
    budget = [0]
    selection = _read(source / "selection.json")
    summaries = _rows(source / "artists.json")
    artists = {
        row["artist_mbid"]: {**row, "name": chosen["name"], "pages": []}
        for row, chosen in zip(summaries, selection["artists"], strict=True)
    }
    if any(
        row["artist_mbid"] != chosen["artist_mbid"]
        for row, chosen in zip(summaries, selection["artists"], strict=True)
    ):
        raise ValueError("native summary order differs from frozen selected identities")
    current: str | None = None
    buffered: list[dict[str, Any]] = []
    page_sources: dict[str, dict[str, Any]] = {}
    row_count = 0

    def flush() -> None:
        if current is None or not buffered:
            return
        artist = artists[current]
        page = len(artist["pages"])
        relative = f"artists/{current}/{page:04d}.json"
        _write(
            output,
            relative,
            {"artist_mbid": current, "page": page, "recordings": buffered, "sources": page_sources},
            budget,
        )
        artist["pages"].append({"path": relative, "count": len(buffered)})
        buffered.clear()
        page_sources.clear()

    for identity, fact, provenance in _observations(source):
        if current != identity:
            flush()
            current = identity
        buffered.append(fact)
        page_sources[str(provenance["capture_sequence"])] = provenance
        row_count += 1
        if len(buffered) == PAGE_SIZE:
            flush()
    flush()
    for artist in artists.values():
        if sum(page["count"] for page in artist["pages"]) != artist["returned_nonprobe_rows"]:
            raise ValueError("static rows differ from native approved nonprobe denominator")
    index = {
        "revision": REVISION,
        "license": "CC0-1.0",
        "license_url": "https://musicbrainz.org/doc/About/Data_License",
        "scope": SCOPE,
        "source": {
            "receipt_sha256": SOURCE_RECEIPT_SHA256,
            "freeze_sha256": sha256_file(source / "pre-http-freeze.json")[0],
            "roster_sha256": selection["roster_sha256"],
        },
        "counts": {
            "artists": len(artists),
            "observed_recording_artist_rows": row_count,
            "baseline_per_artist_count_sum": sum(
                row["baseline_advertised_count"] for row in summaries
            ),
            "observed_unique_per_artist_count_sum": sum(
                row["unique_exact_credited_recordings"] for row in summaries
            ),
            "counts_are_not_global_unique_recordings": True,
        },
        "artists": list(artists.values()),
    }
    _write(output, "index.json", index, budget)
    _write(output, "native-replay.json", native_replay, budget)
    implementation_sha, implementation_bytes = sha256_file(Path(__file__))
    if budget[0] + implementation_bytes > MAX_OUTPUT_BYTES:
        raise ValueError("recording implementation snapshot exceeds output byte cap")
    with (output / "implementation.py").open("xb") as stream:
        stream.write(Path(__file__).read_bytes())
    budget[0] += implementation_bytes
    _write(
        output,
        "construction.json",
        {
            "argv": sys.argv,
            "source_directory": str(source),
            "source_receipt_sha256": SOURCE_RECEIPT_SHA256,
            "root_directory": str(root),
            "implementation_sha256": implementation_sha,
            "parameters": {"page_size": PAGE_SIZE, "max_output_bytes": MAX_OUTPUT_BYTES},
            "seed_policy": "No random selection, fitting, ranking or musical review.",
        },
        budget,
    )
    receipt = {
        "revision": REVISION,
        "source_receipt_sha256": SOURCE_RECEIPT_SHA256,
        "implementation_sha256": implementation_sha,
        "page_size": PAGE_SIZE,
        "max_output_bytes": MAX_OUTPUT_BYTES,
        "files": _inventory(output),
    }
    _write(output, "receipt.json", receipt, budget)
    peak = _check_memory()
    return {
        "rows": row_count,
        "artists": len(artists),
        "bytes": budget[0],
        "proc_vmhwm_bytes": peak,
    }


def replay_catalog(source: Path, root: Path, output: Path) -> dict[str, object]:  # noqa: C901, PLR0912, PLR0915 - closed controls, source snapshots, per-row and denominator guards.
    """Compare every exported recording to native bytes, never to a name match."""
    native_replay = verify_source(source, root)
    receipt = _read(output / "receipt.json")
    if (
        set(receipt)
        != {
            "revision",
            "source_receipt_sha256",
            "implementation_sha256",
            "page_size",
            "max_output_bytes",
            "files",
        }
        or receipt["revision"] != REVISION
        or receipt["source_receipt_sha256"] != SOURCE_RECEIPT_SHA256
    ):
        raise ValueError("recording view source contract differs")
    if receipt["files"] != _inventory(output):
        raise ValueError("recording view closed hashes differ")
    if receipt["implementation_sha256"] != sha256_file(Path(__file__))[0]:
        raise ValueError("recording view implementation changed")
    if (
        sha256_file(output / "implementation.py")[0] != receipt["implementation_sha256"]
        or _read(output / "native-replay.json") != native_replay
    ):
        raise ValueError("recording view source replay or implementation snapshot differs")
    construction = _read(output / "construction.json")
    if (
        construction["source_receipt_sha256"] != SOURCE_RECEIPT_SHA256
        or construction["implementation_sha256"] != receipt["implementation_sha256"]
        or construction["parameters"]
        != {"page_size": PAGE_SIZE, "max_output_bytes": MAX_OUTPUT_BYTES}
        or construction["seed_policy"] != "No random selection, fitting, ranking or musical review."
    ):
        raise ValueError("recording view construction policy differs")
    index = _read(output / "index.json")
    if set(index) != {"revision", "license", "license_url", "scope", "source", "counts", "artists"}:
        raise ValueError("recording view index includes undeclared claims")
    summaries = _rows(source / "artists.json")
    selection = _read(source / "selection.json")
    expected_source = {
        "receipt_sha256": SOURCE_RECEIPT_SHA256,
        "freeze_sha256": sha256_file(source / "pre-http-freeze.json")[0],
        "roster_sha256": selection["roster_sha256"],
    }
    if (
        index["revision"] != REVISION
        or index["license"] != "CC0-1.0"
        or index["license_url"] != "https://musicbrainz.org/doc/About/Data_License"
        or index["scope"] != SCOPE
        or index["source"] != expected_source
    ):
        raise ValueError("recording view changed license, musical scope or native source pins")
    if receipt["page_size"] != PAGE_SIZE or receipt["max_output_bytes"] != MAX_OUTPUT_BYTES:
        raise ValueError("recording view changed its frozen pagination or output budget")
    logical = (
        sum(row["bytes"] for row in receipt["files"].values())
        + (output / "receipt.json").stat().st_size
    )
    if logical > MAX_OUTPUT_BYTES:
        raise ValueError("recording view closed files exceed50MB")
    expected_names = {row["artist_mbid"]: row["name"] for row in selection["artists"]}
    if len(index["artists"]) != len(summaries):
        raise ValueError("recording view lost selected artists")
    observations = iter(_observations(source))
    count = 0
    expected_files = {"index.json", "native-replay.json", "implementation.py", "construction.json"}
    for artist, summary in zip(index["artists"], summaries, strict=True):
        if (
            set(artist) != set(summary) | {"name", "pages"}
            or {key: artist[key] for key in summary} != summary
            or artist["name"] != expected_names[summary["artist_mbid"]]
        ):
            raise ValueError("recording view changed native artist coverage or identity")
        if len(artist["pages"]) != (summary["returned_nonprobe_rows"] + PAGE_SIZE - 1) // PAGE_SIZE:
            raise ValueError("recording view artist pagination denominator differs")
        for page_number, metadata in enumerate(artist["pages"]):
            expected = f"artists/{artist['artist_mbid']}/{page_number:04d}.json"
            expected_files.add(expected)
            expected_count = min(
                PAGE_SIZE, summary["returned_nonprobe_rows"] - PAGE_SIZE * page_number
            )
            if (
                set(metadata) != {"path", "count"}
                or metadata["path"] != expected
                or type(metadata["count"]) is not int
                or metadata["count"] != expected_count
            ):
                raise ValueError("recording view page path or bounded row count differs")
            page = _read(output / expected)
            if (
                set(page) != {"artist_mbid", "page", "recordings", "sources"}
                or page["artist_mbid"] != artist["artist_mbid"]
                or type(page["page"]) is not int
                or page["page"] != page_number
                or len(page["recordings"]) != metadata["count"]
            ):
                raise ValueError("recording view page identity or count differs")
            used_sources = set()
            for row in page["recordings"]:
                identity, expected_row, provenance = next(observations)
                if (
                    identity != artist["artist_mbid"]
                    or row != expected_row
                    or page["sources"].get(str(provenance["capture_sequence"])) != provenance
                ):
                    raise ValueError("recording view row differs from exact native credited fact")
                count += 1
                used_sources.add(str(provenance["capture_sequence"]))
            if set(page["sources"]) != used_sources:
                raise ValueError("recording view source disclosure contains unreferenced claims")
    if set(receipt["files"]) != expected_files:
        raise ValueError("recording view contains unreferenced extra artifacts")
    if (
        next(observations, None) is not None
        or count != index["counts"]["observed_recording_artist_rows"]
    ):
        raise ValueError("recording view dropped native rows or changed denominator")
    expected_counts = {
        "artists": len(summaries),
        "observed_recording_artist_rows": count,
        "baseline_per_artist_count_sum": sum(row["baseline_advertised_count"] for row in summaries),
        "observed_unique_per_artist_count_sum": sum(
            row["unique_exact_credited_recordings"] for row in summaries
        ),
        "counts_are_not_global_unique_recordings": True,
    }
    if index["counts"] != expected_counts:
        raise ValueError("recording view changed native coverage denominators")
    return {
        "verified": True,
        "rows": count,
        "artists": len(summaries),
        "proc_vmhwm_bytes": _check_memory(),
    }
