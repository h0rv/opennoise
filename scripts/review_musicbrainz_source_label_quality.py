"""Create a local, non-filtering label-quality review overlay."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from itertools import pairwise
from pathlib import Path

import numpy as np
from scipy import sparse

from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.ml.emergent_topics import NOISE, NONMUSICAL_TAGS, _normalize, _usable

_BASELINE = Path(".cache/microgenre-features-primary-v2-policy-v2/artist-features.jsonl")
_AUGMENTED = Path(".cache/microgenre-features-primary-v4/artist-features.jsonl")
_GENRES = Path(".cache/musicbrainz-native-genre-labels/labels.json")
_ATLAS = Path(".cache/named-style-atlas-20260930-v3/data.json")
_ASSESSMENT = Path(".cache/bulk-feature-increment-assessment-20260930-v2.json")
_SCOPE = "source-label-review-only-un-calibrated-no-filtering"
_CLASS_LABELS = frozenset({0, 1})
_EXPECTED_NEW_LABELS = 17_807
_EXPECTED_NEW_PAIRS = 114_889
_EXPECTED_DEFAULT_LABELS = 2_226
_MINIMUM_DESCRIPTIVE_AUC = 0.70
_SINGLETON_SUPPORT = 1
_LOW_SUPPORT_MAX = 5
_MID_SUPPORT_MAX = 19
_CATEGORIES = (
    "musical_style_candidate",
    "performance_role",
    "biography",
    "pure_place_language",
    "editorial_technical",
    "thematic",
    "unknown",
)

_INPUT_SHA256 = {
    _BASELINE.as_posix(): "70f8dd0de2853b2d927eeaa8a92fbcc4a3f7c968c0d54476d473e8a347abc4b2",
    _AUGMENTED.as_posix(): "2b6179b4c969588f1268c9837b410c9da7b16d54c094850eb13ba00514b6f252",
    _GENRES.as_posix(): "dd0d201c0942d55d423a6af4f45c2bee15675c4182b1d076c61c13b0773a9577",
    _ATLAS.as_posix(): "b9c46915c714528d0de55a4313accaff30c94fb9156628a1bc38419745064828",
    _ASSESSMENT.as_posix(): "2b5870f81ddf142e2824cc36f32a110f453e9923c7883bc673667b823a44322a",
}

# These are explicit source-label semantics reviewed for this experiment. None
# is a main-pipeline rejection rule or a claim about the artist's identity.
_REVIEWED_NONSTYLE: dict[str, str] = {
    "countertenor": "performance_role",
    "conductor": "performance_role",
    "english conductor": "performance_role",
    "french orchestra": "performance_role",
    "hungarian conductor": "performance_role",
    "period instrument orchestra": "performance_role",
    "russian orchestra": "performance_role",
    "battl victory records": "editorial_technical",
    "free download": "editorial_technical",
    "has bandcamp subscription": "editorial_technical",
    "multiple vgmdb profiles": "editorial_technical",
}

_PLACE_LANGUAGE = frozenset(
    {
        "american",
        "british",
        "english",
        "french",
        "german",
        "japanese",
        "uk",
        "us",
        "usa",
        "united kingdom",
        "united states",
        "england",
        "scotland",
        "wales",
        "ireland",
        "london",
        "berlin",
        "paris",
        "tokyo",
        "new york",
        "los angeles",
        "canada",
        "germany",
        "france",
        "japan",
        "sweden",
        "finland",
        "norway",
        "australia",
        "new zealand",
        "brazil",
        "argentina",
        "mexico",
        "spain",
        "italy",
    }
)
_THEMATIC = frozenset(
    {
        "coldness",
        "feelings",
        "individualism",
        "introspection",
        "satanism",
        "self-destruction",
        "spiritualism",
        "transcendence",
    }
)
_AMBIGUOUS = {
    "hololive": "Entertainment brand/music-scene context; not a biography trait or genre claim.",
    "modern": "Broad era or descriptor; the string alone does not resolve style meaning.",
    "non-music": "Native dictionary string, but its literal meaning is not a musical style.",
    "prog related": "Editorial relation phrase; insufficient evidence of a style label.",
    "romanticism": "Could refer to a musical era or a general theme; keep unresolved.",
    "string quartet": "Musical ensemble/form context; this is not automatically a genre.",
    "tge24": "Opaque label; no defensible semantic category from the string alone.",
}
_PROTECTED_STYLE_CANDIDATES = {
    "70's rock": "Keep source-supported genre compound; no normalization to a validated subgenre.",
    "acoustic lo-fi": "Plausible music-style compound retained for review only.",
    "comfy synth": "Reviewed plausible dungeon-synth/music-style candidate.",
    "death thrash": "Plausible metal subgenre compound retained for review only.",
    "denpa": "Reviewed specific Japanese music-scene candidate.",
    "finnish string quartet": "Keep geographic ensemble/form compound available for review.",
    "festival trap": "Keep as a possible style compound; no genre fact inferred.",
    "french metal": "Keep geographic genre compound available for review.",
    "instrumental": "Musical-form descriptor; retain for review without asserting genre truth.",
    "latin": "Broad geographic/music label; preserve without inferring a single genre.",
    "latin jazz": "Keep geographic genre compound available for review.",
    "melodic death": "Plausible genre-family shorthand; retain without expanding its meaning.",
    "neoprog": "Plausible genre-family shorthand; abbreviation remains unresolved.",
    "ostschlager": "Plausible regional popular-music style candidate retained for review.",
    "prairie hip hop": "Keep geographic genre compound available for review.",
    "progressive deathcore": "Plausible named subgenre compound retained for review only.",
    "riff rock": "Plausible music-style compound retained for review only.",
    "soft visual": "Keep source-supported scene/style phrase available for review.",
    "visual kei": "Keep the specific music-scene/style phrase available for review.",
}
_ROLE_TERMS = frozenset(
    {
        "arranger",
        "composer",
        "conductor",
        "countertenor",
        "drummer",
        "guitarist",
        "orchestra",
        "pianist",
        "violinist",
        "vocalist",
    }
)
_EDITORIAL_PATTERN = re.compile(
    r"(?:subscription|profiles|download|records|catalog(?:ue)?|barcode)"
)
_BIOGRAPHY_PATTERN = re.compile(r"\b(?:born|birth|died|real name|member of|formed in)\b")


def _verify_inputs() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path, expected in _INPUT_SHA256.items():
        actual, _ = sha256_file(Path(path))
        if actual != expected:
            raise ValueError(f"pinned review input changed: {path}")
        hashes[path] = actual
    return hashes


def _support_by_value(path: Path) -> Counter[str]:
    support: Counter[str] = Counter()
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            values = {
                _normalize(str(feature["value"]))
                for feature in row["features"]
                if _usable(str(feature["namespace"]), _normalize(str(feature["value"])))
                and str(feature["namespace"])
                in {"artist_genre", "artist_tag", "release_genre", "release_tag"}
            }
            support.update(values)
    return support


def _family(value: str) -> str:
    """Return the Unicode final-word head used to group lexical subgenres."""
    normalized = _normalize(value)
    words = re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)
    return words[-1] if words else normalized


def _family_groups(labels: list[str]) -> list[str]:
    """Join word-head groups when labels differ only by punctuation or spacing."""
    heads = [_family(label) for label in labels]
    parent = {head: head for head in heads}

    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: str, right: str) -> None:
        root_left = find(left)
        root_right = find(right)
        if root_left != root_right:
            parent[max(root_left, root_right)] = min(root_left, root_right)

    alias_heads: dict[str, str] = {}
    for label, head in zip(labels, heads, strict=True):
        compact_alias = "".join(character for character in _normalize(label) if character.isalnum())
        if not compact_alias:
            continue
        prior_head = alias_heads.setdefault(compact_alias, head)
        union(head, prior_head)
    return [find(head) for head in heads]


def _lexical_features(label: str) -> Counter[str]:
    words = re.findall(r"[^\W_]+", _normalize(label), flags=re.UNICODE)
    features: Counter[str] = Counter(f"w:{word}" for word in words)
    features.update(f"w2:{left}_{right}" for left, right in pairwise(words))
    for word in words:
        padded = f" {word} "
        for size in range(2, 6):
            features.update(
                f"c:{padded[index : index + size]}" for index in range(len(padded) - size + 1)
            )
    return features


def _fit_lexical_centroids(
    train_texts: list[str], train_labels: list[int], test_texts: list[str]
) -> np.ndarray:
    train_features = [_lexical_features(text) for text in train_texts]
    document_frequency: Counter[str] = Counter()
    for features in train_features:
        document_frequency.update(features.keys())
    vocabulary = {feature: index for index, feature in enumerate(sorted(document_frequency))}
    idf = {
        feature: float(np.log((1 + len(train_features)) / (1 + frequency)) + 1)
        for feature, frequency in document_frequency.items()
    }

    def matrix_for(rows: list[Counter[str]]) -> sparse.csr_matrix:
        data: list[float] = []
        indices: list[int] = []
        indptr = [0]
        for features in rows:
            weighted: list[tuple[int, float]] = []
            for feature, count in features.items():
                if feature in vocabulary:
                    weighted.append((vocabulary[feature], (1 + np.log(count)) * idf[feature]))
            norm = float(np.sqrt(sum(weight * weight for _index, weight in weighted)))
            for index, weight in sorted(weighted):
                indices.append(index)
                data.append(weight / max(norm, 1e-12))
            indptr.append(len(data))
        return sparse.csr_matrix(
            (np.asarray(data), np.asarray(indices), np.asarray(indptr)),
            shape=(len(rows), len(vocabulary)),
        )

    train_matrix = matrix_for(train_features)
    positive = train_matrix[np.asarray(train_labels) == 1].mean(axis=0)
    negative = train_matrix[np.asarray(train_labels) == 0].mean(axis=0)
    positive_vector = np.asarray(positive).ravel()
    negative_vector = np.asarray(negative).ravel()
    positive_vector /= max(float(np.linalg.norm(positive_vector)), 1e-12)
    negative_vector /= max(float(np.linalg.norm(negative_vector)), 1e-12)
    test_matrix = matrix_for([_lexical_features(text) for text in test_texts])
    return np.asarray(test_matrix @ positive_vector - test_matrix @ negative_vector).ravel()


def _training_rows(
    native_labels: set[str],
) -> tuple[list[str], list[int], list[str], dict[str, str]]:
    positive = {_normalize(label) for label in native_labels}
    negative_sources = {
        _normalize(label): "current_noise_policy" for label in NOISE | NONMUSICAL_TAGS
    }
    negative_sources.update({_normalize(label): role for label, role in _REVIEWED_NONSTYLE.items()})
    conflicts = positive & set(negative_sources)
    positive -= conflicts
    for label in conflicts:
        negative_sources.pop(label, None)
    texts = sorted(positive | set(negative_sources))
    labels = [int(value in positive) for value in texts]
    families = _family_groups(texts)
    origins = dict.fromkeys(positive, "native_musicbrainz_genre_name")
    origins.update(negative_sources)
    return texts, labels, families, origins


def _family_aware_metrics(
    texts: list[str], labels: list[int], families: list[str]
) -> dict[str, object]:
    family_rows: dict[str, list[int]] = defaultdict(list)
    for index, family in enumerate(families):
        family_rows[family].append(index)
    folds: list[list[str]] = [[] for _ in range(5)]
    fold_sizes = [0] * 5
    for family, indices in sorted(family_rows.items(), key=lambda item: (-len(item[1]), item[0])):
        fold = min(range(len(folds)), key=lambda index: (fold_sizes[index], index))
        folds[fold].append(family)
        fold_sizes[fold] += len(indices)
    predictions = np.zeros(len(texts), dtype=np.int8)
    margins = np.full(len(texts), np.nan)
    fold_receipts: list[dict[str, int]] = []
    for fold, held_families in enumerate(folds):
        test_family_set = set(held_families)
        train = [index for index, family in enumerate(families) if family not in test_family_set]
        test = [index for index, family in enumerate(families) if family in test_family_set]
        if {labels[index] for index in train} != _CLASS_LABELS:
            raise ValueError("family-aware fold lost a training class")
        train_groups = {families[index] for index in train}
        test_groups = {families[index] for index in test}
        if train_groups & test_groups:
            raise ValueError("lexical family leaked across a validation fold")
        decision = _fit_lexical_centroids(
            [texts[index] for index in train],
            [labels[index] for index in train],
            [texts[index] for index in test],
        )
        margins[test] = decision
        predictions[test] = (decision >= 0).astype(np.int8)
        fold_receipts.append(
            {
                "fold": fold,
                "train_labels": len(train),
                "test_labels": len(test),
                "train_families": len(train_groups),
                "test_families": len(test_groups),
            }
        )
    actual = np.asarray(labels, dtype=np.int8)
    order = np.argsort(margins)
    sorted_margins = margins[order]
    ranks = np.empty(len(order), dtype=float)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and sorted_margins[end] == sorted_margins[start]:
            end += 1
        ranks[start:end] = (start + 1 + end) / 2
        start = end
    rank_by_row = np.empty(len(order), dtype=float)
    rank_by_row[order] = ranks
    positive_ranks = rank_by_row[actual == 1]
    negative_count = int(np.sum(actual == 0))
    roc_auc = (
        float(positive_ranks.sum()) - len(positive_ranks) * (len(positive_ranks) + 1) / 2
    ) / max(len(positive_ranks) * negative_count, 1)
    true_positive = int(np.sum((actual == 1) & (predictions == 1)))
    false_positive = int(np.sum((actual == 0) & (predictions == 1)))
    false_negative = int(np.sum((actual == 1) & (predictions == 0)))
    true_negative = int(np.sum((actual == 0) & (predictions == 0)))
    recall = true_positive / max(true_positive + false_negative, 1)
    specificity = true_negative / max(true_negative + false_positive, 1)
    precision = true_positive / max(true_positive + false_positive, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-12)
    return {
        "method": "five_fold_family_holdout_nearest_tfidf_centroid",
        "family_definition": (
            "Unicode final lexical token; groups with exact punctuation/spacing-stripped "
            "alphanumeric label aliases are unioned"
        ),
        "family_alias_limit": (
            "Does not guarantee that semantic synonyms, transliterations, or all aliases "
            "share a fold."
        ),
        "families": len(set(families)),
        "labels": len(labels),
        "positive_native_dictionary_labels": int(actual.sum()),
        "negative_clear_nonstyle_labels": int(len(actual) - actual.sum()),
        "decision_threshold": 0,
        "scores_are_calibrated_probabilities": False,
        "roc_auc": round(roc_auc, 6),
        "balanced_accuracy": round((recall + specificity) / 2, 6),
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "folds": fold_receipts,
        "use": "uncalibrated label-review triage only; not independent genre validation",
    }


def _manual_category(value: str, *, native_positive: bool) -> tuple[str, str]:  # noqa: PLR0911
    normalized = _normalize(value)
    if normalized in _AMBIGUOUS:
        return "unknown", _AMBIGUOUS[normalized]
    if normalized in _REVIEWED_NONSTYLE:
        return (
            _REVIEWED_NONSTYLE[normalized],
            "Reviewed nonstyle metadata/context; retain as source evidence only.",
        )
    if _EDITORIAL_PATTERN.search(normalized):
        return "editorial_technical", "Editorial/catalogue metadata; not a style label."
    if normalized in _PLACE_LANGUAGE:
        return (
            "pure_place_language",
            "Exact place/language descriptor; keep geographic genre compounds separate.",
        )
    if normalized in _THEMATIC:
        return "thematic", "Theme/ideology annotation; not a musical-style identity."
    tokens = set(re.findall(r"[a-z0-9]+", normalized))
    if tokens & _ROLE_TERMS:
        return (
            "performance_role",
            "Role or ensemble context; musically meaningful, but not itself a style.",
        )
    if _BIOGRAPHY_PATTERN.search(normalized):
        return "biography", "Biographical phrase; not a musical-style identity."
    if normalized in _PROTECTED_STYLE_CANDIDATES:
        return "musical_style_candidate", _PROTECTED_STYLE_CANDIDATES[normalized]
    if native_positive:
        return (
            "musical_style_candidate",
            "Exact native dictionary name; registry membership is not genre truth.",
        )
    return (
        "unknown",
        "No conservative semantic category; keep unknown regardless of lexical margin.",
    )


def _sample_for_support(
    rows: list[dict[str, object]], per_bucket: int = 12
) -> dict[str, list[str]]:
    buckets = {"1": [], "2-5": [], "6-19": [], "20-99": []}
    for row in rows:
        support = int(row["support"])
        key = (
            "1"
            if support == _SINGLETON_SUPPORT
            else "2-5"
            if support <= _LOW_SUPPORT_MAX
            else "6-19"
            if support <= _MID_SUPPORT_MAX
            else "20-99"
        )
        buckets[key].append(str(row["label"]))
    sample: dict[str, list[str]] = {}
    for key, labels in buckets.items():
        labels.sort(key=lambda label: hashlib.sha256(label.encode("utf-8")).hexdigest())
        sample[key] = labels[:per_bucket]
    return sample


def build_review(output: Path) -> dict[str, object]:  # noqa: PLR0915
    """Build the pinned analysis-only label review and write its receipt."""
    source_hashes = _verify_inputs()
    old_support = _support_by_value(_BASELINE)
    new_support = _support_by_value(_AUGMENTED)
    if not old_support.keys() <= new_support.keys():
        raise ValueError("augmented features removed a baseline canonical musical value")
    novel = {value: count for value, count in new_support.items() if value not in old_support}

    genres_object = json.loads(_GENRES.read_text(encoding="utf-8"))
    native_labels = {_normalize(str(item["canonical_name"])) for item in genres_object["genres"]}
    atlas = json.loads(_ATLAS.read_text(encoding="utf-8"))
    defaults = [style for style in atlas["styles"] if style["default_visible"] is True]
    defaults_by_name = {_normalize(str(style["name"])): style for style in defaults}
    if len(defaults) != _EXPECTED_DEFAULT_LABELS:
        raise ValueError("pinned style atlas no longer has 2,226 default-visible labels")

    texts, labels, families, training_origins = _training_rows(native_labels)
    metrics = _family_aware_metrics(texts, labels, families)
    model_usable = float(metrics["roc_auc"]) >= _MINIMUM_DESCRIPTIVE_AUC
    reviewed_labels = sorted(set(novel) | {str(style["name"]) for style in defaults})
    reviewed_margins = _fit_lexical_centroids(
        texts, labels, [_normalize(label) for label in reviewed_labels]
    )
    label_rows: dict[str, dict[str, object]] = {}
    for label, raw_score in zip(reviewed_labels, reviewed_margins, strict=True):
        normalized = _normalize(label)
        score = float(raw_score)
        is_native = normalized in native_labels
        category, rationale = _manual_category(label, native_positive=is_native)
        style = defaults_by_name.get(normalized)
        label_rows[label] = {
            "label": label,
            "support": int(new_support.get(normalized, 0)),
            "novel_in_primary_v4": normalized in novel,
            "default_visible_primary_v2_atlas": style is not None,
            "default_atlas_support": int(style["source_artist_support"]) if style else None,
            "native_dictionary_member": is_native,
            "native_genre_ids": list(style["native_genre_ids"]) if style else [],
            "weak_lexical_margin": round(score, 8),
            "weak_model_used_for_category_assignment": False,
            "category": category,
            "rationale": rationale,
        }
    ordered_rows = [label_rows[label] for label in sorted(label_rows)]
    sample = _sample_for_support([row for row in ordered_rows if row["novel_in_primary_v4"]])
    distribution = Counter(
        "1"
        if support == _SINGLETON_SUPPORT
        else "2-5"
        if support <= _LOW_SUPPORT_MAX
        else "6-19"
        if support <= _MID_SUPPORT_MAX
        else "20-99"
        for support in novel.values()
    )
    new_categories = Counter(
        str(row["category"]) for row in ordered_rows if row["novel_in_primary_v4"]
    )
    default_categories = Counter(
        str(row["category"]) for row in ordered_rows if row["default_visible_primary_v2_atlas"]
    )
    for category in _CATEGORIES:
        new_categories.setdefault(category, 0)
        default_categories.setdefault(category, 0)
    report: dict[str, object] = {
        "revision": "musicbrainz-source-label-quality-review-v2",
        "scope": _SCOPE,
        "review_script_sha256": sha256_file(Path(__file__))[0],
        "feature_input_scope": (
            "198409 exact artist UUID cohort; only source label values are analyzed"
        ),
        "non_inputs": {
            "artist_identity_name_data": False,
            "historical_every_noise_assignments": False,
            "audio": False,
            "independent_human_genre_gold": False,
        },
        "sources": source_hashes,
        "normalizer_sha256": sha256_file(Path("src/opennoise/ml/emergent_topics.py"))[0],
        "label_rows_sha256": "",
        "label_rows_bytes": 0,
        "category_definitions": {
            "musical_style_candidate": (
                "weak label-review candidate only; not a native fact or validated genre"
            ),
            "performance_role": "role or ensemble context that is not itself a style",
            "biography": "explicit biographical phrase, excluded from genre-likeness positives",
            "pure_place_language": (
                "standalone place/language descriptor only; compounds stay separate"
            ),
            "editorial_technical": "catalogue, subscription, platform, or technical metadata",
            "thematic": "topic/ideology annotation distinct from genre identity",
            "unknown": "string alone is insufficient; retain for manual review",
        },
        "native_dictionary": {
            "sha256": source_hashes[_GENRES.as_posix()],
            "label_count": len(native_labels),
            "license": genres_object["license"],
            "role": "weak registry-name positives only; not independent musical ground truth",
        },
        "family_aware_weak_classifier": metrics,
        "descriptive_signal_flag_roc_auc_ge_0_70": model_usable,
        "negative_sources": {
            "current_policy_noise_set_count": len(NOISE | NONMUSICAL_TAGS),
            "explicitly_reviewed_nonstyle_seed_count": len(_REVIEWED_NONSTYLE),
            "reviewed_nonstyle_seeds": _REVIEWED_NONSTYLE,
            "ambiguous_labels_excluded_from_negative_training": sorted(_AMBIGUOUS),
            "musical_form_and_geographic_compounds_excluded_from_negative_training": sorted(
                {
                    "french metal",
                    "prairie hip hop",
                    "string quartet",
                    "finnish string quartet",
                    "latin jazz",
                }
            ),
        },
        "increment": {
            "novel_canonical_value_count": len(novel),
            "new_canonical_artist_value_pairs": (
                sum(new_support.values()) - sum(old_support.values())
            ),
            "new_support_distribution": dict(sorted(distribution.items())),
            "support_stratified_sample": sample,
            "default_visible_primary_v2_count": len(defaults),
            "reviewed_label_union_count": len(ordered_rows),
        },
        "category_counts_new_labels": dict(sorted(new_categories.items())),
        "category_counts_default_visible": dict(sorted(default_categories.items())),
        "limitations": [
            "Labels are source atoms; artist support is not genre quality or listening relevance.",
            "Dictionary names and current source policy negatives share MusicBrainz lineage.",
            (
                "The lexical split tests registry-name discrimination across final-word families, "
                "not independent musical truth."
            ),
            "Margins are uncalibrated and all categories are an analysis-only review overlay.",
            (
                "No main feature filters, predictor, fitter, atlas, public data, or deployment are "
                "changed."
            ),
        ],
    }
    if report["increment"]["novel_canonical_value_count"] != _EXPECTED_NEW_LABELS:
        raise ValueError("novel feature vocabulary differs from the pinned assessment")
    if report["increment"]["new_canonical_artist_value_pairs"] != _EXPECTED_NEW_PAIRS:
        raise ValueError("new pair count differs from the pinned assessment")
    output.mkdir(parents=True, exist_ok=False)
    rows_path = output / "label-review.jsonl"
    digest = hashlib.sha256()
    byte_size = 0
    with rows_path.open("wb") as stream:
        for row in ordered_rows:
            encoded = canonical_json(row) + b"\n"
            stream.write(encoded)
            digest.update(encoded)
            byte_size += len(encoded)
    report["label_rows_sha256"] = digest.hexdigest()
    report["label_rows_bytes"] = byte_size
    report["training_label_source_kinds"] = dict(sorted(Counter(training_origins.values()).items()))
    report["output_sha256"] = sha256_json(report)
    (output / "report.json").write_bytes(canonical_json(report) + b"\n")
    return report


def main() -> int:
    """Write one create-only local review artifact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=Path(".cache/musicbrainz-source-label-quality-20260930-v1"),
    )
    args = parser.parse_args()
    if args.output_directory.exists():
        parser.error("output directory already exists; choose a new path")
    receipt = build_review(args.output_directory)
    sys.stdout.write(str(receipt["output_sha256"]) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
