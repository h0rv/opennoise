"""Prepare a sharded, local-only direct MusicBrainz discovery candidate.

The candidate is deliberately outside the Wikidata v1/v2 static-discovery
schemas. It exposes only literal proper-genre artist-record observations joined
to exact-MBID canonical names, and it never authorizes publication or serving.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import stat
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Final, Literal

from pydantic import Field, model_validator

from opennoise.checkpoints.musicbrainz_direct_discovery_delta import (
    _certified_asset,
    _node_ids,
)
from opennoise.deployment.musicbrainz_direct_artist_name_recovery import (
    DirectArtistNameRecoveryReceipt,
    iter_verified_unique_recovered_names,
)
from opennoise.deployment.musicbrainz_direct_canonical_artist_name_custody import (
    DirectCanonicalArtistNameCustodyReceipt,
    iter_verified_direct_canonical_artist_names,
)
from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreCustodyReceipt,
    iter_verified_portable_direct_proper_genre_claims,
)
from opennoise.models import FrozenModel
from opennoise.types import (
    Sha256,  # noqa: TC001  # Pydantic resolves this annotation at definition.
)

_STATIC_ASSET: Final = "static_discovery"
_ATLAS_ASSET: Final = "semantic_atlas"
_MAX_ROWS_PER_SHARD: Final = 1_000
_MAXIMUM_SHARD_BYTES: Final = 8 * 1024 * 1024
_MAXIMUM_MEMBERSHIP_ROW_BYTES: Final = 16 * 1024
_MAXIMUM_MANIFEST_BYTES: Final = 2 * 1024 * 1024
_EXPECTED_PLACED_CANDIDATE_SEED_COUNT: Final = 412


class LocalMusicBrainzStaticCandidateError(ValueError):
    """The requested local candidate cannot be proven direct and custody-bound."""


class LocalCandidateMembership(FrozenModel):
    """One direct source pair; no inferred, tag, release, or peer evidence is representable."""

    seed_id: str = Field(min_length=1)
    artist_mbid: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    canonical_name: str = Field(min_length=1)
    musicbrainz_genre_id: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    source_kind: Literal["musicbrainz_direct_proper_genre_exact_artist_record"] = (
        "musicbrainz_direct_proper_genre_exact_artist_record"
    )
    source_record_id: str = Field(min_length=1)
    source_record_sha256: Sha256
    source_evidence_ref: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_exact_artist_source_identity(self) -> LocalCandidateMembership:
        """Prevent a name, tag, release, or other namespace from masquerading as direct."""
        if self.source_record_id != f"musicbrainz:artist:{self.artist_mbid}":
            raise ValueError("candidate membership source record is not its exact artist MBID")
        return self


class LocalCandidateShard(FrozenModel):
    """One immutable bounded genre-local JSONL file."""

    seed_id: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    path: str = Field(pattern=r"^genres/[0-9a-f]{64}/[0-9]{4}\.[0-9a-f]{64}\.jsonl$")
    row_count: int = Field(gt=0, le=_MAX_ROWS_PER_SHARD)
    sha256: Sha256
    byte_count: int = Field(gt=0, le=_MAXIMUM_SHARD_BYTES)


class LocalMusicBrainzStaticCandidateManifest(FrozenModel):
    """The complete local-only candidate index and its custody bindings."""

    revision: Literal["musicbrainz-direct-local-static-candidate-v1"] = (
        "musicbrainz-direct-local-static-candidate-v1"
    )
    publication_scope: Literal["local_candidate_preparation_only"] = (
        "local_candidate_preparation_only"
    )
    public_export_authorized: Literal[False] = False
    serving_authorized: Literal[False] = False
    membership_claims_authorized: Literal[False] = False
    release_gate: Literal[False] = False
    source_kind: Literal["musicbrainz_direct_proper_genre_exact_artist_record"] = (
        "musicbrainz_direct_proper_genre_exact_artist_record"
    )
    direct_custody_receipt_sha256: Sha256
    direct_custody_output_sha256: Sha256
    direct_claims_object_sha256: Sha256
    canonical_name_receipt_sha256: Sha256
    canonical_name_object_sha256: Sha256
    recovered_name_receipt_sha256: Sha256
    recovered_name_object_sha256: Sha256
    certified_static_discovery_sha256: Sha256
    certified_semantic_atlas_sha256: Sha256
    placed_candidate_seed_ids: tuple[str, ...] = Field(min_length=1)
    membership_count: int = Field(gt=0)
    shard_row_limit: Literal[1000] = _MAX_ROWS_PER_SHARD
    shards: tuple[LocalCandidateShard, ...] = Field(min_length=1)
    output_sha256: Sha256

    @model_validator(mode="after")
    def require_consistent_local_manifest(self) -> LocalMusicBrainzStaticCandidateManifest:
        """Require a complete deterministic partition without loosening local-only policy."""
        if (
            self.public_export_authorized
            or self.serving_authorized
            or self.membership_claims_authorized
            or self.release_gate
        ):
            raise ValueError("local candidate manifest cannot authorize publication or serving")
        if self.placed_candidate_seed_ids != tuple(sorted(self.placed_candidate_seed_ids)):
            raise ValueError("candidate seed IDs must be sorted")
        if len(self.placed_candidate_seed_ids) != len(set(self.placed_candidate_seed_ids)):
            raise ValueError("candidate seed IDs repeat")
        if tuple((item.seed_id, item.ordinal) for item in self.shards) != tuple(
            sorted((item.seed_id, item.ordinal) for item in self.shards)
        ):
            raise ValueError("candidate shards must be source-seed and ordinal ordered")
        if sum(item.row_count for item in self.shards) != self.membership_count:
            raise ValueError("candidate shard rows do not equal membership count")
        shards_by_seed = {
            seed_id: tuple(item.ordinal for item in self.shards if item.seed_id == seed_id)
            for seed_id in self.placed_candidate_seed_ids
        }
        if set(shards_by_seed) != {item.seed_id for item in self.shards}:
            raise ValueError("candidate shard seed is outside placed candidate scope")
        if any(
            not ordinals or ordinals != tuple(range(len(ordinals)))
            for ordinals in shards_by_seed.values()
        ):
            raise ValueError("candidate shard ordinals must be contiguous per seed")
        return self


def local_candidate_manifest_sha256(manifest: LocalMusicBrainzStaticCandidateManifest) -> str:
    """Hash the manifest independently of its self-reference."""
    return _sha256_bytes(
        _canonical_json(manifest.model_dump(mode="json", exclude={"output_sha256"}))
    )


def verify_local_musicbrainz_direct_static_candidate(
    output_directory: Path,
) -> LocalMusicBrainzStaticCandidateManifest:
    """Verify local output integrity, not the separately checked source custody inputs."""
    _require_real_directory(output_directory, "candidate output directory")
    manifest_path = output_directory / "manifest.json"
    manifest_bytes = _read_regular_file(
        manifest_path, "candidate manifest", maximum_bytes=_MAXIMUM_MANIFEST_BYTES
    )
    try:
        manifest = LocalMusicBrainzStaticCandidateManifest.model_validate_json(manifest_bytes)
    except ValueError as error:
        raise LocalMusicBrainzStaticCandidateError("candidate manifest is invalid") from error
    if local_candidate_manifest_sha256(manifest) != manifest.output_sha256:
        raise LocalMusicBrainzStaticCandidateError("candidate manifest self-hash does not match")
    if manifest_bytes != _canonical_json(manifest.model_dump(mode="json")) + b"\n":
        raise LocalMusicBrainzStaticCandidateError("candidate manifest is not canonical JSON")

    observed_memberships: set[tuple[str, str]] = set()
    last_artist_by_seed: dict[str, str] = {}
    observed_count = 0
    for shard in manifest.shards:
        _verify_candidate_shard(
            output_directory,
            shard,
            observed_memberships=observed_memberships,
            last_artist_by_seed=last_artist_by_seed,
        )
        observed_count += shard.row_count
    if observed_count != manifest.membership_count:
        raise LocalMusicBrainzStaticCandidateError(
            "candidate membership count does not match shards"
        )
    return manifest


def build_local_musicbrainz_direct_static_candidate(  # noqa: PLR0913 - explicit custody inputs.
    *,
    output_directory: Path,
    direct_custody_receipt_path: Path,
    direct_custody_receipt_sha256: str,
    direct_object_store: Path,
    canonical_name_receipt_path: Path,
    canonical_name_receipt_sha256: str,
    canonical_name_object_store: Path,
    recovered_name_receipt_path: Path,
    recovered_name_receipt_sha256: str,
    recovered_name_object_store: Path,
    static_discovery_path: Path,
    certified_manifest_path: Path,
    certified_layout_path: Path,
    expected_placed_candidate_seed_count: int = _EXPECTED_PLACED_CANDIDATE_SEED_COUNT,
) -> LocalMusicBrainzStaticCandidateManifest:
    """Write a new sharded candidate only after every source and scope gate verifies."""
    if output_directory.exists() or output_directory.is_symlink():
        raise LocalMusicBrainzStaticCandidateError("candidate output directory already exists")
    direct_bytes = _read_receipt(direct_custody_receipt_path, direct_custody_receipt_sha256)
    name_bytes = _read_receipt(canonical_name_receipt_path, canonical_name_receipt_sha256)
    recovery_bytes = _read_receipt(recovered_name_receipt_path, recovered_name_receipt_sha256)
    try:
        direct = DirectProperGenreCustodyReceipt.model_validate_json(direct_bytes)
        names = DirectCanonicalArtistNameCustodyReceipt.model_validate_json(name_bytes)
        recovered = DirectArtistNameRecoveryReceipt.model_validate_json(recovery_bytes)
    except ValueError as error:
        raise LocalMusicBrainzStaticCandidateError(
            "candidate custody receipt is invalid"
        ) from error
    _require_input_bindings(
        direct,
        names,
        recovered,
        direct_custody_receipt_sha256=direct_custody_receipt_sha256,
        canonical_name_receipt_sha256=canonical_name_receipt_sha256,
    )
    candidate_ids, static_sha, atlas_sha = _placed_candidate_seed_ids(
        static_discovery_path=static_discovery_path,
        certified_manifest_path=certified_manifest_path,
        certified_layout_path=certified_layout_path,
        direct=direct,
        direct_object_store=direct_object_store,
    )
    if len(candidate_ids) != expected_placed_candidate_seed_count:
        raise LocalMusicBrainzStaticCandidateError("placed candidate seed count does not match pin")
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".mb-direct-candidate-", dir=output_directory.parent
    ) as temp:
        staging = Path(temp) / "candidate"
        staging.mkdir()
        manifest = _write_candidate(
            staging,
            direct=direct,
            direct_object_store=direct_object_store,
            names=names,
            canonical_name_object_store=canonical_name_object_store,
            recovered=recovered,
            recovered_name_object_store=recovered_name_object_store,
            candidate_ids=candidate_ids,
            direct_receipt_sha256=direct_custody_receipt_sha256,
            canonical_name_receipt_sha256=canonical_name_receipt_sha256,
            recovered_name_receipt_sha256=recovered_name_receipt_sha256,
            static_sha=static_sha,
            atlas_sha=atlas_sha,
        )
        staging.replace(output_directory)
    return manifest


def _write_candidate(  # noqa: PLR0913 - source custody dimensions stay explicit.
    staging: Path,
    *,
    direct: DirectProperGenreCustodyReceipt,
    direct_object_store: Path,
    names: DirectCanonicalArtistNameCustodyReceipt,
    canonical_name_object_store: Path,
    recovered: DirectArtistNameRecoveryReceipt,
    recovered_name_object_store: Path,
    candidate_ids: tuple[str, ...],
    direct_receipt_sha256: str,
    canonical_name_receipt_sha256: str,
    recovered_name_receipt_sha256: str,
    static_sha: str,
    atlas_sha: str,
) -> LocalMusicBrainzStaticCandidateManifest:
    with closing(sqlite3.connect(staging / "join.sqlite")) as connection:
        connection.row_factory = sqlite3.Row
        _create_join_tables(connection)
        _stream_names(
            connection,
            names=names,
            canonical_name_object_store=canonical_name_object_store,
            recovered=recovered,
            recovered_name_object_store=recovered_name_object_store,
        )
        _stream_direct_claims(
            connection,
            direct=direct,
            direct_object_store=direct_object_store,
            candidate_ids=frozenset(candidate_ids),
        )
        _require_complete_named_scope(connection, candidate_ids)
        shards = _write_shards(staging, connection, candidate_ids)
    (staging / "join.sqlite").unlink()
    draft = LocalMusicBrainzStaticCandidateManifest(
        direct_custody_receipt_sha256=direct_receipt_sha256,
        direct_custody_output_sha256=direct.output_sha256,
        direct_claims_object_sha256=direct.claims_object_sha256,
        canonical_name_receipt_sha256=canonical_name_receipt_sha256,
        canonical_name_object_sha256=names.names_object_sha256,
        recovered_name_receipt_sha256=recovered_name_receipt_sha256,
        recovered_name_object_sha256=recovered.recovery_object_sha256,
        certified_static_discovery_sha256=static_sha,
        certified_semantic_atlas_sha256=atlas_sha,
        placed_candidate_seed_ids=candidate_ids,
        membership_count=sum(shard.row_count for shard in shards),
        shards=shards,
        output_sha256="0" * 64,
    )
    manifest = draft.model_copy(update={"output_sha256": local_candidate_manifest_sha256(draft)})
    (staging / "manifest.json").write_bytes(
        _canonical_json(manifest.model_dump(mode="json")) + b"\n"
    )
    return manifest


def _create_join_tables(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE names (
            artist_mbid TEXT PRIMARY KEY,
            canonical_name TEXT NOT NULL
        ) WITHOUT ROWID;
        CREATE TABLE claims (
            seed_id TEXT NOT NULL,
            artist_mbid TEXT NOT NULL,
            musicbrainz_genre_id TEXT NOT NULL,
            source_record_id TEXT NOT NULL,
            source_record_sha256 TEXT NOT NULL,
            source_evidence_ref TEXT NOT NULL,
            PRIMARY KEY (seed_id, artist_mbid)
        ) WITHOUT ROWID;
        """
    )


