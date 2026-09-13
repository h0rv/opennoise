"""Receipt validation and bounded pair/matrix cache I/O."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from array import array
from contextlib import closing
from pathlib import Path
from typing import cast

import numpy as np
from scipy import sparse

from opennoise.checkpoints.source_neutral_certification import (
    SourceNeutralCheckpointCertification,
    verify_source_neutral_checkpoint_certification,
)
from opennoise.common import canonical_json, sha256_file, write_atomic_bytes
from opennoise.evidence.graph_projection import (
    EvidenceGraphProjectionArtifact,
    verify_evidence_graph_projection,
)

from .contracts import (
    _CHANNELS,
    _SEED_COUNT,
    ChannelPairCounts,
    FullGraphSignalError,
    FullGraphSignalInputs,
    FullGraphSignalSettings,
    MatrixBinding,
    MatrixCacheMetadata,
    NumericArray,
    _cache_metadata_sha256,
    _PairData,
    full_graph_signal_settings_sha256,
)


def _load_cache_metadata(
    path: Path,
    graph_receipt: EvidenceGraphProjectionArtifact,
    certificate: SourceNeutralCheckpointCertification,
    settings: FullGraphSignalSettings,
) -> MatrixCacheMetadata:
    """Validate every cache binding before either pair or matrix bytes are reused."""
    try:
        metadata = MatrixCacheMetadata.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise FullGraphSignalError("matrix cache metadata is invalid") from error
    if (
        metadata.output_sha256 != _cache_metadata_sha256(metadata)
        or metadata.graph_receipt_output_sha256 != graph_receipt.output_sha256
        or metadata.construction_certificate_output_sha256 != certificate.output_sha256
        or metadata.settings_sha256 != full_graph_signal_settings_sha256(settings)
    ):
        raise FullGraphSignalError("matrix cache metadata does not bind current inputs")
    return metadata


def _split_pair(artist_id: str, seed_id: str, settings: FullGraphSignalSettings) -> bool:
    value = int(
        hashlib.sha256(f"{settings.split_seed}:{artist_id}:{seed_id}".encode()).hexdigest()[:16], 16
    )
    return value / (2**64) < settings.heldout_fraction


def _load_inputs(
    inputs: FullGraphSignalInputs,
) -> tuple[EvidenceGraphProjectionArtifact, SourceNeutralCheckpointCertification]:
    try:
        receipt = EvidenceGraphProjectionArtifact.model_validate_json(
            inputs.graph_receipt.read_bytes()
        )
        verify_evidence_graph_projection(receipt)
        certificate = SourceNeutralCheckpointCertification.model_validate_json(
            inputs.construction_certificate.read_bytes()
        )
        verify_source_neutral_checkpoint_certification(certificate)
    except (OSError, ValueError) as error:
        raise FullGraphSignalError(
            "sealed receipt or construction certificate is invalid"
        ) from error
    database_sha, database_size = sha256_file(inputs.graph_database)
    if (database_sha, database_size) != (receipt.database_sha256, receipt.database_bytes):
        raise FullGraphSignalError("evidence graph database does not bind its receipt")
    database_binding = next(
        (binding for binding in certificate.inputs if binding.role == "evidence_graph_database"),
        None,
    )
    receipt_binding = next(
        (binding for binding in certificate.inputs if binding.role == "evidence_graph_receipt"),
        None,
    )
    if (
        database_binding is None
        or receipt_binding is None
        or (
            database_binding.bytes_sha256 != database_sha
            or receipt_binding.logical_sha256 != receipt.output_sha256
        )
    ):
        raise FullGraphSignalError(
            "construction certificate does not bind graph receipt and database"
        )
    if (
        certificate.membership.certified_observed_seed_count
        + certificate.membership.certified_unknown_seed_count
        != _SEED_COUNT
    ):
        raise FullGraphSignalError("construction certificate seed accounting is incomplete")
    return receipt, certificate


def _readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)


def _load_pairs(database_path: Path, settings: FullGraphSignalSettings) -> _PairData:  # noqa: C901, PLR0915
    """Stream sorted claims and deduplicate full pairs before assigning a split."""
    with closing(_readonly(database_path)) as database:
        seeds = tuple(
            str(row[0])
            for row in database.execute(
                "SELECT identifier FROM identity WHERE namespace = 'stable_seed' "
                "ORDER BY identifier"
            )
        )
        if len(seeds) != _SEED_COUNT:
            raise FullGraphSignalError("graph lacks the complete stable seed universe")
        seed_index = {seed_id: index for index, seed_id in enumerate(seeds)}
        cursor = database.execute(
            "SELECT subject_identifier, object_identifier, evidence_kind, release_group_id "
            "FROM claim WHERE subject_namespace = 'musicbrainz_artist' "
            "AND predicate = 'artist_membership' AND object_namespace = 'stable_seed' "
            "ORDER BY subject_identifier, object_identifier, evidence_kind, release_group_id"
        )
        artist_index: dict[str, int] = {}
        artist_ids: list[str] = []
        rows, columns = array("I"), array("I")
        full_weights, direct_weights, support_weights = array("f"), array("f"), array("f")
        heldout_rows, heldout_columns = array("I"), array("I")
        channel_counts: dict[str, int] = dict.fromkeys(_CHANNELS, 0)
        current: tuple[str, str] | None = None
        has_direct = has_alias = False
        support_groups: set[str] = set()
        claims_streamed = unique_pairs = 0

        def finish() -> None:
            nonlocal unique_pairs, has_direct, has_alias
            if current is None:
                return
            artist_id, seed_id = current
            artist_row = artist_index.setdefault(artist_id, len(artist_ids))
            if artist_row == len(artist_ids):
                artist_ids.append(artist_id)
            if has_direct:
                channel_counts["artist_direct"] += 1
            if support_groups:
                channel_counts["release_group_support"] += 1
            if has_alias:
                channel_counts["reviewed_alias_context"] += 1
            unique_pairs += 1
            if unique_pairs > settings.maximum_pairs:
                raise FullGraphSignalError("unique membership pair bound exceeded")
            if _split_pair(artist_id, seed_id, settings):
                heldout_rows.append(artist_row)
                heldout_columns.append(seed_index[seed_id])
            else:
                rows.append(artist_row)
                columns.append(seed_index[seed_id])
                direct = 1.0 if has_direct else 0.0
                support = math.log1p(len(support_groups)) + (1.0 if has_alias else 0.0)
                direct_weights.append(direct)
                support_weights.append(support)
                full_weights.append(3.0 * direct + support if direct or support else 1.0)
            has_direct = has_alias = False
            support_groups.clear()

        for artist_id, seed_id, evidence_kind, release_group_id in cursor:
            claims_streamed += 1
            pair = str(artist_id), str(seed_id)
            if pair != current:
                finish()
                current = pair
            if evidence_kind == "artist_direct":
                has_direct = True
            elif evidence_kind == "release_group_support" and release_group_id:
                support_groups.add(str(release_group_id))
            elif evidence_kind == "reviewed_alias_context":
                has_alias = True
        finish()
    return _PairData(
        rows=rows,
        columns=columns,
        full_weights=full_weights,
        direct_weights=direct_weights,
        support_weights=support_weights,
        heldout_rows=heldout_rows,
        heldout_columns=heldout_columns,
        artist_ids=tuple(artist_ids),
        seed_ids=seeds,
        claims_streamed=claims_streamed,
        channel_pairs=ChannelPairCounts(**channel_counts),
    )


def _save_matrix(path: Path, matrix: sparse.csr_matrix, name: str) -> MatrixBinding:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".partial.npz")
    sparse.save_npz(temporary, matrix, compressed=True)
    temporary.replace(path)
    digest, size = sha256_file(path)
    return MatrixBinding(
        name=name,
        path=path.name,
        sha256=digest,
        byte_count=size,
        row_count=matrix.shape[0],
        nonzero_count=matrix.nnz,
    )


def _save_pair_data(path: Path, data: _PairData) -> MatrixBinding:
    """Atomically persist the complete deduplicated split as typed primitive arrays."""
    temporary = path.with_suffix(".partial.npz")
    np.savez_compressed(
        temporary,
        rows=np.frombuffer(data.rows, dtype=np.uint32),
        columns=np.frombuffer(data.columns, dtype=np.uint32),
        full_weights=np.frombuffer(data.full_weights, dtype=np.float32),
        direct_weights=np.frombuffer(data.direct_weights, dtype=np.float32),
        support_weights=np.frombuffer(data.support_weights, dtype=np.float32),
        heldout_rows=np.frombuffer(data.heldout_rows, dtype=np.uint32),
        heldout_columns=np.frombuffer(data.heldout_columns, dtype=np.uint32),
        claims_streamed=np.asarray([data.claims_streamed], dtype=np.uint64),
        channel_pairs=np.asarray(
            [
                data.channel_pairs.artist_direct,
                data.channel_pairs.release_group_support,
                data.channel_pairs.reviewed_alias_context,
            ],
            dtype=np.uint64,
        ),
    )
    temporary.replace(path)
    digest, size = sha256_file(path)
    return MatrixBinding(
        name="deduplicated_complete_pair_split",
        path=path.name,
        sha256=digest,
        byte_count=size,
        row_count=len(data.artist_ids),
        nonzero_count=len(data.rows) + len(data.heldout_rows),
    )


def _save_artist_ids(path: Path, data: _PairData) -> tuple[str, int]:
    """Persist row/column identity sidecar separately from numeric sparse arrays."""
    payload = canonical_json({"artist_ids": data.artist_ids, "seed_ids": data.seed_ids}) + b"\n"
    write_atomic_bytes(path, payload)
    return sha256_file(path)


def _load_pair_data(
    cache_directory: Path, binding: MatrixBinding, artist_ids_sha: str, artist_ids_size: int
) -> _PairData:
    """Reload a fully verified pair/index sidecar without touching the claim table."""
    if Path(binding.path).is_absolute():
        raise FullGraphSignalError("cache paths must be relative to the configured cache root")
    pair_path = cache_directory / binding.path
    identities_path = (
        cache_directory
        / f"artist-ids-{binding.path.removeprefix('pairs-').removesuffix('.npz')}.json"
    )
    if sha256_file(pair_path) != (binding.sha256, binding.byte_count) or sha256_file(
        identities_path
    ) != (artist_ids_sha, artist_ids_size):
        raise FullGraphSignalError("pair cache bytes do not replay")
    identities = json.loads(identities_path.read_text(encoding="utf-8"))
    with np.load(pair_path, allow_pickle=False) as arrays:

        def values(name: str, code: str, dtype: np.dtype[np.generic]) -> NumericArray:
            source = arrays[name]
            if source.dtype != dtype or source.ndim != 1:
                raise FullGraphSignalError("pair cache array has an unexpected primitive dtype")
            output = array(code)
            output.frombytes(np.ascontiguousarray(source).tobytes())
            return cast("NumericArray", output)

        channels = arrays["channel_pairs"]
        if channels.dtype != np.dtype(np.uint64) or channels.shape != (3,):
            raise FullGraphSignalError(
                "pair cache channel counts have an unexpected primitive dtype"
            )
        return _PairData(
            rows=values("rows", "I", np.dtype(np.uint32)),
            columns=values("columns", "I", np.dtype(np.uint32)),
            full_weights=values("full_weights", "f", np.dtype(np.float32)),
            direct_weights=values("direct_weights", "f", np.dtype(np.float32)),
            support_weights=values("support_weights", "f", np.dtype(np.float32)),
            heldout_rows=values("heldout_rows", "I", np.dtype(np.uint32)),
            heldout_columns=values("heldout_columns", "I", np.dtype(np.uint32)),
            artist_ids=tuple(str(value) for value in identities["artist_ids"]),
            seed_ids=tuple(str(value) for value in identities["seed_ids"]),
            claims_streamed=int(arrays["claims_streamed"][0]),
            channel_pairs=ChannelPairCounts(
                artist_direct=int(channels[0]),
                release_group_support=int(channels[1]),
                reviewed_alias_context=int(channels[2]),
            ),
        )


def _load_or_write_matrices(  # noqa: PLR0913, PLR0917
    cache_directory: Path,
    cache_key: str,
    graph_receipt: EvidenceGraphProjectionArtifact,
    certificate: SourceNeutralCheckpointCertification,
    settings: FullGraphSignalSettings,
    pair_binding: MatrixBinding,
    artist_ids_sha: str,
    artist_ids_size: int,
    binary: sparse.csr_matrix,
    weighted: sparse.csr_matrix,
    direct: sparse.csr_matrix,
) -> tuple[
    tuple[MatrixBinding, ...],
    tuple[sparse.csr_matrix, sparse.csr_matrix, sparse.csr_matrix],
    Path,
    str,
]:
    """Reuse only a hash-bound cache; otherwise atomically replace all matrices."""
    cache_directory.mkdir(parents=True, exist_ok=True)
    metadata_path = cache_directory / f"cache-{cache_key}.json"
    if metadata_path.exists():
        try:
            metadata = _load_cache_metadata(metadata_path, graph_receipt, certificate, settings)
            loaded: list[sparse.csr_matrix] = []
            for binding in metadata.matrices:
                if Path(binding.path).is_absolute():
                    raise FullGraphSignalError("matrix cache paths must be relative")
                path = cache_directory / binding.path
                digest, size = sha256_file(path)
                if (digest, size) != (binding.sha256, binding.byte_count):
                    raise FullGraphSignalError("matrix cache bytes do not match metadata")
                matrix = sparse.load_npz(path).tocsr().astype(np.float32)
                if matrix.shape != binary.shape or matrix.nnz != binding.nonzero_count:
                    raise FullGraphSignalError("matrix cache shape does not match current graph")
                loaded.append(matrix)
            if tuple(binding.name for binding in metadata.matrices) != (
                "binary_all_open",
                "weighted_all_open",
                "binary_direct_only",
            ):
                raise FullGraphSignalError("matrix cache has an unknown matrix set")
            return (
                metadata.matrices,
                (loaded[0], loaded[1], loaded[2]),
                metadata_path,
                metadata.output_sha256,
            )
        except (OSError, ValueError) as error:
            raise FullGraphSignalError("matrix cache exists but cannot be safely reused") from error
    bindings = (
        _save_matrix(cache_directory / f"binary-{cache_key}.npz", binary, "binary_all_open"),
        _save_matrix(cache_directory / f"weighted-{cache_key}.npz", weighted, "weighted_all_open"),
        _save_matrix(cache_directory / f"direct-{cache_key}.npz", direct, "binary_direct_only"),
    )
    preliminary = MatrixCacheMetadata(
        graph_receipt_output_sha256=graph_receipt.output_sha256,
        construction_certificate_output_sha256=certificate.output_sha256,
        settings_sha256=full_graph_signal_settings_sha256(settings),
        pair_data_npz=pair_binding,
        artist_ids_sha256=artist_ids_sha,
        artist_ids_byte_count=artist_ids_size,
        matrices=bindings,
        output_sha256="0" * 64,
    )
    metadata = preliminary.model_copy(update={"output_sha256": _cache_metadata_sha256(preliminary)})
    write_atomic_bytes(metadata_path, metadata.model_dump_json(indent=2).encode() + b"\n")
    return bindings, (binary, weighted, direct), metadata_path, metadata.output_sha256


def _load_or_stream_pair_data(  # noqa: PLR0913, PLR0917
    cache_directory: Path,
    cache_key: str,
    graph_receipt: EvidenceGraphProjectionArtifact,
    certificate: SourceNeutralCheckpointCertification,
    settings: FullGraphSignalSettings,
    database_path: Path,
) -> tuple[_PairData, MatrixBinding, str, int]:
    """Bypass the claim scan entirely when a verified pair/index sidecar exists."""
    cache_directory.mkdir(parents=True, exist_ok=True)
    metadata_path = cache_directory / f"cache-{cache_key}.json"
    if metadata_path.exists():
        metadata = _load_cache_metadata(metadata_path, graph_receipt, certificate, settings)
        data = _load_pair_data(
            cache_directory,
            metadata.pair_data_npz,
            metadata.artist_ids_sha256,
            metadata.artist_ids_byte_count,
        )
        return (
            data,
            metadata.pair_data_npz,
            metadata.artist_ids_sha256,
            metadata.artist_ids_byte_count,
        )
    data = _load_pairs(database_path, settings)
    pair_binding = _save_pair_data(cache_directory / f"pairs-{cache_key}.npz", data)
    artist_ids_sha, artist_ids_size = _save_artist_ids(
        cache_directory / f"artist-ids-{cache_key}.json", data
    )
    return data, pair_binding, artist_ids_sha, artist_ids_size
