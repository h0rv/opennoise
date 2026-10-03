"""Lossless deterministic tables of native observations, not deduplicated musical works."""

from __future__ import annotations

import gzip
import hashlib
import json
import sys
import zlib
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, TypedDict

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

from opennoise.serving.metadata.recording_catalog_export import (
    SOURCE_RECEIPT_SHA256,
    _check_memory,
    _observations,
    verify_source,
)
from opennoise.serving.metadata.selected_recording_catalog import canonical_json, sha256_file

REVISION = "selected150-native-recording-observations-v1"
MAX_ENCODED_BYTES = 10_000_000
MAX_LINE_BYTES = 1_000_000
MAX_CONTROL_BYTES = 262_144
SEED_POLICY = "No randomness, fitting, ranking, musical review, or global recording deduplication."
POLICY = {
    "license": "CC0-1.0",
    "license_url": "https://musicbrainz.org/doc/About/Data_License",
    "observation_key": ["artist_mbid", "source.capture_sequence", "source.row_index"],
    "recording_mbid": "Exact native identity; eligible for joins, not a claim of a unique song.",
    "joint_recordings": (
        "Retain separate source observations for each credited selected artist; "
        "no global deduplication or conflict resolution."
    ),
    "denominator": "Source recording/artist observations; not globally unique recordings.",
    "atomic_snapshot": False,
    "representative_judgments": 0,
    "musical_relevance": "not_assessed",
    "audio_permission": "Metadata does not grant audio permissions.",
    "gzip_mtime": 0,
    "max_encoded_dataset_bytes": MAX_ENCODED_BYTES,
    "max_process_bytes": 40_000_000,
}


class SourcePin(TypedDict):
    """Bind one producing source snapshot without mixing path and byte-count types."""

    path: str
    sha256: str
    bytes: int


def _facts(source: Path) -> Iterator[dict[str, Any]]:
    for identity, fact, _provenance in _observations(source):
        yield {"artist_mbid": identity, **fact}


def _captures(source: Path) -> Iterator[dict[str, Any]]:
    with (source / "request-ledger.jsonl").open("rb") as stream:
        for raw in stream:
            event = json.loads(raw)
            if event["event"] != "outcome":
                continue
            capture = event["capture"]
            custody = capture.get("custody")
            yield {
                "capture_sequence": event["sequence"],
                "request": capture["request"],
                "fetched_at": capture["fetched_at"],
                "status_code": capture["status_code"],
                "outcome": capture["outcome"],
                "decoded_sha256": custody["decoded_sha256"] if custody else None,
                "decoded_bytes": custody["decoded_bytes"] if custody else 0,
                "complete_body": custody["complete_body"] if custody else False,
            }


def _metadata(source: Path) -> dict[str, Any]:
    chosen = json.loads((source / "selection.json").read_bytes())
    summaries = json.loads((source / "artists.json").read_bytes())
    names = {row["artist_mbid"]: row["name"] for row in chosen["artists"]}
    return {
        "revision": REVISION,
        "policy": POLICY,
        "source_receipt_sha256": SOURCE_RECEIPT_SHA256,
        "source_freeze_sha256": sha256_file(source / "pre-http-freeze.json")[0],
        "roster_sha256": chosen["roster_sha256"],
        "artists": [{**row, "name": names[row["artist_mbid"]]} for row in summaries],
        "counts": {
            "selected_artists": len(summaries),
            "baseline_per_artist_count_sum": sum(
                row["baseline_advertised_count"] for row in summaries
            ),
            "observed_recording_artist_rows": sum(
                row["returned_nonprobe_rows"] for row in summaries
            ),
            "observed_unique_per_artist_count_sum": sum(
                row["unique_exact_credited_recordings"] for row in summaries
            ),
            "global_unique_recordings": None,
        },
    }


def _size(output: Path) -> int:
    return sum(path.stat().st_size for path in output.rglob("*") if path.is_file())


def _destination(source: Path, output: Path) -> None:
    """Reject destinations inside immutable native custody or behind aliases."""
    if any(path.is_symlink() for path in [output, *output.parents]):
        raise ValueError("normalized destination has a symlink ancestor")
    resolved_source, resolved_output = source.resolve(), output.resolve()
    if resolved_output == resolved_source or resolved_source in resolved_output.parents:
        raise ValueError("normalized destination must remain outside native source custody")


