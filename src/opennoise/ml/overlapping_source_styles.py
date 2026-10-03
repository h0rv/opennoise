"""Overlapping source-value communities with authority and bounded sparse support.

A community is an observed musical value's weighted association neighborhood.
Memberships overlap freely; these are metadata hypotheses, not genre identities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from scipy import sparse

from opennoise.ml.artist_feature_enrichment import MAX_BATCH, _matrix
from opennoise.ml.artist_style_associations import _weighted_cues

if TYPE_CHECKING:
    from collections.abc import Sequence

    from opennoise.ml.artist_style_associations import StyleProfiles

NEIGHBORS = 128
MIN_SUPPORT = 2
SMOOTHING = 4
MAX_PAIR_WORK = 50_000_000


@dataclass
class OverlappingStyles:
    """Each observed value seeds one overlapping, regularized source community."""

    vocabulary: tuple[str, ...]
    associations: sparse.csr_matrix
    rarity_power: float

    def rank_batch(
        self, profiles: StyleProfiles, artists: Sequence[str]
    ) -> dict[str, tuple[str, ...]]:
        """Rank hypotheses using deduplicated authority, excluding all known values."""
        return {
            artist: tuple(value for value, _score in values)
            for artist, values in self.score_batch(profiles, artists).items()
        }

    def score_batch(
        self, profiles: StyleProfiles, artists: Sequence[str]
    ) -> dict[str, tuple[tuple[str, float], ...]]:
        """Expose raw association scores without changing the frozen top-ten ranking.

        Missing queries and primary-cold queries abstain. Raw scores are not
        probabilities of genre membership or source observation.
        """
        if len(artists) > MAX_BATCH:
            raise ValueError("overlap ranking batch exceeds bound")
        present = tuple(artist for artist in artists if artist in profiles.music)
        scores = (_weighted_cues(profiles, present, self.vocabulary) @ self.associations).tocsr()
        result: dict[str, tuple[tuple[str, float], ...]] = dict.fromkeys(artists, ())
        for row, artist in enumerate(present):
            if not profiles.artist_music[artist]:
                result[artist] = ()
                continue
            start, end = scores.indptr[row : row + 2]
            columns, values = scores.indices[start:end], scores.data[start:end]
            known = set(profiles.music[artist])
            eligible = np.array(
                [i for i, col in enumerate(columns) if self.vocabulary[col] not in known],
                dtype=np.int64,
            )
            chosen = eligible[np.lexsort((columns[eligible], -values[eligible]))[:10]]
            result[artist] = tuple((self.vocabulary[columns[i]], float(values[i])) for i in chosen)
        return result


def fit_overlapping_styles(profiles: StyleProfiles, *, rarity_power: float) -> OverlappingStyles:
    """Fit only training rows, keeping support-two rare values without anchor gates."""
    if rarity_power not in (0.15, 0.35):
        raise ValueError("only the two preregistered rarity corrections are permitted")
    artists = tuple(sorted(profiles.music))
    vocabulary = tuple(sorted({value for row in profiles.music.values() for value in row}))
    binary = _matrix(artists, profiles.music, vocabulary)
    weighted = _weighted_cues(profiles, artists, vocabulary)
    degree = np.asarray(binary.sum(axis=1)).ravel()
    if float(degree @ degree) > MAX_PAIR_WORK:
        raise ValueError("overlap pair multiplication exceeds bound")
    correction = 1 / np.maximum(1, degree) ** 0.5
    joints = (binary.T @ binary).tocsr()
    mass = (weighted.T @ sparse.diags(correction) @ weighted).tocsr()
    cue_mass = np.asarray(weighted.T @ correction).ravel()
    support = np.asarray(binary.sum(axis=0)).ravel()
    prior = support / max(1, len(artists))
    rows, columns, scores = [], [], []
    for cue in range(len(vocabulary)):
        start, end = mass.indptr[cue : cue + 2]
        targets, values = mass.indices[start:end], mass.data[start:end]
        joint = np.asarray(joints[cue, targets].toarray()).ravel()
        keep = (joint >= MIN_SUPPORT) & (targets != cue)
        targets, values, joint = targets[keep], values[keep], joint[keep]
        score = (
            values
            / (cue_mass[cue] + SMOOTHING)
            / np.maximum(prior[targets], 1 / max(1, len(artists))) ** rarity_power
            * joint
            / (joint + MIN_SUPPORT)
        )
        selected = np.lexsort((targets, -score))[:NEIGHBORS]
        rows.extend([cue] * len(selected))
        columns.extend(targets[selected].tolist())
        scores.extend(score[selected].tolist())
    return OverlappingStyles(
        vocabulary,
        sparse.csr_matrix((scores, (rows, columns)), shape=(len(vocabulary), len(vocabulary))),
        rarity_power,
    )
