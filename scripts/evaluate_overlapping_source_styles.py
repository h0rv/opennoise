"""Run two frozen overlap hypotheses on a fresh canonical evidence-group holdout."""

from __future__ import annotations

import argparse
import gzip
import io
import json
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from opennoise.analysis.emergent_community_evaluation import split_feature_evidence
from opennoise.analysis.emergent_topic_holdout import _facts, musical_value
from opennoise.catalog.musicbrainz_candidate import require_local_candidate_destination
from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.ml.artist_feature_enrichment import MAX_BATCH, EnrichmentSettings, fit_enrichment
from opennoise.ml.artist_style_associations import AUTHORITY, StyleProfiles, duplicate_signature
from opennoise.ml.overlapping_source_styles import fit_overlapping_styles

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

SALT = "overlapping-source-style-signature-components-fixed-20261001-v1"
CANDIDATES = (0.15, 0.35)
CONFIRMATION_SALT = "overlapping-source-style-disjoint-confirmation-fixed-20261001-v1"


def partition(
    source: Path,
    *,
    confirmation: bool = False,
) -> tuple[StyleProfiles, list[tuple[str, str]], set[tuple[str, str]], set[str]]:
    """Split shared release groups and whole punctuation-normalized artist/value units."""
    facets: dict[str, dict[str, set[str]]] = {}
    facts = []
    with source.open() as stream:
        for line in stream:
            row = json.loads(line)
            artist = row["artist_mbid"]
            if not artist or artist in facets:
                raise ValueError("source artist identities must be unique and nonempty")
            facets[artist] = {role: set() for role in AUTHORITY}
            for feature in row["features"]:
                value = musical_value(feature)
                if value is None:
                    continue
                signature = duplicate_signature(value)
                if not signature or not feature.get("evidence_refs"):
                    raise ValueError("music evidence requires a value and exact provenance")
                facets[artist][feature["namespace"]].add(signature)
                facts.extend(_facts(artist, feature, signature))
    _, hidden = split_feature_evidence(facts, salt=SALT)
    if confirmation:
        explored = {(fact.artist_id, fact.feature_id) for fact in hidden}
        _, fresh = split_feature_evidence(facts, salt=CONFIRMATION_SALT)
        hidden = tuple(fact for fact in fresh if (fact.artist_id, fact.feature_id) not in explored)
    pairs = sorted({(fact.artist_id, fact.feature_id) for fact in hidden})
    withheld: dict[str, set[str]] = {}
    for artist, value in pairs:
        withheld.setdefault(artist, set()).add(value)
    source_tags = {
        (artist, value) for artist, roles in facets.items() for value in roles["artist_tag"]
    }
    source_proper = {value for roles in facets.values() for value in roles["artist_genre"]}
    music, primary, tags, proper, authority = {}, {}, {}, {}, {}
    for artist, roles in facets.items():
        for values in roles.values():
            values.difference_update(withheld.get(artist, ()))
        music[artist] = tuple(sorted(set().union(*roles.values())))
        primary[artist] = tuple(sorted(roles["artist_genre"] | roles["artist_tag"]))
        tags[artist] = tuple(sorted(roles["artist_tag"]))
        proper[artist] = tuple(sorted(roles["artist_genre"]))
        authority[artist] = {
            value: max(AUTHORITY[role] for role, values in roles.items() if value in values)
            for value in music[artist]
        }
    profiles = StyleProfiles(music, primary, tags, proper, authority, sha256_json(music))
    return profiles, pairs, source_tags, source_proper