def _code_sources(source: Path, root: Path) -> dict[str, Path]:
    frozen = json.loads((source / "pre-http-freeze.json").read_bytes())
    sources: dict[str, Path] = {relative: root / relative for relative in frozen["implementation"]}
    sources["src/opennoise/serving/metadata/normalized_recording_dataset.py"] = Path(__file__)
    projector = sys.modules[_observations.__module__].__file__
    if projector is None:
        raise ValueError("native fact projector has no reproducible source file")
    sources["src/opennoise/serving/metadata/recording_catalog_export.py"] = Path(projector)
    sources["scripts/export_normalized_recording_dataset.py"] = (
        root / "scripts/export_normalized_recording_dataset.py"
    )
    return sources


def _recipe(source: Path, root: Path, output: Path) -> dict[str, Any]:
    arguments = {"source": str(source), "root": str(root), "output": str(output)}
    return {
        "callable": "opennoise.serving.metadata.normalized_recording_dataset.export_dataset",
        "arguments": arguments,
        "cli_argv": [
            str(root / "scripts/export_normalized_recording_dataset.py"),
            "export",
            "--source",
            str(source),
            "--output",
            str(output),
            "--root",
            str(root),
        ],
        "policy": POLICY,
        "seed_policy": SEED_POLICY,
    }


def _single_member_lines(path: Path) -> Iterator[bytes]:
    """Bound gzip decoding and reject padding, empty extra members and truncated tails."""
    codec = zlib.decompressobj(wbits=31)
    buffered = bytearray()
    with path.open("rb") as stream:
        chunk = stream.read(32_768)
        while chunk:
            decoded = codec.decompress(chunk, 65_536)
            buffered.extend(decoded)
            while b"\n" in buffered:
                position = buffered.index(b"\n") + 1
                if position > MAX_LINE_BYTES:
                    raise ValueError("normalized JSONL line exceeds bounded native schema")
                yield bytes(buffered[:position])
                del buffered[:position]
            if len(buffered) > MAX_LINE_BYTES:
                raise ValueError("normalized JSONL line exceeds bounded native schema")
            if codec.eof:
                if codec.unused_data or stream.read(1):
                    raise ValueError("normalized gzip contains trailing members or padding")
                break
            chunk = codec.unconsumed_tail or stream.read(32_768)
    if not codec.eof or buffered:
        raise ValueError("normalized gzip is truncated or lacks a final JSONL newline")


def _write(output: Path, name: str, data: bytes) -> None:
    if _size(output) + len(data) > MAX_ENCODED_BYTES:
        raise ValueError("normalized dataset exceeds its total encoded byte cap")
    path = output / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


class _CappedWriter:
    """Reject an encoded write before it can cross the total closed-dataset ceiling."""

    def __init__(self, raw: BinaryIO, output: Path) -> None:
        self.raw, self.output = raw, output

    def write(self, data: bytes) -> int:
        if _size(self.output) + len(data) > MAX_ENCODED_BYTES:
            raise ValueError("normalized dataset encoded write exceeds its hard cap")
        written = self.raw.write(data)
        if written != len(data):
            raise OSError("partial encoded write; preserve incomplete dataset")
        return written

    def flush(self) -> None:
        self.raw.flush()

    def tell(self) -> int:
        return self.raw.tell()


def _table(output: Path, name: str, rows: Iterable[dict[str, Any]]) -> dict[str, object]:
    digest, decoded_bytes, count = hashlib.sha256(), 0, 0
    with (output / name).open("xb", buffering=0) as raw:  # noqa: SIM117 - close gzip before raw.
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=_CappedWriter(raw, output), mtime=0, compresslevel=6
        ) as compressed:
            for row in rows:
                data = canonical_json(row) + b"\n"
                compressed.write(data)
                digest.update(data)
                decoded_bytes += len(data)
                count += 1
                # Reserve the closing gzip member and small receipt/control files.
                if _size(output) + 512_000 > MAX_ENCODED_BYTES:
                    raise ValueError(
                        "normalized dataset encoded budget exhausted; preserve partial"
                    )
                _check_memory()
    encoded_sha, encoded_bytes = sha256_file(output / name)
    return {
        "sha256": encoded_sha,
        "bytes": encoded_bytes,
        "decoded_sha256": digest.hexdigest(),
        "decoded_bytes": decoded_bytes,
        "rows": count,
    }


