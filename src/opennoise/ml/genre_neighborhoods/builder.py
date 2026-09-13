"""Streaming SQLite construction of a separate-channel co-listen peer signal."""

from __future__ import annotations

import hashlib
import math
import sqlite3
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from opennoise.common import canonical_json, sha256_file, sha256_hex, write_atomic_bytes

from .contracts import (
    REVISION,
    ChannelCoverage,
    GenreNeighborhoodArtifact,
    GenreNeighborhoodError,
    GenreNeighborhoodInputs,
    GenreNeighborhoodReceipt,
    GenreNeighborhoodSettings,
    SplitCoverage,
    artifact_sha256,
    settings_sha256,
    verify_artifact,
)
from .input import certify_inputs

_CHANNELS: Final = ("artist_direct", "reviewed_alias_context")


@dataclass(slots=True)
class _Aggregate:
    raw_mass: float = 0.0
    window_support: int = 0
    artist_pairs: set[tuple[str, str]] = field(default_factory=set)


def build_genre_neighborhoods(
    inputs: GenreNeighborhoodInputs, settings: GenreNeighborhoodSettings | None = None
) -> GenreNeighborhoodArtifact:
    """Build one explainable training-only cache; no historical, audio, or listener IDs enter."""
    resolved = settings or GenreNeighborhoodSettings()
    certified = certify_inputs(inputs)
    input_hash = sha256_hex(
        canonical_json(
            {
                "revision": REVISION,
                "construction_revision": "artist-scope-v1",
                "inputs": [item.model_dump() for item in certified.bindings],
                "settings": settings_sha256(resolved),
            }
        )
    )
    output = inputs.cache_directory / input_hash
    database_path = output / "genre-neighborhoods.sqlite"
    if database_path.exists():
        try:
            existing = GenreNeighborhoodArtifact.model_validate_json(
                (output / "artifact.json").read_bytes()
            )
            verify_artifact(existing)
            if (
                existing.input_sha256 != input_hash
                or existing.cache_database_sha256 != sha256_file(database_path)[0]
            ):
                raise GenreNeighborhoodError("existing cache does not bind current inputs")
            return existing
        except (OSError, ValueError) as error:
            raise GenreNeighborhoodError("bound cache is partial or does not replay") from error
    output.mkdir(parents=True, exist_ok=True)
    temporary = output / "genre-neighborhoods.partial.sqlite"
    try:
        coverage = _build_cache(temporary, inputs, resolved)
        temporary.replace(database_path)
        database_sha, database_size = sha256_file(database_path)
        preliminary = GenreNeighborhoodArtifact(
            inputs=certified.bindings,
            graph_receipt_output_sha256=certified.graph_logical_sha256,
            colisten_receipt_output_sha256=certified.colisten_logical_sha256,
            settings=resolved,
            settings_sha256=settings_sha256(resolved),
            input_sha256=input_hash,
            cache_database_sha256=database_sha,
            cache_database_byte_count=database_size,
            colisten_artist_count=coverage[2],
            split=coverage[0],
            channels=coverage[1],
            output_sha256="0" * 64,
        )
        return preliminary.model_copy(update={"output_sha256": artifact_sha256(preliminary)})
    finally:
        temporary.unlink(missing_ok=True)


def _build_cache(
    path: Path, inputs: GenreNeighborhoodInputs, settings: GenreNeighborhoodSettings
) -> tuple[SplitCoverage, tuple[ChannelCoverage, ChannelCoverage], int]:
    memberships: dict[str, dict[str, tuple[str, ...]]] = {channel: {} for channel in _CHANNELS}
    base_state: dict[str, str] = {}
    colisten_artists = _colisten_artists(inputs.colisten_database)
    with closing(_readonly(inputs.graph_database)) as graph:
        for seed_id, disposition in graph.execute(
            "SELECT identifier, disposition FROM identity WHERE namespace = 'stable_seed' ORDER BY identifier"
        ):
            base_state[str(seed_id)] = (
                "abstained" if str(disposition) == "abstained" else "isolated"
            )
        for channel in _CHANNELS:
            grouped: dict[str, list[str]] = defaultdict(list)
            for artist in sorted(colisten_artists):
                rows = graph.execute(
                    "SELECT object_identifier FROM claim WHERE subject_namespace = 'musicbrainz_artist' "
                    "AND subject_identifier = ? AND predicate = 'artist_membership' "
                    "AND object_namespace = 'stable_seed' AND evidence_kind = ? GROUP BY object_identifier",
                    (artist, channel),
                )
                grouped[artist].extend(str(seed) for (seed,) in rows)
            memberships[channel] = {artist: tuple(seeds) for artist, seeds in grouped.items()}
    if len(base_state) != 6291:
        raise GenreNeighborhoodError("stable seed state accounting is incomplete")
    with closing(sqlite3.connect(path)) as cache, cache:
        _schema(cache)
        observed = _channel_observed_states(base_state, memberships)
        cache.executemany(
            "INSERT INTO genre_state(channel, seed_id, state) VALUES (?, ?, ?)",
            (
                (channel, seed, observed[channel][seed])
                for channel in _CHANNELS
                for seed in sorted(base_state)
            ),
        )
        cache.executemany(
            "INSERT INTO membership(channel, artist_mbid, seed_id) VALUES (?, ?, ?)",
            (
                (channel, artist, seed)
                for channel in _CHANNELS
                for artist, seeds in memberships[channel].items()
                for seed in seeds
            ),
        )
        split, heldout = _stream_colistens(cache, inputs.colisten_database, memberships, settings)
        _score(cache, settings)
        channel_coverage = _evaluate(cache, memberships, heldout)
        _verify_cache(cache)
    return split, channel_coverage, len(colisten_artists)


def _stream_colistens(
    cache: sqlite3.Connection,
    colisten_path: Path,
    memberships: dict[str, dict[str, tuple[str, ...]]],
    settings: GenreNeighborhoodSettings,
) -> tuple[SplitCoverage, dict[str, set[tuple[str, str]]]]:
    artist_pairs: set[tuple[str, str]] = set()
    train_pairs: set[tuple[str, str]] = set()
    heldout_pairs: set[tuple[str, str]] = set()
    aggregates: dict[tuple[str, str, str], _Aggregate] = {}
    heldout: dict[str, set[tuple[str, str]]] = {channel: set() for channel in _CHANNELS}
    train_windows = heldout_windows = 0
    with closing(_readonly(colisten_path)) as source:
        rows = source.execute(
            "SELECT left_artist_mbid, right_artist_mbid, distinct_user_count FROM colisten_relation "
            "ORDER BY left_artist_mbid, right_artist_mbid, window_start, evidence_fingerprint"
        )
        for left, right, users in rows:
            pair = str(left), str(right)
            artist_pairs.add(pair)
            is_heldout = _heldout_pair(pair, settings)
            (heldout_pairs if is_heldout else train_pairs).add(pair)
            if is_heldout:
                heldout_windows += 1
            else:
                train_windows += 1
            weight = math.log1p(int(users))
            for channel in _CHANNELS:
                left_seeds = memberships[channel].get(pair[0], ())
                right_seeds = memberships[channel].get(pair[1], ())
                if not left_seeds or not right_seeds:
                    continue
                unit = weight / (len(left_seeds) * len(right_seeds))
                for left_seed in left_seeds:
                    for right_seed in right_seeds:
                        if left_seed == right_seed:
                            continue
                        if is_heldout:
                            heldout[channel].add((left_seed, right_seed))
                            heldout[channel].add((right_seed, left_seed))
                            continue
                        _accumulate_pair(aggregates, channel, left_seed, right_seed, unit, pair)
                        _accumulate_pair(aggregates, channel, right_seed, left_seed, unit, pair)
    cache.executemany(
        "INSERT INTO raw_pair(channel, seed_id, neighbor_seed_id, raw_mass, window_support, artist_pair_support) VALUES (?, ?, ?, ?, ?, ?)",
        (
            (channel, seed, neighbor, value.raw_mass, value.window_support, len(value.artist_pairs))
            for (channel, seed, neighbor), value in sorted(aggregates.items())
        ),
    )
    return SplitCoverage(
        canonical_artist_pair_count=len(artist_pairs),
        training_artist_pair_count=len(train_pairs),
        heldout_artist_pair_count=len(heldout_pairs),
        training_window_count=train_windows,
        heldout_window_count=heldout_windows,
    ), heldout


def _accumulate_pair(
    aggregates: dict[tuple[str, str, str], _Aggregate],
    channel: str,
    seed: str,
    neighbor: str,
    mass: float,
    artist_pair: tuple[str, str],
) -> None:
    key = (channel, seed, neighbor)
    value = aggregates.setdefault(key, _Aggregate())
    value.raw_mass += mass
    value.window_support += 1
    value.artist_pairs.add(artist_pair)


def _score(cache: sqlite3.Connection, settings: GenreNeighborhoodSettings) -> None:
    for channel in _CHANNELS:
        total = float(
            cache.execute(
                "SELECT coalesce(sum(raw_mass), 0) FROM raw_pair WHERE channel = ?", (channel,)
            ).fetchone()[0]
        )
        if total == 0:
            continue
        marginals = {
            str(seed): float(mass)
            for seed, mass in cache.execute(
                "SELECT seed_id, sum(raw_mass) FROM raw_pair WHERE channel = ? GROUP BY seed_id",
                (channel,),
            )
        }
        for seed, neighbor, mass, windows, artists in cache.execute(
            "SELECT seed_id, neighbor_seed_id, raw_mass, window_support, artist_pair_support FROM raw_pair WHERE channel = ?",
            (channel,),
        ):
            joint = float(mass) / total
            pmi = math.log(
                joint / ((marginals[str(seed)] / total) * (marginals[str(neighbor)] / total))
            )
            npmi = pmi / -math.log(joint)
            shrunk = npmi * (float(mass) / (float(mass) + settings.shrinkage_prior_mass))
            if (
                int(windows) >= settings.minimum_window_support
                and float(mass) >= settings.minimum_raw_mass
                and shrunk > 0
            ):
                cache.execute(
                    "INSERT INTO scored_pair(channel, seed_id, neighbor_seed_id, unshrunk_npmi, shrunk_npmi, raw_mass, window_support, artist_pair_support) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (channel, seed, neighbor, npmi, shrunk, mass, windows, artists),
                )
        cache.execute(
            "INSERT INTO neighbor(channel, seed_id, neighbor_seed_id, rank, relation_kind, shrunk_npmi, unshrunk_npmi, raw_mass, window_support, artist_pair_support) "
            "SELECT channel, seed_id, neighbor_seed_id, rank, 'peer_not_parent_child', shrunk_npmi, unshrunk_npmi, raw_mass, window_support, artist_pair_support FROM "
            "(SELECT *, row_number() OVER (PARTITION BY channel, seed_id ORDER BY shrunk_npmi DESC, neighbor_seed_id) AS rank FROM scored_pair WHERE channel = ?) WHERE rank <= ?",
            (channel, settings.top_k),
        )


def _evaluate(
    cache: sqlite3.Connection,
    memberships: dict[str, dict[str, tuple[str, ...]]],
    heldout: dict[str, set[tuple[str, str]]],
) -> tuple[ChannelCoverage, ChannelCoverage]:
    results: list[ChannelCoverage] = []
    for channel in _CHANNELS:
        positives = heldout[channel]
        scored_sources = {
            str(seed)
            for (seed,) in cache.execute(
                "SELECT DISTINCT seed_id FROM neighbor WHERE channel = ?", (channel,)
            )
        }
        recovered = {
            (str(seed), str(neighbor))
            for seed, neighbor in cache.execute(
                "SELECT seed_id, neighbor_seed_id FROM neighbor WHERE channel = ?", (channel,)
            )
        }
        scoreable = {item for item in positives if item[0] in scored_sources}
        hit = scoreable & recovered
        observed = int(
            cache.execute(
                "SELECT count(DISTINCT seed_id) FROM membership WHERE channel = ?", (channel,)
            ).fetchone()[0]
        )
        training = int(
            cache.execute("SELECT count(*) FROM raw_pair WHERE channel = ?", (channel,)).fetchone()[
                0
            ]
        )
        retained = int(
            cache.execute("SELECT count(*) FROM neighbor WHERE channel = ?", (channel,)).fetchone()[
                0
            ]
        )
        results.append(
            ChannelCoverage(
                channel=channel,
                membership_count=sum(len(value) for value in memberships[channel].values()),
                membership_artist_count=len(memberships[channel]),
                observed_seed_count=observed,
                training_positive_count=training,
                retained_neighbor_count=retained,
                heldout_positive_count=len(positives),
                heldout_scoreable_positive_count=len(scoreable),
                heldout_recovered_at_k_count=len(hit),
                heldout_overlap_coverage=(len(scoreable) / len(positives) if positives else None),
                heldout_recovery_at_k=(len(hit) / len(scoreable) if scoreable else None),
            )
        )
    return results[0], results[1]


def _heldout_pair(pair: tuple[str, str], settings: GenreNeighborhoodSettings) -> bool:
    value = int(
        hashlib.sha256(f"{settings.split_seed}:{pair[0]}:{pair[1]}".encode()).hexdigest()[:16], 16
    )
    return value / 2**64 < settings.heldout_fraction


def _channel_observed_states(
    base_state: dict[str, str], memberships: dict[str, dict[str, tuple[str, ...]]]
) -> dict[str, dict[str, str]]:
    """Derive channel-local state without allowing one evidence channel to contaminate another."""
    return {
        channel: {
            seed: "observed"
            if seed in {item for values in memberships[channel].values() for item in values}
            else state
            for seed, state in base_state.items()
        }
        for channel in _CHANNELS
    }


def _readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)


def _colisten_artists(path: Path) -> set[str]:
    with closing(_readonly(path)) as source:
        return {
            str(artist)
            for (artist,) in source.execute(
                "SELECT left_artist_mbid FROM colisten_relation UNION SELECT right_artist_mbid FROM colisten_relation"
            )
        }


def _schema(cache: sqlite3.Connection) -> None:
    cache.executescript("""
    PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA foreign_keys=ON;
    CREATE TABLE genre_state(channel TEXT NOT NULL CHECK(channel IN ('artist_direct','reviewed_alias_context')), seed_id TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('observed','abstained','isolated')), PRIMARY KEY(channel, seed_id)) WITHOUT ROWID;
    CREATE TABLE membership(channel TEXT NOT NULL CHECK(channel IN ('artist_direct','reviewed_alias_context')), artist_mbid TEXT NOT NULL, seed_id TEXT NOT NULL, PRIMARY KEY(channel, artist_mbid, seed_id)) WITHOUT ROWID;
    CREATE TABLE raw_pair(channel TEXT NOT NULL, seed_id TEXT NOT NULL, neighbor_seed_id TEXT NOT NULL, raw_mass REAL NOT NULL, window_support INTEGER NOT NULL, artist_pair_support INTEGER NOT NULL, PRIMARY KEY(channel, seed_id, neighbor_seed_id)) WITHOUT ROWID;
    CREATE TABLE scored_pair(channel TEXT NOT NULL, seed_id TEXT NOT NULL, neighbor_seed_id TEXT NOT NULL, unshrunk_npmi REAL NOT NULL, shrunk_npmi REAL NOT NULL, raw_mass REAL NOT NULL, window_support INTEGER NOT NULL, artist_pair_support INTEGER NOT NULL, PRIMARY KEY(channel, seed_id, neighbor_seed_id)) WITHOUT ROWID;
    CREATE TABLE neighbor(channel TEXT NOT NULL, seed_id TEXT NOT NULL, neighbor_seed_id TEXT NOT NULL, rank INTEGER NOT NULL, relation_kind TEXT NOT NULL CHECK(relation_kind = 'peer_not_parent_child'), shrunk_npmi REAL NOT NULL, unshrunk_npmi REAL NOT NULL, raw_mass REAL NOT NULL, window_support INTEGER NOT NULL, artist_pair_support INTEGER NOT NULL, PRIMARY KEY(channel, seed_id, neighbor_seed_id));
    CREATE INDEX neighbor_query ON neighbor(channel, seed_id, rank);
    """)


def _verify_cache(cache: sqlite3.Connection) -> None:
    if cache.execute("PRAGMA integrity_check").fetchone() != ("ok",):
        raise GenreNeighborhoodError("neighborhood cache integrity check failed")
    if cache.execute("SELECT count(*) FROM genre_state").fetchone() != (12582,):
        raise GenreNeighborhoodError("neighborhood cache lost stable seed states")


def write_genre_neighborhoods(
    output: Path, receipt_path: Path, artifact: GenreNeighborhoodArtifact
) -> GenreNeighborhoodReceipt:
    """Atomically publish a logical artifact and byte-custody receipt after replay validation."""
    verify_artifact(artifact)
    write_atomic_bytes(output, canonical_json(artifact.model_dump(mode="json")) + b"\n")
    digest, size = sha256_file(output)
    receipt = GenreNeighborhoodReceipt(
        artifact_sha256=digest,
        artifact_byte_count=size,
        logical_output_sha256=artifact.output_sha256,
        cache_database_sha256=artifact.cache_database_sha256,
    )
    write_atomic_bytes(receipt_path, canonical_json(receipt.model_dump(mode="json")) + b"\n")
    return receipt
