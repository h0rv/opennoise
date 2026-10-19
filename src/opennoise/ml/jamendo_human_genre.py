"""Prospective nine-class human-vote metadata diagnostic; local noncommercial research."""

from __future__ import annotations

import hashlib
import json
import platform
from collections import Counter
from dataclasses import dataclass
from http import HTTPStatus
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import numpy as np
from scipy.special import logsumexp

from opennoise.ml import jamendo_human_mood as native

PROTOCOL_SHA256 = "994399146138008c4329946315d9ac8f7b78021c03dbf2bd87fa515fcf83796b"
CLASSES = (
    "alternative",
    "blues",
    "electronic",
    "folkcountry",
    "funksoulrnb",
    "jazz",
    "pop",
    "raphiphop",
    "rock",
)
METHODS = ("training_human_prior", "genre_instrument_nb", "mapped_uploader_genre")
MAPPING = (
    ("alternative",),
    ("blues",),
    ("electronic",),
    ("folk", "country"),
    ("funk", "soul", "rnb"),
    ("jazz",),
    ("pop",),
    ("rap", "hiphop"),
    ("rock",),
)
SALT = "opennoise-jamendo-human-genre-dortmund-v1"
FOLDS = 5
VOTES = 3
MIN_CLASS_COMPONENTS = 5
MIN_TRACKS = 200
MIN_COMPONENTS = 50
CLIP = 1e-15
MAX_BYTES = 20_000_000
RIGHTS = {
    "source_license": "CC-BY-NC-SA-4.0",
    "research_only": True,
    "attribution": (
        "Music Technology Group; Bogdanov, Won, Tovstogan, Porter and Serra (2019), "
        "The MTG-Jamendo Dataset for Automatic Music Tagging; "
        "Music Classification Annotations documentation"
    ),
}


@dataclass(frozen=True)
class GenreObservation(native.Observation):
    """Keep canonical tokens and raw-source recognition as separate eligibility facts."""

    invalid_raw_vote: bool = False


def encoded(value: object) -> bytes:
    """Serialize finite local research artifacts deterministically."""
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def digest(path: Path) -> str:
    """Reuse the native bounded-input source hash primitive."""
    return native.digest(path)


def read(path: Path) -> Any:  # noqa: ANN401 - JSON stages deliberately contain objects and arrays.
    """Read bounded regular research JSON without following symlinks."""
    if (
        any(p.is_symlink() for p in (path, *path.parents))
        or not path.is_file()
        or path.stat().st_size > MAX_BYTES
    ):
        raise ValueError("Research JSON is not a bounded regular file")
    return json.loads(path.read_bytes())


def runtime() -> dict[str, Any]:
    """Pin new math/parser and unchanged identity helpers and numerical dependencies."""
    script = Path(__file__).resolve().parents[3] / "scripts/run_jamendo_human_genre.py"
    return {
        "python": platform.python_version(),
        "numpy": version("numpy"),
        "scipy": version("scipy"),
        "code": {p.name: digest(p) for p in (Path(__file__), Path(native.__file__), script)},
    }


def destination(output: Path, sources: tuple[Path, ...]) -> None:
    """Reject overlapping or existing outputs before parsing or fitting."""
    if (
        output.exists()
        or any(p.is_symlink() for p in (output, *output.parents))
        or any(
            output.resolve().is_relative_to(p.resolve())
            or p.resolve().is_relative_to(output.resolve())
            for p in sources
        )
    ):
        raise ValueError("Fresh research output outside inputs required")


def publish(output: Path, files: dict[str, Any], sources: tuple[Path, ...]) -> str:
    """Publish one fresh bounded stage atomically, refusing input overlap."""
    destination(output, sources)
    raw = {name: file_bytes(name, value) for name, value in files.items()}
    if sum(map(len, raw.values())) > MAX_BYTES:
        raise ValueError("Combined research output byte cap exceeded")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".jamendo-human-genre-", dir=output.parent) as temporary:
        stage = Path(temporary) / "result"
        stage.mkdir()
        for name, content in raw.items():
            (stage / name).write_bytes(content)
        stage.rename(output)
    return digest(output / ("seal.json" if "seal.json" in files else "receipt.json"))


