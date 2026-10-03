"""Frozen, source-conditional completion of observed artist P136 statements.

An absent statement is unknown. The calibrated event is recovery of one
deterministically masked *observed* statement, not a musical membership truth.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import ijson
import zstandard

REVISION = "wikidata-artist-completion-v1"
SEED = "opennoise-artist-completion-v1-frozen"
TRAIN_BUCKETS = 6
CALIBRATION_BOUNDARY = 8
HTTP_OK = 200
RARE_TARGET_SUPPORT = 10
LANGUAGES = "en|es|fr|de|ja|zh|pt|ar|ru|hi|ko|it|id|tr|pl|sv"
ARMS = ("popularity", "co_observation", "typed_parent", "combined")
PARAMETERS: dict[str, Any] = {
    "split": "SHA256(seed:artist UUID), modulo 10: train 0..5/calibration 6..7/confirmation 8..9",
    "minimum_label_support": 5,
    "minimum_pair_support": 3,
    "smoothing": 1.0,
    "combined_parent_weight": 0.25,
    "score_bins": [0.0, 0.1, 0.2, 0.4, 0.6, 0.8, 1.000001],
    "minimum_calibration_events": 20,
    "rank_limit": 10,
    "proposal_limit": 5,
    "proposal_policy": "combined arm frozen before inspection; no winner selection",
}


def sha(path: Path) -> str:
    """Hash without allocating a whole input."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def split(mbid: str) -> str:
    """Assign exact artists before target inspection."""
    bucket = int(hashlib.sha256(f"{SEED}:{mbid}".encode()).hexdigest(), 16) % 10
    return (
        "train"
        if bucket < TRAIN_BUCKETS
        else "calibration"
        if bucket < CALIBRATION_BOUNDARY
        else "confirmation"
    )


def item_ids(statements: list[dict[str, Any]]) -> tuple[str, ...]:
    """Read only literal native entity-valued statements."""
    result = set()
    for row in statements:
        value = row.get("datavalue", {})
        native = value.get("value", {})
        if value.get("type") == "wikibase-entityid" and isinstance(native, dict):
            qid = native.get("id")
            if (
                isinstance(qid, str)
                and qid.startswith("Q")
                and qid[1:].isdigit()
                and not qid.startswith("Q0")
            ):
                result.add(qid)
    return tuple(sorted(result))


@dataclass(frozen=True)
class Artist:
    """Compact exact identity and observations, including zero-positive artists."""

    mbid: str
    qid: str
    labels: tuple[str, ...]
    fold: str


def masked(artist: Artist) -> tuple[tuple[str, ...], str | None]:
    """Freeze a target without dropping zero/one-positive queries."""
    if not artist.labels:
        return (), None
    target = min(
        artist.labels,
        key=lambda qid: hashlib.sha256(f"{SEED}:mask:{artist.mbid}:{qid}".encode()).digest(),
    )
    return tuple(qid for qid in artist.labels if qid != target), target


def check_files(root: Path) -> dict[str, Any]:
    """Enforce the complete sealed inventory, paths, bytes and hashes."""
    if any(path.is_symlink() for path in root.rglob("*")):
        raise ValueError("sealed source pack cannot contain symlinks")
    receipt = json.loads((root / "receipt.json").read_bytes())
    expected = set(receipt["files"]) | {"receipt.json"}
    actual = {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}
    if actual != expected:
        raise ValueError("source inventory differs from sealed receipt")
    for name, entry in receipt["files"].items():
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("source member must be a contained regular file")
        if path.stat().st_size != entry["bytes"] or sha(path) != entry["sha256"]:
            raise ValueError(f"source bytes changed: {name}")
    return {"receipt_sha256": sha(root / "receipt.json"), "files": len(expected)}


def _raw(root: Path, path: str) -> dict[str, Any]:
    if path.endswith(".zst"):
        with (
            (root / path).open("rb") as source,
            zstandard.ZstdDecompressor().stream_reader(source) as stream,
        ):
            return json.load(stream)
    return json.loads((root / path).read_bytes())


