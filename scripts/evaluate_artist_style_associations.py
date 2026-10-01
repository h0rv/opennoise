"""Prespecified fresh nested source-tag reconstruction for authority-aware fine styles."""

from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from opennoise.analysis.emergent_topic_holdout import musical_value, partition_feature_file
from opennoise.catalog.musicbrainz_candidate import require_local_candidate_destination
from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.ml.artist_feature_enrichment import MAX_BATCH, EnrichmentSettings, fit_enrichment
from opennoise.ml.artist_style_associations import (
    AUTHORITY,
    FineStyleSettings,
    StyleAssociationModel,
    StyleProfiles,
    duplicate_signature,
    fit_style_associations,
    read_style_profiles,
    save_style_model,
)
from scripts.evaluate_artist_feature_enrichment import _baselines, _metrics

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

OUTER_SALT = "authority-aware-fine-style-outer-v1-fixed-20260930"
INNER_SALT = "authority-aware-fine-style-inner-v1-fixed-20260930"
EXAMPLE_LIMIT = 30
CANDIDATE_NAMES = ("default", "moderate", "strong")
CANDIDATES = (
    FineStyleSettings(),
    FineStyleSettings(
        smoothing=24,
        minimum_joint_support=4,
        minimum_anchor_coverage=0.55,
        minimum_association_lift=2.5,
    ),
    FineStyleSettings(
        smoothing=32,
        minimum_target_support=10,
        minimum_joint_support=5,
        minimum_anchor_coverage=0.6,
        minimum_association_lift=3,
        strongest_cues=1,
    ),
)


def _rank(model: StyleAssociationModel, profiles: StyleProfiles) -> dict[str, tuple[str, ...]]:
    artists = tuple(sorted(profiles.music))
    result: dict[str, tuple[str, ...]] = {}
    for start in range(0, len(artists), MAX_BATCH):
        result.update(model.rank_batch(profiles, artists[start : start + MAX_BATCH]))
    return result


def _held_artist_tags(source: Path, pairs: Sequence[tuple[str, str]]) -> set[tuple[str, str]]:
    targets = set(pairs)
    result = set()
    with source.open(encoding="utf-8") as stream:
        for line in stream:
            row = TypeAdapter(dict[str, object]).validate_json(line)
            artist = str(row["artist_mbid"])
            for feature in TypeAdapter(list[dict[str, object]]).validate_python(row["features"]):
                if (
                    feature["namespace"] == "artist_tag"
                    and (value := musical_value(feature)) is not None
                    and (artist, value) in targets
                ):
                    result.add((artist, value))
    return result


def _ranking_receipt(rankings: Mapping[str, Sequence[str]]) -> dict[str, object]:
    """Freeze a prediction identity without exporting artist-wide prediction data."""
    return {
        "rankings_sha256": sha256_json(rankings),
        "artist_count": len(rankings),
        "nonempty_artist_count": sum(bool(ranked) for ranked in rankings.values()),
        "proposal_count": sum(map(len, rankings.values())),
        "rank_limit": 10,
        "full_predictions_exported": False,
    }