def sources(protocol_path: Path, receipt_path: Path, receipt_pin: str) -> tuple[Path, Path]:
    """Verify exact prior-authorized official blobs against the fresh acquisition receipt."""
    spec, receipt = read(protocol_path), read(receipt_path)
    if digest(protocol_path) != PROTOCOL_SHA256 or digest(receipt_path) != receipt_pin:
        raise ValueError("Protocol or fresh acquisition receipt differs")
    if (
        receipt["protocol_sha256"] != PROTOCOL_SHA256
        or receipt["source_commit"] != spec["source_commit"]
        or len(receipt["requests"]) != len(spec["input_files"])
        or receipt["success"] is not True
        or receipt["retries"] != 0
        or receipt["redirects"] is not False
        or receipt["audio_requested"] is not False
        or receipt["total_bytes"] != sum(r["bytes"] for r in spec["input_files"])
        or receipt["fresh_capture"] is not True
        or receipt["source_license"] != RIGHTS["source_license"]
        or receipt["research_only"] is not True
    ):
        raise ValueError("Fresh acquisition association differs")
    result = []
    for expected, actual in zip(spec["input_files"], receipt["requests"], strict=True):
        path = Path(actual["local_path"])
        if (
            any(p.is_symlink() for p in (path, *path.parents))
            or not path.is_file()
            or path.stat().st_size != expected["bytes"]
        ):
            raise ValueError("Official source file type or size differs")
        content = path.read_bytes()
        blob = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()  # noqa: S324 - official Git blob plus SHA256.
        if (
            actual["path"] != expected["path"]
            or actual["url"]
            != f"https://raw.githubusercontent.com/MTG/mtg-jamendo-dataset/{spec['source_commit']}/{expected['path']}"
            or actual["attempt"] != 1
            or actual["integrity"] != "pass"
            or actual["status"] != HTTPStatus.OK
            or actual["bytes"] != expected["bytes"]
            or actual["git_blob_sha1"] != expected["git_blob_sha1"]
            or blob != expected["git_blob_sha1"]
            or hashlib.sha256(content).hexdigest() != expected["sha256"]
            or actual["sha256"] != expected["sha256"]
        ):
            raise ValueError("Official source content differs")
        result.append(path)
    return result[0], result[1]


def fold(component: int) -> int:
    """Assign the new label-blind salt to the unchanged native component minimum."""
    return int.from_bytes(hashlib.sha256(f"{SALT}|{component}".encode()).digest(), "big") % FOLDS


def cohort(rows: list[native.Observation]) -> list[dict[str, Any]]:
    """Freeze complete metadata identity and artist/album components before target parsing."""
    groups = native.components(rows)
    return [
        {
            "track_id": r.track_id,
            "artist_id": r.artist_id,
            "album_id": r.album_id,
            "path": r.path,
            "duration": r.duration,
            "component_id": groups[r.track_id],
            "fold": fold(groups[r.track_id]),
        }
        for r in rows
    ]


def vote_reason(row: native.Observation) -> str | None:
    """Treat empty serialization as missing and preserve all recognized disagreement."""
    if not row.votes:
        return "missing_votes"
    if len(row.votes) != VOTES:
        return "wrong_vote_count"
    if (isinstance(row, GenreObservation) and row.invalid_raw_vote) or any(
        v not in CLASSES for v in row.votes
    ):
        return "invalid_vote"
    return None


def target(row: native.Observation) -> np.ndarray:
    """Build the fixed ordered nine-class fractional vote target."""
    if vote_reason(row) is not None:
        raise ValueError("Ineligible human target")
    return np.array([sum(v == c for v in row.votes or ()) / VOTES for c in CLASSES])


def class_components(rows: list[native.Observation], groups: dict[int, int]) -> list[int]:
    """Count distinct positive-vote components for each fixed class without weighting."""
    return [len({groups[r.track_id] for r in rows if c in (r.votes or ())}) for c in CLASSES]