def outcomes(  # noqa: C901, PLR0913, PLR0917 - explicit frozen evaluation strata.
    path: Path,
    profiles: StyleProfiles,
    pairs: Sequence[tuple[str, str]],
    rankings: Mapping[str, Mapping[str, Sequence[str]]],
    source_tags: set[tuple[str, str]],
    source_proper: set[str],
) -> dict[str, dict[str, dict[str, float | int]]]:
    """Retain every positive rank and replayable strata, including unseen/cold cases."""
    support = Counter(value for row in profiles.artist_tags.values() for value in row)
    all_support = Counter(value for row in profiles.music.values() for value in row)
    family_support = Counter(value for row in profiles.proper.values() for value in row)
    families = {value for value, _ in family_support.most_common(20)}
    metrics: dict[str, dict[str, dict[str, float | int]]] = {}
    with (
        path.open("xb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed,
        io.TextIOWrapper(compressed, encoding="utf-8") as stream,
    ):
        for artist, value in pairs:
            strata = ["all", "training_seen" if all_support[value] else "training_unseen"]
            if value in source_proper:
                strata.append("source_proper_genre")
            strata.extend(
                f"observed_family:{family}"
                for family in profiles.proper[artist]
                if family in families
            )
            if not profiles.proper[artist]:
                strata.append("without_observed_proper_genre")
            if (artist, value) in source_tags and value not in source_proper:
                strata.append("artist_tag_only")
                if support[value] <= 0.005 * len(profiles.music):
                    strata.append("rare_artist_tag_only")
            if not profiles.artist_music[artist]:
                strata.append("primary_cold")
            ranks = {}
            for name, ranking in rankings.items():
                predicted = ranking.get(artist, ())
                rank = predicted.index(value) + 1 if value in predicted else 0
                ranks[name] = rank
                for stratum in strata:
                    cell = metrics.setdefault(name, {}).setdefault(
                        stratum, {"positives": 0, "hits": 0, "reciprocal_sum": 0.0}
                    )
                    cell["positives"] += 1
                    cell["hits"] += bool(rank)
                    cell["reciprocal_sum"] += 1 / rank if rank else 0
            stream.write(
                json.dumps({"artist": artist, "value": value, "strata": strata, "ranks": ranks})
                + "\n"
            )
    for method in metrics.values():
        for cell in method.values():
            cell["recall_at_10"] = cell["hits"] / cell["positives"]
            cell["mrr_at_10"] = cell["reciprocal_sum"] / cell["positives"]
    return metrics


def evaluate(source: Path, output: Path, *, confirmation: bool = False) -> dict[str, object]:
    """Seal declaration before splitting; report all hypotheses without held-out selection."""
    require_local_candidate_destination(output)
    output.mkdir(parents=True, exist_ok=False)
    project = Path(__file__).resolve().parents[1]
    paths = [
        Path(__file__),
        *(
            project / "src/opennoise" / value
            for value in (
                "ml/overlapping_source_styles.py",
                "ml/artist_feature_enrichment.py",
                "ml/artist_style_associations.py",
                "ml/emergent_topics.py",
                "analysis/emergent_topic_holdout.py",
                "analysis/emergent_community_evaluation.py",
            )
        ),
    ]
    frozen = output / "frozen-code"
    frozen.mkdir()
    for path in paths:
        (frozen / path.name).write_bytes(path.read_bytes())
    declaration = {
        "salt": CONFIRMATION_SALT if confirmation else SALT,
        "confirmation_disjoint_from_exploratory_targets": confirmation,
        "selection_source": "exploratory run rare-tag result" if confirmation else "none",
        "source_sha256": sha256_file(source)[0],
        "candidate_rarity_powers": (0.35,) if confirmation else CANDIDATES,
        "selection": "none; report both fixed hypotheses",
        "implementation": {str(path.relative_to(project)): sha256_file(path)[0] for path in paths},
        "split": "canonical artist-value signature components and global release groups",
        "canonicalization": "case-normalized musical value with punctuation and spaces removed",
        "scope": "local research only",
        "audio_used": False,
        "historical_inputs_used": False,
        "independent_relevance": "not measured; no independent listener/artifact gold used",
        "corpus_previously_explored": True,
    }
    (output / "declaration.json").write_bytes(canonical_json(declaration) + b"\n")
    profiles, pairs, source_tags, source_proper = partition(source, confirmation=confirmation)
    artists = tuple(sorted(profiles.music))
    rankings = {}
    diagnostics = {}
    for power in (0.35,) if confirmation else CANDIDATES:
        model = fit_overlapping_styles(profiles, rarity_power=power)
        name = f"overlap_{power}"
        rankings[name] = {}
        for start in range(0, len(artists), MAX_BATCH):
            rankings[name].update(model.rank_batch(profiles, artists[start : start + MAX_BATCH]))
        diagnostics[name] = {
            "communities": len(model.vocabulary),
            "associations": model.associations.nnz,
        }
        print(name, diagnostics[name], flush=True)  # noqa: T201 - experiment progress.
    baseline = fit_enrichment(
        profiles.music, profiles.proper, settings=EnrichmentSettings(smoothing=4)
    )
    rankings["enrichment_4"] = {}
    for start in range(0, len(artists), MAX_BATCH):
        batch = artists[start : start + MAX_BATCH]
        rankings["enrichment_4"].update(
            baseline.rank_batch(
                {artist: profiles.music[artist] for artist in batch},
                {artist: profiles.proper[artist] for artist in batch},
            )
        )
    metrics = outcomes(
        output / "outcomes.jsonl.gz", profiles, pairs, rankings, source_tags, source_proper
    )
    report = {
        "declaration_sha256": sha256_file(output / "declaration.json")[0],
        "training_profile_sha256": profiles.input_sha256,
        "artist_count": len(artists),
        "positive_count": len(pairs),
        "ranking_sha256": {name: sha256_json(ranking) for name, ranking in rankings.items()},
        "outcomes_sha256": sha256_file(output / "outcomes.jsonl.gz")[0],
        "diagnostics": diagnostics,
        "metrics": metrics,
        "independent_relevance_proven": False,
        "production_promotion": False,
    }
    (output / "report.json").write_bytes(canonical_json(report) + b"\n")
    return report


def main() -> None:
    """Run the frozen local experiment from explicit source and output paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--confirmation", action="store_true")
    args = parser.parse_args()
    print(  # noqa: T201 - CLI report.
        json.dumps(evaluate(args.features, args.output, confirmation=args.confirmation), indent=2)
    )


if __name__ == "__main__":
    main()
