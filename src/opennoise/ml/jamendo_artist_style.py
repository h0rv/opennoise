"""Development-only human-style evaluation of unchanged artist retrieval geometry."""

# ruff: noqa: PLR2004 -- immutable source, target and metric dimensions.
from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from opennoise.ml import jamendo_artist_coherence as old
from opennoise.ml import jamendo_human_genre as base
from opennoise.ml import jamendo_human_mood as native

PROTOCOL = "dd0ee95db87b418d111d318312945c1a3c32c4511562a16ba43dd425b7fe7f59"
ATTRIBUTES = ("aggressive", "electronic", "party", "relaxed", "sad")
METHODS = (*old.ARMS, "exact_random_expectation")
PARTS = ("positive", "negative", "total")
MAX_BYTES = 15_000_000
PAYLOADS = {"geometry-proof.json", "rankings.json", "evaluation.json"}
PROOF_FILES = {"indices.json", "rankings.json"}
PROOF_PINS = {
    "indices.json": "d8df92b119a1404dc250c6c45dbe44813b72a6ae750c849dbdca4d0b6f3abe91",
    "rankings.json": "172e49d3f86561bceab1e76b8a2711dc8d0629860c0b6d5e3cbd896a61eba212",
}
OLD_MODULE = "3a310f1fa978c1cfb1d76ded48151b21c1f7060c7f61dfd867652c074fbf7ac4"


@dataclass(frozen=True)
class Inputs:
    """Exact raw sources, frozen protocol, and a closed two-file historical proof."""

    metadata: Path
    human: Path
    protocol: Path
    protocol_sha256: str
    historical: Path

    @property
    def paths(self) -> tuple[Path, ...]:
        """Protect every input from publication overlap."""
        return self.metadata, self.human, self.protocol, self.historical

    def pins(self) -> dict[str, Any]:
        """Retain source and historical custody without absolute paths."""
        return {
            "source": old.SOURCE,
            "protocol_sha256": self.protocol_sha256,
            "historical": PROOF_PINS,
            "amendment_sha256": base.AMENDMENT_SHA256,
        }


def runtime() -> dict[str, Any]:
    """Pin new evaluation and the unchanged numerical reconstruction."""
    script = Path(__file__).resolve().parents[3] / "scripts/run_jamendo_artist_style.py"
    return {
        "original": old.runtime(),
        "code": {p.name: base.digest(p) for p in (Path(__file__), script)},
    }


def validate(inputs: Inputs) -> None:
    """Fail closed on protocol, runtime, inventory and physical source custody."""
    if inputs.protocol_sha256 != PROTOCOL or base.digest(inputs.protocol) != PROTOCOL:
        raise ValueError("Frozen style development protocol differs")
    if base.digest(Path(old.__file__)) != OLD_MODULE:
        raise ValueError("Frozen artist reconstruction differs")
    if any(base.runtime()["code"][k] != v for k, v in old.OLD_CODE.items()):
        raise ValueError("Frozen native helpers differ")
    for name, binding in old.SOURCE.items():
        p = getattr(inputs, name)
        if (
            any(q.is_symlink() for q in (p, *p.parents))
            or not p.is_file()
            or p.stat().st_size != binding["bytes"]
            or base.digest(p) != binding["sha256"]
        ):
            raise ValueError("Exact official source bytes differ")
    base.check_inventory(inputs.historical, PROOF_FILES)
    if sum((inputs.historical / n).stat().st_size for n in PROOF_FILES) > MAX_BYTES:
        raise ValueError("Historical proof cap exceeded")
    if any(base.digest(inputs.historical / n) != pin for n, pin in PROOF_PINS.items()):
        raise ValueError("Pinned historical geometry proof differs")


def selected_votes(cells: list[str], attribute: str) -> tuple[list[str] | None, str | None]:
    """Interpret only one selected exact binary taxonomy, without normalization."""
    prefix = f"mood_{attribute}---"
    values = [c[len(prefix) :] for c in cells if c.startswith(prefix)]
    if len(values) > 1:
        raise ValueError("Duplicate selected human taxonomy")
    votes = values[0].split(",") if values and values[0] else None
    reason = (
        "missing_votes"
        if not votes
        else "wrong_vote_count"
        if len(votes) != 3
        else "invalid_vote"
        if any(v not in (attribute, "not_" + attribute) for v in votes)
        else None
    )
    return votes, reason


def style_row(identity: dict[str, Any], fold: int, cells: list[str]) -> dict[str, Any]:
    """Apply reserved identity role before invoking any selected-style accessor."""
    if fold == 4:
        return {**identity, "status": "reserved"}
    selected = {}
    for a in ATTRIBUTES:
        votes, reason = selected_votes(cells, a)
        selected[a] = {"raw_votes": votes, "reason": reason}
    return {**identity, "status": "development", "attributes": selected}