def _stream_names(
    connection: sqlite3.Connection,
    *,
    names: DirectCanonicalArtistNameCustodyReceipt,
    canonical_name_object_store: Path,
    recovered: DirectArtistNameRecoveryReceipt,
    recovered_name_object_store: Path,
) -> None:
    try:
        for row in iter_verified_direct_canonical_artist_names(
            names, object_store=canonical_name_object_store
        ):
            connection.execute(
                "INSERT INTO names VALUES (?, ?)", (row.artist_mbid, row.canonical_name)
            )
        for row in iter_verified_unique_recovered_names(
            recovered, object_store=recovered_name_object_store
        ):
            connection.execute(
                "INSERT INTO names VALUES (?, ?)", (row.artist_mbid, row.canonical_name)
            )
    except sqlite3.IntegrityError as error:
        raise LocalMusicBrainzStaticCandidateError(
            "canonical and recovered names overlap"
        ) from error
    except (OSError, ValueError, RuntimeError) as error:
        raise LocalMusicBrainzStaticCandidateError(
            "exact name custody object did not verify"
        ) from error


def _stream_direct_claims(
    connection: sqlite3.Connection,
    *,
    direct: DirectProperGenreCustodyReceipt,
    direct_object_store: Path,
    candidate_ids: frozenset[str],
) -> None:
    try:
        for claim in iter_verified_portable_direct_proper_genre_claims(
            direct, object_store=direct_object_store
        ):
            if claim.seed_id in candidate_ids:
                connection.execute(
                    "INSERT INTO claims VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        claim.seed_id,
                        claim.artist_mbid,
                        claim.musicbrainz_genre_id,
                        claim.source_record_id,
                        claim.source_record_sha256,
                        claim.source_evidence_ref,
                    ),
                )
    except sqlite3.IntegrityError as error:
        raise LocalMusicBrainzStaticCandidateError(
            "direct source repeats an output membership pair"
        ) from error
    except (OSError, ValueError, RuntimeError) as error:
        raise LocalMusicBrainzStaticCandidateError(
            "direct proper-genre custody object did not verify"
        ) from error