def check_requests(root: Path) -> dict[str, dict[str, Any]]:
    """Replay successful request identity/status/bytes against the capture ledger."""
    captures = json.loads((root / "captures.json").read_bytes())
    result = {}
    for capture in captures:
        if not capture["admitted"]:
            continue
        params = capture["params"]
        expected_props = "labels" if capture.get("kind") == "context" else "claims|labels"
        if (
            capture["http_status"] != HTTP_OK
            or not capture["body_complete"]
            or capture["endpoint"] != "https://www.wikidata.org/w/api.php"
            or capture["params"]["action"] != "wbgetentities"
            or capture["params"]["ids"].split("|") != capture["requested"]
            or params
            != {
                "action": "wbgetentities",
                "format": "json",
                "ids": "|".join(capture["requested"]),
                "props": expected_props,
                "languages": LANGUAGES,
                "maxlag": "5",
            }
        ):
            raise ValueError("capture successful request contract differs")
        path = capture["raw_path"]
        if path in result:
            raise ValueError("duplicate request body path")
        if path.endswith(".zst"):
            with (
                (root / path).open("rb") as source,
                zstandard.ZstdDecompressor().stream_reader(source) as stream,
            ):
                body = stream.read(10_000_001)
        else:
            body = (root / path).read_bytes()
        if len(body) != capture["bytes"] or hashlib.sha256(body).hexdigest() != capture["sha256"]:
            raise ValueError("capture raw-body bytes differ")
        entities = json.loads(body)["entities"]
        if set(entities) != set(capture["requested"]):
            raise ValueError("raw response entity IDs differ from exact request")
        result[path] = capture
        del entities, body
    return result


def check_role(root: Path, revision: str) -> None:
    """Reject an unapproved source role or licence instead of hardcoding its grant."""
    receipt = json.loads((root / "receipt.json").read_bytes())
    with (root / "projection.json").open("rb") as source:
        metadata = {
            prefix: value
            for prefix, event, value in ijson.parse(source)
            if prefix in {"license", "revision"} and event == "string"
        }
    if receipt.get("revision") != revision or metadata != {
        "license": "CC0-1.0",
        "revision": revision,
    }:
        raise ValueError("source role/revision/CC0 license contract differs")