def export_dataset(source: Path, root: Path, output: Path) -> dict[str, object]:
    """Replay native inputs and exclusively create deterministic portable compressed tables."""
    _destination(source, output)
    native = verify_source(source, root)
    _check_memory()
    output.mkdir(exist_ok=False)
    tables = {"observations.jsonl.gz": _table(output, "observations.jsonl.gz", _facts(source))}
    tables["captures.jsonl.gz"] = _table(output, "captures.jsonl.gz", _captures(source))
    metadata = _metadata(source)
    if (
        tables["observations.jsonl.gz"]["rows"]
        != metadata["counts"]["observed_recording_artist_rows"]
    ):
        raise ValueError("normalized source observation denominator differs")
    _write(output, "dataset.json", canonical_json(metadata))
    _write(output, "native-replay.json", canonical_json(native))
    implementation: dict[str, SourcePin] = {}
    for sequence, (relative, path) in enumerate(sorted(_code_sources(source, root).items())):
        filename = f"code/{sequence:02d}-{path.name}"
        _write(output, filename, path.read_bytes())
        digest, count = sha256_file(path)
        implementation[relative] = {"path": filename, "sha256": digest, "bytes": count}
    recipe = _recipe(source, root, output)
    # Library API callers have a bound callable recipe; only exact CLI calls claim
    # historical argv. The external process proof is separately retained.
    is_cli = sys.argv == recipe["cli_argv"]
    _write(
        output,
        "construction.json",
        canonical_json(
            {
                "recipe": recipe,
                "invocation_kind": "cli" if is_cli else "python_api",
                "actual_cli_argv": sys.argv if is_cli else None,
                "implementation": implementation,
            }
        ),
    )
    instructions = """# Native selected-150 recording observations

Read dataset.json for the complete 150-artist coverage states and licence.
Stream observations.jsonl.gz as UTF-8 JSONL. Each row contains exact artist and
recording UUIDs, title, nullable length_ms, literal credited_artist_mbids, and
source.capture_sequence/source.row_index. Stream captures.jsonl.gz and join on
capture_sequence for the native request URL, UTC time, decoded source SHA256,
and declared completeness. Do not join names or collapse joint-artist records
into unique songs. No recording has been listened to or judged representative.

Python example:

    import gzip, json
    with gzip.open('observations.jsonl.gz', 'rt', encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line)
            # Process one exact credited source observation.

receipt.json binds every regular member plus gzip decoded hashes and row counts.
The separately retained original native pack is required for independent replay;
a self-consistent receipt alone does not prove musical truth or source custody.
"""
    _write(output, "README.md", instructions.encode())
    files = {
        path.relative_to(output).as_posix(): {
            "sha256": sha256_file(path)[0],
            "bytes": path.stat().st_size,
        }
        for path in output.rglob("*")
        if path.is_file()
    }
    _write(
        output,
        "receipt.json",
        canonical_json(
            {
                "revision": REVISION,
                "source_receipt_sha256": SOURCE_RECEIPT_SHA256,
                "files": files,
                "tables": tables,
            }
        ),
    )
    return {
        "rows": tables["observations.jsonl.gz"]["rows"],
        "encoded_bytes": _size(output),
        "proc_vmhwm_bytes": _check_memory(),
    }