def _require_complete_named_scope(
    connection: sqlite3.Connection, candidate_ids: tuple[str, ...]
) -> None:
    found = tuple(
        str(row[0])
        for row in connection.execute("SELECT DISTINCT seed_id FROM claims ORDER BY seed_id")
    )
    if found != candidate_ids:
        raise LocalMusicBrainzStaticCandidateError(
            "placed candidate seed lacks a direct proper-genre pair"
        )
    unnamed = connection.execute(
        """
        SELECT COUNT(*) FROM claims
        LEFT JOIN names USING (artist_mbid)
        WHERE names.artist_mbid IS NULL
        """
    ).fetchone()
    if unnamed is None or int(unnamed[0]) != 0:
        raise LocalMusicBrainzStaticCandidateError(
            "direct output membership lacks an exact canonical name"
        )


def _write_shards(
    staging: Path, connection: sqlite3.Connection, candidate_ids: tuple[str, ...]
) -> tuple[LocalCandidateShard, ...]:
    shards: list[LocalCandidateShard] = []
    for seed_id in candidate_ids:
        rows = connection.execute(
            """
            SELECT claims.seed_id, claims.artist_mbid, names.canonical_name,
                   claims.musicbrainz_genre_id, claims.source_record_id,
                   claims.source_record_sha256, claims.source_evidence_ref
            FROM claims JOIN names USING (artist_mbid)
            WHERE claims.seed_id = ?
            ORDER BY claims.artist_mbid
            """,
            (seed_id,),
        )
        chunk: list[bytes] = []
        ordinal = 0
        for row in rows:
            membership = LocalCandidateMembership(
                seed_id=str(row["seed_id"]),
                artist_mbid=str(row["artist_mbid"]),
                canonical_name=str(row["canonical_name"]),
                musicbrainz_genre_id=str(row["musicbrainz_genre_id"]),
                source_record_id=str(row["source_record_id"]),
                source_record_sha256=str(row["source_record_sha256"]),
                source_evidence_ref=str(row["source_evidence_ref"]),
            )
            chunk.append(_canonical_json(membership.model_dump(mode="json")) + b"\n")
            if len(chunk) == _MAX_ROWS_PER_SHARD:
                shards.append(_write_shard(staging, seed_id, ordinal, tuple(chunk)))
                ordinal += 1
                chunk = []
        if chunk:
            shards.append(_write_shard(staging, seed_id, ordinal, tuple(chunk)))
    return tuple(shards)


