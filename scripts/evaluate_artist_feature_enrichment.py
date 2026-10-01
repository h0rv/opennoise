"""Run a prespecified nested, duplicate-safe source-feature enrichment experiment."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from scipy import sparse

from opennoise.analysis.emergent_topic_holdout import (
    _binary,
    partition_feature_file,
    rank_positive_features,
)
from opennoise.catalog.musicbrainz_candidate import require_local_candidate_destination
from opennoise.common import canonical_json, sha256_file
from opennoise.ml.artist_feature_enrichment import (
    MAX_BATCH,
    EnrichmentModel,
    EnrichmentSettings,
    fit_enrichment,
    save_enrichment,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

OUTER_SALT = "artist-feature-enrichment-outer-v1-20260930"
INNER_SALT = "artist-feature-enrichment-inner-v1-20260930"
CANDIDATES = tuple(EnrichmentSettings(smoothing=value) for value in (4, 16, 64))
RARE_SUPPORT_LIMIT = 5
SPARSE_EXAMPLE_DEGREE = 2
EXAMPLE_LIMIT = 30


def _rankings(
    model: EnrichmentModel, profiles: dict[str, tuple[str, ...]], proper: dict[str, tuple[str, ...]]
) -> dict[str, tuple[str, ...]]:
    artists = tuple(sorted(profiles))
    result: dict[str, tuple[str, ...]] = {}
    for start in range(0, len(artists), MAX_BATCH):
        block = artists[start : start + MAX_BATCH]
        result.update(
            model.rank_batch(
                {artist: profiles[artist] for artist in block},
                {artist: proper[artist] for artist in block},
            )
        )
    return result


def _baselines(
    profiles: dict[str, tuple[str, ...]], proper: dict[str, tuple[str, ...]]
) -> dict[str, dict[str, tuple[str, ...]]]:
    artists = tuple(sorted(profiles))
    vocabulary = tuple(sorted({value for values in profiles.values() for value in values}))
    genres = tuple(sorted({value for values in proper.values() for value in values}))
    observed = _binary(artists, profiles, vocabulary)
    genre_matrix = _binary(artists, proper, genres)
    counts = np.asarray(genre_matrix.sum(axis=0)).ravel()
    conditional = (sparse.diags(1 / np.maximum(1, counts)) @ genre_matrix.T @ observed).tocsr()
    frequency = np.asarray(observed.sum(axis=0)).ravel()
    result: dict[str, dict[str, tuple[str, ...]]] = {
        "global_frequency": {},
        "proper_genre_conditional": {},
    }
    for start in range(0, len(artists), MAX_BATCH):
        end = min(start + MAX_BATCH, len(artists))
        scores = (genre_matrix[start:end] @ conditional).toarray()
        cold = np.asarray(genre_matrix[start:end].sum(axis=1)).ravel() == 0
        scores[cold] = frequency
        for local, row in enumerate(range(start, end)):
            known = observed.indices[observed.indptr[row] : observed.indptr[row + 1]]
            result["global_frequency"][artists[row]] = tuple(
                vocabulary[column] for column in rank_positive_features(frequency, known)
            )
            result["proper_genre_conditional"][artists[row]] = tuple(
                vocabulary[column] for column in rank_positive_features(scores[local], known)
            )
    return result


def _metrics(
    rankings: Mapping[str, Sequence[str]],
    pairs: Sequence[tuple[str, str]],
    profiles: Mapping[str, Sequence[str]],
    proper_values: set[str],
) -> dict[str, dict[str, int | float | None]]:
    counts = Counter(value for values in profiles.values() for value in values)
    totals: dict[str, list[float]] = defaultdict(lambda: [0, 0, 0])
    for artist, value in pairs:
        ranked = tuple(rankings.get(artist, ()))[:10]
        rank = ranked.index(value) + 1 if value in ranked else None
        strata = ["all", "proper_genre_values" if value in proper_values else "tag_only_values"]
        if len(profiles[artist]) == 1:
            strata.append("one_observed_value")
        if not profiles[artist]:
            strata.append("cold_artist")
        if counts[value] <= RARE_SUPPORT_LIMIT:
            strata.append("rare_training_support_le5")
        if counts[value] == 0:
            strata.append("unseen_feature")
        for stratum in strata:
            totals[stratum][0] += 1
            totals[stratum][1] += int(rank is not None)
            totals[stratum][2] += 1 / rank if rank is not None else 0
    return {
        stratum: {
            "positive_count": int(values[0]),
            "hits_at_10": int(values[1]),
            "recall_at_10": values[1] / values[0] if values[0] else None,
            "mrr_at_10_per_positive": values[2] / values[0] if values[0] else None,
        }
        for stratum, values in sorted(totals.items())
    }


def evaluate(features: Path, output: Path) -> dict[str, object]:
    """Select on inner validation, freeze, then score one fresh outer split exactly once."""
    require_local_candidate_destination(output)
    if output.exists():
        raise FileExistsError("refusing to replace a frozen nested evaluation")
    output.mkdir(parents=True)
    project = Path(__file__).resolve().parents[1]
    paths = [
        Path(__file__),
        project / "src/opennoise/ml/artist_feature_enrichment.py",
        project / "src/opennoise/ml/emergent_topics.py",
        project / "src/opennoise/analysis/emergent_topic_holdout.py",
        project / "src/opennoise/analysis/emergent_community_evaluation.py",
    ]
    bindings = {str(path): sha256_file(path)[0] for path in paths}
    declaration = {
        "outer_salt": OUTER_SALT,
        "inner_salt": INNER_SALT,
        "candidates": [asdict(candidate) for candidate in CANDIDATES],
        "default_smoothing": 16,
        "selection": "maximum_inner_all_positive_recall_at_10_then_lower_smoothing",
        "source_sha256": sha256_file(features)[0],
        "implementation_bindings": bindings,
        "prior_corpus_and_other_split_exploration": True,
        "rank_limit": 10,
        "no_outer_reselection": True,
        "split_unit": "canonical_artist_value_components_and_global_release_groups",
    }
    (output / "pre-fit-declaration.json").write_bytes(canonical_json(declaration) + b"\n")
    outer_file = output / "outer-training.jsonl"
    outer_profiles, outer_proper, outer_targets, proper_values = partition_feature_file(
        features, outer_file, salt=OUTER_SALT
    )
    inner_file = output / "inner-training.jsonl"
    inner_profiles, inner_proper, inner_targets, inner_proper_values = partition_feature_file(
        outer_file, inner_file, salt=INNER_SALT
    )
    inner_pairs = tuple(sorted({(fact.artist_id, fact.feature_id) for fact in inner_targets}))
    validation = []
    for settings in CANDIDATES:
        model = fit_enrichment(
            inner_profiles,
            inner_proper,
            settings=settings,
            training_sha256=sha256_file(inner_file)[0],
        )
        rankings = _rankings(model, inner_profiles, inner_proper)
        (output / f"inner-rankings-smoothing-{int(settings.smoothing)}.json").write_bytes(
            canonical_json(rankings) + b"\n"
        )
        validation.append(
            {
                "settings": asdict(settings),
                "metrics": _metrics(rankings, inner_pairs, inner_profiles, inner_proper_values),
            }
        )
    chosen = max(
        range(len(CANDIDATES)),
        key=lambda index: (
            validation[index]["metrics"]["all"]["recall_at_10"],
            -CANDIDATES[index].smoothing,
        ),
    )
    selected = CANDIDATES[chosen]
    (output / "selected-before-outer-scoring.json").write_bytes(
        canonical_json({"settings": asdict(selected), "validation": validation}) + b"\n"
    )
    model = fit_enrichment(
        outer_profiles, outer_proper, settings=selected, training_sha256=sha256_file(outer_file)[0]
    )
    model_receipt = save_enrichment(model, output / "selected-model")
    rankings = {
        "artist_feature_enrichment": _rankings(model, outer_profiles, outer_proper),
        **_baselines(outer_profiles, outer_proper),
    }
    for name, ranking in rankings.items():
        (output / f"outer-rankings-{name}.json").write_bytes(canonical_json(ranking) + b"\n")
    # Outer positives enter metric calculation only after all rankings have been written.
    outer_pairs = tuple(sorted({(fact.artist_id, fact.feature_id) for fact in outer_targets}))
    (output / "outer-positive-pairs.json").write_bytes(canonical_json(outer_pairs) + b"\n")
    examples = []
    with outer_file.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            artist = row["artist_mbid"]
            if (
                0 < len(outer_profiles[artist]) <= SPARSE_EXAMPLE_DEGREE
                and rankings["artist_feature_enrichment"][artist]
            ):
                examples.append(
                    {
                        "artist_mbid": artist,
                        "observed_values": outer_profiles[artist],
                        "proposals": model.proposals(row, limit=3),
                    }
                )
                if len(examples) == EXAMPLE_LIMIT:
                    break
    (output / "source-explanation-examples.json").write_bytes(canonical_json(examples) + b"\n")
    if bindings != {str(path): sha256_file(path)[0] for path in paths}:
        raise ValueError("implementation changed during frozen nested evaluation")
    report = {
        "revision": "nested-artist-feature-enrichment-evaluation-v1",
        "scope": "local_research_only",
        "evaluation_role": "new_split_on_previously_explored_corpus_within_source_reconstruction",
        "independent_source_gold": False,
        "absence_is_negative": False,
        "historical_inputs_used": False,
        "audio_used": False,
        "source_artist_count": len(outer_profiles),
        "outer_positive_pair_count": len(outer_pairs),
        "inner_positive_pair_count": len(inner_pairs),
        "selected_settings": asdict(selected),
        "prespecification": declaration,
        "inner_validation": validation,
        "model_receipt": model_receipt,
        "outer_metrics": {
            name: _metrics(ranking, outer_pairs, outer_profiles, proper_values)
            for name, ranking in rankings.items()
        },
        "cold_positives_retained": True,
        "unseen_positives_retained": True,
        "all_duplicate_facets_removed_before_fit": True,
        "source_scores_calibrated": False,
        "shared_artist_response_values_may_straddle_split": True,
        "artifacts": {
            path.name: sha256_file(path)[0] for path in sorted(output.iterdir()) if path.is_file()
        },
    }
    (output / "report.json").write_bytes(canonical_json(report) + b"\n")
    return report


def main() -> None:
    """Require local immutable source features and a fresh research destination."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = evaluate(args.features, args.output)
    print(  # noqa: T201 - research CLI diagnostics.
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
