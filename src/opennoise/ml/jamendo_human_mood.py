"""Research-only, frozen human-vote diagnostic; never a serving or audio pipeline."""

from __future__ import annotations

import hashlib
import json
import platform
import re
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np
from scipy.special import expit

PROTOCOL_SHA256 = "8832fc5c34298073394ef5a6470f909a607575843211005febf3c202f63d12c0"
METHODS = ("human_prior", "genre_instrument_nb", "privileged_happy_tag")
FOLDS = 5
VOTES = 3
DRAWS = 2000
SEED = 20261017
MAX_OUTPUT_BYTES = 20000000
MAX_LINE = 65536
MAX_ROWS = 15000
MAX_FIELDS = 250
IDENTITY_FIELDS = 5


@dataclass(frozen=True)
class Observation:
    """One exact identity and only permitted source tags and target votes."""

    track_id: int
    artist_id: int
    album_id: int
    path: str
    duration: str
    tags: tuple[str, ...] = ()
    votes: tuple[str, ...] | None = None

    @property
    def identity(self) -> tuple[int, int, int, str, str]:
        """Identity comparison includes duration, never a predictive feature."""
        return self.track_id, self.artist_id, self.album_id, self.path, self.duration


def digest(path: Path) -> str:
    """Hash bounded local artifact bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def components(rows: list[Observation]) -> dict[int, int]:
    """Join artist and album identities over the entire nominated cohort."""
    by_track = {r.track_id: r for r in rows}
    if len(by_track) != len(rows) or len({r.path for r in rows}) != len(rows):
        raise ValueError("Duplicate native ID or path")
    parent = {r.track_id: r.track_id for r in rows}

    def root(identity: int) -> int:
        while parent[identity] != identity:
            parent[identity] = parent[parent[identity]]
            identity = parent[identity]
        return identity

    owners: dict[tuple[str, int], int] = {}
    for row in rows:
        for key in (("artist", row.artist_id), ("album", row.album_id)):
            old = owners.setdefault(key, row.track_id)
            a, b = root(old), root(row.track_id)
            parent[max(a, b)] = min(a, b)
    return {identity: root(identity) for identity in sorted(parent)}


def fold(component: int) -> int:
    """Assign immutable, label-blind component folds."""
    value = hashlib.sha256(f"opennoise-jamendo-human-happy-v1|{component}".encode()).digest()
    return int.from_bytes(value, "big") % FOLDS


def vote_reason(votes: tuple[str, ...] | None) -> str | None:
    """Retain missing, wrong-count and invalid-target reasons distinctly."""
    if votes is None or not votes:
        return "missing_votes"
    if len(votes) != VOTES:
        return "wrong_vote_count"
    if any(v not in {"happy", "not_happy"} for v in votes):
        return "invalid_vote"
    return None


def feature_tags(row: Observation) -> set[str]:
    """Exclude all mood/theme tags and all human labels from NB inputs."""
    return {t for t in row.tags if t.startswith(("genre---", "instrument---"))}


@dataclass
class BernoulliModel:
    """Fractional-vote Bernoulli NB with component-weighted training masses."""

    vocabulary: tuple[str, ...]
    prior: float
    happy: np.ndarray
    not_happy: np.ndarray


def fit(rows: list[Observation], groups: dict[int, int]) -> BernoulliModel | None:
    """Fit alpha1 presence and absence probabilities on eligible training rows only."""
    if not rows:
        return None
    if any(vote_reason(r.votes) is not None for r in rows):
        raise ValueError("Ineligible training vote sequence")
    counts = Counter(groups[r.track_id] for r in rows)
    weights = np.array([1.0 / counts[groups[r.track_id]] for r in rows])
    y = np.array([sum(v == "happy" for v in r.votes or ()) / VOTES for r in rows])
    observed = [feature_tags(r) for r in rows]
    frequency = Counter(tag for tags in observed for tag in tags)
    vocabulary = tuple(sorted(tag for tag, count in frequency.items() if count < len(rows)))
    x = np.array([[tag in tags for tag in vocabulary] for tags in observed], dtype=float)
    positive, negative = weights * y, weights * (1 - y)
    return BernoulliModel(
        vocabulary,
        float((1 + positive.sum()) / (2 + weights.sum())),
        (1 + positive @ x) / (2 + positive.sum()),
        (1 + negative @ x) / (2 + negative.sum()),
    )


def predict(model: BernoulliModel, row: Observation) -> list[float]:
    """Apply feature-only NB and a separately labelled privileged uploader-tag rule."""
    tags = feature_tags(row)
    x = np.array([tag in tags for tag in model.vocabulary], dtype=float)
    odds = np.log(model.prior / (1 - model.prior))
    odds += np.sum(x * np.log(model.happy / model.not_happy))
    odds += np.sum((1 - x) * np.log((1 - model.happy) / (1 - model.not_happy)))
    return [
        model.prior,
        float(expit(odds)),
        1.0 if "mood/theme---happy" in row.tags else model.prior,
    ]


def losses(probabilities: list[float], target: float) -> np.ndarray:
    """Individual-vote Brier differs from squared error against the vote mean."""
    p = np.asarray(probabilities)
    return np.column_stack((p * p - 2 * p * target + target, (p - target) ** 2))


def summarize(predictions: list[dict[str, Any]], nominated: int) -> dict[str, Any]:
    """Keep abstentions explicit; paired intervals condition on fixed OOF predictions."""
    eligible = [r for r in predictions if r["eligibility_reason"] is None]
    covered = [r for r in eligible if r["probabilities"] is not None]
    sums: dict[int, np.ndarray] = {}
    counts: Counter[int] = Counter()
    for row in covered:
        component = row["component_id"]
        sums.setdefault(component, np.zeros((len(METHODS), 2)))
        sums[component] += losses(row["probabilities"], row["happy_fraction"])
        counts[component] += 1
    # Include eligible-but-unpredicted components in draws; never silently remove them.
    identities = sorted({r["component_id"] for r in eligible})
    totals = np.array([sums.get(c, np.zeros((len(METHODS), 2))) for c in identities])
    sizes = np.array([counts[c] for c in identities])

    def metrics(indices: np.ndarray) -> np.ndarray:
        if not len(indices) or not sizes[indices].sum():
            return np.full((len(METHODS), 3), np.nan)
        valid = indices[sizes[indices] > 0]
        component = np.mean(totals[valid, :, 0] / sizes[valid, None], axis=0)
        track = totals[indices].sum(axis=0) / sizes[indices].sum()
        return np.column_stack((component, track))

    point = metrics(np.arange(len(identities)))
    rng = np.random.Generator(np.random.PCG64(SEED))
    samples = np.full((DRAWS, 3), np.nan)
    for draw in range(DRAWS):
        indices = rng.integers(0, len(identities), len(identities)) if identities else np.array([])
        current = metrics(indices)
        samples[draw] = current[1] - current[0]
    names = ("component_equal_vote_brier", "track_vote_brier", "track_mean_target_squared_error")
    result: dict[str, Any] = {
        "nominated": nominated,
        "eligible": len(eligible),
        "predicted": len(covered),
        "coverage_all_nominated": len(covered) / nominated if nominated else None,
        "coverage_eligible": len(covered) / len(eligible) if eligible else None,
        "eligible_components": len(identities),
        "predicted_components": len(counts),
        "undefined_reason": None if covered else "no_scored_eligible_queries",
        "methods": {},
        "nb_minus_prior": {},
        "bootstrap": {"draws": DRAWS, "seed": SEED, "conditional_fixed_predictions": True},
    }
    for i, method in enumerate(METHODS):
        result["methods"][method] = {
            name: float(point[i, j]) if np.isfinite(point[i, j]) else None
            for j, name in enumerate(names)
        }
    for j, name in enumerate(names):
        finite = samples[:, j][np.isfinite(samples[:, j])]
        delta = point[1, j] - point[0, j]
        result["nb_minus_prior"][name] = {
            "difference": float(delta) if np.isfinite(delta) else None,
            "interval": np.quantile(finite, [0.025, 0.975]).tolist() if len(finite) else None,
            "valid_draws": len(finite),
            "undefined_draws": DRAWS - len(finite),
        }
    return result


def _write(path: Path, value: object) -> None:
    content = (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()
    if len(content) > MAX_OUTPUT_BYTES:
        raise ValueError("Output byte guard exceeded")
    existing = sum(p.stat().st_size for p in path.parent.iterdir() if p.is_file() and p != path)
    if existing + len(content) > MAX_OUTPUT_BYTES:
        raise ValueError("Combined output byte guard exceeded")
    path.write_bytes(content)


def _versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        **{name: version(name) for name in ("numpy", "scipy")},
    }


def _code() -> dict[str, str]:
    root = Path(__file__).resolve().parents[3]
    names = ("src/opennoise/ml/jamendo_human_mood.py", "scripts/run_jamendo_human_mood.py")
    return {name: digest(root / name) for name in names}


def sources(protocol: Path, receipt: Path, receipt_sha256: str) -> tuple[Path, Path]:
    """Require official frozen blob identities and externally pinned acquisition receipt."""
    if digest(protocol) != PROTOCOL_SHA256 or digest(receipt) != receipt_sha256:
        raise ValueError("Protocol or acquisition receipt differs")
    spec, acquired = json.loads(protocol.read_text()), json.loads(receipt.read_text())
    if (
        acquired["protocol_sha256"] != PROTOCOL_SHA256
        or acquired["source_commit"] != spec["source_commit"]
        or len(acquired["requests"]) != len(spec["input_files"])
    ):
        raise ValueError("Source capture association differs")
    paths = []
    for expected, actual in zip(spec["input_files"], acquired["requests"], strict=True):
        path = Path(actual["local_path"])
        if path.is_symlink() or path.stat().st_size != expected["bytes"]:
            raise ValueError("Source length or file type differs")
        content = path.read_bytes()
        blob = hashlib.sha1(  # noqa: S324 - official Git blob identity, SHA256 also checked.
            f"blob {len(content)}\0".encode() + content
        ).hexdigest()
        if (
            actual["path"] != expected["path"]
            or actual["bytes"] != expected["bytes"]
            or actual["git_blob_sha1"] != expected["git_blob_sha1"]
            or blob != expected["git_blob_sha1"]
            or hashlib.sha256(content).hexdigest() != actual["sha256"]
        ):
            raise ValueError("Source content differs from published identities")
        paths.append(path)
    return paths[0], paths[1]


def _identity(fields: list[str]) -> tuple[int, int, int, str, str]:
    """Validate canonical IDs and their exact relative recording path."""
    identities = []
    for value, prefix in zip(fields[:3], ("track", "artist", "album"), strict=True):
        match = re.fullmatch(prefix + r"_([0-9]+)", value)
        if match is None or int(match[1]) <= 0:
            raise ValueError("Invalid positive native identity")
        identities.append(int(match[1]))
    match = re.fullmatch(r"([0-9]{2})/([0-9]+)\.mp3", fields[3])
    if match is None or int(match[2]) != identities[0] or int(match[1]) != identities[0] % 100:
        raise ValueError("Native path does not match track identity")
    try:
        duration = Decimal(fields[4])
    except InvalidOperation as error:
        raise ValueError("Invalid duration") from error
    if not duration.is_finite() or duration <= 0:
        raise ValueError("Invalid positive finite duration")
    return identities[0], identities[1], identities[2], fields[3], str(duration.normalize())


def parse(path: Path, *, human: bool, identity_only: bool) -> list[Observation]:
    """Bounded TSV parsing; identity phase never interprets any trailing label cells."""
    result = []
    expected = ["TRACK_ID", "ARTIST_ID", "ALBUM_ID", "PATH", "DURATION"]
    with path.open("rb") as stream:
        header = stream.readline(MAX_LINE + 1)
        if header.decode().rstrip("\r\n").split("\t") != [
            *expected,
            "ANNOTATIONS" if human else "TAGS",
        ]:
            raise ValueError("Unexpected official TSV header")
        for line in stream:
            if len(line) > MAX_LINE or len(result) >= MAX_ROWS:
                raise ValueError("TSV row/line guard exceeded")
            fields = line.decode("utf-8").rstrip("\r\n").split("\t")
            if not IDENTITY_FIELDS <= len(fields) <= MAX_FIELDS:
                raise ValueError("TSV field guard exceeded")
            identity = _identity(fields)
            tags, target = (), None
            if not identity_only:
                if human:
                    cells = [cell for cell in fields[5:] if cell.startswith("mood_happy---")]
                    if len(cells) > 1:
                        raise ValueError("Duplicate mood_happy target cell")
                    if cells:
                        target = tuple(cells[0].removeprefix("mood_happy---").split(","))
                else:
                    tags = tuple(sorted(set(fields[5:]) - {""}))
            result.append(Observation(*identity, tags, target))
    components(result)  # Duplicate aliases/paths fail even outside the joined cohort.
    return sorted(result, key=lambda r: r.track_id)


def join(metadata: list[Observation], annotations: list[Observation]) -> list[Observation]:
    """Use only metadata-nominated tracks; never replace absent human rows."""
    by_id = {r.track_id: r for r in annotations}
    result = []
    for row in metadata:
        human = by_id.get(row.track_id)
        if human is not None and row.identity != human.identity:
            raise ValueError("Joined native identity mismatch")
        result.append(
            Observation(*row.identity, row.tags, human.votes if human is not None else None)
        )
    return result


def _cohort(rows: list[Observation]) -> list[dict[str, Any]]:
    groups = components(rows)
    return [
        {
            "track_id": row.track_id,
            "artist_id": row.artist_id,
            "album_id": row.album_id,
            "path": row.path,
            "duration": row.duration,
            "component_id": groups[row.track_id],
            "fold": fold(groups[row.track_id]),
        }
        for row in rows
    ]


def prepare(protocol: Path, receipt: Path, receipt_sha256: str, output: Path) -> dict[str, Any]:
    """Persist identity-only cohort/folds and source/code seal before label interpretation."""
    if output.exists():
        raise ValueError("Fresh output directory required")
    metadata, human = sources(protocol, receipt, receipt_sha256)
    cohort = _cohort(
        join(
            parse(metadata, human=False, identity_only=True),
            parse(human, human=True, identity_only=True),
        )
    )
    output.mkdir(parents=True)
    _write(output / "cohort.json", cohort)
    seal = {
        "revision": "jamendo-human-happy-identity-seal-v1",
        "protocol": str(protocol.resolve()),
        "protocol_sha256": PROTOCOL_SHA256,
        "receipt": str(receipt.resolve()),
        "receipt_sha256": receipt_sha256,
        "cohort_sha256": digest(output / "cohort.json"),
        "code": _code(),
        "versions": _versions(),
        "labels_interpreted": False,
        "research_only": True,
        "source_license": "CC-BY-NC-SA-4.0",
        "attribution": "MTG-Jamendo Dataset; existing human music-classification annotations",
    }
    _write(output / "seal.json", seal)
    return seal


def _load(prepared: Path, seal_sha256: str) -> list[Observation]:
    if digest(prepared / "seal.json") != seal_sha256:
        raise ValueError("Identity seal differs")
    seal = json.loads((prepared / "seal.json").read_text())
    if (
        seal["code"] != _code()
        or seal["versions"] != _versions()
        or seal["labels_interpreted"] is not False
        or digest(prepared / "cohort.json") != seal["cohort_sha256"]
        or {p.name for p in prepared.iterdir()} != {"cohort.json", "seal.json"}
    ):
        raise ValueError("Prepared identities or implementation changed")
    metadata, human = sources(Path(seal["protocol"]), Path(seal["receipt"]), seal["receipt_sha256"])
    # Recheck identity-only association BEFORE parsing the one permitted target.
    identities = join(
        parse(metadata, human=False, identity_only=True),
        parse(human, human=True, identity_only=True),
    )
    if _cohort(identities) != json.loads((prepared / "cohort.json").read_text()):
        raise ValueError("Identity cohort replay differs")
    return join(
        parse(metadata, human=False, identity_only=False),
        parse(human, human=True, identity_only=False),
    )


def predictions(rows: list[Observation]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Five fixed folds; save complete sequences, missingness and all nominated queries."""
    groups = components(rows)
    outputs, models = [], []
    for heldout in range(FOLDS):
        training = [
            r for r in rows if fold(groups[r.track_id]) != heldout and vote_reason(r.votes) is None
        ]
        model = fit(training, groups)
        vocabulary = set(model.vocabulary) if model else set()
        seen = set().union(*(feature_tags(r) for r in training)) if training else set()
        models.append(
            {
                "fold": heldout,
                "training_eligible": len(training),
                "training_components": len({groups[r.track_id] for r in training}),
                "vocabulary": sorted(vocabulary),
                "prior": model.prior if model else None,
                "theta_happy": model.happy.tolist() if model else None,
                "theta_not_happy": model.not_happy.tolist() if model else None,
            }
        )
        for row in rows:
            if fold(groups[row.track_id]) != heldout:
                continue
            reason = vote_reason(row.votes)
            outputs.append(
                {
                    "track_id": row.track_id,
                    "artist_id": row.artist_id,
                    "album_id": row.album_id,
                    "component_id": groups[row.track_id],
                    "fold": heldout,
                    "votes": row.votes,
                    "happy_fraction": sum(v == "happy" for v in row.votes or ()) / VOTES
                    if reason is None
                    else None,
                    "eligibility_reason": reason,
                    "prediction_reason": reason
                    or ("no_training_eligible" if model is None else None),
                    "probabilities": predict(model, row) if reason is None and model else None,
                    "unseen_feature_tags": sorted(feature_tags(row) - seen),
                }
            )
    return sorted(outputs, key=lambda r: r["track_id"]), models