def _write_shard(
    staging: Path, seed_id: str, ordinal: int, rows: tuple[bytes, ...]
) -> LocalCandidateShard:
    content = b"".join(rows)
    digest = _sha256_bytes(content)
    seed_digest = _sha256_bytes(seed_id.encode())
    relative = f"genres/{seed_digest}/{ordinal:04d}.{digest}.jsonl"
    path = staging / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return LocalCandidateShard(
        seed_id=seed_id,
        ordinal=ordinal,
        path=relative,
        row_count=len(rows),
        sha256=digest,
        byte_count=len(content),
    )


def _verify_candidate_shard(
    output_directory: Path,
    shard: LocalCandidateShard,
    *,
    observed_memberships: set[tuple[str, str]],
    last_artist_by_seed: dict[str, str],
) -> None:
    expected_path = (
        f"genres/{_sha256_bytes(shard.seed_id.encode())}/{shard.ordinal:04d}.{shard.sha256}.jsonl"
    )
    if shard.path != expected_path:
        raise LocalMusicBrainzStaticCandidateError(
            "candidate shard path does not bind its seed and hash"
        )
    path = output_directory / shard.path
    _require_real_directory(output_directory / "genres", "candidate genres directory")
    _require_real_directory(path.parent, "candidate seed shard directory")
    try:
        metadata = path.lstat()
    except OSError as error:
        raise LocalMusicBrainzStaticCandidateError("candidate shard is missing") from error
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != shard.byte_count:
        raise LocalMusicBrainzStaticCandidateError(
            "candidate shard type or byte count does not match"
        )

    digest = hashlib.sha256()
    row_count = 0
    previous_artist_mbid = last_artist_by_seed.get(shard.seed_id)
    try:
        with path.open("rb") as stream:
            while line := stream.readline(_MAXIMUM_MEMBERSHIP_ROW_BYTES + 1):
                digest.update(line)
                row_count += 1
                if len(line) > _MAXIMUM_MEMBERSHIP_ROW_BYTES:
                    raise LocalMusicBrainzStaticCandidateError(
                        "candidate shard membership row exceeds byte limit"
                    )
                previous_artist_mbid = _verify_membership_line(
                    line,
                    shard=shard,
                    previous_artist_mbid=previous_artist_mbid,
                    observed_memberships=observed_memberships,
                )
    except OSError as error:
        raise LocalMusicBrainzStaticCandidateError("candidate shard cannot be read") from error
    if row_count != shard.row_count:
        raise LocalMusicBrainzStaticCandidateError("candidate shard row count does not match")
    if digest.hexdigest() != shard.sha256:
        raise LocalMusicBrainzStaticCandidateError("candidate shard SHA-256 does not match")
    if previous_artist_mbid is None:
        raise LocalMusicBrainzStaticCandidateError("candidate shard contains no memberships")
    last_artist_by_seed[shard.seed_id] = previous_artist_mbid


