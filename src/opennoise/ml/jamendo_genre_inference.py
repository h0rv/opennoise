# ruff: noqa: PLR2004 -- frozen native schemas and bounds.
"""Source-free inference on explicitly caller-supplied historical genre-tag profiles."""

from __future__ import annotations

import hashlib
import json
import math
import platform
import re
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import numpy as np
from scipy.special import logsumexp

CONTRACT = "41ea14ecdfe9136a6134821abae789b03e81c9bfd9958bad3680c6b9ca4ca634"
REVISION = "jamendo-genre-profile-capsule-v1"
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
METHODS = ("training_human_prior", "genre_instrument_nb", "mapped_uploader_genre", "temperature_nb")
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
RIGHTS = {
    "source_license": "CC-BY-NC-SA-4.0",
    "research_only": True,
    "attribution": (
        "Music Technology Group; Bogdanov, Won, Tovstogan, Porter and Serra (2019), "
        "The MTG-Jamendo Dataset for Automatic Music Tagging; "
        "Music Classification Annotations documentation"
    ),
}
SOURCE = {
    "metadata_sha256": ("c80e43416e89afc0b2656848e9d4d6f076ca0426003d7e0148ac8cdc6254d366"),
    "outer_models_sha256": ("d13b4e8e807e703e9fdb71634ff00bfa6de78993dbeeb378153eb26f2c1a4208"),
    "selected_models_sha256": ("7b199721a01cc81f1c972d2b2a227586cd59e76f14078b2495aa1ccd0d318206"),
    "temperature_protocol_sha256": (
        "012af3ed3453c5157d3a5bce79323bdb086da2d8b18a594bca8c76e981b74eff"
    ),
    "original_protocol_sha256": (
        "994399146138008c4329946315d9ac8f7b78021c03dbf2bd87fa515fcf83796b"
    ),
    "serialization_amendment_sha256": (
        "09ef671b841afb7d7b29e6ac6daa526b09beb369ce16a3b5ea38c56ac01612c4"
    ),
    "source_commit": "cafd8e20c265ed84f1e61f1c875327971f43a62f",
}
FILES = {"models.json", "routing.json"}
CAPSULE_BYTES = 1_000_000
IO_BYTES = 2_000_000
MAX_PROFILES = 100
MAX_TAGS = 250
TAG = re.compile(r"(genre|instrument)---[a-z0-9]{1,64}")
HASH = re.compile(r"[0-9a-f]{64}")


def encoded(value: object) -> bytes:
    """Encode finite deterministic research JSON."""
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def sha(path: Path) -> str:
    """Hash bytes without interpreting payloads."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe(path: Path) -> None:
    """Reject indirection at the local artifact boundary."""
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Symlink artifact path")


def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate JSON object keys instead of silently taking the last value."""
    result: dict[str, Any] = {}
    for key, value in values:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def read(path: Path, limit: int, pin: str | None = None) -> Any:  # noqa: ANN401 - strict validators follow this JSON boundary.
    """Check physical bounds and optional external pin before interpreting JSON."""
    safe(path)
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError("Bounded regular JSON required")
    raw = path.read_bytes()
    if pin is not None and (not HASH.fullmatch(pin) or hashlib.sha256(raw).hexdigest() != pin):
        raise ValueError("External artifact pin differs")
    return json.loads(raw, object_pairs_hook=pairs)


def fresh(output: Path, inputs: tuple[Path, ...]) -> None:
    """Require a fresh output outside every declared input."""
    safe(output)
    if output.exists() or any(
        output.resolve().is_relative_to(p.resolve()) or p.resolve().is_relative_to(output.resolve())
        for p in inputs
    ):
        raise ValueError("Fresh non-overlapping output required")


def runtime() -> dict[str, Any]:
    """Pin only pure inference, CLI and numerical runtime, never import training code."""
    script = Path(__file__).resolve().parents[3] / "scripts/run_jamendo_genre_capsule.py"
    return {
        "python": platform.python_version(),
        "numpy": version("numpy"),
        "scipy": version("scipy"),
        "code": {p.name: sha(p) for p in (Path(__file__), script)},
    }


def positive(value: object) -> bool:
    """Require a positive native uint32 integer, excluding coercible lookalikes."""
    return type(value) is int and 0 < value <= 2**32 - 1


def fold(component: int) -> int:
    """Route only by the unchanged original native component hash."""
    return (
        int.from_bytes(
            hashlib.sha256(
                f"opennoise-jamendo-human-genre-dortmund-v1|{component}".encode()
            ).digest(),
            "big",
        )
        % 5
    )


