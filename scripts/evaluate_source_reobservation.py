"""Replay a bounded, source-component-isolated calibration and abstention experiment."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import heapq
import json
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from scipy import sparse

from opennoise.analysis.emergent_topic_holdout import _facts, musical_value
from opennoise.catalog.musicbrainz_candidate import require_local_candidate_destination
from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.ml.artist_feature_enrichment import MAX_BATCH
from opennoise.ml.artist_style_associations import AUTHORITY, StyleProfiles, duplicate_signature
from opennoise.ml.overlapping_source_styles import fit_overlapping_styles
from opennoise.ml.source_reobservation import (
    SCORE_EDGES,
    calibration_to_dict,
    fit_source_reobservation,
    score_bin,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from opennoise.analysis.emergent_community_evaluation import FeatureFact

COHORT_LIMIT = 25_000
COHORT_SALT = "bounded-source-reobservation-cohort-fixed-20261002-v1"
SPLIT_SALT = "source-reobservation-components-fixed-20261002-v1"
THRESHOLD = 0.1


def partition_components(
    facts: Iterable[FeatureFact],
) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """Assign whole canonical/value and globally shared release components to roles.

    Sixty percent of hashed components train; twenty percent calibrate; twenty
    percent test. Component sizes can make observed fractions differ.
    """
    rows = tuple(sorted(set(facts)))
    parent: dict[str, str] = {}

    def root(value: str) -> str:
        parent.setdefault(value, value)
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    pairs: dict[tuple[str, str], str] = {}
    for fact in rows:
        group = root(fact.evidence_group)
        other = root(pairs.setdefault((fact.artist_id, fact.feature_id), group))
        parent[max(group, other)] = min(group, other)
    roles: list[set[tuple[str, str]]] = [set(), set(), set()]
    evidence_roles: dict[str, int] = {}
    for fact in rows:
        digest = hashlib.sha256(f"{SPLIT_SALT}\0{root(fact.evidence_group)}".encode()).digest()
        bucket = int.from_bytes(digest, "big") % 5
        role = min(2, bucket)
        previous = evidence_roles.setdefault(fact.evidence_group, role)
        if previous != role:
            raise ValueError("source component crossed roles")
        roles[role].add((fact.artist_id, fact.feature_id))
    if roles[0] & roles[1] or roles[0] & roles[2] or roles[1] & roles[2]:
        raise ValueError("canonical source pair crossed roles")
    return roles[0], roles[1]


def cohort_profiles(
    source: Path,
) -> tuple[StyleProfiles, set[tuple[str, str]], set[tuple[str, str]]]:
    """Read only bounded hash-selected artists, preserving source roles and duplicates."""
    with source.open() as stream:
        artists = heapq.nsmallest(
            COHORT_LIMIT,
            (
                (
                    hashlib.sha256(
                        f"{COHORT_SALT}\0{json.loads(line)['artist_mbid']}".encode()
                    ).digest(),
                    json.loads(line)["artist_mbid"],
                )
                for line in stream
            ),
        )
    selected = {artist for _digest, artist in artists}
    facets: dict[str, dict[str, set[str]]] = {}
    facts = []
    with source.open() as stream:
        for line in stream:
            row = json.loads(line)
            artist = row["artist_mbid"]
            if artist not in selected:
                continue
            if artist in facets:
                raise ValueError("source repeats a selected artist")
            facets[artist] = {role: set() for role in AUTHORITY}
            for feature in row["features"]:
                if (value := musical_value(feature)) is None:
                    continue
                signature = duplicate_signature(value)
                if not signature or not feature.get("evidence_refs"):
                    raise ValueError("source music requires signature and provenance")
                facets[artist][feature["namespace"]].add(signature)
                facts.extend(_facts(artist, feature, signature))
    calibration, test = partition_components(facts)
    hidden: dict[str, set[str]] = {}
    for artist, value in calibration | test:
        hidden.setdefault(artist, set()).add(value)
    music, primary, tags, proper, authority = {}, {}, {}, {}, {}
    for artist, roles in facets.items():
        for values in roles.values():
            values.difference_update(hidden.get(artist, ()))
        music[artist] = tuple(sorted(set().union(*roles.values())))
        primary[artist] = tuple(sorted(roles["artist_genre"] | roles["artist_tag"]))
        tags[artist] = tuple(sorted(roles["artist_tag"]))
        proper[artist] = tuple(sorted(roles["artist_genre"]))
        authority[artist] = {
            value: max(AUTHORITY[role] for role, values in roles.items() if value in values)
            for value in music[artist]
        }
    return (
        StyleProfiles(music, primary, tags, proper, authority, sha256_json(music)),
        calibration,
        test,
    )


def source_permission(source: Path, receipt_path: Path) -> dict[str, object]:
    """Require explicit local research authorization on the exact feature projection.

    This does not rewrite upstream custody or training flags, and no license
    name by itself authorizes fitting. Public promotion remains prohibited.
    """
    receipt = json.loads(receipt_path.read_bytes())
    source_sha = sha256_file(source)[0]
    if (
        receipt.get("feature_sha256") != source_sha
        or receipt.get("research_model_input_authorized") is not True
        or receipt.get("research_model_scope") != "local_noncommercial_research"
        or receipt.get("public_export_authorized") is not False
        or receipt.get("training_authorized") is False
        or not receipt.get("derived_output_obligations")
    ):
        raise ValueError("exact source projection lacks local research authorization")
    return {
        "source_sha256": source_sha,
        "source_projection_receipt_path": str(receipt_path),
        "source_projection_receipt_sha256": sha256_file(receipt_path)[0],
        "research_model_input_authorized": True,
        "research_model_scope": "local_noncommercial_research",
        "public_export_authorized": False,
        "derived_output_obligations": receipt["derived_output_obligations"],
        "authorization_basis": "exact feature projection receipt; upstream flags unchanged",
    }


def evaluate(  # noqa: C901, PLR0915 - immutable experiment boundary.
    source: Path, output: Path, *, source_receipt: Path | None = None
) -> dict[str, object]:
    """Freeze declaration, scorer and calibration, then reveal the untouched test events."""
    permission = source_permission(source, source_receipt or source.parent / "receipt.json")
    require_local_candidate_destination(output)
    output.mkdir(parents=True, exist_ok=False)
    project = Path(__file__).resolve().parents[1]
    paths = [
        Path(__file__),
        *[
            project / "src/opennoise" / name
            for name in (
                "ml/source_reobservation.py",
                "ml/overlapping_source_styles.py",
                "ml/artist_style_associations.py",
                "ml/artist_feature_enrichment.py",
                "ml/emergent_topics.py",
                "analysis/emergent_topic_holdout.py",
                "analysis/emergent_community_evaluation.py",
            )
        ],
    ]
    frozen = output / "frozen-code"
    frozen.mkdir()
    for path in paths:
        (frozen / path.name).write_bytes(path.read_bytes())
    declaration = {
        **permission,
        "cohort_limit": COHORT_LIMIT,
        "cohort_salt": COHORT_SALT,
        "split_salt": SPLIT_SALT,
        "component_assignment": "hash-modulo-5: calibration=0, test=1, training=2..4",
        "rarity_power": 0.35,
        "score_edges": SCORE_EDGES,
        "minimum_source_detection_rate": THRESHOLD,
        "target_event": "nominated value detected in held source component",
        "absence_is_semantic_negative": False,
        "historical_inputs_used": False,
        "audio_used": False,
        "public_export_authorized": False,
        "source_license": "optional MusicBrainz CC-BY-NC-SA tag/genre research pack",
        "implementation": {str(p.relative_to(project)): sha256_file(p)[0] for p in paths},
    }
    (output / "declaration.json").write_bytes(canonical_json(declaration) + b"\n")
    profiles, calibration_pairs, test_pairs = cohort_profiles(source)
    model = fit_overlapping_styles(profiles, rarity_power=0.35)
    sparse.save_npz(output / "associations.npz", model.associations)
    (output / "vocabulary.json").write_bytes(canonical_json(model.vocabulary) + b"\n")
    scorer_sha = sha256_json(
        {
            "training_sha256": profiles.input_sha256,
            "associations_sha256": sha256_file(output / "associations.npz")[0],
            "vocabulary_sha256": sha256_file(output / "vocabulary.json")[0],
            "rarity_power": 0.35,
        }
    )
    artists = tuple(sorted(profiles.music))
    scored = {}
    for start in range(0, len(artists), MAX_BATCH):
        scored.update(model.score_batch(profiles, artists[start : start + MAX_BATCH]))
    calibration = fit_source_reobservation(
        (
            (score, (artist, value) in calibration_pairs)
            for artist, values in scored.items()
            for value, score in values
        ),
        source_sha256=str(declaration["source_sha256"]),
        scorer_sha256=scorer_sha,
        split_salt=SPLIT_SALT,
    )
    (output / "calibration.json").write_bytes(
        canonical_json(calibration_to_dict(calibration)) + b"\n"
    )
    # No test targets have entered fitting, score bins, shrinkage or threshold choice.
    proposed = {
        artist: tuple(
            str(row["value"])
            for row in calibration.proposals(values, minimum_detection_rate=THRESHOLD)
        )
        for artist, values in scored.items()
    }
    raw = {artist: tuple(value for value, _score in values) for artist, values in scored.items()}
    counts = {name: Counter() for name in ("frozen_overlap_0.35", "calibrated_abstention_0.1")}
    support = Counter(value for values in profiles.music.values() for value in values)
    with (
        (output / "outcomes.jsonl.gz").open("xb") as file,
        gzip.GzipFile(filename="", fileobj=file, mode="wb", mtime=0) as stream,
    ):
        for artist, value in sorted(test_pairs):
            strata = ["all", "training_seen" if support[value] else "training_unseen"]
            if not profiles.artist_music[artist]:
                strata.append("primary_cold")
            ranks = {}
            for name, ranking in (
                ("frozen_overlap_0.35", raw),
                ("calibrated_abstention_0.1", proposed),
            ):
                rank = ranking[artist].index(value) + 1 if value in ranking[artist] else 0
                ranks[name] = rank
                for stratum in strata:
                    counts[name][stratum + ":positives"] += 1
                    counts[name][stratum + ":hits"] += bool(rank)
            stream.write(
                canonical_json({"artist": artist, "value": value, "strata": strata, "ranks": ranks})
                + b"\n"
            )
    bins: list[dict[str, float]] = [
        {"nominated": 0, "detected": 0, "predicted_sum": 0} for _edge in SCORE_EDGES
    ]
    brier, constant_brier, evaluated, unsupported = 0.0, 0.0, 0, 0
    with (
        (output / "scored-nominations.jsonl.gz").open("xb") as file,
        gzip.GzipFile(filename="", fileobj=file, mode="wb", mtime=0) as stream,
    ):
        for artist, values in scored.items():
            for value, score in values:
                rate, calibration_support = calibration.estimate(score)
                event = (artist, value) in test_pairs
                stream.write(
                    canonical_json(
                        {
                            "artist": artist,
                            "value": value,
                            "score": score,
                            "held_source_detection_rate": rate,
                            "calibration_support": calibration_support,
                            "test_source_detected": event,
                            "retained": value in proposed[artist],
                            "absence_is_semantic_negative": False,
                        }
                    )
                    + b"\n"
                )
                if rate is None:
                    unsupported += 1
                    continue
                brier += (rate - event) ** 2
                constant_brier += (calibration.global_rate - event) ** 2
                evaluated += 1
                cell = bins[score_bin(score)]
                cell["nominated"] += 1
                cell["detected"] += event
                cell["predicted_sum"] += rate
    metrics = {}
    for name, count in counts.items():
        metrics[name] = {
            stratum: {
                "positives": count[stratum + ":positives"],
                "hits": count[stratum + ":hits"],
                "recall_at_10": count[stratum + ":hits"] / count[stratum + ":positives"],
            }
            for stratum in ("all", "training_seen", "training_unseen", "primary_cold")
            if count[stratum + ":positives"]
        }
    eligible = sum(bool(values) for values in profiles.artist_music.values())
    report = {
        "artist_count": len(artists),
        "eligible_primary_artist_count": eligible,
        "coverage_before_all_artists": sum(bool(v) for v in raw.values()) / len(artists),
        "coverage_after_all_artists": sum(bool(v) for v in proposed.values()) / len(artists),
        "coverage_before_eligible_artists": sum(bool(v) for v in raw.values()) / max(1, eligible),
        "coverage_after_eligible_artists": sum(bool(v) for v in proposed.values())
        / max(1, eligible),
        "test_held_source_detection_fraction_before": counts["frozen_overlap_0.35"]["all:hits"]
        / max(1, sum(len(v) for v in raw.values())),
        "test_held_source_detection_fraction_after": counts["calibrated_abstention_0.1"]["all:hits"]
        / max(1, sum(len(v) for v in proposed.values())),
        "detection_fraction_is_semantic_precision": False,
        "calibration_nominations_per_bin": calibration.nominated,
        "calibration_detections_per_bin": calibration.detected,
        "training_profile_sha256": profiles.input_sha256,
        "calibration_positive_count": len(calibration_pairs),
        "test_positive_count": len(test_pairs),
        "calibration_test_pair_overlap": len(calibration_pairs & test_pairs),
        "metrics": metrics,
        "nominated_candidates": sum(len(v) for v in raw.values()),
        "retained_candidates": sum(len(v) for v in proposed.values()),
        "covered_artists_before": sum(bool(v) for v in raw.values()),
        "covered_artists_after": sum(bool(v) for v in proposed.values()),
        "source_detection_brier": brier / max(1, evaluated),
        "constant_source_detection_brier": constant_brier / max(1, evaluated),
        "evaluated_nominations": evaluated,
        "thin_bin_abstentions": unsupported,
        "test_reliability_bins": bins,
        "calibration_global_detection_rate": calibration.global_rate,
        "independent_relevance_proven": False,
        "production_promotion": False,
        "source_calibration_transport_to_full_fit_proven": False,
        "files": {
            str(p.relative_to(output)): sha256_file(p)[0]
            for p in sorted(output.rglob("*"))
            if p.is_file()
        },
    }
    (output / "report.json").write_bytes(canonical_json(report) + b"\n")
    return report


def main() -> None:
    """Run only the explicit bounded local research experiment."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-receipt", type=Path)
    args = parser.parse_args()
    print(  # noqa: T201 - CLI report.
        json.dumps(
            evaluate(args.features, args.output, source_receipt=args.source_receipt), indent=2
        )
    )


if __name__ == "__main__":
    main()