def source(inputs: Inputs) -> dict[str, Any]:  # noqa: C901 -- explicit role-first custody checks.
    """Seal native roles first; reserved rows never reach selected vote extraction."""
    validate(inputs)
    metadata = native.parse(inputs.metadata, human=False, identity_only=False)
    human_identity = native.parse(inputs.human, human=True, identity_only=True)
    native.join(metadata, human_identity)
    identities = base.cohort(metadata)
    protocol = base.read(inputs.protocol)
    if (
        hashlib.sha256(base.file_bytes("cohort.json", identities)).hexdigest()
        != protocol["source"]["identity_cohort_sha256"]
    ):
        raise ValueError("Full native component cohort differs")
    by_id = {r["track_id"]: r for r in identities}
    observations = defaultdict(list)
    for r in metadata:
        observations[r.artist_id].append(r)
    artists: list[dict[str, Any]] = []
    for artist, rows in sorted(observations.items()):
        components = {by_id[r.track_id]["component_id"] for r in rows}
        if len(components) != 1:
            raise ValueError("Artist spans components")
        component = next(iter(components))
        artists.append(
            {
                "artist_id": artist,
                "component_id": component,
                "fold": base.fold(component),
                "track_ids": [r.track_id for r in rows],
                "album_ids": sorted({r.album_id for r in rows}),
                "tag_counts": dict(
                    sorted(Counter(t for r in rows for t in native.feature_tags(r)).items())
                ),
                "attributes": {},
            }
        )
    if len(artists) != 713 or len({r["component_id"] for r in artists}) != 713:
        raise ValueError("Expected native one-artist components")
    artist_by_id = {r["artist_id"]: r for r in artists}
    evidence = {a: defaultdict(list) for a in ATTRIBUTES}
    tracks = []
    for line in inputs.human.read_text().splitlines()[1:]:
        cells = line.split("\t")
        tid = native._identity(cells)[0]  # noqa: SLF001 -- unchanged strict native grammar.
        identity = by_id[tid]
        row = style_row(identity, artist_by_id[identity["artist_id"]]["fold"], cells[5:])
        if row["status"] == "development":
            for a in ATTRIBUTES:
                selected = row["attributes"][a]
                if selected["reason"] is None:
                    evidence[a][identity["artist_id"]].append(selected["raw_votes"].count(a))
                row["attributes"][a] = {
                    "reason": selected["reason"],
                    "vote_count": len(selected["raw_votes"] or []),
                }
        tracks.append(row)
    for r in artists:
        if r["fold"] == 4:
            r["status"] = "reserved"
            del r["attributes"]
            continue
        r["status"] = "development"
        for a in ATTRIBUTES:
            pos = evidence[a][r["artist_id"]]
            r["attributes"][a] = {
                "eligible_tracks": len(pos),
                "positive_votes": sum(pos),
                "negative_votes": 3 * len(pos) - sum(pos),
            }
        r["complete"] = all(r["attributes"][a]["eligible_tracks"] > 0 for a in ATTRIBUTES)
        r["robust"] = all(r["attributes"][a]["eligible_tracks"] >= 2 for a in ATTRIBUTES)
    return {"tracks": tracks, "artists": artists, "support": support(tracks, artists)}


def support(tracks: list[dict[str, Any]], artists: list[dict[str, Any]]) -> dict[str, Any]:
    """Count availability and every fixed gate without targets, vectors or scores."""
    development = [r for r in artists if r["fold"] != 4]
    folds = []
    for f in range(4):
        query = [r for r in development if r["fold"] == f]
        gallery = [r for r in development if r["fold"] != f]
        complete = [r for r in gallery if r["complete"]]
        attr = {
            a: {
                part: sum(r["attributes"][a][part + "_votes"] > 0 for r in complete)
                for part in ("positive", "negative")
            }
            for a in ATTRIBUTES
        }
        folds.append(
            {
                "fold": f,
                "query_metadata": len(query),
                "query_complete": sum(r["complete"] for r in query),
                "query_robust": sum(r["robust"] for r in query),
                "gallery_metadata": len(gallery),
                "gallery_complete": len(complete),
                "attribute_support": attr,
                "gate": len(complete) >= 50 and all(min(v.values()) >= 5 for v in attr.values()),
            }
        )
    devtracks = [r for r in tracks if r["status"] == "development"]
    return {
        "metadata_tracks": len(tracks),
        "development_tracks": len(devtracks),
        "reserved_tracks": len(tracks) - len(devtracks),
        "artists": len(artists),
        "development_artists": len(development),
        "reserved_artists": len(artists) - len(development),
        "complete_queries": sum(r["complete"] for r in development),
        "robust_queries": sum(r["robust"] for r in development),
        "track_reasons": {
            a: dict(Counter(r["attributes"][a]["reason"] or "eligible" for r in devtracks))
            for a in ATTRIBUTES
        },
        "folds": folds,
        "gate": sum(r["complete"] for r in development) >= 100 and all(r["gate"] for r in folds),
        "idf_builds": 0,
        "supervised_fits": 0,
        "style_metrics_computed": False,
    }