def number(value: object) -> bool:
    """Require a finite real probability strictly inside zero and one."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0 < value < 1
    )


def validate_models(body: dict[str, Any]) -> list[dict[str, Any]]:  # noqa: C901 - closed model boundary.
    """Reject changed classes, literal mapping, dimensions, weights and fallback semantics."""
    if (
        not isinstance(body, dict)
        or set(body) != {"classes", "mapping", "folds"}
        or body["classes"] != list(CLASSES)
        or body["mapping"] != [list(t) for t in MAPPING]
        or not isinstance(body["folds"], list)
        or len(body["folds"]) != 5
    ):
        raise ValueError("Frozen model schema differs")
    for i, row in enumerate(body["folds"]):
        if (
            not isinstance(row, dict)
            or set(row) != {"fold", "model", "temperature", "temperature_reason", "model_reason"}
            or type(row["fold"]) is not int
            or row["fold"] != i
            or type(row["temperature"]) is not int
            or row["temperature"] not in (1, 2, 4, 8)
        ):
            raise ValueError("Outer model or selected temperature differs")
        reason = row["temperature_reason"]
        if reason not in (
            None,
            "inner_training_class_support_failed",
            "incomplete_inner_oof_coverage",
            "original_outer_abstention",
        ) or (reason is not None and row["temperature"] != 1):
            raise ValueError("Temperature fallback differs")
        model = row["model"]
        if model is None:
            if (
                row["model_reason"]
                not in ("insufficient_training_class_support", "global_feasibility_support_failed")
                or reason != "original_outer_abstention"
            ):
                raise ValueError("Original unavailable model reason differs")
            continue
        if (
            row["model_reason"] is not None
            or reason == "original_outer_abstention"
            or not isinstance(model, dict)
            or set(model) != {"prior", "vocabulary", "theta"}
        ):
            raise ValueError("Model fields differ")
        vocab, prior, theta = model["vocabulary"], model["prior"], model["theta"]
        if (
            not isinstance(vocab, list)
            or len(vocab) > MAX_TAGS
            or any(not isinstance(t, str) or not TAG.fullmatch(t) for t in vocab)
            or vocab != sorted(set(vocab))
        ):
            raise ValueError("Model vocabulary differs")
        if (
            not isinstance(prior, list)
            or len(prior) != len(CLASSES)
            or not all(number(v) for v in prior)
            or not math.isclose(sum(prior), 1, rel_tol=0, abs_tol=1e-12)
        ):
            raise ValueError("Model prior differs")
        if (
            not isinstance(theta, list)
            or len(theta) != len(CLASSES)
            or any(
                not isinstance(r, list) or len(r) != len(vocab) or not all(number(v) for v in r)
                for r in theta
            )
        ):
            raise ValueError("Model theta dimensions or probability differs")
    return body["folds"]


@dataclass(frozen=True)
class Capsule:
    """Validated frozen parameters and exact context maps; contains no recording profiles."""

    manifest: dict[str, Any]
    pin: str
    models: list[dict[str, Any]]
    artists: dict[int, tuple[int, int]]
    albums: dict[int, tuple[int, int]]
    observed: set[tuple[int, int]]


def routing(
    body: dict[str, Any],
) -> tuple[dict[int, tuple[int, int]], dict[int, tuple[int, int]], set[tuple[int, int]]]:
    """Validate native identity/fold joins and retain only actually observed pairs."""
    if (
        not isinstance(body, dict)
        or set(body) != {"pairs"}
        or not isinstance(body["pairs"], list)
        or not 1 <= len(body["pairs"]) <= 15_000
    ):
        raise ValueError("Routing schema or bounds differ")
    artists: dict[int, tuple[int, int]] = {}
    albums: dict[int, tuple[int, int]] = {}
    observed: set[tuple[int, int]] = set()
    previous = None
    for row in body["pairs"]:
        if (
            not isinstance(row, list)
            or len(row) != 4
            or not all(positive(v) for v in row[:3])
            or type(row[3]) is not int
            or row[3] != fold(row[2])
        ):
            raise ValueError("Native context or fold differs")
        a, b, component, outer = row
        pair = (a, b)
        if previous is not None and pair <= previous:
            raise ValueError("Duplicate or unsorted observed context")
        previous = pair
        context = (component, outer)
        if artists.setdefault(a, context) != context or albums.setdefault(b, context) != context:
            raise ValueError("Native component identity conflicts")
        observed.add(pair)
    return artists, albums, observed


def load(directory: Path, pin: str) -> Capsule:  # noqa: C901, PLR0912 - closed artifact/provenance boundary.
    """Load only closed, pinned, semantically validated inference payloads."""
    safe(directory)
    if {p.name for p in directory.iterdir()} != FILES | {"manifest.json"}:
        raise ValueError("Capsule inventory differs")
    total = 0
    for name in FILES | {"manifest.json"}:
        p = directory / name
        safe(p)
        if not p.is_file():
            raise ValueError("Regular capsule payload required")
        total += p.stat().st_size
    if total > CAPSULE_BYTES:
        raise ValueError("Capsule byte cap exceeded")
    manifest = read(directory / "manifest.json", CAPSULE_BYTES, pin)
    if (
        not isinstance(manifest, dict)
        or set(manifest)
        != {
            "revision",
            "contract_sha256",
            "source",
            "runtime",
            "builder",
            "rights",
            "counts",
            "files",
        }
        or manifest["revision"] != REVISION
        or manifest["contract_sha256"] != CONTRACT
        or manifest["runtime"] != runtime()
        or manifest["rights"] != RIGHTS
        or manifest["rights"].get("research_only") is not True
    ):
        raise ValueError("Capsule revision, contract, rights or runtime differs")
    source = manifest["source"]
    if (
        not isinstance(source, dict)
        or set(source)
        != set(SOURCE) | {"study_receipt_sha256", "study_inputs", "inner_census_sha256"}
        or any(source[k] != v for k, v in SOURCE.items())
        or not isinstance(source["study_receipt_sha256"], str)
        or not HASH.fullmatch(source["study_receipt_sha256"])
    ):
        raise ValueError("Source provenance differs")
    provenance = source["study_inputs"]
    if (
        not isinstance(provenance, dict)
        or set(provenance) != {"protocol", "identity_seal", "census_seal", "result_receipt"}
        or any(not isinstance(v, str) or not HASH.fullmatch(v) for v in provenance.values())
        or provenance["protocol"] != SOURCE["temperature_protocol_sha256"]
        or not isinstance(source["inner_census_sha256"], str)
        or not HASH.fullmatch(source["inner_census_sha256"])
    ):
        raise ValueError("Study source/census provenance differs")
    builder = manifest["builder"]
    if (
        not isinstance(builder, dict)
        or set(builder) != {"jamendo_genre_capsule.py", "jamendo_human_mood.py"}
        or any(not isinstance(v, str) or not HASH.fullmatch(v) for v in builder.values())
        or builder["jamendo_human_mood.py"]
        != "9848cd3a855e8b40018c50e949d3d38b6aad533c2323f8d68a7419cd5a5002e9"
    ):
        raise ValueError("Builder provenance differs")
    if not isinstance(manifest["files"], dict) or set(manifest["files"]) != FILES:
        raise ValueError("Capsule binding inventory differs")
    for name in FILES:
        p = directory / name
        binding = manifest["files"][name]
        if (
            not isinstance(binding, dict)
            or set(binding) != {"bytes", "sha256"}
            or type(binding["bytes"]) is not int
        ):
            raise ValueError("Strict physical binding schema differs")
        if binding != {"sha256": sha(p), "bytes": p.stat().st_size}:
            raise ValueError("Capsule physical payload differs")
    models = validate_models(read(directory / "models.json", CAPSULE_BYTES))
    artists, albums, observed = routing(read(directory / "routing.json", CAPSULE_BYTES))
    counts = {
        "artists": len(artists),
        "albums": len(albums),
        "pairs": len(observed),
        "components": len({c for c, _ in artists.values()}),
    }
    if (
        not isinstance(manifest["counts"], dict)
        or any(type(v) is not int for v in manifest["counts"].values())
        or manifest["counts"] != counts
        or counts != {"artists": 713, "albums": 2365, "pairs": 2365, "components": 713}
    ):
        raise ValueError("Complete native context census differs")
    return Capsule(manifest, pin, models, artists, albums, observed)


def probabilities(
    model: dict[str, Any], tags: set[str], temperature: int
) -> dict[str, list[float]]:
    """Calculate original presence/absence estimates from NEW caller tags, without fitting."""
    x = np.array([t in tags for t in model["vocabulary"]], dtype=float)
    prior, theta = np.array(model["prior"]), np.array(model["theta"])
    logits = np.log(prior) + (np.log(theta) * x + np.log1p(-theta) * (1 - x)).sum(axis=1)
    nb = np.exp(logits - logsumexp(logits)) if model["vocabulary"] else prior.copy()
    matched = [i for i, tokens in enumerate(MAPPING) if any("genre---" + t in tags for t in tokens)]
    direct = np.zeros(len(CLASSES)) if matched else prior.copy()
    if matched:
        direct[matched] = 1 / len(matched)
    scaled = logits / temperature
    softened = nb if temperature == 1 else np.exp(scaled - logsumexp(scaled))
    return dict(
        zip(METHODS, (prior.tolist(), nb.tolist(), direct.tolist(), softened.tolist()), strict=True)
    )


def validate_request(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Reject malformed requests atomically, preserving ordered duplicates as requests."""
    if (
        not isinstance(body, dict)
        or set(body) != {"profiles"}
        or not isinstance(body["profiles"], list)
        or not 1 <= len(body["profiles"]) <= MAX_PROFILES
    ):
        raise ValueError("Request schema or profile cap differs")
    for row in body["profiles"]:
        if (
            not isinstance(row, dict)
            or set(row) != {"artist_id", "album_id", "tags"}
            or not positive(row["artist_id"])
            or not positive(row["album_id"])
        ):
            raise ValueError("Strict native context fields required")
        tags = row["tags"]
        if (
            not isinstance(tags, list)
            or len(tags) > MAX_TAGS
            or any(not isinstance(t, str) or not TAG.fullmatch(t) for t in tags)
            or len(set(tags)) != len(tags)
        ):
            raise ValueError("Unique canonical genre/instrument tags required")
    return body["profiles"]