def fit(rows: list[native.Observation], groups: dict[int, int]) -> dict[str, Any]:
    """Fit a fractional multiclass Bernoulli model on supplied eligible training rows only."""
    if not rows or any(vote_reason(r) is not None for r in rows):
        raise ValueError("Eligible training rows required")
    counts = Counter(groups[r.track_id] for r in rows)
    w = np.array([1 / counts[groups[r.track_id]] for r in rows])
    y = np.array([target(r) for r in rows])
    tags = [native.feature_tags(r) for r in rows]
    frequency = Counter(t for row in tags for t in row)
    vocabulary = tuple(sorted(t for t, n in frequency.items() if n < len(rows)))
    x = np.array([[t in observed for t in vocabulary] for observed in tags], dtype=float).reshape(
        len(rows), len(vocabulary)
    )
    masses = w @ y
    prior = (1 + masses) / (len(CLASSES) + w.sum())
    theta = (1 + (w[:, None] * y).T @ x) / (2 + masses[:, None])
    return {"vocabulary": list(vocabulary), "prior": prior.tolist(), "theta": theta.tolist()}


def predict(model: dict[str, Any], row: native.Observation) -> dict[str, list[float]]:
    """Predict solely from permitted uploader tags, without inspecting query human votes."""
    tags = native.feature_tags(row)
    x = np.array([t in tags for t in model["vocabulary"]], dtype=float)
    prior, theta = np.array(model["prior"]), np.array(model["theta"])
    odds = np.log(prior) + (np.log(theta) * x + np.log1p(-theta) * (1 - x)).sum(axis=1)
    nb = np.exp(odds - logsumexp(odds)) if model["vocabulary"] else prior.copy()
    mapped = [i for i, tokens in enumerate(MAPPING) if any("genre---" + t in tags for t in tokens)]
    direct = np.zeros(len(CLASSES)) if mapped else prior.copy()
    if mapped:
        direct[mapped] = 1 / len(mapped)
    return dict(zip(METHODS, (prior.tolist(), nb.tolist(), direct.tolist()), strict=True))


