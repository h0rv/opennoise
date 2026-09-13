"""Bounded sparse overlap transformations."""

from __future__ import annotations

from typing import cast

import numpy as np
from scipy import sparse

from .contracts import FullGraphSignalError, FullGraphSignalSettings, NumericArray


def _csr(
    rows: NumericArray, columns: NumericArray, values: NumericArray, shape: tuple[int, int]
) -> sparse.csr_matrix:
    matrix = sparse.csr_matrix(
        (
            np.frombuffer(values, dtype=np.float32),
            (np.frombuffer(rows, dtype=np.uint32), np.frombuffer(columns, dtype=np.uint32)),
        ),
        shape=shape,
        dtype=np.float32,
    )
    matrix.sum_duplicates()
    matrix.eliminate_zeros()
    return matrix


def _trim_rows(matrix: sparse.csr_matrix, limit: int) -> sparse.csr_matrix:
    """Keep deterministic top overlap neighbors per seed to bound ranking work."""
    output_rows: list[np.ndarray] = []
    output_columns: list[np.ndarray] = []
    output_values: list[np.ndarray] = []
    for row in range(matrix.shape[0]):
        start, end = matrix.indptr[row], matrix.indptr[row + 1]
        values, columns = matrix.data[start:end], matrix.indices[start:end]
        if len(values) > limit:
            selected = np.argpartition(values, -limit)[-limit:]
            selected = selected[np.lexsort((columns[selected], -values[selected]))]
            values, columns = values[selected], columns[selected]
        if len(values):
            output_rows.append(np.full(len(values), row, dtype=np.uint32))
            output_columns.append(columns.astype(np.uint32, copy=False))
            output_values.append(values.astype(np.float32, copy=False))
    if not output_rows:
        return sparse.csr_matrix(matrix.shape, dtype=np.float32)
    return sparse.csr_matrix(
        (
            np.concatenate(output_values),
            (np.concatenate(output_rows), np.concatenate(output_columns)),
        ),
        shape=matrix.shape,
        dtype=np.float32,
    )


def _cap_artist_rows(
    matrix: sparse.csr_matrix, settings: FullGraphSignalSettings
) -> sparse.csr_matrix:
    """Bound feature expansion while retaining the complete deduplicated pair matrix on disk."""
    return _trim_rows(matrix, settings.maximum_genres_per_artist_for_cooccurrence)


def _cooccurrence(
    matrix: sparse.csr_matrix, settings: FullGraphSignalSettings
) -> sparse.csr_matrix:
    bounded = _cap_artist_rows(matrix, settings)
    cooccurrence = cast("sparse.csr_matrix", (bounded.T @ bounded).tocsr().astype(np.float32))
    cooccurrence.setdiag(0.0)
    cooccurrence.eliminate_zeros()
    if cooccurrence.nnz > settings.maximum_cooccurrence_nnz:
        raise FullGraphSignalError("raw sparse cooccurrence bound exceeded")
    return cooccurrence


def _jaccard_neighbors(
    binary: sparse.csr_matrix,
    cooccurrence: sparse.csr_matrix,
    settings: FullGraphSignalSettings,
) -> sparse.csr_matrix:
    cooccurrence = cast("sparse.csr_matrix", cooccurrence.copy())
    counts = np.asarray(binary.sum(axis=0)).ravel()
    rows = np.repeat(np.arange(cooccurrence.shape[0]), np.diff(cooccurrence.indptr))
    cooccurrence.data /= counts[rows] + counts[cooccurrence.indices] - cooccurrence.data
    return _trim_rows(cooccurrence, settings.maximum_genre_neighbors)


def _cosine_neighbors(
    weighted: sparse.csr_matrix, settings: FullGraphSignalSettings
) -> sparse.csr_matrix:
    cooccurrence = _cooccurrence(weighted, settings)
    norms = np.sqrt(np.asarray(weighted.multiply(weighted).sum(axis=0)).ravel())
    rows = np.repeat(np.arange(cooccurrence.shape[0]), np.diff(cooccurrence.indptr))
    denominator = norms[rows] * norms[cooccurrence.indices]
    cooccurrence.data = np.divide(
        cooccurrence.data, denominator, out=np.zeros_like(cooccurrence.data), where=denominator > 0
    )
    cooccurrence.eliminate_zeros()
    return _trim_rows(cooccurrence, settings.maximum_genre_neighbors)


def _ppmi_neighbors(
    binary: sparse.csr_matrix,
    cooccurrence: sparse.csr_matrix,
    settings: FullGraphSignalSettings,
) -> sparse.csr_matrix:
    cooccurrence = cast("sparse.csr_matrix", cooccurrence.copy())
    counts = np.asarray(binary.sum(axis=0)).ravel()
    rows = np.repeat(np.arange(cooccurrence.shape[0]), np.diff(cooccurrence.indptr))
    numerator = cooccurrence.data * binary.shape[0]
    denominator = counts[rows] * counts[cooccurrence.indices]
    cooccurrence.data = np.maximum(0.0, np.log(np.divide(numerator, denominator)))
    cooccurrence.eliminate_zeros()
    return _trim_rows(cooccurrence, settings.maximum_genre_neighbors)
