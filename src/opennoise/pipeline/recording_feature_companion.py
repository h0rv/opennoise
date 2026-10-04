"""Replayable exact-recording feature joins that retain every source observation."""

from __future__ import annotations

import gzip
import json
import tempfile
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

from opennoise.common import sha256_file
from opennoise.ingest.acousticbrainz.native_sonic import verify_native_sonic
from opennoise.ingest.acousticbrainz.projection import NUMERIC_PATHS
from opennoise.serving.metadata.normalized_recording_dataset import replay_dataset
from opennoise.serving.metadata.recording_facts import verify_recording_fact_pack

if TYPE_CHECKING:
    from collections.abc import Iterator

REVISION = "exact-recording-feature-companion-v1"
MAX_ROWS = 250_000
MAX_OUTPUT_BYTES = 20_000_000
MEMBERS = {"features.jsonl.gz", "report.json"}


def _json(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def join_observation(
    observation: dict[str, Any], companion: dict[str, Any] | None
) -> dict[str, Any]:
    """Join verified native rows by recording ID and concordant complete credit sets.

    Callers must first replay both input packs. Cohort associations, titles and
    uploader artist tags never establish a join. Conflicting credits quarantine
    the entire feature vector, even when the requested artist occurs in both.
    """
    values: list[float | None] = [None] * len(NUMERIC_PATHS)
    artist_credits = observation["credited_artist_mbids"]
    state = "missing_observation_credit"
    if artist_credits is not None:
        if companion is None:
            state = "no_companion_recording"
        elif companion["recording_mbid"] != observation["recording_mbid"]:
            raise ValueError("feature companion must use the exact recording identity")
        elif companion["state"] != "available" or companion["identity_state"] != "matched":
            state = "unavailable_sonic_source"
        elif companion["exact_credit"]["fact"] is None:
            state = "missing_companion_credit"
        else:
            fact = companion["exact_credit"]["fact"]
            if fact["recording_mbid"] != observation["recording_mbid"]:
                raise ValueError("companion credit recording identity differs")
            if observation["artist_mbid"] not in artist_credits or set(artist_credits) != set(
                fact["credited_artist_mbids"]
            ):
                state = "credit_conflict"
            else:
                descriptors = companion["descriptors"]
                if [row["path"] for row in descriptors] != list(NUMERIC_PATHS):
                    raise ValueError("companion descriptor order differs from native schema")
                values = [row["value"] for row in descriptors]
                state = "joined"
    return {
        **observation,
        "join_state": state,
        "values": values,
        "observed": [value is not None for value in values],
        "companion": None
        if companion is None
        else {
            "sonic_state": companion["state"],
            "identity_state": companion["identity_state"],
            "source_sha256": companion["source_sha256"],
            "source_observed_at": companion["source_observed_at"],
            "source_transport_completeness": companion["source_transport_completeness"],
            "credit_state": companion["exact_credit"]["state"],
            "credit_fact": companion["exact_credit"]["fact"],
        },
    }


def _fact_observations(directory: Path, projection: dict[str, Any]) -> Iterator[dict[str, Any]]:
    facts = {
        (artist["artist_mbid"], row["recording_mbid"]): row
        for artist in projection["artists"]
        for row in artist["recordings"]
    }
    receipt = json.loads((directory / "receipt.json").read_bytes())
    for index, capture in enumerate(receipt["captures"]):
        artist, recording = capture["artist_mbid"], capture["recording_mbid"]
        fact = facts.get((artist, recording))
        yield {
            "artist_mbid": artist,
            "recording_mbid": recording,
            "credited_artist_mbids": fact["credited_artist_mbids"] if fact else None,
            "source": {"capture_index": index, "capture": capture},
        }


def _normalized_observations(directory: Path) -> Iterator[dict[str, Any]]:
    with gzip.open(directory / "observations.jsonl.gz", "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            yield {
                key: row[key]
                for key in ("artist_mbid", "recording_mbid", "credited_artist_mbids", "source")
            }


def _inputs(
    observations: Path, sonic: Path, native_source: Path | None, root: Path | None
) -> tuple[Iterator[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    companion = verify_native_sonic(sonic)
    if native_source is None:
        if root is not None:
            raise ValueError("root requires a normalized dataset native source")
        projection = verify_recording_fact_pack(observations)
        rows = _fact_observations(observations, projection)
        coverage = [
            {
                key: artist[key]
                for key in ("artist_mbid", "requested_recordings", "missing_recordings")
            }
            for artist in projection["artists"]
        ]
        kind = "recording_facts"
    else:
        if root is None:
            raise ValueError("normalized observations require native source and repository root")
        replay_dataset(native_source, root, observations)
        rows = _normalized_observations(observations)
        coverage = json.loads((observations / "dataset.json").read_bytes())["artists"]
        kind = "normalized_recording_observations"
    provenance = {
        "observation_kind": kind,
        "observation_receipt": _binding(observations / "receipt.json"),
        "sonic_receipt": _binding(sonic / "receipt.json"),
        "source_artist_coverage": coverage,
    }
    return rows, companion, provenance


def _binding(path: Path) -> dict[str, object]:
    digest, size = sha256_file(path)
    return {"sha256": digest, "bytes": size}


def _destination(output: Path, sources: tuple[Path, ...]) -> None:
    if any(path.is_symlink() for path in (output, *output.parents)):
        raise ValueError("feature destination has a symlink ancestor")
    if any(output.resolve().is_relative_to(source.resolve()) for source in sources):
        raise ValueError("feature destination must remain outside source custody")


def build_companion(
    observations: Path,
    sonic: Path,
    output: Path,
    *,
    native_source: Path | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Verify native custody, stream a bounded left join and export unfitted numeric rows."""
    _destination(output, (observations, sonic, *((native_source,) if native_source else ())))
    if output.exists():
        raise ValueError("feature output must be fresh")
    rows, companion, provenance = _inputs(observations, sonic, native_source, root)
    by_recording = {row["recording_mbid"]: row for row in companion["records"]}
    if len(by_recording) != len(companion["records"]):
        raise ValueError("ambiguous companion recording identities")
    states: Counter[str] = Counter()
    artists: dict[str, Counter[str]] = {
        row["artist_mbid"]: Counter() for row in provenance["source_artist_coverage"]
    }
    observed = [0] * len(NUMERIC_PATHS)
    total = complete = decoded_bytes = 0
    output.mkdir(parents=True)
    with (output / "features.jsonl.gz").open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as compressed:
            for observation in rows:
                total += 1
                if total > MAX_ROWS:
                    raise ValueError("feature observation row budget exceeded")
                row = join_observation(observation, by_recording.get(observation["recording_mbid"]))
                states[row["join_state"]] += 1
                artists[row["artist_mbid"]][row["join_state"]] += 1
                complete += all(row["observed"])
                observed = [a + b for a, b in zip(observed, row["observed"], strict=True)]
                line = _json(row)
                decoded_bytes += len(line)
                compressed.write(line)
                if raw.tell() > MAX_OUTPUT_BYTES:
                    raise ValueError("feature encoded byte budget exceeded")
        if raw.tell() > MAX_OUTPUT_BYTES:
            raise ValueError("feature encoded byte budget exceeded")
    report = {
        "revision": REVISION,
        "inputs": provenance,
        "implementation": _binding(Path(__file__)),
        "numeric_paths": list(NUMERIC_PATHS),
        "observation_rows": total,
        "join_states": dict(states),
        "artist_join_states": {key: dict(value) for key, value in artists.items()},
        "observed_rows_per_column": observed,
        "complete_feature_rows": complete,
        "decoded_bytes": decoded_bytes,
        "features": _binding(output / "features.jsonl.gz"),
        "policy": {
            "license": "CC0-1.0",
            "row_unit": "source artist/recording observation, not a unique recording or song",
            "join": "exact recording MBID and concordant complete native artist-credit sets",
            "missing_values": "null; no imputation or fitted column selection",
            "credit_conflicts": "quarantine entire vector; preserve source facts",
            "model_fit_performed": False,
            "musical_validation_established": False,
            "audio_permissions_granted": False,
            "max_rows": MAX_ROWS,
            "max_output_bytes": MAX_OUTPUT_BYTES,
        },
    }
    body = _json(report)
    if len(body) + (output / "features.jsonl.gz").stat().st_size > MAX_OUTPUT_BYTES:
        raise ValueError("feature total byte budget exceeded")
    (output / "report.json").write_bytes(body)
    return report


def replay_companion(
    observations: Path,
    sonic: Path,
    output: Path,
    *,
    native_source: Path | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Rebuild from both native packs; a resealed output receipt cannot certify itself."""
    _destination(output, (observations, sonic, *((native_source,) if native_source else ())))
    if {path.name for path in output.iterdir()} != MEMBERS or any(
        path.is_symlink() or not path.is_file() for path in output.iterdir()
    ):
        raise ValueError("feature artifact file set differs")
    if sum(path.stat().st_size for path in output.iterdir()) > MAX_OUTPUT_BYTES:
        raise ValueError("feature total byte budget exceeded")
    with tempfile.TemporaryDirectory(prefix="opennoise-feature-replay-") as temporary:
        rebuilt = Path(temporary) / "rebuilt"
        report = build_companion(
            observations, sonic, rebuilt, native_source=native_source, root=root
        )
        if any(sha256_file(output / name) != sha256_file(rebuilt / name) for name in MEMBERS):
            raise ValueError("feature companion differs from native replay")
    return report
