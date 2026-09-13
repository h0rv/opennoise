"""Conservative Unicode and compositional label mechanics.

These functions deliberately never compute edit distance.  Candidate retrieval
requires a shared normalized token, and promotion requires a unique normalized
form; character n-grams only rank already-retrieved candidates.
"""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Final

_TOKEN: Final = re.compile(r"[^\W_]+", re.UNICODE)
_GENERIC_ROOTS: Final = frozenset({"music", "popular music", "genre", "genres", "style"})
_ACRONYM_IGNORED: Final = frozenset({"the", "a", "an", "of", "for", "to", "in", "on"})
_CONJUNCTION: Final = "and"
_MIN_ACRONYM_TERMS: Final = 2
_MIN_ACRONYM_LENGTH: Final = 3
_MAX_ACRONYM_LENGTH: Final = 8
_NGRAM_SIZE: Final = 3


def normalized_label(value: str) -> str:
    """Return a stable Unicode/punctuation-insensitive label form."""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    expanded = without_marks.replace("&", " and ")
    return " ".join(_TOKEN.findall(expanded))


def tokens(value: str) -> tuple[str, ...]:
    """Return normalized unique-preserving lexical tokens."""
    return tuple(dict.fromkeys(normalized_label(value).split()))


def is_generic_root(value: str) -> bool:
    """Reject target-to-root mappings that communicate no genre distinction."""
    return normalized_label(value) in _GENERIC_ROOTS


def token_jaccard(left: str, right: str) -> float:
    """Return token Jaccard after conservative Unicode normalization."""
    left_tokens, right_tokens = frozenset(tokens(left)), frozenset(tokens(right))
    union = left_tokens | right_tokens
    return len(left_tokens & right_tokens) / len(union) if union else 0.0


def character_ngram_cosine(left: str, right: str) -> float:
    """Rank lexical candidates without making typo-only retrieval possible."""
    left_grams, right_grams = _ngrams(normalized_label(left)), _ngrams(normalized_label(right))
    if not left_grams or not right_grams:
        return 0.0
    return len(left_grams & right_grams) / math.sqrt(len(left_grams) * len(right_grams))


def head_modifier_score(seed_name: str, candidate_name: str) -> float:
    """Score shared heads and explicit modifier containment for review only."""
    seed_tokens, candidate_tokens = tokens(seed_name), tokens(candidate_name)
    if not seed_tokens or not candidate_tokens:
        return 0.0
    shared_head = 1.0 if seed_tokens[-1] == candidate_tokens[-1] else 0.0
    seed_modifiers = frozenset(seed_tokens[:-1])
    candidate_modifiers = frozenset(candidate_tokens[:-1])
    modifier_union = seed_modifiers | candidate_modifiers
    modifier_score = (
        len(seed_modifiers & candidate_modifiers) / len(modifier_union) if modifier_union else 1.0
    )
    return 0.6 * shared_head + 0.4 * modifier_score


def shares_retrieval_token(seed_name: str, candidate_name: str) -> bool:
    """Require a real common token before n-grams can influence a ranking."""
    return bool(set(tokens(seed_name)) & set(tokens(candidate_name)))


def initialism_forms(value: str) -> frozenset[str]:
    """Return explainable compact forms without inventing synonym dictionaries.

    ``and`` is rendered as ``n`` because that is the standard compact form in
    labels such as ``drum and bass``.  This is only a retrieval signal; the
    caller must separately require one source and one seed-side expansion.
    """
    label_tokens = tuple(token for token in tokens(value) if token not in _ACRONYM_IGNORED)
    if len(label_tokens) < _MIN_ACRONYM_TERMS:
        return frozenset()
    normal = "".join("n" if token == _CONJUNCTION else token[0] for token in label_tokens)
    compact = normalized_label(value).replace(" ", "")
    forms = {normal}
    if len(compact) >= _MIN_ACRONYM_LENGTH:
        forms.add(compact)
    return frozenset(
        form
        for form in forms
        if _MIN_ACRONYM_LENGTH <= len(form) <= _MAX_ACRONYM_LENGTH and form.isalnum()
    )


def _ngrams(value: str) -> frozenset[str]:
    padded = f"^{value}$"
    if len(padded) <= _NGRAM_SIZE:
        return frozenset({padded})
    return frozenset(
        padded[index : index + _NGRAM_SIZE] for index in range(len(padded) - _NGRAM_SIZE + 1)
    )