def check_roster(root: Path, captures: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Bind all captured artist batches to the frozen identity roster."""
    selection = json.loads((root / "selection.json").read_bytes())["artists"]
    selected = {row["artist_mbid"]: row for row in selection}
    if len(selected) != len(selection):
        raise ValueError("frozen selection contains duplicate artist UUIDs")
    artist_captures = [capture for capture in captures.values() if capture.get("kind") == "artists"]
    for capture in artist_captures:
        start = capture["index"] * 50
        expected = sorted({row["wikidata_qid"] for row in selection[start : start + 50]})
        if capture["requested"] != expected:
            raise ValueError("artist request plan differs from frozen roster")
    return selected


def replay_artist(row: dict[str, Any], entity: dict[str, Any]) -> tuple[str, ...]:
    """Replay one literal native UUID and overlapping source labels."""
    if entity["id"] != row["wikidata_qid"] or entity.get("type") != "item":
        raise ValueError("raw entity identity differs")
    claims = entity.get("claims", {})
    identifiers = {
        str(UUID(claim["mainsnak"]["datavalue"]["value"]))
        for claim in claims.get("P434", [])
        if claim.get("rank") != "deprecated"
        and claim.get("mainsnak", {}).get("snaktype") == "value"
    }
    if identifiers != {row["artist_mbid"]}:
        raise ValueError("raw P434 is not the unique exact artist UUID")
    projected = item_ids(row.get("claims", {}).get("P136", []))
    native = item_ids(
        [
            {"datavalue": claim["mainsnak"]["datavalue"]}
            for claim in claims.get("P136", [])
            if claim.get("rank") != "deprecated"
            and claim.get("mainsnak", {}).get("snaktype") == "value"
            and "datavalue" in claim["mainsnak"]
        ]
    )
    if projected != native:
        raise ValueError("raw P136 does not replay projected observations")
    return projected


def load_artists(root: Path) -> tuple[list[Artist], dict[str, Any]]:
    """Replay exact P434 identity and P136 projection independently, per batch."""
    verification = check_files(root)
    check_role(root, "wikidata-entity-evidence-v1")
    captures = check_requests(root)
    selected = check_roster(root, captures)
    rows = []
    seen = set()
    raw_path = None
    raw: dict[str, Any] = {}
    exclusions = Counter()
    with (root / "projection.json").open("rb") as source:
        for row in ijson.items(source, "artists.item"):
            mbid = row["artist_mbid"]
            fold = split(mbid)  # Assignment before reading target claims.
            if mbid in seen:
                raise ValueError("duplicate exact artist identity")
            seen.add(mbid)
            if mbid not in selected or any(
                row[key] != selected[mbid][key] for key in ("artist_mbid", "wikidata_qid", "name")
            ):
                raise ValueError("projection identity differs from frozen roster")
            if row["status"] != "exact_identity":
                exclusions[row["status"]] += 1
                continue
            if row["raw_sha256"] != captures[row["raw_path"]]["sha256"]:
                raise ValueError("projection raw provenance differs from capture")
            if row["raw_path"] != raw_path:
                raw_path = row["raw_path"]
                raw = {}
                raw = _raw(root, raw_path)["entities"]
            projected = replay_artist(row, raw[row["wikidata_qid"]])
            rows.append(Artist(mbid, row["wikidata_qid"], projected, fold))
    if seen != set(selected):
        raise ValueError("projection omitted frozen exact artist query identities")
    verification.update(excluded_non_exact=dict(exclusions), exact_artists=len(rows))
    return rows, verification


def load_parents(root: Path) -> tuple[dict[str, tuple[str, ...]], dict[str, Any]]:
    """Read and independently replay P279 only; P31 is never a distance edge."""
    verification = check_files(root)
    check_role(root, "wikidata-native-genre-context-v1")
    captures = check_requests(root)
    parents = {}
    raw_path = None
    raw: dict[str, Any] = {}
    with (root / "projection.json").open("rb") as source:
        for qid, row in ijson.kvitems(source, "entities"):
            if row["status"] != "native_entity":
                continue
            if row["raw_sha256"] != captures[row["raw_path"]]["sha256"]:
                raise ValueError("genre projection raw provenance differs from capture")
            if row["raw_path"] != raw_path:
                raw_path = row["raw_path"]
                raw = {}
                raw = _raw(root, raw_path)["entities"]
            entity = raw[qid]
            if entity.get("id") != qid or entity.get("type") != "item":
                raise ValueError("raw genre entity identity/type differs")
            native = item_ids(
                [
                    {"datavalue": claim["mainsnak"]["datavalue"]}
                    for claim in entity.get("claims", {}).get("P279", [])
                    if claim.get("rank") != "deprecated"
                    and claim.get("mainsnak", {}).get("snaktype") == "value"
                    and "datavalue" in claim["mainsnak"]
                ]
            )
            projected = item_ids(row.get("claims", {}).get("P279", []))
            if native != projected:
                raise ValueError("raw typed P279 differs from projection")
            parents[qid] = native
    verification.update(parent_edges=sum(map(len, parents.values())))
    return parents, verification


@dataclass
class Model:
    """Train-only source counts; no held-out artist can affect fitting."""

    support: Counter[str]
    pairs: dict[str, Counter[str]]
    vocabulary: tuple[str, ...]
    parents: dict[str, tuple[str, ...]]
    train_count: int

    def rank(self, seeds: tuple[str, ...], arm: str) -> list[tuple[str, float]]:
        """Return candidates or explicit cold-seed abstention."""
        supported = tuple(qid for qid in seeds if qid in self.vocabulary)
        if not supported:
            return []
        scores: dict[str, float] = {}
        for candidate in self.vocabulary:
            if candidate in seeds:
                continue
            co = max(
                (
                    (self.pairs.get(seed, {}).get(candidate, 0) + 1) / (self.support[seed] + 2)
                    if self.pairs.get(seed, {}).get(candidate, 0)
                    >= PARAMETERS["minimum_pair_support"]
                    else 0.0
                )
                for seed in supported
            )
            parent = float(any(candidate in self.parents.get(seed, ()) for seed in supported))
            if arm == "popularity":
                score = self.support[candidate] / self.train_count
            elif arm == "co_observation":
                score = co
            elif arm == "typed_parent":
                score = parent
            elif arm == "combined":
                score = 0.75 * co + 0.25 * parent
            else:
                raise ValueError("unknown frozen model arm")
            if score > 0:
                scores[candidate] = score
        return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))[:10]


def fit(artists: list[Artist], parents: dict[str, tuple[str, ...]]) -> Model:
    """Fit from training artists only, preserving overlapping native labels."""
    support: Counter[str] = Counter()
    pairs: dict[str, Counter[str]] = defaultdict(Counter)
    train = [artist for artist in artists if artist.fold == "train"]
    for artist in train:
        support.update(artist.labels)
        for seed in artist.labels:
            pairs[seed].update(qid for qid in artist.labels if qid != seed)
    vocabulary = tuple(
        sorted(qid for qid, n in support.items() if n >= PARAMETERS["minimum_label_support"])
    )
    return Model(support, pairs, vocabulary, parents, len(train))


def score_bin(score: float) -> int:
    """Use fixed bins, never optimized against confirmation events."""
    edges = PARAMETERS["score_bins"]
    return next(
        index for index in range(len(edges) - 1) if edges[index] <= score < edges[index + 1]
    )


def wilson(successes: int, count: int) -> tuple[float, float]:
    """95% interval for a masked-source recovery event, not genre truth."""
    if not count:
        return (0.0, 1.0)
    p = successes / count
    denominator = 1 + 1.96**2 / count
    center = (p + 1.96**2 / (2 * count)) / denominator
    margin = 1.96 * math.sqrt(p * (1 - p) / count + 1.96**2 / (4 * count**2)) / denominator
    return center - margin, center + margin


def events(artists: list[Artist], model: Model, fold: str, arm: str) -> list[dict[str, Any]]:
    """Keep every held-out exact identity, including target/seed abstentions."""
    result = []
    for artist in artists:
        if artist.fold != fold:
            continue
        seeds, target = masked(artist)
        ranked = model.rank(seeds, arm)
        result.append(
            {
                "artist_mbid": artist.mbid,
                "observed_labels": len(artist.labels),
                "seed_labels": list(seeds),
                "masked_observed_target": target,
                "target_in_training_vocabulary": target in model.vocabulary,
                "target_training_support": model.support.get(target, 0),
                "ranked": ranked,
                "abstention": "unlabelled"
                if target is None
                else "no_observed_seed"
                if not seeds
                else "unsupported_or_disconnected_seed"
                if not ranked
                else None,
            }
        )
    return result


def calibrate(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Calibrate first-ranked masked target recovery on calibration artists only."""
    totals = Counter()
    successes = Counter()
    for row in rows:
        if row["ranked"] and row["masked_observed_target"] is not None:
            qid, score = row["ranked"][0]
            bucket = score_bin(score)
            totals[bucket] += 1
            successes[bucket] += int(qid == row["masked_observed_target"])
    return {
        bucket: {
            "count": totals[bucket],
            "recoveries": successes[bucket],
            "probability": successes[bucket] / totals[bucket]
            if totals[bucket] >= PARAMETERS["minimum_calibration_events"]
            else None,
            "interval_95": list(wilson(successes[bucket], totals[bucket])),
        }
        for bucket in range(6)
    }


def metrics(rows: list[dict[str, Any]], bins: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Positive-only recall; source absence is never a negative genre annotation."""
    labelled = [row for row in rows if row["masked_observed_target"] is not None]
    hits = {
        k: sum(
            row["masked_observed_target"] in [qid for qid, _ in row["ranked"][:k]]
            for row in labelled
        )
        for k in (1, 5, 10)
    }
    calibrated = []
    confirmation_bins: dict[int, Counter[str]] = defaultdict(Counter)
    for row in labelled:
        if row["ranked"]:
            qid, score = row["ranked"][0]
            probability = bins[score_bin(score)]["probability"]
            if probability is not None:
                outcome = int(qid == row["masked_observed_target"])
                calibrated.append((probability, outcome))
                confirmation_bins[score_bin(score)]["count"] += 1
                confirmation_bins[score_bin(score)]["recoveries"] += outcome
    calibration_count = sum(value["count"] for value in bins.values())
    constant_probability = (
        sum(value["recoveries"] for value in bins.values()) / calibration_count
        if calibration_count
        else None
    )
    strata = {}
    for name, subset in {
        "unseen_target": [row for row in labelled if row["target_training_support"] == 0],
        "rare_target_1_to_10_train_artists": [
            row for row in labelled if 0 < row["target_training_support"] <= RARE_TARGET_SUPPORT
        ],
        "common_target_over_10_train_artists": [
            row for row in labelled if row["target_training_support"] > RARE_TARGET_SUPPORT
        ],
    }.items():
        strata[name] = {
            "positive_queries": len(subset),
            "recall_at_10": sum(
                row["masked_observed_target"] in [qid for qid, _ in row["ranked"]] for row in subset
            )
            / len(subset)
            if subset
            else None,
        }
    return {
        "all_exact_artist_queries": len(rows),
        "masked_observed_positive_queries": len(labelled),
        "unlabelled_queries": len(rows) - len(labelled),
        "one_positive_queries": sum(row["observed_labels"] == 1 for row in rows),
        "target_outside_training_vocabulary_queries": sum(
            not row["target_in_training_vocabulary"] for row in labelled
        ),
        "unseen_target_queries": sum(row["target_training_support"] == 0 for row in labelled),
        "seen_below_minimum_support_queries": sum(
            0 < row["target_training_support"] < PARAMETERS["minimum_label_support"]
            for row in labelled
        ),
        "abstentions": dict(Counter(row["abstention"] for row in rows if row["abstention"])),
        "recall": {str(k): hits[k] / len(labelled) if labelled else None for k in hits},
        "calibrated_confirmation_events": len(calibrated),
        "masked_recovery_brier": sum((p - outcome) ** 2 for p, outcome in calibrated)
        / len(calibrated)
        if calibrated
        else None,
        "masked_recovery_constant_baseline_brier": (
            sum((constant_probability - outcome) ** 2 for _, outcome in calibrated)
            / len(calibrated)
            if calibrated and constant_probability is not None
            else None
        ),
        "calibrated_bin_reliability": {
            str(bucket): {
                "queries": value["count"],
                "recovered": value["recoveries"],
                "frozen_calibration_probability": bins[bucket]["probability"],
                "observed_masked_recovery_fraction": value["recoveries"] / value["count"],
                "confirmation_interval_95": list(wilson(value["recoveries"], value["count"])),
            }
            for bucket, value in sorted(confirmation_bins.items())
        },
        "target_support_strata": strata,
        "scope": (
            "masked observed-source recovery; no musical truth, prevalence or absence negatives"
        ),
    }


def build(artist_pack: Path, genre_pack: Path, output: Path) -> dict[str, Any]:
    """Construct a separately named artifact without overwriting any prior work."""
    output.mkdir(parents=True, exist_ok=False)
    (output / "implementation.py").write_bytes(Path(__file__).read_bytes())
    (output / "frozen-policy.json").write_text(
        json.dumps(
            {"revision": REVISION, "seed": SEED, "arms": ARMS, "parameters": PARAMETERS}, indent=2
        )
        + "\n"
    )
    artists, artist_verification = load_artists(artist_pack)
    parents, genre_verification = load_parents(genre_pack)
    genre_receipt = json.loads((genre_pack / "receipt.json").read_bytes())
    if genre_receipt["source_receipt_sha256"] != artist_verification["receipt_sha256"]:
        raise ValueError("genre context is not bound to this exact artist source pack")
    model = fit(artists, parents)
    (output / "fitted-model.json").write_text(
        json.dumps(
            {
                "training_artists": model.train_count,
                "training_support": dict(sorted(model.support.items())),
                "training_pairs": {
                    key: dict(sorted(value.items())) for key, value in sorted(model.pairs.items())
                },
                "training_vocabulary": model.vocabulary,
                "native_typed_parents": parents,
            },
            sort_keys=True,
        )
        + "\n"
    )
    report = {
        "revision": REVISION,
        "source_license": "CC0-1.0",
        "artist_replay": artist_verification,
        "genre_replay": genre_verification,
        "folds": dict(Counter(artist.fold for artist in artists)),
        "training_vocabulary": len(model.vocabulary),
        "parameters": PARAMETERS,
        "arms": {},
        "musical_validity": "requires independent listeners; unassessed",
        "default_promotion": False,
        "implementation_sha256": sha(Path(__file__)),
        "preserved_implementation_sha256": sha(output / "implementation.py"),
        "frozen_policy_sha256": sha(output / "frozen-policy.json"),
        "sampling_limit": (
            "bounded source-selected Wikidata/MBID roster; "
            "no claim of representative artist population"
        ),
        "native_region_language_features": (
            "not used for genre inference in this frozen experiment; "
            "source properties are not musical facts"
        ),
    }
    with (
        (output / "artist-fold-targets.jsonl.zst").open("xb") as raw,
        zstandard.ZstdCompressor(level=3).stream_writer(raw) as stream,
    ):
        for artist in artists:
            seeds, target = masked(artist)
            row = {
                "artist_mbid": artist.mbid,
                "wikidata_qid": artist.qid,
                "split": artist.fold,
                "observed_genre_qids": artist.labels,
                "masked_observed_target": target,
                "seed_genre_qids": seeds,
            }
            stream.write((json.dumps(row, sort_keys=True) + "\n").encode())
    all_bins = {}
    for arm in ARMS:
        calibration = events(artists, model, "calibration", arm)
        bins = calibrate(calibration)
        all_bins[arm] = bins
        confirmation = events(artists, model, "confirmation", arm)
        report["arms"][arm] = {
            "calibration_bins": bins,
            "calibration": metrics(calibration, bins),
            "confirmation": metrics(confirmation, bins),
        }
        with (
            (output / f"{arm}-confirmation.jsonl.zst").open("xb") as raw,
            zstandard.ZstdCompressor(level=3).stream_writer(raw) as stream,
        ):
            for row in confirmation:
                stream.write((json.dumps(row, sort_keys=True) + "\n").encode())
    bins = all_bins["combined"]
    with (
        (output / "artist-proposals.jsonl.zst").open("xb") as raw,
        zstandard.ZstdCompressor(level=3).stream_writer(raw) as stream,
    ):
        for artist in artists:
            ranked = model.rank(artist.labels, "combined")[:5]
            proposals = []
            for rank, (qid, score) in enumerate(ranked, 1):
                calibration = bins[score_bin(score)]
                proposals.append(
                    {
                        "genre_qid": qid,
                        "score": score,
                        "rank": rank,
                        "calibration_support": calibration["count"],
                        "masked_task_bin_reference_probability": calibration["probability"],
                        "proposal_probability": None,
                        "probability_scope": (
                            "full-seed proposals differ from masked protocol; "
                            "bin reference is not a calibrated proposal probability"
                        ),
                        "musical_membership_probability": None,
                        "supported_seed_evidence": [
                            {
                                "seed_genre_qid": seed,
                                "train_seed_artist_count": model.support[seed],
                                "train_pair_artist_count": model.pairs.get(seed, {}).get(qid, 0),
                                "literal_seed_P279_parent": qid in parents.get(seed, ()),
                            }
                            for seed in artist.labels
                            if seed in model.vocabulary
                            and (
                                model.pairs.get(seed, {}).get(qid, 0)
                                >= PARAMETERS["minimum_pair_support"]
                                or qid in parents.get(seed, ())
                            )
                        ],
                        "evidence": (
                            "train artist P136 co-observation plus literal typed P279; "
                            "proposal not source observation"
                        ),
                    }
                )
            row = {
                "artist_mbid": artist.mbid,
                "wikidata_qid": artist.qid,
                "split": artist.fold,
                "observed_genre_qids": list(artist.labels),
                "proposals": proposals,
                "abstention": "no_supported_candidates" if not proposals else None,
                "namespace": "experimental-source-completion-v1",
                "default_promotion": False,
            }
            stream.write((json.dumps(row, sort_keys=True) + "\n").encode())
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    inventory = {
        path.name: {"bytes": path.stat().st_size, "sha256": sha(path)}
        for path in sorted(output.iterdir())
    }
    (output / "receipt.json").write_text(
        json.dumps({"revision": REVISION, "files": inventory}, indent=2, sort_keys=True) + "\n"
    )
    return report