def replay_dataset(source: Path, root: Path, output: Path) -> dict[str, object]:  # noqa: C901, PLR0912, PLR0915 - explicit independent custody, closure and row guards.
    """Compare every compressed observation and capture to freshly replayed native sources."""
    native = verify_source(source, root)
    _destination(source, output)
    members = list(output.rglob("*"))
    if any(
        path.is_symlink() or (not path.is_file() and path != output / "code") for path in members
    ):
        raise ValueError("normalized dataset source alias or unexpected directory")
    if _size(output) > MAX_ENCODED_BYTES:
        raise ValueError("normalized dataset exceeds encoded byte cap")
    if any(
        (output / name).stat().st_size > MAX_CONTROL_BYTES
        for name in ["receipt.json", "construction.json", "dataset.json", "native-replay.json"]
    ):
        raise ValueError("normalized control file exceeds bounded native schema")
    receipt = json.loads((output / "receipt.json").read_bytes())
    sources = _code_sources(source, root)
    implementation: dict[str, SourcePin] = {}
    for sequence, (relative, path) in enumerate(sorted(sources.items())):
        digest, count = sha256_file(path)
        implementation[relative] = {
            "path": f"code/{sequence:02d}-{path.name}",
            "sha256": digest,
            "bytes": count,
        }
    expected = {
        "observations.jsonl.gz",
        "captures.jsonl.gz",
        "dataset.json",
        "native-replay.json",
        "construction.json",
        "README.md",
    } | {pin["path"] for pin in implementation.values()}
    if (
        set(receipt) != {"revision", "source_receipt_sha256", "files", "tables"}
        or receipt["revision"] != REVISION
        or receipt["source_receipt_sha256"] != SOURCE_RECEIPT_SHA256
        or set(receipt["files"]) != expected
    ):
        raise ValueError("normalized dataset closed contract differs")
    if {path.relative_to(output).as_posix() for path in members if path.is_file()} != expected | {
        "receipt.json"
    }:
        raise ValueError("normalized dataset has extra files or aliases")
    if _size(output) > MAX_ENCODED_BYTES:
        raise ValueError("normalized dataset exceeds encoded byte cap")
    for name, pin in receipt["files"].items():
        if sha256_file(output / name) != (pin["sha256"], pin["bytes"]):
            raise ValueError("normalized dataset member bytes differ")
    if (output / "dataset.json").read_bytes() != canonical_json(_metadata(source)) or (
        output / "native-replay.json"
    ).read_bytes() != canonical_json(native):
        raise ValueError("normalized dataset changed native coverage or scope")
    for pin in implementation.values():
        if sha256_file(output / pin["path"]) != (pin["sha256"], pin["bytes"]):
            raise ValueError("normalized dataset producing implementation differs")
    if set(receipt["tables"]) != {"observations.jsonl.gz", "captures.jsonl.gz"}:
        raise ValueError("normalized dataset table declaration differs")
    for name, rows in [
        ("observations.jsonl.gz", _facts(source)),
        ("captures.jsonl.gz", _captures(source)),
    ]:
        digest, decoded_bytes, count = hashlib.sha256(), 0, 0
        with (output / name).open("rb") as header:
            if header.read(10) != bytes.fromhex("1f8b08000000000000ff"):
                raise ValueError("normalized gzip has a timestamp, filename or undeclared format")
        lines = _single_member_lines(output / name)
        for expected_row in rows:
            expected_line = canonical_json(expected_row) + b"\n"
            line = next(lines, None)
            if line != expected_line:
                raise ValueError("normalized observation/capture differs from exact native row")
            digest.update(line)
            decoded_bytes += len(line)
            count += 1
            _check_memory()
        if next(lines, None) is not None:
            raise ValueError("normalized table has extra decoded rows")
        pin = receipt["tables"][name]
        encoded_sha, encoded_bytes = sha256_file(output / name)
        if pin != {
            "sha256": encoded_sha,
            "bytes": encoded_bytes,
            "decoded_sha256": digest.hexdigest(),
            "decoded_bytes": decoded_bytes,
            "rows": count,
        }:
            raise ValueError("normalized table counts or encoded/decoded hashes differ")
    construction = json.loads((output / "construction.json").read_bytes())
    if set(construction) != {"recipe", "invocation_kind", "actual_cli_argv", "implementation"}:
        raise ValueError("normalized construction fields differ")
    recipe = construction["recipe"]
    arguments = recipe.get("arguments", {})
    if set(arguments) != {"source", "root", "output"} or any(
        not isinstance(value, str) for value in arguments.values()
    ):
        raise ValueError("normalized construction arguments differ")
    expected_recipe = _recipe(
        Path(arguments["source"]), Path(arguments["root"]), Path(arguments["output"])
    )
    if canonical_json(recipe) != canonical_json(expected_recipe) or canonical_json(
        construction["implementation"]
    ) != canonical_json(implementation):
        raise ValueError("normalized construction policy differs")
    if construction["invocation_kind"] == "cli":
        if construction["actual_cli_argv"] != recipe["cli_argv"]:
            raise ValueError("normalized CLI invocation differs from executable recipe")
    elif (
        construction["invocation_kind"] != "python_api"
        or construction["actual_cli_argv"] is not None
    ):
        raise ValueError("normalized invocation kind differs")
    return {
        "verified": True,
        "rows": receipt["tables"]["observations.jsonl.gz"]["rows"],
        "encoded_bytes": _size(output),
        "proc_vmhwm_bytes": _check_memory(),
    }