def _verify_membership_line(
    line: bytes,
    *,
    shard: LocalCandidateShard,
    previous_artist_mbid: str | None,
    observed_memberships: set[tuple[str, str]],
) -> str:
    if not line.endswith(b"\n"):
        raise LocalMusicBrainzStaticCandidateError("candidate shard JSONL row lacks a newline")
    try:
        membership = LocalCandidateMembership.model_validate_json(line)
    except ValueError as error:
        raise LocalMusicBrainzStaticCandidateError(
            "candidate shard has an invalid membership row"
        ) from error
    if line != _canonical_json(membership.model_dump(mode="json")) + b"\n":
        raise LocalMusicBrainzStaticCandidateError(
            "candidate shard membership row is not canonical JSON"
        )
    if membership.seed_id != shard.seed_id:
        raise LocalMusicBrainzStaticCandidateError(
            "candidate shard membership seed does not match shard"
        )
    if previous_artist_mbid is not None and membership.artist_mbid <= previous_artist_mbid:
        raise LocalMusicBrainzStaticCandidateError(
            "candidate shard artist MBIDs are not strictly ordered"
        )
    membership_key = (membership.seed_id, membership.artist_mbid)
    if membership_key in observed_memberships:
        raise LocalMusicBrainzStaticCandidateError(
            "candidate shards repeat a direct source membership"
        )
    observed_memberships.add(membership_key)
    return membership.artist_mbid