def receipt(inputs: Inputs, files: dict[str, Any], revision: str) -> dict[str, Any]:
    """Bind exact physical files, runtime and local research rights."""
    return {
        "revision": revision,
        "inputs": inputs.pins(),
        "runtime": runtime(),
        "files": base.bindings(files),
        **base.RIGHTS,
    }


def check_combined(directory: Path | None, files: dict[str, Any]) -> None:
    """Enforce the declared combined cap including both stage custody envelopes."""
    previous = sum(p.stat().st_size for p in directory.iterdir()) if directory else 0
    if previous + sum(len(base.file_bytes(n, v)) for n, v in files.items()) > MAX_BYTES:
        raise ValueError("Combined census/result cap exceeded")


def census(inputs: Inputs, output: Path) -> str:
    """Publish count-only evidence before any style score math."""
    base.destination(output, inputs.paths)
    files = {"census.json": source(inputs)}
    complete = {**files, "seal.json": receipt(inputs, files, "artist-style-census-v1")}
    check_combined(None, complete)
    return old.publish(output, complete, inputs.paths)


def load_stage(  # noqa: PLR0913, PLR0917 -- explicit stage custody roles.
    inputs: Inputs, directory: Path, pin: str, names: set[str], revision: str, marker: str
) -> dict[str, Any]:
    """Verify closed inventory and exact bytes before interpreting artifacts."""
    base.check_inventory(directory, names | {marker})
    if sum(p.stat().st_size for p in directory.iterdir()) > MAX_BYTES:
        raise ValueError("Style stage cap exceeded")
    if base.digest(directory / marker) != pin:
        raise ValueError("External stage pin differs")
    seal = base.read(directory / marker)
    base.check_file_bindings(directory, names, seal["files"])
    files = {n: base.read(directory / n) for n in names}
    expected = receipt(inputs, files, revision)
    if marker == "receipt.json":
        expected["census_sha256"] = seal["census_sha256"]
    if base.encoded(expected) != base.encoded(seal):
        raise ValueError("Runtime/source/schema custody differs")
    return files


def targets(artists: list[dict[str, Any]]) -> dict[int, np.ndarray]:
    """Compute development-only equal-track binary-vote probabilities."""
    return {
        r["artist_id"]: np.array(
            [
                r["attributes"][a]["positive_votes"] / (3 * r["attributes"][a]["eligible_tracks"])
                for a in ATTRIBUTES
            ]
        )
        for r in artists
        if r["fold"] != 4 and r["complete"]
    }


def gains(query: np.ndarray, candidates: np.ndarray) -> np.ndarray:
    """Keep positive and negative agreement separate; macro is equal attribute mean."""
    positive, negative = candidates * query, (1 - candidates) * (1 - query)
    values = np.stack((positive, negative, positive + negative), axis=-1)
    return np.concatenate((values, values.mean(axis=-2, keepdims=True)), axis=-2)