def _write_target_outcomes(  # noqa: PLR0913 - explicit replay inputs for frozen positive ranks.
    destination: Path,
    *,
    rankings: Mapping[str, Mapping[str, Sequence[str]]],
    pairs: Sequence[tuple[str, str]],
    profiles: StyleProfiles,
    proper_values: set[str],
    tag_pairs: set[tuple[str, str]],
) -> None:
    """Save bounded held-positive ranks and source strata for independent metric replay."""
    music_frequency = Counter(value for values in profiles.music.values() for value in values)
    tag_frequency = Counter(value for values in profiles.artist_tags.values() for value in values)
    proper_signatures = {duplicate_signature(value) for value in proper_values}
    with (
        destination.open("xb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as stream,
    ):
        for artist, value in pairs:
            ranks = {}
            for name, predictions in rankings.items():
                ranked = tuple(predictions.get(artist, ()))[:10]
                ranks[name] = ranked.index(value) + 1 if value in ranked else None
            stream.write(
                canonical_json(
                    {
                        "artist_mbid": artist,
                        "value": value,
                        "rank_at_10": ranks,
                        "training_music_artist_support": music_frequency[value],
                        "training_artist_tag_support": tag_frequency[value],
                        "observed_music_value_count": len(profiles.music[artist]),
                        "observed_artist_primary_value_count": len(profiles.artist_music[artist]),
                        "source_proper_genre_value": value in proper_values,
                        "source_proper_genre_duplicate_signature": (
                            duplicate_signature(value) in proper_signatures
                        ),
                        "source_artist_tag_positive": (artist, value) in tag_pairs,
                    }
                )
                + b"\n"
            )


def _score(
    rankings: Mapping[str, Sequence[str]],
    pairs: Sequence[tuple[str, str]],
    profiles: StyleProfiles,
    proper_values: set[str],
    tag_pairs: set[tuple[str, str]],
) -> dict[str, dict[str, int | float | None]]:
    result = dict(_metrics(rankings, pairs, profiles.music, proper_values))
    frequency = Counter(value for values in profiles.artist_tags.values() for value in values)
    rare_limit = CANDIDATES[0].maximum_target_share * len(profiles.music)
    proper_signatures = {duplicate_signature(value) for value in proper_values}
    tag_only = [
        (artist, value)
        for artist, value in pairs
        if (artist, value) in tag_pairs and duplicate_signature(value) not in proper_signatures
    ]
    rare = [(artist, value) for artist, value in tag_only if frequency[value] <= rare_limit]
    for name, selected in (
        ("source_artist_tag_only", tag_only),
        ("rare_source_artist_tag_only", rare),
        (
            "artist_primary_cold",
            [(artist, value) for artist, value in pairs if not profiles.artist_music[artist]],
        ),
        (
            "one_primary_artist_value",
            [(artist, value) for artist, value in pairs if len(profiles.artist_music[artist]) == 1],
        ),
    ):
        hits = reciprocal = 0.0
        for artist, value in selected:
            ranked = tuple(rankings.get(artist, ()))[:10]
            if value in ranked:
                hits += 1
                reciprocal += 1 / (ranked.index(value) + 1)
        result[name] = {
            "positive_count": len(selected),
            "hits_at_10": int(hits),
            "recall_at_10": hits / len(selected) if selected else None,
            "mrr_at_10_per_positive": reciprocal / len(selected) if selected else None,
            "zero_training_support_positive_count": sum(
                frequency[value] == 0 for _, value in selected
            ),
            "artist_primary_cold_positive_count": sum(
                not profiles.artist_music[artist] for artist, _ in selected
            ),
        }
    return result


def evaluate_styles(*, features: Path, output: Path) -> dict[str, object]:  # noqa: PLR0915 - freeze nested split, selection, and scoring in one audited boundary.
    """Select only on inner rare-tag positives, then freeze before one outer scoring pass."""
    require_local_candidate_destination(output)
    if output.exists():
        raise FileExistsError("refusing to replace a frozen style experiment")
    output.mkdir(parents=True)
    project = Path(__file__).resolve().parents[1]
    paths = (
        Path(__file__),
        project / "src/opennoise/ml/artist_style_associations.py",
        project / "src/opennoise/ml/artist_feature_enrichment.py",
        project / "src/opennoise/ml/emergent_topics.py",
        project / "src/opennoise/analysis/emergent_topic_holdout.py",
        project / "src/opennoise/analysis/emergent_community_evaluation.py",
        project / "scripts/evaluate_artist_feature_enrichment.py",
    )
    bindings = {str(path): sha256_file(path)[0] for path in paths}
    frozen = output / "frozen-code"
    frozen.mkdir()
    for path in paths:
        (frozen / path.name).write_bytes(path.read_bytes())
    declaration = {
        "outer_salt": OUTER_SALT,
        "inner_salt": INNER_SALT,
        "source_sha256": sha256_file(features)[0],
        "implementation_bindings": bindings,
        "candidates": [asdict(settings) for settings in CANDIDATES],
        "candidate_names": CANDIDATE_NAMES,
        "cue_authority": AUTHORITY,
        "selection": "maximum_inner_rare_source_artist_tag_only_recall_at_10_then_candidate_order",
        "rare_target_definition": (
            "artist_tag_value_outside_source_proper_genre_duplicate_signatures_with_train_tag_artist_share_"
            "le_0.005_including_zero"
        ),
        "cold_and_unseen_positives_retained": True,
        "absence_is_negative": False,
        "prior_corpus_and_other_fold_exploration": True,
        "no_outer_reselection": True,
        "target_role": "source_artist_tag_style_candidate_not_native_or_taxonomy_truth",
        "rank_limit": 10,
        "baseline_smoothing": 4,
        "baseline_settings": asdict(EnrichmentSettings(smoothing=4)),
        "split_unit": "canonical_artist_value_components_and_global_release_groups",
        "full_predictions_exported": False,
        "held_positive_ranks_exported_for_independent_metric_replay": True,
        "model_target_gates_fitted_only_on_training_partition": True,
    }
    (output / "pre-fit-declaration.json").write_bytes(canonical_json(declaration) + b"\n")
    outer_file = output / "outer-training.jsonl"
    _, _, outer_targets, proper_values = partition_feature_file(
        features, outer_file, salt=OUTER_SALT
    )
    inner_file = output / "inner-training.jsonl"
    _, _, inner_targets, inner_proper_values = partition_feature_file(
        outer_file, inner_file, salt=INNER_SALT
    )
    inner = read_style_profiles(inner_file)
    inner_pairs = tuple(sorted({(fact.artist_id, fact.feature_id) for fact in inner_targets}))
    validation_rankings, model_diagnostics = [], []
    for index, settings in enumerate(CANDIDATES):
        model = fit_style_associations(inner, settings)
        ranking = _rank(model, inner)
        validation_rankings.append(ranking)
        model_diagnostics.append(
            {"target_count": len(model.targets), "association_count": model.associations.nnz}
        )
        (output / f"inner-ranking-receipt-{index}.json").write_bytes(
            canonical_json(_ranking_receipt(ranking)) + b"\n"
        )
    # Validation target facet roles are read only after every candidate ranking is frozen.
    inner_tag_pairs = _held_artist_tags(outer_file, inner_pairs)
    _write_target_outcomes(
        output / "inner-target-outcomes.jsonl.gz",
        rankings=dict(zip(CANDIDATE_NAMES, validation_rankings, strict=True)),
        pairs=inner_pairs,
        profiles=inner,
        proper_values=inner_proper_values,
        tag_pairs=inner_tag_pairs,
    )
    validation_metrics = [
        _score(ranking, inner_pairs, inner, inner_proper_values, inner_tag_pairs)
        for ranking in validation_rankings
    ]
    validation = [
        {
            "candidate_name": name,
            "settings": asdict(settings),
            "model": diagnostics,
            "metrics": metrics,
        }
        for name, settings, diagnostics, metrics in zip(
            CANDIDATE_NAMES, CANDIDATES, model_diagnostics, validation_metrics, strict=True
        )
    ]
    selected_index = max(
        range(len(CANDIDATES)),
        key=lambda index: (
            validation_metrics[index]["rare_source_artist_tag_only"]["recall_at_10"] or 0,
            -index,
        ),
    )
    settings = CANDIDATES[selected_index]
    (output / "selected-before-outer-scoring.json").write_bytes(
        canonical_json(
            {
                "candidate_index": selected_index,
                "candidate_name": CANDIDATE_NAMES[selected_index],
                "settings": asdict(settings),
                "validation": validation,
            }
        )
        + b"\n"
    )
    outer = read_style_profiles(outer_file)
    model = fit_style_associations(outer, settings)
    model_receipt = save_style_model(model, output / "selected-model")
    baseline = fit_enrichment(
        outer.music,
        outer.proper,
        settings=EnrichmentSettings(smoothing=4),
        training_sha256=outer.input_sha256,
    )
    baseline_rankings: dict[str, tuple[str, ...]] = {}
    artists = tuple(sorted(outer.music))
    for start in range(0, len(artists), MAX_BATCH):
        block = artists[start : start + MAX_BATCH]
        baseline_rankings.update(
            baseline.rank_batch(
                {artist: outer.music[artist] for artist in block},
                {artist: outer.proper[artist] for artist in block},
            )
        )
    rankings = {
        "authority_aware_style": _rank(model, outer),
        "frozen_artist_feature_enrichment": baseline_rankings,
        **_baselines(outer.music, outer.proper),
    }
    for name, ranking in rankings.items():
        (output / f"outer-ranking-receipt-{name}.json").write_bytes(
            canonical_json(_ranking_receipt(ranking)) + b"\n"
        )
    outer_pairs = tuple(sorted({(fact.artist_id, fact.feature_id) for fact in outer_targets}))
    (output / "outer-positive-receipt.json").write_bytes(
        canonical_json({"pair_count": len(outer_pairs), "pairs_sha256": sha256_json(outer_pairs)})
        + b"\n"
    )
    # All outer predictions are immutable before reading target namespaces or computing any metric.
    outer_tag_pairs = _held_artist_tags(features, outer_pairs)
    _write_target_outcomes(
        output / "outer-target-outcomes.jsonl.gz",
        rankings=rankings,
        pairs=outer_pairs,
        profiles=outer,
        proper_values=proper_values,
        tag_pairs=outer_tag_pairs,
    )
    examples = []
    with outer_file.open(encoding="utf-8") as stream:
        for line in stream:
            row = TypeAdapter(dict[str, object]).validate_json(line)
            if rankings["authority_aware_style"][str(row["artist_mbid"])]:
                examples.append(
                    {"artist_mbid": row["artist_mbid"], "proposals": model.proposals(row, outer)}
                )
                if len(examples) == EXAMPLE_LIMIT:
                    break
    (output / "source-explanation-examples.json").write_bytes(canonical_json(examples) + b"\n")
    if bindings != {str(path): sha256_file(path)[0] for path in paths}:
        raise ValueError("style experiment implementation changed during the frozen run")
    report: dict[str, object] = {
        "revision": "fresh-nested-authority-aware-style-evaluation-v1",
        "scope": "local_research_only",
        "public_export_authorized": False,
        "source_positive_reconstruction_not_sonic_or_taxonomy_gold": True,
        "source_sha256": declaration["source_sha256"],
        "prespecification": declaration,
        "source_artist_count": len(outer.music),
        "outer_positive_pair_count": len(outer_pairs),
        "inner_positive_pair_count": len(inner_pairs),
        "selected_candidate_name": CANDIDATE_NAMES[selected_index],
        "selected_settings": asdict(settings),
        "inner_validation": validation,
        "model_receipt": model_receipt,
        "outer_metrics": {
            name: _score(ranking, outer_pairs, outer, proper_values, outer_tag_pairs)
            for name, ranking in rankings.items()
        },
        "proposed_artist_count": sum(
            bool(ranking) for ranking in rankings["authority_aware_style"].values()
        ),
        "native_fact": False,
        "score_calibrated": False,
        "absence_is_negative": False,
        "all_copies_of_held_artist_value_removed": True,
        "global_release_group_components_kept_together": True,
        "cold_and_unseen_positives_retained": True,
        "test_based_reselection": False,
        "historical_inputs_used": False,
        "audio_used": False,
        "full_predictions_exported": False,
        "ranking_receipts": {name: _ranking_receipt(ranking) for name, ranking in rankings.items()},
        "artifacts": {
            path.name: sha256_file(path)[0] for path in sorted(output.iterdir()) if path.is_file()
        },
    }
    report["output_sha256"] = sha256_json(report)
    (output / "report.json").write_bytes(canonical_json(report) + b"\n")
    return report


def main() -> None:
    """Require source-only features and a fresh local experiment directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = evaluate_styles(features=args.features, output=args.output)
    print(  # noqa: T201 - local research diagnostics.
        json.dumps(
            {
                "selected_settings": report["selected_settings"],
                "outer_metrics": report["outer_metrics"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