def evaluation(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Report all missingness and disagreement without consensus filtering."""
    result = summarize(records, len(records))
    result.update(
        eligibility_reasons=dict(Counter(r["eligibility_reason"] or "eligible" for r in records)),
        prediction_reasons=dict(Counter(r["prediction_reason"] or "predicted" for r in records)),
        vote_sequences=dict(Counter(",".join(r["votes"] or []) for r in records)),
        disagreement=sum(
            r["eligibility_reason"] is None and len(set(r["votes"])) > 1 for r in records
        ),
        artists=len({r["artist_id"] for r in records}),
        albums=len({r["album_id"] for r in records}),
        components=len({r["component_id"] for r in records}),
        largest_component=max(Counter(r["component_id"] for r in records).values(), default=0),
        unseen_feature_rows=sum(bool(r["unseen_feature_tags"]) for r in records),
        folds=[
            {
                "fold": f,
                "nominated": sum(r["fold"] == f for r in records),
                "eligible": sum(
                    r["fold"] == f and r["eligibility_reason"] is None for r in records
                ),
                "components": len({r["component_id"] for r in records if r["fold"] == f}),
            }
            for f in range(FOLDS)
        ],
        interpretation=[
            "Metadata predictiveness for existing human votes, not audio-based musical usefulness.",
            "Happy-tag rule has privileged mood input, not a matched-feature comparison.",
            "Source-global preprocessing and annotator selection may affect this cohort.",
            "Artist/album components do not establish audio-fingerprint or alias independence.",
            "Fixed-OOF bootstrap, not retraining or population inference.",
            "Noncommercial research: CC-BY-NC-SA artifacts are not MIT serving assets.",
        ],
    )
    return result


def evaluate(prepared: Path, seal_sha256: str, output: Path) -> dict[str, Any]:
    """Persist predictions before evaluating, without networking or audio access."""
    if output.exists():
        raise ValueError("Fresh output directory required")
    records, models = predictions(_load(prepared, seal_sha256))
    output.mkdir(parents=True)
    _write(output / "predictions.json", records)
    _write(output / "models.json", models)
    _write(output / "evaluation.json", evaluation(records))
    receipt = {
        "seal_sha256": seal_sha256,
        "source_license": "CC-BY-NC-SA-4.0",
        "attribution": "MTG-Jamendo Dataset; existing human music-classification annotations",
        "research_only": True,
        "files": {
            p.name: {"sha256": digest(p), "bytes": p.stat().st_size} for p in output.iterdir()
        },
    }
    _write(output / "receipt.json", receipt)
    return receipt


def replay(prepared: Path, seal_sha256: str, output: Path) -> None:
    """Verify custody and exact deterministic model/prediction/evaluation recomputation."""
    receipt = json.loads((output / "receipt.json").read_text())
    if (
        set(receipt) != {"seal_sha256", "source_license", "attribution", "research_only", "files"}
        or receipt["source_license"] != "CC-BY-NC-SA-4.0"
        or receipt["research_only"] is not True
        or receipt["attribution"]
        != "MTG-Jamendo Dataset; existing human music-classification annotations"
    ):
        raise ValueError("Research rights or receipt claims differ")
    if (
        receipt["seal_sha256"] != seal_sha256
        or set(receipt["files"]) != {"predictions.json", "models.json", "evaluation.json"}
        or {p.name for p in output.iterdir()} != set(receipt["files"]) | {"receipt.json"}
    ):
        raise ValueError("Result inventory differs")
    for name, binding in receipt["files"].items():
        if (
            digest(output / name) != binding["sha256"]
            or (output / name).stat().st_size != binding["bytes"]
        ):
            raise ValueError("Result content differs")
    records, models = predictions(_load(prepared, seal_sha256))
    for name, value in (
        ("predictions.json", records),
        ("models.json", models),
        ("evaluation.json", evaluation(records)),
    ):
        if json.loads(json.dumps(value)) != json.loads((output / name).read_text()):
            raise ValueError("Numerical replay differs")