def prevalence(values: np.ndarray) -> dict[str, list[float]]:
    """Append an equal-attribute macro and retain the explicit negative complement."""
    positive = np.append(values, values.mean())
    return {"positive": positive.tolist(), "negative": (1 - positive).tolist()}


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Artist-equal means, prevalence and separately labeled pooled track supports."""
    galleries = {}
    for row in rows:
        galleries[str(row["fold"])] = row["gallery_support"]
    return {
        "queries": len(rows),
        "means": np.mean([r["metrics"] for r in rows], axis=0).tolist() if rows else None,
        "prevalence": {
            "query_artist_equal": prevalence(np.mean([r["query_prevalence"] for r in rows], axis=0))
            if rows
            else None,
            "gallery_artist_equal_then_query_equal": prevalence(
                np.mean([r["gallery_prevalence"] for r in rows], axis=0)
            )
            if rows
            else None,
            "query_artist_denominator": len(rows),
            "pooled_query_eligible_tracks_by_attribute": np.sum(
                [r["eligible_track_counts"] for r in rows], axis=0
            ).tolist()
            if rows
            else [0] * 5,
            "gallery_support_by_query_fold": galleries,
            "note": (
                "Query prevalence is artist-equal. Gallery prevalence is the query-weighted "
                "mean of within-fold artist-equal gallery means, not unique-gallery pooled. "
                "Track counts are pooled support only, not weights; galleries listed once per fold."
            ),
        },
    }


def bootstrap(rows: list[dict[str, Any]], seed: int) -> dict[str, Any]:
    """Reuse paired component draws across every attribute, term and arm comparison."""
    if not rows:
        return {"queries": 0, "seed": seed, "intervals": None}
    data = np.array([r["metrics"] for r in rows])
    differences = np.stack(
        (data[:, 1] - data[:, 0], data[:, 0] - data[:, 2], data[:, 1] - data[:, 2]), axis=1
    )
    rng = np.random.Generator(np.random.PCG64(seed))
    means = np.array(
        [differences[rng.integers(0, len(rows), len(rows))].mean(axis=0) for _ in range(2000)]
    )
    return {
        "queries": len(rows),
        "seed": seed,
        "mean_differences": differences.mean(axis=0).tolist(),
        "intervals": np.quantile(means, [0.025, 0.975], axis=0).tolist(),
    }


def evaluate(
    artists: list[dict[str, Any]], rankings: dict[str, dict[int, dict[str, Any]]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply identity roles first, target completeness second, never modify feature order."""
    by_id = {r["artist_id"]: r for r in artists}
    observed = targets(artists)
    results = []
    for artist in artists:
        a, f = artist["artist_id"], artist["fold"]
        if f == 4:
            results.append(
                {
                    "artist_id": a,
                    "component_id": artist["component_id"],
                    "fold": f,
                    "status": "reserved",
                }
            )
            continue
        gallery = sorted(c for c in observed if by_id[c]["fold"] != f)
        random_gain = (
            gains(observed[a], np.array([observed[c] for c in gallery])).mean(axis=0)
            if a in observed
            else None
        )
        methods, arms = [], {}
        for arm in old.ARMS:
            ranked = rankings[arm][a]
            role_order = [
                (c, s) for c, s in ranked["positive_order"] if by_id[c]["fold"] not in (f, 4)
            ]
            full = role_order[:10]
            judged = [(c, s) for c, s in role_order if c in observed][:10]
            full_observed = [c for c, _ in full if c in observed]
            metrics = (
                gains(observed[a], np.array([observed[c] for c, _ in judged]).reshape(-1, 5)).sum(
                    axis=0
                )
                / 10
                if a in observed
                else None
            )
            if metrics is not None:
                methods.append(metrics)
            arms[arm] = {
                "reason": ranked["reason"],
                "development_positive_candidates": len(role_order),
                "full_development_top10": [
                    {"artist_id": c, "cosine": s, "target_available": c in observed}
                    for c, s in full
                ],
                "condensed_top10": [{"artist_id": c, "cosine": s} for c, s in judged],
                "full_judged_slots": len(full_observed),
                "full_unjudged_slots": len(full) - len(full_observed),
                "full_missing_slots": 10 - len(full),
                "conditional_observed_agreement": gains(
                    observed[a], np.array([observed[c] for c in full_observed])
                )
                .mean(axis=0)
                .tolist()
                if a in observed and full_observed
                else None,
                "historical_catalog_judged_development_slots": sum(
                    c in observed for c, _ in ranked["positive_order"][:10]
                ),
                "historical_catalog_unjudged_development_slots": sum(
                    by_id[c]["fold"] != 4 and c not in observed
                    for c, _ in ranked["positive_order"][:10]
                ),
                "historical_catalog_missing_slots": 10 - len(ranked["positive_order"][:10]),
                "historical_catalog_reserved_slots": sum(
                    by_id[c]["fold"] == 4 for c, _ in ranked["positive_order"][:10]
                ),
            }
        if random_gain is not None:
            methods.append(random_gain)
        results.append(
            {
                "artist_id": a,
                "component_id": artist["component_id"],
                "fold": f,
                "status": "development",
                "target": observed[a].tolist() if a in observed else None,
                "robust": artist["robust"],
                "instrument_present": any(
                    t.startswith("instrument---") for t in artist["tag_counts"]
                ),
                "arms": arms,
                "metrics": np.array(methods).tolist() if methods else None,
                "eligible_track_counts": [
                    artist["attributes"][x]["eligible_tracks"] for x in ATTRIBUTES
                ],
                "gallery_support": {
                    "artists": len(gallery),
                    "pooled_eligible_tracks_by_attribute": [
                        sum(by_id[c]["attributes"][x]["eligible_tracks"] for c in gallery)
                        for x in ATTRIBUTES
                    ],
                },
                "query_prevalence": observed[a].tolist() if a in observed else None,
                "gallery_prevalence": np.mean([observed[c] for c in gallery], axis=0).tolist(),
            }
        )
    judged = [r for r in results if r.get("target") is not None]
    robust = [r for r in judged if r["robust"]]
    evaluation = {
        "methods": list(METHODS),
        "attributes": [*ATTRIBUTES, "macro"],
        "parts": list(PARTS),
        "overall": summarize(judged),
        "robust_ge2": summarize(robust),
        "bootstrap": bootstrap(judged, 20261019),
        "robust_bootstrap": bootstrap(robust, 20261020),
        "folds": [
            {"fold": f, **summarize([r for r in judged if r["fold"] == f])} for f in range(4)
        ],
        "instrument_strata": {
            str(v): summarize([r for r in judged if r["instrument_present"] == v])
            for v in (False, True)
        },
        "supervised_fits": 0,
        "gallery_idf_index_builds": 5,
        **base.RIGHTS,
    }
    return results, evaluation


