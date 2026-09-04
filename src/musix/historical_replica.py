"""Bounded name-signal helpers for the explicitly separate calibrated-replica experiment."""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


type NamePair = tuple[str, str]
_MAX_GRAM_DOCUMENT_FREQUENCY = 64
_MAX_NAME_CANDIDATES_PER_GENRE = 64


def deterministic_h2_split(genre_ids: tuple[str, ...]) -> tuple[frozenset[str], frozenset[str]]:
    """Produce a stable 80/20 H2 oracle split before any calibration is evaluated."""
    train: set[str] = set()
    holdout: set[str] = set()
    for genre_id in genre_ids:
        bucket = hashlib.sha256(genre_id.encode()).digest()[0] % 5
        (holdout if bucket == 0 else train).add(genre_id)
    if not train or not holdout:
        raise ValueError("H2 split requires nonempty train and holdout partitions")
    return frozenset(train), frozenset(holdout)


def _grams(name: str) -> frozenset[str]:
    words = tuple(word for word in name.casefold().split() if word)
    return frozenset(
        gram
        for word in words
        for gram in (f"^{word}$"[index : index + 3] for index in range(len(word) + 2))
    )


def name_tfidf_cosine(names: Mapping[str, str]) -> dict[NamePair, float]:
    """Compute sparse char-trigram TF-IDF cosine candidates without H2 coordinates."""
    inverted: dict[str, list[str]] = defaultdict(list)
    for genre_id, name in sorted(names.items()):
        for gram in _grams(name):
            inverted[gram].append(genre_id)
    norms: dict[str, float] = defaultdict(float)
    overlap: dict[NamePair, float] = defaultdict(float)
    total = len(names)
    for identifiers in inverted.values():
        if len(identifiers) > _MAX_GRAM_DOCUMENT_FREQUENCY:
            continue
        weight = math.log((total + 1) / (len(identifiers) + 1)) + 1.0
        for genre_id in identifiers:
            norms[genre_id] += weight * weight
        for offset, left in enumerate(identifiers):
            for right in identifiers[offset + 1 :]:
                key = (left, right) if left < right else (right, left)
                overlap[key] += weight * weight
    return {
        pair: value / math.sqrt(norms[pair[0]] * norms[pair[1]])
        for pair, value in overlap.items()
        if norms[pair[0]] and norms[pair[1]]
    }


def bounded_name_tfidf_cosine(names: Mapping[str, str]) -> dict[NamePair, float]:
    """Keep only deterministic top name candidates per genre for laptop-bounded calibration."""
    candidates = name_tfidf_cosine(names)
    per_genre: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for (left, right), score in candidates.items():
        per_genre[left].append((right, score))
        per_genre[right].append((left, score))
    retained: dict[NamePair, float] = {}
    for genre_id, items in per_genre.items():
        for neighbor, score in sorted(items, key=lambda item: (-item[1], item[0]))[
            :_MAX_NAME_CANDIDATES_PER_GENRE
        ]:
            key = (genre_id, neighbor) if genre_id < neighbor else (neighbor, genre_id)
            retained[key] = score
    return retained