def _require_input_bindings(
    direct: DirectProperGenreCustodyReceipt,
    names: DirectCanonicalArtistNameCustodyReceipt,
    recovered: DirectArtistNameRecoveryReceipt,
    *,
    direct_custody_receipt_sha256: str,
    canonical_name_receipt_sha256: str,
) -> None:
    if direct.public_export_authorized:
        raise LocalMusicBrainzStaticCandidateError("direct custody must remain non-public")
    if names.public_export_authorized or recovered.public_export_authorized:
        raise LocalMusicBrainzStaticCandidateError("name custody must remain non-public")
    direct_binding = (
        direct_custody_receipt_sha256,
        direct.output_sha256,
        direct.claims_object_sha256,
    )
    if (
        names.direct_custody_receipt_byte_sha256,
        names.direct_custody_receipt_output_sha256,
        names.direct_claims_object_sha256,
    ) != direct_binding:
        raise LocalMusicBrainzStaticCandidateError(
            "canonical names bind a different direct custody"
        )
    if (
        recovered.direct_custody_receipt_byte_sha256,
        recovered.direct_custody_receipt_output_sha256,
        recovered.direct_claims_object_sha256,
        recovered.name_custody_receipt_byte_sha256,
        recovered.name_custody_receipt_output_sha256,
        recovered.name_custody_object_sha256,
    ) != (
        *direct_binding,
        canonical_name_receipt_sha256,
        names.output_sha256,
        names.names_object_sha256,
    ):
        raise LocalMusicBrainzStaticCandidateError(
            "recovered names bind a different custody cohort"
        )