def losses(probabilities: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Individual-vote nine-class Brier and log loss; only logs use clipping."""
    return np.stack(
        (
            (probabilities * probabilities).sum(axis=-1) - 2 * (probabilities * y).sum(axis=-1) + 1,
            -(y * np.log(np.clip(probabilities, CLIP, 1))).sum(axis=-1),
        ),
        axis=-1,
    )


AMENDMENT_SHA256 = "09ef671b841afb7d7b29e6ac6daa526b09beb369ce16a3b5ea38c56ac01612c4"
ALIASES = {"folk_country": "folkcountry", "funk_soul_rnb": "funksoulrnb", "rap_hiphop": "raphiphop"}


def settings(protocol_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind the immutable pre-acquisition protocol and transparent pre-fit parsing amendment."""
    amendment_path = protocol_path.with_name("source-serialization-amendment.json")
    spec, amendment = read(protocol_path), read(amendment_path)
    if (
        digest(protocol_path) != PROTOCOL_SHA256
        or digest(amendment_path) != AMENDMENT_SHA256
        or amendment["parent_protocol_sha256"] != PROTOCOL_SHA256
        or amendment["raw_to_protocol_class"] != ALIASES
    ):
        raise ValueError("Original protocol or source-serialization amendment differs")
    return spec, amendment


def bindings(files: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Hash all exact serialized local research stage files."""
    return {
        name: {
            "sha256": hashlib.sha256(file_bytes(name, value)).hexdigest(),
            "bytes": len(file_bytes(name, value)),
        }
        for name, value in files.items()
    }


def file_bytes(name: str, value: object) -> bytes:
    """Preserve the independently frozen identity serialization; keep large outputs compact."""
    if name == "cohort.json":
        return (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()
    return encoded(value)


def check_inventory(directory: Path, names: set[str]) -> None:
    """Reject changed inventories, symlinks and combined resource overflow."""
    if (
        any(p.is_symlink() for p in (directory, *directory.parents))
        or {p.name for p in directory.iterdir()} != names
    ):
        raise ValueError("Research stage inventory differs")
    total = 0
    for name in names:
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Research stage file differs")
        total += path.stat().st_size
    if total > MAX_BYTES:
        raise ValueError("Combined research stage byte guard exceeded")


def check_file_bindings(directory: Path, names: set[str], expected: dict[str, Any]) -> None:
    """Check actual physical bytes before parsing or semantic replay."""
    if set(expected) != names:
        raise ValueError("Stage file binding inventory differs")
    for name in names:
        path = directory / name
        if (
            path.stat().st_size != expected[name]["bytes"]
            or digest(path) != expected[name]["sha256"]
        ):
            raise ValueError("Physical stage file bytes differ from external seal")


def prepare(protocol_path: Path, receipt_path: Path, receipt_pin: str, output: Path) -> str:
    """Seal the complete identity-only cohort before interpreting human target cells."""
    destination(output, (protocol_path, receipt_path))
    _, amendment = settings(protocol_path)
    metadata_path, human_path = sources(protocol_path, receipt_path, receipt_pin)
    identities = cohort(
        native.join(
            native.parse(metadata_path, human=False, identity_only=True),
            native.parse(human_path, human=True, identity_only=True),
        )
    )
    cohort_pin = hashlib.sha256(file_bytes("cohort.json", identities)).hexdigest()
    if cohort_pin != amendment["identity_cohort_sha256"]:
        raise ValueError("Native cohort differs from independent pre-fit identity seal")
    seal = {
        "revision": "jamendo-human-genre-identity-v1",
        "protocol": str(protocol_path.resolve()),
        "protocol_sha256": PROTOCOL_SHA256,
        "amendment_sha256": AMENDMENT_SHA256,
        "receipt": str(receipt_path.resolve()),
        "receipt_sha256": receipt_pin,
        "cohort_sha256": cohort_pin,
        "runtime": runtime(),
        "labels_interpreted": False,
        **RIGHTS,
    }
    return publish(
        output,
        {"cohort.json": identities, "seal.json": seal},
        (protocol_path, receipt_path, metadata_path, human_path),
    )


def load_identity(
    prepared: Path, seal_pin: str
) -> tuple[dict[str, Any], list[dict[str, Any]], Path, Path]:
    """Replay native identities and seals before any target interpretation or numerical fit."""
    check_inventory(prepared, {"cohort.json", "seal.json"})
    seal = read(prepared / "seal.json")
    if (
        digest(prepared / "seal.json") != seal_pin
        or seal["revision"] != "jamendo-human-genre-identity-v1"
        or seal["runtime"] != runtime()
        or seal["labels_interpreted"] is not False
        or seal["amendment_sha256"] != AMENDMENT_SHA256
        or seal["protocol_sha256"] != PROTOCOL_SHA256
        or any(seal[k] != v for k, v in RIGHTS.items())
    ):
        raise ValueError("Prepared identity, rights or implementation seal differs")
    _, amendment = settings(Path(seal["protocol"]))
    metadata_path, human_path = sources(
        Path(seal["protocol"]), Path(seal["receipt"]), seal["receipt_sha256"]
    )
    identities = cohort(
        native.join(
            native.parse(metadata_path, human=False, identity_only=True),
            native.parse(human_path, human=True, identity_only=True),
        )
    )
    if (
        digest(prepared / "cohort.json") != seal["cohort_sha256"]
        or seal["cohort_sha256"] != amendment["identity_cohort_sha256"]
        or identities != read(prepared / "cohort.json")
    ):
        raise ValueError("Complete native identity cohort differs")
    return seal, identities, metadata_path, human_path


def parse_targets(
    path: Path,
) -> tuple[list[native.Observation], dict[int, tuple[str, ...] | None], dict[int, str | None]]:
    """Interpret only the fixed target cell, retaining raw and exactly amended tokens separately."""
    identities = native.parse(path, human=True, identity_only=True)
    raw_votes: dict[int, tuple[str, ...] | None] = {}
    payloads: dict[int, str | None] = {}
    observations = []
    with path.open("rb") as stream:
        stream.readline(native.MAX_LINE + 1)
        for line in stream:
            if len(line) > native.MAX_LINE:
                raise ValueError("Target TSV line bound exceeded")
            fields = line.decode().rstrip("\r\n").split("\t")
            identity = native._identity(fields)  # noqa: SLF001 - reuse unchanged exact native identity checks.
            cells = [
                s.removeprefix("genre_dortmund---")
                for s in fields[5:]
                if s.startswith("genre_dortmund---")
            ]
            if len(cells) > 1:
                raise ValueError("Duplicate genre_dortmund target cell")
            payload = cells[0] if cells else None
            raw = tuple(payload.split(",")) if payload else None
            canonical = tuple(ALIASES.get(t, t) for t in raw) if raw else None
            valid_raw = (set(CLASSES) - set(ALIASES.values())) | set(ALIASES)
            observations.append(
                GenreObservation(
                    *identity,
                    votes=canonical,
                    invalid_raw_vote=any(t not in valid_raw for t in raw or ()),
                )
            )
            raw_votes[identity[0]], payloads[identity[0]] = raw, payload
    if [r.identity for r in sorted(observations, key=lambda r: r.track_id)] != [
        r.identity for r in identities
    ]:
        raise ValueError("Human target parsing changed native identities")
    return observations, raw_votes, payloads


def dataset(
    prepared: Path, seal_pin: str
) -> tuple[list[native.Observation], list[dict[str, Any]], dict[int, Any]]:
    """Read permitted features and one target only after full identity-only replay succeeds."""
    _, identities, metadata_path, human_path = load_identity(prepared, seal_pin)
    metadata = native.parse(metadata_path, human=False, identity_only=False)
    human, raw, payloads = parse_targets(human_path)
    joined = native.join(metadata, human)
    invalid = {r.track_id for r in human if isinstance(r, GenreObservation) and r.invalid_raw_vote}
    rows: list[native.Observation] = [
        GenreObservation(*r.identity, r.tags, r.votes, r.track_id in invalid) for r in joined
    ]
    human_ids = {r.track_id for r in human}
    info = {
        r.track_id: {
            "human_row_present": r.track_id in human_ids,
            "invalid_raw_vote": r.track_id in invalid,
            "raw_votes": list(raw[r.track_id] or ()) if raw.get(r.track_id) else None,
            "raw_target_payload": payloads.get(r.track_id),
            "taxonomy_nominated": bool(payloads.get(r.track_id)),
        }
        for r in rows
    }
    return rows, identities, info


def census_report(
    rows: list[native.Observation], identities: list[dict[str, Any]], info: dict[int, Any]
) -> dict[str, Any]:
    """Count support before fitting; heldout class support is descriptive and never a fit gate."""
    groups = {r["track_id"]: r["component_id"] for r in identities}
    eligible = [r for r in rows if vote_reason(r) is None]
    passes = (
        len(eligible) >= MIN_TRACKS
        and len({groups[r.track_id] for r in eligible}) >= MIN_COMPONENTS
    )
    folds = []
    for outer in range(FOLDS):
        train = [r for r in eligible if fold(groups[r.track_id]) != outer]
        query = [r for r in eligible if fold(groups[r.track_id]) == outer]
        support = class_components(train, groups)
        folds.append(
            {
                "fold": outer,
                "training_tracks": len(train),
                "training_components": len({groups[r.track_id] for r in train}),
                "training_class_components": support,
                "training_class_votes": [
                    sum((r.votes or ()).count(c) for r in train) for c in CLASSES
                ],
                "query_eligible_tracks": len(query),
                "query_eligible_components": len({groups[r.track_id] for r in query}),
                "query_class_components": class_components(query, groups),
                "query_class_votes": [
                    sum((r.votes or ()).count(c) for r in query) for c in CLASSES
                ],
                "fit_gate": passes and all(n >= MIN_CLASS_COMPONENTS for n in support),
            }
        )
    return {
        "revision": "jamendo-human-genre-support-v1",
        "classes": list(CLASSES),
        "metadata_tracks": len(rows),
        "metadata_components": len(set(groups.values())),
        "taxonomy_nominations": sum(v["taxonomy_nominated"] for v in info.values()),
        "human_rows_missing": sum(not v["human_row_present"] for v in info.values()),
        "empty_target_cells": sum(v["raw_target_payload"] == "" for v in info.values()),
        "eligible_tracks": len(eligible),
        "eligible_components": len({groups[r.track_id] for r in eligible}),
        "disagreements": sum(len(set(r.votes or ())) > 1 for r in eligible),
        "target_outcomes": dict(Counter(vote_reason(r) or "eligible" for r in rows)),
        "global_support_passes": passes,
        "folds": folds,
        **RIGHTS,
    }


def census(prepared: Path, seal_pin: str, output: Path) -> str:
    """Publish the corrected availability/support census before authorizing numerical evaluation."""
    destination(output, (prepared,))
    rows, identities, info = dataset(prepared, seal_pin)
    report = census_report(rows, identities, info)
    seal = {
        "revision": "jamendo-human-genre-census-seal-v1",
        "identity_seal_sha256": seal_pin,
        "protocol_sha256": PROTOCOL_SHA256,
        "amendment_sha256": AMENDMENT_SHA256,
        "files": bindings({"census.json": report}),
        "runtime": runtime(),
        "fits": 0,
        **RIGHTS,
    }
    return publish(output, {"census.json": report, "seal.json": seal}, (prepared,))


def load_census(
    prepared: Path, identity_pin: str, directory: Path, census_pin: str
) -> tuple[list[native.Observation], list[dict[str, Any]], dict[int, Any], dict[str, Any]]:
    """Require the externally pinned no-fit census and reproduce it before fitting."""
    check_inventory(directory, {"census.json", "seal.json"})
    seal = read(directory / "seal.json")
    if digest(directory / "seal.json") != census_pin:
        raise ValueError("Census external pin differs")
    check_file_bindings(directory, {"census.json"}, seal["files"])
    report = read(directory / "census.json")
    if (
        seal["revision"] != "jamendo-human-genre-census-seal-v1"
        or digest(directory / "seal.json") != census_pin
        or seal["identity_seal_sha256"] != identity_pin
        or seal["runtime"] != runtime()
        or seal["fits"] != 0
        or seal["protocol_sha256"] != PROTOCOL_SHA256
        or seal["amendment_sha256"] != AMENDMENT_SHA256
        or seal["files"] != bindings({"census.json": report})
        or any(seal[k] != v for k, v in RIGHTS.items())
    ):
        raise ValueError("Pre-fit support census seal differs")
    rows, identities, info = dataset(prepared, identity_pin)
    if report != census_report(rows, identities, info):
        raise ValueError("Pre-fit corrected support census differs")
    return rows, identities, info, report


def predictions(
    rows: list[native.Observation],
    identities: list[dict[str, Any]],
    info: dict[int, Any],
    support: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fit each training fold once and predict all heldout metadata without query-label gates."""
    groups = {r["track_id"]: r["component_id"] for r in identities}
    by_id = {r.track_id: r for r in rows}
    models, by_fold = [], {}
    for outer in range(FOLDS):
        train = [r for r in rows if fold(groups[r.track_id]) != outer and vote_reason(r) is None]
        counts = class_components(train, groups)
        allowed = support["global_support_passes"] and all(
            n >= MIN_CLASS_COMPONENTS for n in counts
        )
        if allowed != support["folds"][outer]["fit_gate"]:
            raise ValueError("Training-only class gate differs from pre-fit census")
        model = fit(train, groups) if allowed else None
        by_fold[outer] = model
        models.append(
            {
                "fold": outer,
                "reason": None
                if allowed
                else "insufficient_training_class_support"
                if support["global_support_passes"]
                else "global_feasibility_support_failed",
                "training_track_ids": [r.track_id for r in train],
                "training_components": sorted({groups[r.track_id] for r in train}),
                "training_class_components": counts,
                "model": model,
            }
        )
    records = []
    for identity in identities:
        row = by_id[identity["track_id"]]
        outer = identity["fold"]
        model = by_fold[outer]
        reason = vote_reason(row)
        records.append(
            {
                **identity,
                **info[row.track_id],
                "canonical_votes": list(row.votes) if row.votes else None,
                "target_reason": reason,
                "target": target(row).tolist() if reason is None else None,
                "prediction_reason": models[outer]["reason"],
                "methods": predict(model, row) if model is not None else None,
                "scored": reason is None and model is not None,
            }
        )
    return records, models


def bootstrap(sums: np.ndarray, counts: np.ndarray) -> dict[str, Any]:
    """Use fixed paired component resamples for all methods and both weighting scopes."""
    pairs = ((1, 0), (1, 2), (2, 0))
    names = ("component_equal", "track_weighted")
    metrics = ("vote_brier", "fractional_log_loss")
    if not len(counts):
        return {
            "draws": 2000,
            "valid_draws": 0,
            "comparisons": {
                f"{METHODS[a]}-minus-{METHODS[b]}": {
                    s: {m: {"difference": None, "interval": None} for m in metrics} for s in names
                }
                for a, b in pairs
            },
        }
    point = np.stack(((sums / counts[:, None, None]).mean(axis=0), sums.sum(axis=0) / counts.sum()))
    rng = np.random.default_rng(20261019)
    samples = np.empty((2000, 2, len(METHODS), 2))
    means = sums / counts[:, None, None]
    for draw in range(2000):
        chosen = rng.integers(0, len(counts), size=len(counts))
        samples[draw, 0] = means[chosen].mean(axis=0)
        samples[draw, 1] = sums[chosen].sum(axis=0) / counts[chosen].sum()
    return {
        "draws": 2000,
        "valid_draws": 2000,
        "comparisons": {
            f"{METHODS[a]}-minus-{METHODS[b]}": {
                scope: {
                    metric: {
                        "difference": float(point[i, a, j] - point[i, b, j]),
                        "interval": np.quantile(
                            samples[:, i, a, j] - samples[:, i, b, j], [0.025, 0.975]
                        ).tolist(),
                    }
                    for j, metric in enumerate(metrics)
                }
                for i, scope in enumerate(names)
            }
            for a, b in pairs
        },
    }


def evaluation(records: list[dict[str, Any]], support: dict[str, Any]) -> dict[str, Any]:
    """Score only eligible shared predictions; retain complete availability and clipping counts."""
    scored = [r for r in records if r["scored"]]
    groups = sorted({r["component_id"] for r in scored})
    counts = np.array([sum(r["component_id"] == g for r in scored) for g in groups], dtype=float)
    sums = np.zeros((len(groups), len(METHODS), 2))
    group_index = {g: i for i, g in enumerate(groups)}
    clipping = {m: {"positive_target_class_cells": 0, "tracks": 0} for m in METHODS}
    class_sums = np.zeros((len(groups), len(METHODS), len(CLASSES)))
    for row in scored:
        y = np.array(row["target"])
        p = np.array([row["methods"][m] for m in METHODS])
        index = group_index[row["component_id"]]
        sums[index] += losses(p, y)
        class_sums[index] += p * p - 2 * p * y + y
        clipped = (p < CLIP) & (y > 0)
        for i, method in enumerate(METHODS):
            clipping[method]["positive_target_class_cells"] += int(clipped[i].sum())
            clipping[method]["tracks"] += int(clipped[i].any())
    component = (sums / counts[:, None, None]).mean(axis=0) if groups else None
    tracks = sums.sum(axis=0) / counts.sum() if groups else None
    class_means = (class_sums / counts[:, None, None]).mean(axis=0) if groups else None
    per_class = []
    for c, name in enumerate(CLASSES):
        positive = [r for r in scored if r["target"][c] > 0]
        per_class.append(
            {
                "class": name,
                "scored_positive_tracks": len(positive),
                "scored_positive_components": len({r["component_id"] for r in positive}),
                "scored_positive_votes": sum(
                    (r["canonical_votes"] or []).count(name) for r in positive
                ),
                "component_equal_ovr_vote_brier": {
                    m: float(class_means[i, c]) if positive and class_means is not None else None
                    for i, m in enumerate(METHODS)
                },
            }
        )
    return {
        "revision": "jamendo-human-genre-evaluation-v1",
        "protocol_sha256": PROTOCOL_SHA256,
        "amendment_sha256": AMENDMENT_SHA256,
        "support": support,
        "counts": {
            "metadata_tracks": len(records),
            "metadata_components": len({r["component_id"] for r in records}),
            "taxonomy_nominations": sum(r["taxonomy_nominated"] for r in records),
            "eligible_tracks": sum(r["target_reason"] is None for r in records),
            "predicted_tracks": sum(r["methods"] is not None for r in records),
            "predicted_components": len(
                {r["component_id"] for r in records if r["methods"] is not None}
            ),
            "scored_tracks": len(scored),
            "scored_components": len(groups),
            "prediction_abstentions": dict(
                Counter(
                    r["prediction_reason"] for r in records if r["prediction_reason"] is not None
                )
            ),
            "target_outcomes": dict(Counter(r["target_reason"] or "eligible" for r in records)),
        },
        "scores": {
            m: {
                "component_equal_vote_brier": float(component[i, 0])
                if component is not None
                else None,
                "component_equal_fractional_log_loss": float(component[i, 1])
                if component is not None
                else None,
                "track_weighted_vote_brier": float(tracks[i, 0]) if tracks is not None else None,
                "track_weighted_fractional_log_loss": float(tracks[i, 1])
                if tracks is not None
                else None,
            }
            for i, m in enumerate(METHODS)
        },
        "log_loss_clipping": clipping,
        "per_class": per_class,
        "bootstrap": bootstrap(sums, counts),
        "interpretation": (
            "Fixed historical cohort and predictions; no population significance, "
            "fresh cohort confirmation, calibration, retrieval usefulness "
            "or EveryNoise parity claim"
        ),
        **RIGHTS,
    }


def evaluate(
    prepared: Path, identity_pin: str, census_directory: Path, census_pin: str, output: Path
) -> str:
    """Execute the unchanged model plan only after the separately sealed pre-fit census."""
    destination(output, (prepared, census_directory))
    rows, identities, info, support = load_census(
        prepared, identity_pin, census_directory, census_pin
    )
    records, models = predictions(rows, identities, info, support)
    files = {
        "predictions.json": records,
        "models.json": models,
        "evaluation.json": evaluation(records, support),
    }
    receipt = {
        "revision": "jamendo-human-genre-result-v1",
        "identity_seal_sha256": identity_pin,
        "census_seal_sha256": census_pin,
        "protocol_sha256": PROTOCOL_SHA256,
        "amendment_sha256": AMENDMENT_SHA256,
        "runtime": runtime(),
        "files": bindings(files),
        **RIGHTS,
    }
    return publish(output, {**files, "receipt.json": receipt}, (prepared, census_directory))


def replay(  # noqa: PLR0913, PLR0917 - three externally pinned research stages.
    prepared: Path,
    identity_pin: str,
    census_directory: Path,
    census_pin: str,
    output: Path,
    result_pin: str,
) -> dict[str, Any]:
    """Reproduce all local predictions, models, proper scores and bootstrap under external pins."""
    check_inventory(output, {"predictions.json", "models.json", "evaluation.json", "receipt.json"})
    receipt = read(output / "receipt.json")
    if digest(output / "receipt.json") != result_pin:
        raise ValueError("Result external pin differs")
    check_file_bindings(
        output, {"predictions.json", "models.json", "evaluation.json"}, receipt["files"]
    )
    files = {
        name: read(output / name) for name in ("predictions.json", "models.json", "evaluation.json")
    }
    if (
        digest(output / "receipt.json") != result_pin
        or receipt["revision"] != "jamendo-human-genre-result-v1"
        or receipt["identity_seal_sha256"] != identity_pin
        or receipt["census_seal_sha256"] != census_pin
        or receipt["protocol_sha256"] != PROTOCOL_SHA256
        or receipt["amendment_sha256"] != AMENDMENT_SHA256
        or receipt["runtime"] != runtime()
        or receipt["files"] != bindings(files)
        or any(receipt[k] != v for k, v in RIGHTS.items())
    ):
        raise ValueError("Result inventory, runtime, rights or external pins differ")
    rows, identities, info, support = load_census(
        prepared, identity_pin, census_directory, census_pin
    )
    records, models = predictions(rows, identities, info, support)
    report = evaluation(records, support)
    if files != {"predictions.json": records, "models.json": models, "evaluation.json": report}:
        raise ValueError("Numerical model/prediction/evaluation replay differs")
    return report
