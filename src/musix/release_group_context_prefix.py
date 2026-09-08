"""Bounded, target-masked release-group context extraction."""

# ruff: noqa: C901, PLR0913, TRY300, TRY301

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from musix.genre_seed_universe import normalize_label
from musix.musicbrainz_seed_targets import load_seed_target_artifact
from musix.seed_reconciliation import load_seed_reconciliation
from musix.sources.musicbrainz import (
    AdapterLimits,
    MusicBrainzAdapterError,
    MusicBrainzReleaseGroup,
    iter_json_archive_lines,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from musix.musicbrainz_seed_targets import MusicBrainzSeedTargetArtifact
    from musix.seed_reconciliation import SeedReconciliationArtifact

RELEASE_GROUP_CONTEXT_PREFIX_REVISION = "release-group-context-prefix-pilot-v2"
DEFAULT_RECORD_CAP = 100_000
EXPECTED_SEED_COUNT = 6_291
DEFAULT_ARCHIVE_SHA256 = "6f153846228dc6034b2f8f43b472b088792cc2e242b09783a8968fa8d4bd7a43"


class ReleaseGroupContextError(ValueError):
    """Raised when an input cannot prove its safe source binding."""


@dataclass(frozen=True, slots=True)
class ReviewedAlias:
    """One reviewed spelling expansion tied to a stable seed."""

    source_item_id: str
    alias: str
    approval_ref: str


@dataclass(frozen=True, slots=True)
class TargetMask:
    """Complete lexical and identity target exclusion set."""

    genre_ids: frozenset[str]
    normalized_tokens: frozenset[str]
    normalized_tag_aliases: frozenset[str]
    target_seed_count: int
    reconciliation_sha256: str
    seed_target_sha256: str
    alias_config_sha256: str

    def matches(self, *, kind: str, token_id: str | None, token_name: str) -> bool:
        """Return whether either source representation identifies a target."""
        normalized = normalize_label(token_name)
        return (
            token_id in self.genre_ids
            or normalized in self.normalized_tokens
            or (kind == "tag" and normalized in self.normalized_tag_aliases)
        )


def file_sha256(path: Path) -> str:
    """Return a byte-level local-file checksum."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1_048_576):
            digest.update(block)
    return digest.hexdigest()


def _seed_identity_fingerprint(rows: object) -> str:
    """Hash stable seed triples independently of producer-specific wrappers."""
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _verify_complete_seed_binding(
    reconciliation: SeedReconciliationArtifact, seed_target: MusicBrainzSeedTargetArtifact
) -> None:
    """Verify the all-seed join without equating producer-local input hashes."""
    if (
        seed_target.seed_count != reconciliation.seed_count
        or seed_target.seed_source_id != reconciliation.seed_source_id
        or seed_target.seed_source_content_sha256 != reconciliation.seed_source_content_sha256
    ):
        raise ReleaseGroupContextError(
            "seed-target artifact and reconciliation do not share a complete seed binding"
        )
    if reconciliation.seed_count != EXPECTED_SEED_COUNT:
        raise ReleaseGroupContextError(
            "reconciliation must account for the complete 6291-seed universe"
        )
    target_rows = [
        {
            "source_item_id": row.seed_source_item_id,
            "source_external_id": row.seed_source_external_id,
            "name": row.seed_name,
        }
        for row in sorted(seed_target.coverage, key=lambda item: item.seed_source_item_id)
    ]
    reconciliation_rows = [
        {
            "source_item_id": row.source_item_id,
            "source_external_id": row.source_external_id,
            "name": row.seed_name,
        }
        for row in sorted(reconciliation.dispositions, key=lambda item: item.source_item_id)
    ]
    target_fingerprint = _seed_identity_fingerprint(target_rows)
    if (
        target_fingerprint != _seed_identity_fingerprint(reconciliation_rows)
        or target_fingerprint != reconciliation.seed_identity_sha256
    ):
        raise ReleaseGroupContextError(
            "seed-target artifact and reconciliation do not share stable seed identities"
        )


def load_target_mask(
    reconciliation_path: Path, seed_target_path: Path, alias_config_path: Path
) -> TargetMask:
    """Load the full seed vocabulary and verify its complete seed-target binding."""
    reconciliation = load_seed_reconciliation(reconciliation_path)
    seed_target = load_seed_target_artifact(seed_target_path)
    _verify_complete_seed_binding(reconciliation, seed_target)
    disposition_by_id = {item.source_item_id: item for item in reconciliation.dispositions}
    tokens = {normalize_label(item.seed_name) for item in reconciliation.dispositions}
    genre_ids: set[str] = set()
    for disposition in reconciliation.dispositions:
        for identity in disposition.musicbrainz_identities:
            if identity.namespace == "musicbrainz_genre_id":
                genre_ids.add(identity.identifier)
            elif identity.namespace == "musicbrainz_tag_name":
                tokens.add(normalize_label(identity.identifier.removeprefix("tag:")))
                tokens.add(normalize_label(identity.name))
    try:
        alias_document = json.loads(alias_config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseGroupContextError("cannot read reviewed alias configuration") from error
    if not isinstance(alias_document, list):
        raise ReleaseGroupContextError("reviewed alias configuration must be a list")
    aliases: list[ReviewedAlias] = []
    for row in alias_document:
        if not isinstance(row, dict) or set(row) != {
            "source_item_id",
            "alias",
            "approval_ref",
            "facets",
        }:
            raise ReleaseGroupContextError("reviewed alias configuration has an invalid row")
        if not all(
            isinstance(row[key], str) and row[key]
            for key in ("source_item_id", "alias", "approval_ref")
        ) or row["facets"] != ["tag"]:
            raise ReleaseGroupContextError("reviewed alias configuration has unsupported scope")
        aliases.append(ReviewedAlias(row["source_item_id"], row["alias"], row["approval_ref"]))
    tag_aliases: set[str] = set()
    for alias in aliases:
        if alias.source_item_id not in disposition_by_id:
            raise ReleaseGroupContextError(
                "approved alias references a seed outside reconciliation"
            )
        tag_aliases.add(normalize_label(alias.alias))
    return TargetMask(
        frozenset(genre_ids),
        frozenset(tokens),
        frozenset(tag_aliases),
        reconciliation.seed_count,
        file_sha256(reconciliation_path),
        file_sha256(seed_target_path),
        file_sha256(alias_config_path),
    )


def _rows_for_release_group(
    release_group: MusicBrainzReleaseGroup, mask: TargetMask | None
) -> tuple[tuple[str, str, str, str | None, str, int | None], ...]:
    artists = tuple(str(credit.artist.id) for credit in release_group.artist_credit)
    tokens: list[tuple[str, str | None, str, int | None]] = [
        ("genre", str(item.id), item.name, item.count) for item in release_group.genres
    ]
    tokens.extend(("tag", None, item.name, item.count) for item in release_group.tags)
    if any(count is not None and count <= 0 for _, _, _, count in tokens):
        raise ReleaseGroupContextError("MusicBrainz context token count must be positive")
    return tuple(
        (artist, str(release_group.id), kind, token_id, token_name, source_vote_count)
        for kind, token_id, token_name, source_vote_count in tokens
        if mask is None or not mask.matches(kind=kind, token_id=token_id, token_name=token_name)
        for artist in artists
    )


def _iter_prefix(archive: Path, record_cap: int) -> Iterator[bytes]:
    """Yield the prefix, swallowing only the expected exact-cap sentinel."""
    seen = 0
    try:
        for raw in iter_json_archive_lines(
            archive,
            AdapterLimits(max_records=record_cap, max_archive_bytes=2 * 1024**3),
            member_name="release-group",
        ):
            seen += 1
            yield raw
    except MusicBrainzAdapterError as error:
        if str(error) != "MusicBrainz dump exceeds max_records" or seen != record_cap:
            raise


def _audit_database(connection: sqlite3.Connection, mask: TargetMask) -> None:
    leaked = connection.execute(
        "SELECT token_id, token_name FROM context_token WHERE token_id IS NOT NULL"
    ).fetchall()
    leaked.extend(
        connection.execute(
            "SELECT token_id, token_name FROM context_token WHERE token_id IS NULL"
        ).fetchall()
    )
    if any(
        mask.matches(
            kind="genre" if row[0] is not None else "tag", token_id=row[0], token_name=row[1]
        )
        for row in leaked
    ):
        raise ReleaseGroupContextError("post-build target-token audit found a masked token leak")


def build_context_prefix(
    *,
    archive: Path,
    reconciliation: Path,
    seed_target: Path,
    alias_config: Path,
    output_root: Path,
    record_cap: int = DEFAULT_RECORD_CAP,
    expected_archive_sha256: str | None = DEFAULT_ARCHIVE_SHA256,
) -> dict[str, object]:
    """Build v2 SQLite context with all target forms excluded."""
    if record_cap < 1:
        raise ReleaseGroupContextError("record cap must be positive")
    archive_sha256 = file_sha256(archive)
    if expected_archive_sha256 is not None and archive_sha256 != expected_archive_sha256:
        raise ReleaseGroupContextError("archive SHA-256 does not match the approved source")
    mask = load_target_mask(reconciliation, seed_target, alias_config)
    if output_root.exists():
        raise ReleaseGroupContextError("refusing to overwrite an existing v2 output root")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(
        tempfile.mkdtemp(prefix=".release-group-context-v2-", dir=output_root.parent)
    )
    database = staging_root / "context.sqlite"
    manifest = {
        "revision": RELEASE_GROUP_CONTEXT_PREFIX_REVISION,
        "source_archive_sha256": archive_sha256,
        "reconciliation_sha256": mask.reconciliation_sha256,
        "seed_target_sha256": mask.seed_target_sha256,
        "approved_alias_config_sha256": mask.alias_config_sha256,
        "record_cap": record_cap,
        "target_seed_count": mask.target_seed_count,
        "sampling": "first-record-cap-records-in-verified-archive-member-not-representative",
        "mask": "complete-reconciliation-vocabulary-identities-and-reviewed-aliases",
    }
    try:
        with sqlite3.connect(database) as connection:
            connection.executescript("""DROP TABLE IF EXISTS context_token;
            CREATE TABLE context_token (
              artist_mbid TEXT NOT NULL, release_group_mbid TEXT NOT NULL,
              token_kind TEXT NOT NULL CHECK(token_kind IN ('genre','tag')),
              token_id TEXT, token_name TEXT NOT NULL,
              source_vote_count INTEGER NULL CHECK(source_vote_count > 0),
              PRIMARY KEY(artist_mbid, release_group_mbid, token_kind, token_name)
            ) WITHOUT ROWID;""")
            records_seen = malformed_records = masked_occurrences = inserted_rows = 0
            for raw in _iter_prefix(archive, record_cap):
                records_seen += 1
                try:
                    release_group = MusicBrainzReleaseGroup.model_validate_json(raw)
                except ValueError:
                    malformed_records += 1
                    continue
                all_rows = _rows_for_release_group(release_group, None)
                kept_rows = _rows_for_release_group(release_group, mask)
                masked_occurrences += len(all_rows) - len(kept_rows)
                before = connection.total_changes
                connection.executemany(
                    "INSERT OR IGNORE INTO context_token VALUES (?, ?, ?, ?, ?, ?)", kept_rows
                )
                inserted_rows += connection.total_changes - before
            _audit_database(connection, mask)
            if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise ReleaseGroupContextError("SQLite integrity check failed")
            artists, stored_rows, weighted_rows, unweighted_rows = connection.execute(
                """SELECT count(DISTINCT artist_mbid), count(*),
                coalesce(sum(source_vote_count IS NOT NULL), 0),
                coalesce(sum(source_vote_count IS NULL), 0)
                FROM context_token"""
            ).fetchone()
        report = {
            **manifest,
            "records_seen": records_seen,
            "stored_rows": stored_rows,
            "inserted_rows": inserted_rows,
            "artists_with_context": artists,
            "weighted_stored_rows": weighted_rows,
            "unweighted_stored_rows": unweighted_rows,
            "malformed_records": malformed_records,
            "masked_artist_token_occurrences": masked_occurrences,
            "derived_database_sha256": file_sha256(database),
            "derived_database_bytes": database.stat().st_size,
            "training": False,
            "membership_promotion": False,
        }
        (staging_root / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")
        (staging_root / "report.json").write_text(json.dumps(report, sort_keys=True) + "\n")
        staging_root.replace(output_root)
        return report
    except BaseException:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise
