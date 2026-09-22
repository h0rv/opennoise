"""Build a source-only, local MusicBrainz proper-genre overlap graph."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, model_validator

from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreCustodyReceipt,
    iter_verified_portable_direct_proper_genre_claims,
)
from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    receipt_sha256 as custody_receipt_sha256,
)
from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

TOP_K: Final = 10
MINIMUM_SHARED_ARTISTS: Final = 2
MAX_PAIR_VISITS: Final = 5_000_000
_REVISION: Final = "musicbrainz-direct-custody-peer-graph-v1"


class DirectCustodyPeerGraphError(ValueError):
    """Report invalid source custody or graph construction state."""


@dataclass(frozen=True, slots=True)
class _BuildAccounting:
    """Bounded counts produced while constructing the local database."""

    claims: int
    duplicates: int
    seeds: int
    artists: int
    unique_memberships: int
    pair_visits: int
    observed_pairs: int
    candidates: int
    abstentions: int
    isolated: int
    neighbors: int


class DirectCustodyPeerGraphReceipt(FrozenModel):
    """Typed receipt for a bounded SQLite graph built from custody only."""

    revision: Literal["musicbrainz-direct-custody-peer-graph-v1"] = _REVISION
    scope: Literal["local_research_only"] = "local_research_only"
    metric: Literal["idf_weighted_jaccard"] = "idf_weighted_jaccard"
    idf_formula: Literal["1+ln((seed_count+1)/(artist_seed_degree+1))"] = (
        "1+ln((seed_count+1)/(artist_seed_degree+1))"
    )
    minimum_shared_artists: Literal[2] = MINIMUM_SHARED_ARTISTS
    top_k: Literal[10] = TOP_K
    custody_receipt_byte_sha256: Sha256
    custody_receipt_sha256: Sha256
    custody_receipt_output_sha256: Sha256
    custody_object_sha256: Sha256
    database_sha256: Sha256
    claim_count: int = Field(ge=0)
    duplicate_seed_artist_claim_count: int = Field(ge=0)
    seed_count: int = Field(ge=0)
    artist_count: int = Field(ge=0)
    unique_seed_artist_count: int = Field(ge=0)
    pair_visit_count: int = Field(ge=0, le=MAX_PAIR_VISITS)
    observed_pair_count: int = Field(ge=0)
    candidate_pair_count: int = Field(ge=0)
    one_overlap_abstention_count: int = Field(ge=0)
    isolated_seed_count: int = Field(ge=0)
    directional_neighbor_count: int = Field(ge=0)
    historical_inputs_used: Literal[False] = False
    tags_or_lastfm_used: Literal[False] = False
    release_rows_used: Literal[False] = False
    h3_or_historical_evaluation_used: Literal[False] = False
    public_export_authorized: Literal[False] = False
    serving_authorized: Literal[False] = False
    output_sha256: Sha256

    @model_validator(mode="after")
    def check_accounting(self) -> DirectCustodyPeerGraphReceipt:
        """Require pair accounting and immutable local-only policy to agree."""
        if self.observed_pair_count != (
            self.candidate_pair_count + self.one_overlap_abstention_count
        ):
            raise ValueError("observed pair accounting does not balance")
        if self.directional_neighbor_count > self.seed_count * self.top_k:
            raise ValueError("directional neighbors exceed the configured top-k bound")
        return self


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def _sha256_file(path: Path) -> Sha256:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1_048_576), b""):
            digest.update(block)
    return digest.hexdigest()


def _receipt_output_sha256(receipt: DirectCustodyPeerGraphReceipt) -> Sha256:
    """Hash the receipt payload without its self-referential checksum."""
    return hashlib.sha256(
        _canonical(receipt.model_dump(mode="json", exclude={"output_sha256"}))
    ).hexdigest()


def verify_direct_custody_peer_graph_receipt(
    receipt: DirectCustodyPeerGraphReceipt, *, database: Path
) -> None:
    """Verify a generated database against its immutable sidecar receipt."""
    if receipt.output_sha256 != _receipt_output_sha256(receipt):
        raise DirectCustodyPeerGraphError("peer graph receipt output hash is invalid")
    if not database.is_file() or _sha256_file(database) != receipt.database_sha256:
        raise DirectCustodyPeerGraphError("peer graph database differs from its receipt")
    with closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        row = connection.execute(
            "SELECT value FROM metadata WHERE key = 'custody_receipt_sha256'"
        ).fetchone()
    if row is None or row[0] != receipt.custody_receipt_sha256:
        raise DirectCustodyPeerGraphError("database does not bind the supplied custody receipt")


def _schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode = DELETE;
        PRAGMA synchronous = FULL;
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
        CREATE TABLE seed_node (
          seed_id TEXT PRIMARY KEY,
          artist_count INTEGER NOT NULL,
          peer_count INTEGER NOT NULL DEFAULT 0,
          abstained_pair_count INTEGER NOT NULL DEFAULT 0,
          state TEXT NOT NULL DEFAULT 'isolated'
        ) WITHOUT ROWID;
        CREATE TABLE seed_artist (
          seed_id TEXT NOT NULL,
          artist_mbid TEXT NOT NULL,
          PRIMARY KEY (seed_id, artist_mbid)
        ) WITHOUT ROWID;
        CREATE TABLE artist_weight (
          artist_mbid TEXT PRIMARY KEY,
          seed_degree INTEGER NOT NULL,
          weight REAL NOT NULL
        ) WITHOUT ROWID;
        CREATE TABLE pair_edge (
          left_seed_id TEXT NOT NULL,
          right_seed_id TEXT NOT NULL,
          shared_artist_count INTEGER NOT NULL,
          raw_jaccard REAL NOT NULL,
          idf_weighted_jaccard REAL NOT NULL,
          disposition TEXT NOT NULL CHECK (disposition IN ('candidate', 'abstained_one_overlap')),
          PRIMARY KEY (left_seed_id, right_seed_id),
          CHECK (left_seed_id < right_seed_id)
        ) WITHOUT ROWID;
        CREATE TABLE peer_neighbor (
          seed_id TEXT NOT NULL,
          rank INTEGER NOT NULL,
          peer_seed_id TEXT NOT NULL,
          shared_artist_count INTEGER NOT NULL,
          raw_jaccard REAL NOT NULL,
          idf_weighted_jaccard REAL NOT NULL,
          PRIMARY KEY (seed_id, rank),
          UNIQUE (seed_id, peer_seed_id)
        ) WITHOUT ROWID;
        CREATE INDEX seed_artist_by_artist ON seed_artist (artist_mbid, seed_id);
        """
    )


def _pair_rows(connection: sqlite3.Connection) -> Iterator[tuple[str, str, str, float]]:
    """Stream pair-shared artists in a stable order for math.fsum."""
    for row in connection.execute(
        """
        SELECT left.seed_id, right.seed_id, left.artist_mbid, weight.weight
        FROM seed_artist AS left
        JOIN seed_artist AS right
          ON right.artist_mbid = left.artist_mbid AND left.seed_id < right.seed_id
        JOIN artist_weight AS weight ON weight.artist_mbid = left.artist_mbid
        ORDER BY left.seed_id, right.seed_id, left.artist_mbid
        """
    ):
        left, right, artist, weight = row
        yield str(left), str(right), str(artist), float(weight)


def _scalar_int(
    connection: sqlite3.Connection, query: str, parameters: Sequence[object] = ()
) -> int:
    """Read one required SQLite integer without letting sqlite's Any escape."""
    row = connection.execute(query, parameters).fetchone()
    if row is None:
        raise DirectCustodyPeerGraphError("required SQLite count row is missing")
    return int(row[0])


def _build_database(  # noqa: C901, PLR0915 - keep the custody-only bounded build auditable in one flow.
    connection: sqlite3.Connection,
    custody: DirectProperGenreCustodyReceipt,
    object_store: Path,
) -> _BuildAccounting:
    """Stream verified claims into SQLite, score pairs, and materialize top-k."""
    _schema(connection)
    connection.execute("BEGIN")
    connection.execute(
        "INSERT INTO metadata VALUES ('custody_receipt_sha256', ?)",
        (custody_receipt_sha256(custody),),
    )
    claim_count = 0
    duplicate_count = 0
    for claim in iter_verified_portable_direct_proper_genre_claims(
        custody, object_store=object_store
    ):
        claim_count += 1
        connection.execute(
            "INSERT OR IGNORE INTO seed_node(seed_id, artist_count) VALUES (?, 0)",
            (claim.seed_id,),
        )
        inserted = connection.execute(
            "INSERT OR IGNORE INTO seed_artist(seed_id, artist_mbid) VALUES (?, ?)",
            (claim.seed_id, claim.artist_mbid),
        ).rowcount
        duplicate_count += int(inserted == 0)
    if claim_count != custody.claim_count:
        raise DirectCustodyPeerGraphError("verified custody claim count changed during replay")
    seed_count = _scalar_int(connection, "SELECT count(*) FROM seed_node")
    artist_count = _scalar_int(connection, "SELECT count(DISTINCT artist_mbid) FROM seed_artist")
    unique_count = _scalar_int(connection, "SELECT count(*) FROM seed_artist")
    connection.execute(
        "UPDATE seed_node SET artist_count = "
        "(SELECT count(*) FROM seed_artist WHERE seed_artist.seed_id = seed_node.seed_id)"
    )
    degree_rows = connection.execute(
        "SELECT artist_mbid, count(*) FROM seed_artist GROUP BY artist_mbid ORDER BY artist_mbid"
    )
    for row in degree_rows:
        artist, degree = str(row[0]), int(row[1])
        weight = 1.0 + math.log((seed_count + 1) / (degree + 1))
        connection.execute("INSERT INTO artist_weight VALUES (?, ?, ?)", (artist, degree, weight))
    pair_visits = _scalar_int(
        connection,
        "SELECT coalesce(sum(n * (n - 1) / 2), 0) FROM "
        "(SELECT count(*) AS n FROM seed_artist GROUP BY artist_mbid)",
    )
    if pair_visits > MAX_PAIR_VISITS:
        raise DirectCustodyPeerGraphError("artist sharing exceeds the configured pair-visit bound")
    weights_by_seed: dict[str, float] = {}
    for row in connection.execute("SELECT seed_id FROM seed_node ORDER BY seed_id"):
        seed = str(row[0])
        weights = (
            float(row[0])
            for row in connection.execute(
                "SELECT weight.weight FROM seed_artist "
                "JOIN artist_weight AS weight USING (artist_mbid) "
                "WHERE seed_artist.seed_id = ? ORDER BY seed_artist.artist_mbid",
                (seed,),
            )
        )
        weights_by_seed[seed] = math.fsum(weights)
    pair_count = 0
    candidate_count = 0
    abstention_count = 0
    current_pair: tuple[str, str] | None = None
    common_weights: list[float] = []

    def flush_pair(pair: tuple[str, str], shared_weights: list[float]) -> None:
        nonlocal pair_count, candidate_count, abstention_count
        left, right = pair
        shared_count = len(shared_weights)
        common_weight = math.fsum(shared_weights)
        left_count = _scalar_int(
            connection, "SELECT artist_count FROM seed_node WHERE seed_id = ?", (left,)
        )
        right_count = _scalar_int(
            connection, "SELECT artist_count FROM seed_node WHERE seed_id = ?", (right,)
        )
        raw_jaccard = shared_count / (left_count + right_count - shared_count)
        weighted_jaccard = common_weight / (
            weights_by_seed[left] + weights_by_seed[right] - common_weight
        )
        disposition = (
            "candidate" if shared_count >= MINIMUM_SHARED_ARTISTS else "abstained_one_overlap"
        )
        connection.execute(
            "INSERT INTO pair_edge VALUES (?, ?, ?, ?, ?, ?)",
            (left, right, shared_count, raw_jaccard, weighted_jaccard, disposition),
        )
        pair_count += 1
        if disposition == "candidate":
            candidate_count += 1
        else:
            abstention_count += 1

    for left, right, _artist, weight in _pair_rows(connection):
        pair = (left, right)
        if current_pair is not None and pair != current_pair:
            flush_pair(current_pair, common_weights)
            common_weights = []
        current_pair = pair
        common_weights.append(float(weight))
    if current_pair is not None:
        flush_pair(current_pair, common_weights)
    connection.execute(
        """
        INSERT INTO peer_neighbor
        SELECT seed_id, row_number, peer_seed_id, shared_artist_count,
               raw_jaccard, idf_weighted_jaccard
        FROM (
          SELECT source_seed AS seed_id,
                 row_number() OVER (
                   PARTITION BY source_seed
                   ORDER BY idf_weighted_jaccard DESC, shared_artist_count DESC, peer_seed_id ASC
                 ) AS row_number,
                 peer_seed_id, shared_artist_count, raw_jaccard, idf_weighted_jaccard
          FROM (
            SELECT left_seed_id AS source_seed, right_seed_id AS peer_seed_id,
                   shared_artist_count, raw_jaccard, idf_weighted_jaccard
            FROM pair_edge WHERE disposition = 'candidate'
            UNION ALL
            SELECT right_seed_id, left_seed_id, shared_artist_count,
                   raw_jaccard, idf_weighted_jaccard
            FROM pair_edge WHERE disposition = 'candidate'
          )
        ) WHERE row_number <= ?
        """,
        (TOP_K,),
    )
    connection.execute(
        """
        UPDATE seed_node SET
          peer_count = (SELECT count(*) FROM peer_neighbor
                        WHERE peer_neighbor.seed_id = seed_node.seed_id),
          abstained_pair_count = (
            SELECT count(*) FROM pair_edge
            WHERE disposition = 'abstained_one_overlap'
              AND (pair_edge.left_seed_id = seed_node.seed_id
                   OR pair_edge.right_seed_id = seed_node.seed_id)
          ),
          state = CASE
            WHEN EXISTS (
              SELECT 1 FROM pair_edge
              WHERE disposition = 'candidate'
                AND (pair_edge.left_seed_id = seed_node.seed_id
                     OR pair_edge.right_seed_id = seed_node.seed_id)
            ) THEN 'has_candidates'
            WHEN EXISTS (
              SELECT 1 FROM pair_edge
              WHERE disposition = 'abstained_one_overlap'
                AND (pair_edge.left_seed_id = seed_node.seed_id
                     OR pair_edge.right_seed_id = seed_node.seed_id)
            ) THEN 'only_weak_overlap'
            ELSE 'isolated'
          END
        """
    )
    isolated_count = _scalar_int(
        connection, "SELECT count(*) FROM seed_node WHERE state = 'isolated'"
    )
    neighbor_count = _scalar_int(connection, "SELECT count(*) FROM peer_neighbor")
    connection.commit()
    return _BuildAccounting(
        claims=claim_count,
        duplicates=duplicate_count,
        seeds=seed_count,
        artists=artist_count,
        unique_memberships=unique_count,
        pair_visits=pair_visits,
        observed_pairs=pair_count,
        candidates=candidate_count,
        abstentions=abstention_count,
        isolated=isolated_count,
        neighbors=neighbor_count,
    )


def build_direct_custody_peer_graph(
    *,
    custody: DirectProperGenreCustodyReceipt,
    object_store: Path,
    custody_receipt_byte_sha256: Sha256,
    database: Path,
    receipt_output: Path,
) -> DirectCustodyPeerGraphReceipt:
    """Build a no-publication graph directly from the verified custody stream."""
    if database.exists() or receipt_output.exists():
        raise FileExistsError("refusing to replace a peer graph database or receipt")
    database.parent.mkdir(parents=True, exist_ok=True)
    receipt_output.parent.mkdir(parents=True, exist_ok=True)
    db_fd, db_name = tempfile.mkstemp(prefix=f".{database.name}.", dir=database.parent)
    os.close(db_fd)
    receipt_fd, receipt_name = tempfile.mkstemp(
        prefix=f".{receipt_output.name}.", dir=receipt_output.parent
    )
    os.close(receipt_fd)
    temporary_db, temporary_receipt = Path(db_name), Path(receipt_name)
    database_linked = False
    try:
        with closing(sqlite3.connect(temporary_db)) as connection, connection:
            accounting = _build_database(connection, custody, object_store)
        placeholder = DirectCustodyPeerGraphReceipt(
            custody_receipt_byte_sha256=custody_receipt_byte_sha256,
            custody_receipt_sha256=custody_receipt_sha256(custody),
            custody_receipt_output_sha256=custody.output_sha256,
            custody_object_sha256=custody.claims_object_sha256,
            database_sha256=_sha256_file(temporary_db),
            claim_count=accounting.claims,
            duplicate_seed_artist_claim_count=accounting.duplicates,
            seed_count=accounting.seeds,
            artist_count=accounting.artists,
            unique_seed_artist_count=accounting.unique_memberships,
            pair_visit_count=accounting.pair_visits,
            observed_pair_count=accounting.observed_pairs,
            candidate_pair_count=accounting.candidates,
            one_overlap_abstention_count=accounting.abstentions,
            isolated_seed_count=accounting.isolated,
            directional_neighbor_count=accounting.neighbors,
            output_sha256="0" * 64,
        )
        receipt = placeholder.model_copy(
            update={"output_sha256": _receipt_output_sha256(placeholder)}
        )
        payload = _canonical(receipt.model_dump(mode="json")) + b"\n"
        temporary_receipt.write_bytes(payload)
        try:
            os.link(temporary_db, database)
            database_linked = True
            os.link(temporary_receipt, receipt_output)
        except OSError as error:
            if database_linked:
                database.unlink(missing_ok=True)
            if isinstance(error, FileExistsError):
                raise FileExistsError(
                    "refusing to replace a peer graph database or receipt"
                ) from error
            raise
        return receipt
    finally:
        temporary_db.unlink(missing_ok=True)
        temporary_receipt.unlink(missing_ok=True)
