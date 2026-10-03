"""Freeze a source-aware human musical review cohort from all native FMA metadata."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

import zstandard

SEED = 20261003
TRACKS_SHA256 = "2a51ad101f8972182475a4e162efbc5604eee127b80089abd5ee10c64a56b687"
ARTISTS_SHA256 = "98bd5b614664f98bc70d40d913219b0eb34ff454f33fc2c9ccfbc21f3a67507a"
FOLDS_SHA256 = "a43584aeb88c874576b2e7a84a25a2ebd1908385935f1c2a20b84e1273642ea7"
GENRES_SHA256 = "e355ffdc5aede4cbfb98098c4be39959493392c43a7d82ee3e1fd447a88b02cd"
COHORT_SIZE = 240
FULL_TRACK_COUNT = 109727
QUERY_COUNT = 240


@dataclass(frozen=True)
class ReviewSources:
    """Input paths and options that define a frozen review packet build."""

    tracks: Path
    artists: Path
    folds: Path
    output: Path
    track_ids: Path | None = None
    size: int = COHORT_SIZE
    sonic_queries: Path | None = None
    membership_results: Path | None = None
    genres: Path | None = None
    calibration_results: Path | None = None


@dataclass(frozen=True)
class ReviewContext:
    """Bounded exact metadata and component joins for frozen validation queries."""

    query_rows: list[dict[str, Any]]
    source_by_id: dict[int, dict[str, Any]]
    artists: dict[int, dict[str, Any]]
    folds: dict[int, dict[str, Any]]
    tracks_hash: str


@dataclass(frozen=True)
class FrozenPopulation:
    """Selected rows and source-level statistics retained after streaming."""

    selected: list[dict[str, Any]]
    artists: dict[int, dict[str, Any]]
    folds: dict[int, dict[str, Any]]
    source_by_id: dict[int, dict[str, Any]]
    query_rows: list[dict[str, Any]]
    artist_track_counts: Counter[int]
    strata_denominators: Counter[tuple[str, str, str]]
    track_count: int
    artist_cuts: tuple[int, int]
    genre_cuts: tuple[int, int]
    hashes: tuple[str, str, str]
    stratum: Callable[[dict[str, Any]], tuple[str, str, str]]


def read_jsonl_zst(path: Path) -> list[dict[str, Any]]:
    """Read a bounded auxiliary FMA member (artists or taxonomy), not tracks."""
    with zstandard.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def iter_jsonl_zst(path: Path) -> Iterator[dict[str, Any]]:
    """Yield one native source row at a time to bound peak memory."""
    with zstandard.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def digest(path: Path) -> str:
    """Return a streaming SHA-256 digest for a source or generated file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_manifest(directory: Path) -> None:
    """Bind a review packet directory to the exact hashes of its files."""
    files = {
        path.relative_to(directory).as_posix(): digest(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    }
    (directory / "manifest.json").write_text(
        json.dumps({"sha256": files}, indent=2, sort_keys=True) + "\n"
    )


def build_validation_review(
    sources: ReviewSources,
    context: ReviewContext,
) -> dict[str, Any] | None:
    """Build method-blind retrieval and candidate-membership review packets."""
    query_summary = None
    query_rows = context.query_rows
    sonic_queries_path = sources.sonic_queries
    membership_results_path = sources.membership_results
    genres_path = sources.genres
    output = sources.output
    if sonic_queries_path:
        qdir = output.parent / "fma-validation-query-review"
        qdir.mkdir(parents=True, exist_ok=True)
        qcoord = qdir.parent / (qdir.name + "-coordinator")
        qcoord.mkdir(parents=True, exist_ok=True)
        ordered_query_rows = list(query_rows)
        random.Random(SEED ^ 0x3D91).shuffle(ordered_query_rows)  # noqa: S311
        review_queries, method_key, q_assignments = _query_rows(ordered_query_rows, context)
        query_declaration = {
            "revision": "fma-sonic-neighbor-independent-review-v1",
            "source_queries": str(sonic_queries_path),
            "source_queries_sha256": digest(sonic_queries_path),
            "denominator": 7332,
            "denominator_scope": (
                "all known validation queries in frozen leakage-aware component split; this "
                "review sample uses the 240 query IDs frozen by the acoustic retrieval report"
            ),
            "sample_size": len(review_queries),
            "query_order_seed": SEED ^ 0x3D91,
            "candidate_order": (
                "per-query deterministic SHA-independent PRNG seed string; A/B/C labels "
                "randomized with assignment key separated"
            ),
            "candidate_construction": (
                "one top-ranked track per each of two compared methods and fixed-order "
                "control; candidate slots randomized deterministically; method and "
                "source-label key stored separately"
            ),
            "reviewers_per_item": 2,
            "rater_scale": {
                "fit_1_5": (
                    "1 does not fit; 2 mostly does not fit; 3 mixed/uncertain; 4 good fit; 5 very "
                    "strong fit"
                ),
                "confidence_1_5": "1 very unsure to 5 very high confidence",
            },
            "frozen_judgment_coding": {
                "fit_positive": "both reviewers >=4 and neither unsure/unsupported",
                "otherwise": "retain mixed/indeterminate and original rows",
                "method_preference": (
                    "explicit reviewer preference only; preserve ties/neither/abstention"
                ),
            },
            "limitations": [
                "Candidate retrieval ranking alone is not musical truth.",
                "FMA-native IDs are not bridged to MusicBrainz.",
                (
                    "Genre annotations are hidden and source-positive values are stored only in "
                    "coordinator key."
                ),
                (
                    "Audio access, exact playback match, per-track permission and regional/date "
                    "availability are unverified."
                ),
                (
                    "FMA is an endogenous 2017 source; unknown region, language and era "
                    "remain unknown."
                ),
            ],
        }
        (qdir / "declaration.json").write_text(
            json.dumps(query_declaration, indent=2, sort_keys=True) + "\n"
        )
        (qdir / "queries.json").write_text(
            json.dumps({"queries": review_queries}, indent=2, sort_keys=True) + "\n"
        )
        (qdir / "reviewer-assignments.json").write_text(json.dumps(q_assignments, indent=2) + "\n")
        with (qdir / "neighbor-review-form.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "item_id",
                    "reviewer_slot",
                    "reviewer_id",
                    "familiarity_0_4",
                    "conflict_description",
                    "preferred_candidate_A_B_C_tie_neither",
                    "candidate_A_sonic_fit_1_5",
                    "candidate_B_sonic_fit_1_5",
                    "candidate_C_sonic_fit_1_5",
                    "cultural_relevance_1_5",
                    "confidence_1_5",
                    "unsupported_query",
                    "unsure",
                    "access_failure",
                    "exact_audio_match",
                    "permitted_provider_urls",
                    "region_date_availability",
                    "notes",
                ],
            )
            w.writeheader()
            for row in review_queries:
                for slot in (1, 2):
                    w.writerow(
                        {
                            "item_id": row["item_id"],
                            "reviewer_slot": slot,
                            "reviewer_id": "",
                            "familiarity_0_4": "",
                            "conflict_description": "",
                            "preferred_candidate_A_B_C_tie_neither": "",
                            "candidate_A_sonic_fit_1_5": "",
                            "candidate_B_sonic_fit_1_5": "",
                            "candidate_C_sonic_fit_1_5": "",
                            "cultural_relevance_1_5": "",
                            "confidence_1_5": "",
                            "unsupported_query": "",
                            "unsure": "",
                            "access_failure": "",
                            "exact_audio_match": "",
                            "permitted_provider_urls": "",
                            "region_date_availability": "",
                            "notes": "",
                        }
                    )
        req = (
            "We need two independent listeners for each of 240 frozen FMA validation "
            "queries. For each query, compare three related-track suggestions shown as "
            "A/B/C; their sources and ranks are hidden. One slot is a fixed-order "
            "control. Please rate each candidate's sonic fit and cultural/contextual "
            "relevance separately, then choose A, B, C, tie, neither, unsure or "
            "unsupported. Declare familiarity and conflicts. Use only a provider whose "
            "terms and the recording's per-track license permit your listening; record "
            "exact audio match, provider URL and region/date availability. FMA numeric "
            "IDs are native FMA identities, not MusicBrainz recordings. No audio access "
            "or musical judgment is assumed. The paired suggestions are a frozen "
            "engineering comparison, not established musical truth."
        )
        (qdir / "listener-request.txt").write_text(req + "\n")
        (qdir / "README.md").write_text(
            (
                "# Frozen FMA validation query pair review\n\nThe 240 query IDs are frozen by "
                "the referenced root retrieval pack from a full known-validation denominator "
                "of 7,332 queries. Each review card displays one candidate from each of two "
                "frozen retrieval methods plus a fixed-order control; the A/B/C-to-method key "
                "and source genres are in the sibling coordinator-only directory. All "
                "displayed candidates use FMA native IDs. Missing candidate slots remain "
                "explicit abstentions.\n\nTwo independent reviewers are assigned per query."
                "Judge sonic similarity and cultural/contextual relatedness separately, and "
                "retain ties, neither, unsure, unsupported queries, and playback access "
                "failures. Current listening permission, exact audio match, and availability "
                "have not been checked. The retrieval comparison is an engineering "
                "comparison, not a music-quality result until independent judgments are "
                "returned.\n"
            ),
            encoding="utf-8",
        )
        write_manifest(qdir)
        (qcoord / "method-and-source-key.json").write_text(
            json.dumps(
                {
                    "warning": "Coordinator-only. Do not distribute to listeners.",
                    "items": method_key,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        write_manifest(qcoord)
        query_summary = {
            "queries": len(review_queries),
            "assignments": len(q_assignments),
            "candidate_key_items": len(method_key),
            "source_sha256": digest(sonic_queries_path),
        }
        if membership_results_path and not genres_path:
            raise ValueError("--genres is required with --membership-results")
        if membership_results_path:
            query_summary["membership_review"] = _membership_review(
                sources, context, ordered_query_rows
            )
    return query_summary


def build(sources: ReviewSources) -> dict[str, Any]:
    """Stream FMA inputs and freeze independent review populations."""
    population = _sample_population(sources)
    selected = population.selected
    artists, folds = population.artists, population.folds
    artist_track_counts = population.artist_track_counts
    stratum = population.stratum
    track_count = population.track_count
    strata_denominators = population.strata_denominators
    low_cut, high_cut = population.artist_cuts
    genre_low_cut, genre_high_cut = population.genre_cuts
    tracks_hash, artists_hash, folds_hash = population.hashes
    track_ids_path = sources.track_ids
    output = sources.output
    query_rows, source_by_id = population.query_rows, population.source_by_id
    # Freeze a deterministic method-blind presentation order, even when IDs are
    # supplied externally (such as the root's validation query list).
    random.Random(SEED ^ 0x71B4).shuffle(selected)  # noqa: S311
    cohort = []
    hidden_key = []
    assignments = []
    for n, t in enumerate(selected, 1):
        tid = int(t["track_id"])
        aid = t.get("artist_id")
        a = artists.get(int(aid)) if aid is not None else None
        comp = folds[tid]
        cohort.append(
            {
                "item_id": f"F{n:03d}",
                "native_track_id": tid,
                "native_track_identity": f"fma:track:{tid}",
                "title": t.get("title") or "unknown",
                "artist_identity": f"fma:artist:{int(aid)}"
                if aid is not None and t.get("artist_id_status") == "source_known"
                else None,
                "artist_name": (a or {}).get("name") or t.get("artist_name") or "unknown",
                "identity_namespace": "FMA_native_only; no MusicBrainz bridge inferred",
                "region": "unknown",
                "language": "unknown",
                "era": "unknown",
                "audio_license_title": t.get("audio_license_title"),
                "audio_license_url": t.get("audio_license_url"),
                "source_track_page": t.get("source_metadata_url"),
                "listening_status": "not_verified",
                "permitted_provider_url": "",
                "exact_audio_identity_status": "not_checked",
            }
        )
        hidden_key.append(
            {
                "item_id": f"F{n:03d}",
                "genre_source_positive_ids": sorted({int(x) for x in (t.get("genre_ids") or [])}),
                "label_state": "source_positive"
                if t.get("genre_ids")
                else "unlabelled_unknown_not_negative",
                "artist_track_volume": artist_track_counts.get(int(aid), None)
                if aid is not None
                else None,
                "stratum": dict(
                    zip(
                        ("label_prevalence", "artist_evidence_volume", "metadata_missingness"),
                        stratum(t),
                        strict=True,
                    )
                ),
                "component_id": int(comp["component_id"]),
                "fold": int(comp["fold"]),
                "source_missing_fields": missing_feature_fields(t),
            }
        )
        assignments.extend(
            {
                "item_id": f"F{n:03d}",
                "reviewer_slot": slot,
                "reviewer_id": "",
                "status": "unassigned",
            }
            for slot in (1, 2)
        )

    cell_counts = {
        "|".join(map(str, cell)): {
            "denominator_tracks": count,
            "selected_tracks": sum(stratum(t) == cell for t in selected),
        }
        for cell, count in sorted(strata_denominators.items())
    }
    declaration = {
        "revision": "fma-native-independent-musical-review-v1",
        "seed": SEED,
        "source": {
            "dataset": "FMA native metadata",
            "tracks_rows": track_count,
            "artists_rows": len(artists),
            "tracks_sha256": tracks_hash,
            "artists_sha256": artists_hash,
            "component_table_sha256": folds_hash,
            "metadata_license": "CC-BY-4.0",
            "audio_downloaded": False,
            "attribution": (
                "Michaël Defferrard, Kirell Benzi, Pierre Vandergheynst, Xavier Bresson, FMA:"
                "A Dataset For Music Analysis, ISMIR 2017, https://github.com/mdeff/fma"
            ),
            "track_source_receipt": (
                "/workspace/opennoise/docs/foundation/evidence/fma-native-corpus-20261002.json"
            ),
        },
        "sampling": {
            "denominator": "all 109727 native FMA tracks",
            "sample_size": len(cohort),
            "algorithm": (
                "round-robin across rarest source-positive genre frequency"
                "(rare/medium/common/unlabelled) x known artist catalog-volume "
                "tercile/unknown x actual row-level missing metadata fields; seeded shuffle "
                "for presentation"
            ),
            "component_id": (
                "frozen native leakage-aware FMA components; component IDs retained in "
                "coordinator-only file and are the uncertainty unit"
            ),
            "artist_volume_cutpoints_inclusive": [low_cut, high_cut],
            "rarest_positive_genre_frequency_cutpoints_inclusive": [genre_low_cut, genre_high_cut],
            "strata_denominators": cell_counts,
            "external_frozen_track_id_list": str(track_ids_path) if track_ids_path else None,
        },
        "review": {
            "independent_reviewers_per_item": 2,
            "hide_genre_source_positives_during_fit_review": True,
            "method_names_and_scores_hidden": True,
            "require_familiarity_and_conflicts": True,
            "retain_unsure_unsupported_access_failure": True,
            "no_identity_bridge_fabrication": True,
            "resampling_unit": "component_id",
            "preserve_disagreement": True,
        },
        "rater_scale": {
            "fit_1_5": {
                "1": "does not fit",
                "2": "mostly does not fit",
                "3": "mixed or uncertain fit",
                "4": "good fit",
                "5": "very strong fit",
            },
            "confidence_1_5": {
                "1": "very unsure",
                "2": "low confidence",
                "3": "moderate confidence",
                "4": "high confidence",
                "5": "very high confidence",
            },
            "familiarity_0_4": {
                "0": "not familiar",
                "1": "heard a little",
                "2": "some familiarity",
                "3": "very familiar",
                "4": "expert or close familiarity",
            },
        },
        "frozen_judgment_coding": {
            "fit_positive": "both independent ratings >=4 and neither unsure/unsupported",
            "fit_negative": "both independent ratings <=2 and neither unsure/unsupported",
            "otherwise": "mixed/indeterminate; retain each original answer and access state",
            "promotion": (
                "this review cohort can inform calibration only; freeze any score threshold "
                "before a disjoint confirmation cohort"
            ),
        },
        "interpretation_limits": [
            (
                "FMA is a 2017 source corpus and its native numeric IDs do not bridge "
                "to MusicBrainz IDs."
            ),
            (
                "Track genre IDs are source-positive track annotations, not artist "
                "memberships or exhaustive truth; missing labels are unknown, never negative."
            ),
            (
                "FMA metadata license does not license audio. Each recording has a "
                "per-track audio license declaration; current playback, exact audio "
                "match and regional provider availability remain unverified."
            ),
            (
                "FMA is an endogenous source cohort, not a global population sample; "
                "unknown region, language and era remain unknown."
            ),
            "This packet creates no reviewer identities or musical judgments.",
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "fma-declaration.json").write_text(
        json.dumps(declaration, indent=2, sort_keys=True) + "\n"
    )
    (output / "fma-cohort.json").write_text(
        json.dumps(
            {
                "artists_in_source": len(artists),
                "tracks_in_source": track_count,
                "sample_size": len(cohort),
                "items": cohort,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    coordinator = output.parent / (output.name + "-coordinator")
    coordinator.mkdir(parents=True, exist_ok=True)
    (coordinator / "fma-source-label-key.json").write_text(
        json.dumps(
            {
                "warning": "Coordinator-only. Never distribute with listener packet.",
                "items": hidden_key,
                "strata_denominators": cell_counts,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    (output / "fma-reviewer-assignments.json").write_text(json.dumps(assignments, indent=2) + "\n")
    with (output / "fma-track-fit-form.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "item_id",
                "reviewer_slot",
                "reviewer_id",
                "familiarity_0_4",
                "conflict_description",
                "free_text_genre_or_description",
                "scope_broad_sub_micro",
                "fit_1_5",
                "confidence_1_5",
                "unsure",
                "unsupported",
                "access_failure",
                "exact_audio_match",
                "permitted_provider_url",
                "region_date_availability",
                "notes",
            ],
        )
        w.writeheader()
        for item in cohort:
            for slot in (1, 2):
                w.writerow(
                    {
                        "item_id": item["item_id"],
                        "reviewer_slot": slot,
                        "reviewer_id": "",
                        "familiarity_0_4": "",
                        "conflict_description": "",
                        "free_text_genre_or_description": "",
                        "scope_broad_sub_micro": "",
                        "fit_1_5": "",
                        "confidence_1_5": "",
                        "unsure": "",
                        "unsupported": "",
                        "access_failure": "",
                        "exact_audio_match": "",
                        "permitted_provider_url": "",
                        "region_date_availability": "",
                        "notes": "",
                    }
                )
    request = (
        "We need independent listeners for a frozen sample of 240 tracks drawn by a "
        "declared seed from all 109,727 native Free Music Archive metadata tracks."
        "Each track needs two independent reviews. Please use only an audio provider "
        "whose terms and per-track license permit your listening and record the exact "
        "provider URL, whether the audio matches the identified track, and "
        "region/date availability. The packet gives native FMA track and artist IDs;"
        "these are not MusicBrainz identities. Please describe the music in your own "
        "words and identify any broad/subgenre/micro fit you can support. You may "
        "answer unsure or unsupported. Declare familiarity and conflicts. Genre "
        "source annotations, methods, scores, and source votes are hidden during "
        "musical judgments. The FMA metadata carries CC BY 4.0 attribution; the "
        "separate track audio license controls audio use. Missing genres mean "
        "unknown, not no genre. FMA is an endogenous 2017 archive and has no reliable "
        "global region/language/era fields, so the exercise cannot establish "
        "worldwide coverage. Please return both independent forms; disagreement and "
        "access failures will be preserved."
    )
    (output / "fma-listener-request.txt").write_text(request + "\n")
    (output / "README.md").write_text(
        (
            "# Full FMA native track musical review cohort\n\nThis is a seeded 240-track "
            "sample drawn from the full 109,727-track FMA native metadata denominator."
            "Frozen component IDs, folds, source positives and missingness are retained "
            "in the sibling coordinator-only key for leakage-aware analysis after "
            "independent judgments. FMA track and artist IDs remain in the FMA namespace "
            "and do not imply MusicBrainz recordings. Source-positive genres are hidden "
            "from reviewers. Unlabelled means unknown, not negative.\n\nEach track needs "
            "two independent listeners. The blank form separates musical fit from "
            "familiarity, confidence, unsupported or unsure responses, exact playback "
            "match, permitted provider URL, access failure, and region/date availability."
            "Metadata has a CC BY 4.0 attribution requirement; per-track audio license "
            "facts are separate. Current listening access has not been verified and the "
            "packet does not grant audio rights.\n\nRegenerate from the pinned "
            "source files "
            "with `python scripts/build_fma_musical_review_cohort.py --tracks TRACKS"
            "--artists ARTISTS --folds "
            "data/examples/fma-acoustic-baseline/native-folds.jsonl.zst --output OUTPUT`."
            "Input SHA-256 values are in `fma-declaration.json`.\n"
        ),
        encoding="utf-8",
    )

    write_manifest(output)
    query_summary = build_validation_review(
        sources, ReviewContext(query_rows, source_by_id, artists, folds, tracks_hash)
    )
    return {
        "denominator_tracks": track_count,
        "denominator_artists": len(artists),
        "sample": len(cohort),
        "source_positive": sum(x["label_state"] == "source_positive" for x in hidden_key),
        "unlabelled": sum(x["label_state"] != "source_positive" for x in hidden_key),
        "components": len({x["component_id"] for x in hidden_key}),
        "folds": dict(Counter(x["fold"] for x in hidden_key)),
        "validation_query_review": query_summary,
    }


def _membership_review(
    sources: ReviewSources, context: ReviewContext, ordered_query_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Build membership review."""
    membership_results_path = sources.membership_results
    genres_path = sources.genres
    calibration_results_path = sources.calibration_results
    output = sources.output
    tracks_hash = context.tracks_hash
    if membership_results_path is None or genres_path is None:
        raise ValueError("Membership review requires confirmation results and genres")
    query_ids = {int(row["track_id"]) for row in ordered_query_rows}
    result_by_id: dict[int, dict[str, Any]] = {}
    result_count = 0
    for row in iter_jsonl_zst(membership_results_path):
        result_count += 1
        if int(row["track_id"]) in query_ids:
            result_by_id[int(row["track_id"])] = row
    genres_hash = digest(genres_path)
    if genres_hash != GENRES_SHA256:
        raise ValueError(f"FMA genres source hash mismatch: {genres_hash}")
    genre_rows = {
        int(genre["genre_id"]): {
            "title": genre["title"],
            "parent_id": genre.get("parent_id"),
        }
        for genre in iter_jsonl_zst(genres_path)
    }
    calibration_ids = set()
    if calibration_results_path:
        calibration_ids = {
            int(r["track_id"])
            for r in iter_jsonl_zst(calibration_results_path)
            if int(r["track_id"]) in query_ids
        }
    membership_dir = output.parent / "fma-validation-membership-review"
    membership_dir.mkdir(parents=True, exist_ok=True)
    membership_coord = membership_dir.parent / (membership_dir.name + "-coordinator")
    membership_coord.mkdir(parents=True, exist_ok=True)
    review_id_to_track = {
        int(q["track_id"]): f"Q{i:03d}" for i, q in enumerate(ordered_query_rows, 1)
    }
    membership_items, membership_key, membership_assignments = _membership_rows(
        context, review_id_to_track, result_by_id, genre_rows, calibration_ids
    )
    membership_decl = {
        "revision": "fma-confirmation-membership-independent-review-v1",
        "model_output_source": str(membership_results_path),
        "model_output_sha256": digest(membership_results_path),
        "calibration_partition_source": str(calibration_results_path)
        if calibration_results_path
        else None,
        "calibration_partition_sha256": digest(calibration_results_path)
        if calibration_results_path
        else None,
        "source_tracks_sha256": tracks_hash,
        "genres_source_sha256": digest(genres_path),
        "query_denominator": 7332,
        "sample_query_count": 240,
        "reviewed_confirmation_partition_queries": len(membership_items),
        "calibration_partition_queries_withheld": sum(
            qid in calibration_ids for qid in review_id_to_track
        ),
        "results_considered": (
            "confirmation partition only; no calibration predictions or rows displayed"
        ),
        "candidate_display": (
            "only candidate genre text and parent text shown; model method, rank, score,"
            "threshold, source annotations and percentile hidden"
        ),
        "reviewers_per_candidate": 2,
        "rater_scale": {
            "fit_1_5": (
                "1 does not fit; 2 mostly does not fit; 3 mixed/uncertain; 4 good fit; 5 very "
                "strong fit"
            ),
            "confidence_1_5": "1 very unsure to 5 very high confidence",
        },
        "frozen_coding": {
            "fit_positive": "both reviewers >=4 and neither unsure/unsupported",
            "fit_negative": "both reviewers <=2 and neither unsure/unsupported",
            "otherwise": "mixed/indeterminate; preserve both original responses",
            "score_threshold": (
                "no promotion threshold from this same cohort; freeze before a disjoint "
                "musical confirmation cohort"
            ),
        },
        "limits": [
            "FMA-native track labels are not artist memberships.",
            "Model rank/percentile is not a musical probability.",
            "Track-level genre-source positives and model keys remain coordinator-only.",
            "No ratings or reviewer identities have been entered.",
            (
                "Playback permission and availability remain per-track and unchecked for this "
                "cohort."
            ),
        ],
    }
    (membership_dir / "declaration.json").write_text(
        json.dumps(membership_decl, indent=2, sort_keys=True) + "\n"
    )
    (membership_dir / "items.json").write_text(
        json.dumps({"items": membership_items}, indent=2, sort_keys=True) + "\n"
    )
    (membership_dir / "reviewer-assignments.json").write_text(
        json.dumps(membership_assignments, indent=2) + "\n"
    )
    with (membership_dir / "membership-review-form.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "candidate_id",
                "query_item_id",
                "query_track_id",
                "query_title",
                "query_artist",
                "candidate_genre_display",
                "candidate_parent_display",
                "reviewer_slot",
                "reviewer_id",
                "familiarity_0_4",
                "conflict_description",
                "fit_1_5",
                "scope_broad_sub_micro",
                "confidence_1_5",
                "unsure",
                "unsupported",
                "access_failure",
                "exact_audio_match",
                "permitted_provider_url",
                "notes",
            ],
        )
        w.writeheader()
        for item in membership_items:
            for candidate in item["membership_candidates"]:
                for slot in (1, 2):
                    w.writerow(
                        {
                            "candidate_id": candidate["candidate_id"],
                            "query_item_id": item["query_item_id"],
                            "query_track_id": item["query_track"]["native_track_id"],
                            "query_title": item["query_track"]["title"],
                            "query_artist": item["query_track"]["artist_name"],
                            "candidate_genre_display": candidate["genre_label"],
                            "candidate_parent_display": candidate["parent_label"] or "",
                            "reviewer_slot": slot,
                            "reviewer_id": "",
                            "familiarity_0_4": "",
                            "conflict_description": "",
                            "fit_1_5": "",
                            "scope_broad_sub_micro": "",
                            "confidence_1_5": "",
                            "unsure": "",
                            "unsupported": "",
                            "access_failure": "",
                            "exact_audio_match": "",
                            "permitted_provider_url": "",
                            "notes": "",
                        }
                    )
    req = (
        "We need two independent listeners to assess the genre descriptions shown for "
        "240 frozen FMA validation queries. Each displayed label is a held-out model "
        "suggestion, presented without its method, score or source votes. Judge each "
        "label for this exact track at the broad/subgenre/micro scope; do not treat a "
        "track tag as an artist-wide claim. Rate fit and confidence separately."
        "Unsure, unsupported and playback failure are valid recorded outcomes. Use "
        "only audio whose per-track license permits your listening, and record exact "
        "match and provider access. This review cohort informs calibration only; any "
        "promotion threshold must be frozen before a separate confirmation cohort."
        "FMA track and artist IDs have no implied MusicBrainz bridge."
    )
    (membership_dir / "listener-request.txt").write_text(req + "\n")
    (membership_dir / "README.md").write_text(
        (
            "# FMA validation membership review\n\nThis packet shows candidate "
            "genres from "
            "the frozen confirmation half only. It hides model ranks, score, source "
            "positives and method. Each item is a native FMA track, not an artist-wide "
            "membership claim. Two reviewer rows are supplied per candidate; missing "
            "model output is retained as an abstention task.\n\nThe candidate list can "
            "inform threshold calibration, but cannot confirm the selected threshold on "
            "the same judgments. Freeze a threshold before a disjoint musical "
            "confirmation cohort. Retain disagreements, unsure responses, unsupported "
            "tracks and audio access failures.\n"
        ),
        encoding="utf-8",
    )
    (membership_coord / "membership-output-source-key.json").write_text(
        json.dumps(
            {
                "warning": (
                    "Coordinator-only; keep separate from listener packet until judgments are "
                    "complete."
                ),
                "items": membership_key,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    write_manifest(membership_dir)
    write_manifest(membership_coord)
    return {
        "suggestion_candidates": sum(len(q["membership_candidates"]) for q in membership_items),
        "reviewer_slots": len(membership_assignments),
        "confirmation_results": result_count,
        "membership_source_sha256": digest(membership_results_path),
    }


def _query_rows(
    ordered_query_rows: list[dict[str, Any]], context: ReviewContext
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Build query rows."""
    source_by_id, artists, folds = context.source_by_id, context.artists, context.folds
    review_queries: list[dict[str, Any]] = []
    method_key: list[dict[str, Any]] = []
    q_assignments: list[dict[str, Any]] = []
    for i, q in enumerate(ordered_query_rows, 1):
        qid = int(q["track_id"])
        if qid not in source_by_id:
            raise ValueError(f"Frozen query {qid} absent from exact FMA metadata source")
        qr = source_by_id[qid]

        def display_track(tid: int) -> dict[str, Any]:
            t = source_by_id.get(tid)
            if t is None:
                raise ValueError(f"Candidate {tid} absent from exact FMA metadata source")
            aid = t.get("artist_id")
            artist = artists.get(int(aid)) if aid is not None else None
            return {
                "native_track_id": tid,
                "native_track_identity": f"fma:track:{tid}",
                "title": t.get("title") or "unknown",
                "artist_name": (artist or {}).get("name") or t.get("artist_name") or "unknown",
                "artist_identity": f"fma:artist:{int(aid)}" if aid is not None else None,
                "region": "unknown",
                "language": "unknown",
                "era": "unknown",
                "track_page": t.get("source_metadata_url"),
                "audio_license_title": t.get("audio_license_title"),
                "audio_license_url": t.get("audio_license_url"),
                "listening_status": "not_verified",
                "permitted_provider_url": "",
                "exact_audio_match": "not_checked",
            }

        arm_track_ids = {
            name: [int(x) for x in q["arms"][name]["track_ids"]]
            for name in (
                "standardized_euclidean",
                "training_annotation_frequency",
                "fixed_hash_order",
            )
        }
        # Compare rank-one choices from both retrieval methods with a third
        # baseline candidate. Randomize display order and retain method key.
        candidates = []
        for method in (
            "standardized_euclidean",
            "training_annotation_frequency",
            "fixed_hash_order",
        ):
            ids = arm_track_ids[method]
            value = (
                display_track(ids[0])
                if ids
                else {
                    "native_track_id": None,
                    "native_track_identity": None,
                    "title": "No candidate returned",
                    "artist_name": "",
                    "artist_identity": None,
                    "track_page": None,
                    "audio_license_title": None,
                    "audio_license_url": None,
                    "listening_status": "not_applicable_no_candidate",
                    "permitted_provider_url": "",
                    "exact_audio_match": "not_applicable_no_candidate",
                }
            )
            candidates.append((method, value))
        random.Random(f"{SEED}:{qid}:candidate-order").shuffle(candidates)  # noqa: S311
        slots = ["A", "B", "C"]
        slot_map = {slots[j]: candidates[j][0] for j in range(3)}
        item_id = f"Q{i:03d}"
        review_queries.append(
            {
                "item_id": item_id,
                "query": display_track(qid),
                "candidate_A": candidates[0][1],
                "candidate_B": candidates[1][1],
                "candidate_C": candidates[2][1],
                "question": (
                    "Which candidate is the more useful related track for the query? Rate sonic "
                    "similarity and cultural/contextual relatedness separately; ties, unsure,"
                    "unsupported and access failure are valid."
                ),
            }
        )
        method_key.append(
            {
                "item_id": item_id,
                "slot_to_method": slot_map,
                "query_genre_source_positives": sorted(
                    {int(x) for x in (qr.get("genre_ids") or [])}
                ),
                "query_label_state": "source_positive"
                if qr.get("genre_ids")
                else "unlabelled_unknown_not_negative",
                "arms": {
                    method: {
                        "track_ids": ids,
                        "observed_positives": q["arms"][method]["observed_positives"],
                        "recovered_positives": q["arms"][method]["recovered_positives"],
                        "musical_precision_available": q["arms"][method][
                            "musical_precision_available"
                        ],
                    }
                    for method, ids in arm_track_ids.items()
                },
                "component_id": int(q["component_id"]),
                "fold": int(folds[qid]["fold"]),
            }
        )
        q_assignments.extend(
            {
                "item_id": item_id,
                "reviewer_slot": slot,
                "reviewer_id": "",
                "status": "unassigned",
            }
            for slot in (1, 2)
        )
    return review_queries, method_key, q_assignments


def _sample_population(sources: ReviewSources) -> FrozenPopulation:
    """Build sample population."""
    tracks_path = sources.tracks
    artists_path = sources.artists
    folds_path = sources.folds
    track_ids_path = sources.track_ids
    size = sources.size
    sonic_queries_path = sources.sonic_queries
    tracks_hash = digest(tracks_path)
    if tracks_hash != TRACKS_SHA256:
        raise ValueError(f"FMA tracks source hash mismatch: {tracks_hash}")
    artists_hash = digest(artists_path)
    if artists_hash != ARTISTS_SHA256:
        raise ValueError(f"FMA artists source hash mismatch: {artists_hash}")
    artists = {int(row["artist_id"]): {"name": row["name"]} for row in iter_jsonl_zst(artists_path)}
    folds_hash = digest(folds_path)
    if folds_hash != FOLDS_SHA256:
        raise ValueError(f"FMA component source hash mismatch: {folds_hash}")
    query_rows = (
        json.loads(sonic_queries_path.read_text(encoding="utf-8")) if sonic_queries_path else []
    )
    if sonic_queries_path and len(query_rows) != QUERY_COUNT:
        raise ValueError("Expected root-frozen 240 validation queries")
    query_ids = {int(q["track_id"]) for q in query_rows}
    candidate_ids = {
        int(track_id)
        for q in query_rows
        for method in (
            "standardized_euclidean",
            "training_annotation_frequency",
            "fixed_hash_order",
        )
        for track_id in q["arms"][method]["track_ids"][:1]
    }
    required_metadata_ids = query_ids | candidate_ids
    requested_track_ids = None
    if track_ids_path:
        requested_track_ids = {
            int(line.strip())
            for line in track_ids_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
        if len(requested_track_ids) != size:
            raise ValueError(
                f"Frozen query ID count {len(requested_track_ids)} "
                f"does not equal requested size {size}"
            )
    artist_track_counts, genre_counts, track_count, artist_cuts, genre_cuts = _source_frequencies(
        tracks_path
    )
    low_cut, high_cut = artist_cuts
    genre_low_cut, genre_high_cut = genre_cuts

    stratum = SamplingStrata(artist_track_counts, genre_counts, artist_cuts, genre_cuts)

    # Pass 2: count each stratum. The second complete scan is intentional so the
    # selection quota is frozen before any item is sampled.
    strata_denominators: Counter[tuple[str, str, str]] = Counter()
    for track in iter_jsonl_zst(tracks_path):
        strata_denominators[stratum(track)] += 1
    quotas = _sampling_quotas(strata_denominators, size, track_count, requested_track_ids)
    selected, required_source_rows = _sample_tracks(
        tracks_path, stratum, quotas, required_metadata_ids, requested_track_ids
    )
    if len(selected) != min(size, track_count):
        raise ValueError("Stratified streaming sample does not meet its frozen size")
    selected_ids = {int(track["track_id"]) for track in selected}
    required_fold_ids = required_metadata_ids | selected_ids
    folds = {
        int(row["track_id"]): row
        for row in iter_jsonl_zst(folds_path)
        if int(row["track_id"]) in required_fold_ids
    }
    if required_fold_ids - folds.keys():
        raise ValueError("Selected track or query is absent from the frozen component table")
    source_by_id = required_source_rows
    source_by_id.update({int(track["track_id"]): track for track in selected})

    return FrozenPopulation(
        selected=selected,
        artists=artists,
        folds=folds,
        source_by_id=source_by_id,
        query_rows=query_rows,
        artist_track_counts=artist_track_counts,
        strata_denominators=strata_denominators,
        track_count=track_count,
        artist_cuts=(low_cut, high_cut),
        genre_cuts=(genre_low_cut, genre_high_cut),
        hashes=(tracks_hash, artists_hash, folds_hash),
        stratum=stratum,
    )


def _source_frequencies(
    tracks_path: Path,
) -> tuple[Counter[int], Counter[int], int, tuple[int, int], tuple[int, int]]:
    """Build source frequencies."""
    # Pass 1: stream the complete source to derive artist/genre frequencies.
    # No per-track dictionaries are retained.
    artist_track_counts: Counter[int] = Counter()
    genre_counts: Counter[int] = Counter()
    track_count = 0
    for track in iter_jsonl_zst(tracks_path):
        track_count += 1
        if track.get("artist_id") is not None:
            artist_track_counts[int(track["artist_id"])] += 1
        for genre_id in track.get("genre_ids") or []:
            genre_counts[int(genre_id)] += 1
    if track_count != FULL_TRACK_COUNT:
        raise ValueError("Expected full FMA native track denominator: 109727")
    volume_values = sorted(artist_track_counts.values())
    low_cut, high_cut = (
        volume_values[len(volume_values) // 3],
        volume_values[2 * len(volume_values) // 3],
    )
    genre_volume_values = sorted(genre_counts.values())
    genre_low_cut, genre_high_cut = (
        genre_volume_values[len(genre_volume_values) // 3],
        genre_volume_values[2 * len(genre_volume_values) // 3],
    )

    return (
        artist_track_counts,
        genre_counts,
        track_count,
        (low_cut, high_cut),
        (genre_low_cut, genre_high_cut),
    )


def missing_feature_fields(track: dict[str, Any]) -> list[str]:
    """Derive absent metadata fields from the actual row, not receipt aggregates."""
    metadata_fields = (
        "title",
        "album_id",
        "album_title",
        "source_metadata_url",
        "audio_license_title",
        "audio_license_url",
    )
    missing = [field for field in metadata_fields if not track.get(field)]
    if not track.get("genre_ids"):
        missing.append("genre_ids")
    if track.get("artist_id_status") != "source_known":
        missing.append("artist_id")
    return missing


@dataclass(frozen=True)
class SamplingStrata:
    """Classify actual source rows using frozen native population statistics."""

    artist_track_counts: Counter[int]
    genre_counts: Counter[int]
    artist_cuts: tuple[int, int]
    genre_cuts: tuple[int, int]

    def __call__(self, t: dict[str, Any]) -> tuple[str, str, str]:
        """Return label prevalence, artist volume and observed missingness."""
        aid = t.get("artist_id")
        if aid is None or t.get("artist_id_status") != "source_known":
            volume = "unknown"
        else:
            n = self.artist_track_counts[int(aid)]
            volume = (
                "low"
                if n <= self.artist_cuts[0]
                else "medium"
                if n <= self.artist_cuts[1]
                else "high"
            )
        gids = t.get("genre_ids") or []
        if not gids:
            label = "unlabelled"
        else:
            f = min(self.genre_counts[int(g)] for g in gids)
            label = (
                "rare"
                if f <= self.genre_cuts[0]
                else "medium"
                if f <= self.genre_cuts[1]
                else "common"
            )
        feature = "metadata_missing" if missing_feature_fields(t) else "metadata_complete"
        return label, volume, feature


def _sampling_quotas(
    strata_denominators: Counter[tuple[str, str, str]],
    size: int,
    track_count: int,
    requested_track_ids: set[int] | None,
) -> Counter[tuple[str, str, str]]:
    """Build sampling quotas."""
    quotas: Counter[tuple[str, str, str]] = Counter()
    if requested_track_ids is None:
        cells = sorted(strata_denominators)
        while sum(quotas.values()) < min(size, track_count):
            progressed = False
            for cell in cells:
                if quotas[cell] < strata_denominators[cell] and sum(quotas.values()) < size:
                    quotas[cell] += 1
                    progressed = True
            if not progressed:
                break
    else:
        quotas = Counter()
    return quotas


def _sample_tracks(
    tracks_path: Path,
    stratum: SamplingStrata,
    quotas: Counter[tuple[str, str, str]],
    required_metadata_ids: set[int],
    requested_track_ids: set[int] | None,
) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
    """Build sample tracks."""
    # Pass 3: bounded reservoir sample within frozen cell quotas, while retaining
    # only requested query/candidate metadata and the selected review items.
    reservoirs: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    seen_by_cell: Counter[tuple[str, str, str]] = Counter()
    rng_by_cell = {
        # Deterministic selection uses randomness for sampling, not for secrets.
        cell: random.Random(f"{SEED}:{cell}")  # noqa: S311
        for cell in quotas
    }
    requested_ids = required_metadata_ids | (requested_track_ids or set())
    required_source_rows: dict[int, dict[str, Any]] = {}
    for track in iter_jsonl_zst(tracks_path):
        track_id = int(track["track_id"])
        if track_id in requested_ids:
            required_source_rows[track_id] = track
        if requested_track_ids is None:
            cell = stratum(track)
            seen_by_cell[cell] += 1
            quota = quotas[cell]
            reservoir = reservoirs[cell]
            if len(reservoir) < quota:
                reservoir.append(track)
            elif quota:
                replacement = rng_by_cell[cell].randrange(seen_by_cell[cell])
                if replacement < quota:
                    reservoir[replacement] = track
    if requested_track_ids is not None:
        unknown = sorted(requested_track_ids - required_source_rows.keys())
        if unknown:
            raise ValueError(f"Frozen query list has unknown FMA track IDs: {unknown[:5]}")
        selected = [required_source_rows.pop(track_id) for track_id in sorted(requested_track_ids)]
    else:
        selected = [track for cell in sorted(reservoirs) for track in reservoirs[cell]]
    return selected, required_source_rows


def _membership_rows(
    context: ReviewContext,
    review_id_to_track: dict[int, str],
    result_by_id: dict[int, dict[str, Any]],
    genre_rows: dict[int, dict[str, Any]],
    calibration_ids: set[int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Build membership rows."""
    source_by_id, artists, folds = context.source_by_id, context.artists, context.folds
    membership_items: list[dict[str, Any]] = []
    membership_key: list[dict[str, Any]] = []
    membership_assignments: list[dict[str, Any]] = []
    for qid, qitem in sorted(review_id_to_track.items(), key=lambda kv: kv[1]):
        r = result_by_id.get(qid)
        query_source = source_by_id[qid]
        aid = query_source.get("artist_id")
        artist = artists.get(int(aid)) if aid is not None else None
        track_card = {
            "native_track_id": qid,
            "title": query_source.get("title") or "unknown",
            "artist_name": (artist or {}).get("name")
            or query_source.get("artist_name")
            or "unknown",
            "identity_namespace": "FMA native only",
            "region": "unknown",
            "language": "unknown",
            "era": "unknown",
            "track_page": query_source.get("source_metadata_url"),
            "audio_license_title": query_source.get("audio_license_title"),
            "audio_license_url": query_source.get("audio_license_url"),
            "listening_status": "not_verified",
        }
        memberships = (r or {}).get("memberships", [])
        candidate_genres = []
        for m in memberships:
            gid = int(m["genre_id"])
            genre = genre_rows.get(gid, {})
            parent_id = genre.get("parent_id")
            parent = genre_rows.get(int(parent_id)) if parent_id is not None else None
            candidate_genres.append(
                {
                    "candidate_id": f"{qitem}-G{gid}",
                    "genre_id": gid,
                    "genre_label": genre.get("title", f"FMA genre {gid}"),
                    "parent_label": (parent or {}).get("title"),
                }
            )
        random.Random(f"{SEED}:{qid}:membership-order").shuffle(  # noqa: S311
            candidate_genres
        )
        output_status = (
            "confirmation_memberships"
            if r
            else "calibration_partition_prediction_withheld"
            if qid in calibration_ids
            else "no_confirmation_membership_record"
        )
        membership_key.append(
            {
                "query_item_id": qitem,
                "track_id": qid,
                "component_id": int(folds[qid]["component_id"]),
                "fold": int(folds[qid]["fold"]),
                "source_observed_genre_ids": sorted(
                    {int(g) for g in (query_source.get("genre_ids") or [])}
                ),
                "source_label_state": "positive"
                if query_source.get("genre_ids")
                else "unlabelled_unknown_not_negative",
                "model_output": r,
                "model_output_status": output_status,
            }
        )
        if not r and qid in calibration_ids:
            # Keep calibration IDs in the coordinator denominator, but
            # do not present their predictions as confirmation items.
            continue
        if not candidate_genres:
            candidate_genres = [
                {
                    "candidate_id": f"{qitem}-NONE",
                    "genre_id": None,
                    "genre_label": "",
                    "parent_label": None,
                }
            ]
        membership_items.append(
            {
                "query_item_id": qitem,
                "query_track": track_card,
                "membership_candidates": candidate_genres,
            }
        )
        for candidate in candidate_genres:
            membership_assignments.extend(
                {
                    "candidate_id": candidate["candidate_id"],
                    "query_item_id": qitem,
                    "reviewer_slot": slot,
                    "reviewer_id": "",
                    "status": "unassigned",
                }
                for slot in (1, 2)
            )
    return membership_items, membership_key, membership_assignments


def main() -> int:
    """Build the frozen packet from the exact declared local files."""
    p = argparse.ArgumentParser()
    p.add_argument("--tracks", type=Path, required=True)
    p.add_argument("--artists", type=Path, required=True)
    p.add_argument(
        "--folds",
        type=Path,
        default=Path("data/examples/fma-acoustic-baseline/native-folds.jsonl.zst"),
    )
    p.add_argument("--track-ids", type=Path)
    p.add_argument("--sonic-queries", type=Path)
    p.add_argument("--membership-results", type=Path)
    p.add_argument("--genres", type=Path)
    p.add_argument("--calibration-results", type=Path)
    p.add_argument("--size", type=int, default=COHORT_SIZE)
    p.add_argument("--output", type=Path, default=Path("docs/foundation/musical-review-packet/fma"))
    a = p.parse_args()
    result = build(
        ReviewSources(
            tracks=a.tracks,
            artists=a.artists,
            folds=a.folds,
            output=a.output,
            track_ids=a.track_ids,
            size=a.size,
            sonic_queries=a.sonic_queries,
            membership_results=a.membership_results,
            genres=a.genres,
            calibration_results=a.calibration_results,
        )
    )
    sys.stdout.write(
        json.dumps(
            result,
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
