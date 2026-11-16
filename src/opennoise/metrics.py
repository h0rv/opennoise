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