def compute(inputs: Inputs, directory: Path, pin: str) -> dict[str, Any]:
    """Revalidate count seal, prove frozen geometry, then grade development targets."""
    sealed = load_stage(
        inputs, directory, pin, {"census.json"}, "artist-style-census-v1", "seal.json"
    )
    report = source(inputs)
    if base.encoded(report) != base.encoded(sealed["census.json"]):
        raise ValueError("Count-only census semantic replay differs")
    if not report["support"]["gate"]:
        return {
            "geometry-proof.json": {},
            "rankings.json": [],
            "evaluation.json": {"status": "support_gate_failed", "support": report["support"]},
        }
    features = old.feature_rows(report["artists"])
    indices = []
    rankings = {a: {} for a in old.ARMS}
    for f in range(5):
        bank = old.build_index(features, f)
        indices.append(old.index_evidence(features, bank, f))
        for i, arm in enumerate(old.ARMS):
            rankings[arm].update(old.rank(features, bank, i))
    if (
        hashlib.sha256(base.file_bytes("indices.json", indices)).hexdigest()
        != PROOF_PINS["indices.json"]
    ):
        raise ValueError("Frozen indices/matrix proof differs")
    previous = base.read(inputs.historical / "rankings.json")
    for r in previous:
        for arm in old.ARMS:
            actual = rankings[arm][r["artist_id"]]
            saved = r["arms"][arm]
            projection = [(e["artist_id"], e["cosine"]) for e in saved["full_top10"]]
            if (
                projection != actual["positive_order"][:10]
                or saved["reason"] != actual["reason"]
                or saved["unseen_query_tags"] != actual["unseen_query_tags"]
                or saved["positive_overlap_candidates"] != len(actual["positive_order"])
            ):
                raise ValueError("Frozen historical full-top10 differs")
    rows, evaluation = evaluate(report["artists"], rankings)
    evaluation["support"] = report["support"]
    return {
        "geometry-proof.json": {
            "historical": PROOF_PINS,
            "all713_top10_exact": True,
            "all20_matrix_hashes_exact": True,
            "indices": indices,
        },
        "rankings.json": rows,
        "evaluation.json": evaluation,
    }


def run(inputs: Inputs, directory: Path, pin: str, output: Path) -> str:
    """Publish the bounded development result only after every computation succeeds."""
    sources = (*inputs.paths, directory)
    base.destination(output, sources)
    files = compute(inputs, directory, pin)
    seal = {**receipt(inputs, files, "artist-style-result-v1"), "census_sha256": pin}
    complete = {**files, "receipt.json": seal}
    check_combined(directory, complete)
    return old.publish(output, complete, sources)


def replay(
    inputs: Inputs, directory: Path, pin: str, output: Path, result_pin: str
) -> dict[str, Any]:
    """Repeat the same fixed five banks and development evaluator, not new tuning."""
    files = load_stage(
        inputs, output, result_pin, PAYLOADS, "artist-style-result-v1", "receipt.json"
    )
    if base.read(output / "receipt.json")["census_sha256"] != pin:
        raise ValueError("Result census association differs")
    check_combined(directory, {**files, "receipt.json": base.read(output / "receipt.json")})
    recomputed = compute(inputs, directory, pin)
    if base.encoded(recomputed) != base.encoded(files):
        raise ValueError("Exact development result replay differs")
    return {"status": "passed", "gallery_idf_index_builds": 5, "supervised_fits": 0}