def _placed_candidate_seed_ids(
    *,
    static_discovery_path: Path,
    certified_manifest_path: Path,
    certified_layout_path: Path,
    direct: DirectProperGenreCustodyReceipt,
    direct_object_store: Path,
) -> tuple[tuple[str, ...], str, str]:
    """Derive placed candidate-only direct-custody seeds, never all atlas leftovers."""
    static = _certified_asset(
        manifest_path=certified_manifest_path,
        asset_path=static_discovery_path,
        asset_key=_STATIC_ASSET,
    )
    atlas = _certified_asset(
        manifest_path=certified_manifest_path,
        asset_path=certified_layout_path,
        asset_key=_ATLAS_ASSET,
    )
    static_ids = _node_ids(static.get("genres"), field="node_id", label="static genres")
    placed_ids = _node_ids(atlas.get("nodes"), field="id", label="semantic atlas nodes")
    try:
        direct_ids = frozenset(
            claim.seed_id
            for claim in iter_verified_portable_direct_proper_genre_claims(
                direct, object_store=direct_object_store
            )
        )
    except (OSError, ValueError, RuntimeError) as error:
        raise LocalMusicBrainzStaticCandidateError(
            "direct custody object did not verify for candidate seed scope"
        ) from error
    if len(direct_ids) != direct.seed_count:
        raise LocalMusicBrainzStaticCandidateError(
            "verified direct custody seed IDs do not match custody receipt"
        )
    return (
        tuple(sorted((direct_ids - static_ids) & placed_ids)),
        _sha256_file(static_discovery_path),
        _sha256_file(certified_layout_path),
    )


def _read_receipt(path: Path, expected_sha256: str) -> bytes:
    try:
        content = path.read_bytes()
    except OSError as error:
        raise LocalMusicBrainzStaticCandidateError(
            "candidate custody receipt cannot be read"
        ) from error
    if _sha256_bytes(content) != expected_sha256:
        raise LocalMusicBrainzStaticCandidateError(
            "candidate custody receipt bytes do not match pin"
        )
    return content


def _read_regular_file(path: Path, label: str, *, maximum_bytes: int | None = None) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise LocalMusicBrainzStaticCandidateError(f"{label} is missing") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise LocalMusicBrainzStaticCandidateError(f"{label} is not a regular file")
    if maximum_bytes is not None and metadata.st_size > maximum_bytes:
        raise LocalMusicBrainzStaticCandidateError(f"{label} exceeds byte limit")
    try:
        content = path.read_bytes()
    except OSError as error:
        raise LocalMusicBrainzStaticCandidateError(f"{label} cannot be read") from error
    if len(content) != metadata.st_size:
        raise LocalMusicBrainzStaticCandidateError(f"{label} changed during read")
    return content


def _require_real_directory(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise LocalMusicBrainzStaticCandidateError(f"{label} is missing") from error
    if not stat.S_ISDIR(metadata.st_mode):
        raise LocalMusicBrainzStaticCandidateError(f"{label} is not a real directory")


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