def infer(capsule: Capsule, body: dict[str, Any]) -> dict[str, Any]:
    """Route exact observed contexts and compute caller-profile estimates only."""
    profiles = validate_request(body)
    results = []
    for i, row in enumerate(profiles):
        a, b = row["artist_id"], row["album_id"]
        artist, album = capsule.artists.get(a), capsule.albums.get(b)
        reason = (
            "unknown_artist"
            if artist is None
            else "unknown_album"
            if album is None
            else "conflicting_component"
            if artist != album
            else "unobserved_artist_album_pair"
            if (a, b) not in capsule.observed
            else None
        )
        result: dict[str, Any] = {
            "query_index": i,
            "artist_id": a,
            "album_id": b,
            "profile_sha256": hashlib.sha256(encoded(row)).hexdigest(),
            "status": reason,
            "component_id": None,
            "fold": None,
            "temperature": None,
            "temperature_reason": None,
            "model_reason": None,
            "recognized_nb_feature_count": None,
            "UNSEEN_BY_NB": None,
            "mapped_classes": None,
            "estimates": None,
        }
        if reason is None:
            if artist is None:
                raise ValueError("Missing validated artist context")
            component, outer = artist
            frame = capsule.models[outer]
            result.update(
                component_id=component,
                fold=outer,
                temperature=frame["temperature"],
                temperature_reason=frame["temperature_reason"],
                model_reason=frame["model_reason"],
                frame_sha256=hashlib.sha256(encoded(frame)).hexdigest(),
            )
            model = frame["model"]
            if model is None:
                result["status"] = "original_model_unavailable"
            else:
                tags = set(row["tags"])
                vocab = set(model["vocabulary"])
                result.update(
                    status="emitted",
                    recognized_nb_feature_count=len(tags & vocab),
                    UNSEEN_BY_NB=sorted(tags - vocab),
                    mapped_classes=[
                        CLASSES[j]
                        for j, tokens in enumerate(MAPPING)
                        if any("genre---" + t in tags for t in tokens)
                    ],
                    estimates=probabilities(model, tags, frame["temperature"]),
                )
        results.append(result)
    return {
        "revision": "jamendo-caller-profile-inference-v1",
        "capsule_sha256": capsule.pin,
        "contract_sha256": CONTRACT,
        "source": capsule.manifest["source"],
        "classes": list(CLASSES),
        "methods": list(METHODS),
        "input_provenance": (
            "caller-supplied tags/context; not verified recording observations or class memberships"
        ),
        "profiles": results,
        **RIGHTS,
    }


def infer_file(directory: Path, pin: str, query: Path, query_pin: str, output: Path) -> str:
    """Publish one fresh bounded result only after complete request and capsule validation."""
    fresh(output, (directory, query))
    capsule = load(directory, pin)
    result = infer(capsule, read(query, IO_BYTES, query_pin))
    result["request_sha256"] = query_pin
    raw = encoded(result)
    if len(raw) > IO_BYTES:
        raise ValueError("Result byte cap exceeded")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".genre-infer-", dir=output.parent) as temp:
        candidate = Path(temp) / "result.json"
        candidate.write_bytes(raw)
        candidate.rename(output)
    return sha(output)
