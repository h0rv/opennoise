import re
import unicodedata

import numpy as np


def ranking(predicted, relevant, k=50):
    if k < 1:
        raise ValueError("k must be positive")
    if len(set(predicted)) != len(predicted):
        raise ValueError("predicted items must be unique")
    relevant = set(relevant)
    if not relevant:
        return 0.0, 0.0
    hits = np.array([int(x in relevant) for x in predicted[:k]], dtype=float)
    discount = 1 / np.log2(np.arange(k) + 2)
    recall = hits.sum() / len(relevant)
    ideal = discount[: min(k, len(relevant))].sum()
    return float(recall), float((hits * discount[: len(hits)]).sum() / ideal)


def overlap(predicted, reference, k):
    if k < 1:
        raise ValueError("k must be positive")
    return len(set(predicted[:k]) & set(reference[:k])) / k


def average_precision(predicted, relevant):
    if len(set(predicted)) != len(predicted):
        raise ValueError("predicted items must be unique")
    relevant = set(relevant)
    if not relevant:
        return 0.0
    hits = np.array([item in relevant for item in predicted], dtype=float)
    return float((hits * np.cumsum(hits) / np.arange(1, len(hits) + 1)).sum() / len(relevant))


def best_cluster(truth, assignments):
    truth = np.unique(truth)
    if not len(truth):
        return 0.0, -1, -1
    best = (0.0, -1, -1)
    for level, labels in enumerate(assignments):
        sizes = np.bincount(labels)
        clusters, intersections = np.unique(labels[truth], return_counts=True)
        values = intersections / (len(truth) + sizes[clusters] - intersections)
        index = int(np.argmax(values))
        if values[index] > best[0]:
            best = float(values[index]), level, int(clusters[index])
    return best


def normalized_name(value):
    value = unicodedata.normalize("NFKD", value.casefold())
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


def name_agreement(left, right):
    a, b = normalized_name(left), normalized_name(right)
    tokens_a, tokens_b = set(a.split()), set(b.split())
    union = tokens_a | tokens_b
    return int(bool(a) and a == b), len(tokens_a & tokens_b) / len(union) if union else 0.0
