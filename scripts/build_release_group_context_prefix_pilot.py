"""Build a 100k-record, target-masked release-group context sample; no training."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

from musix.sources.musicbrainz import (
    AdapterLimits,
    MusicBrainzAdapterError,
    MusicBrainzReleaseGroup,
    iter_json_archive_lines,
)

_CAP = 100_000


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1_048_576):
            digest.update(block)
    return digest.hexdigest()


def _masked_tokens(reconciliation: Path) -> tuple[set[str], set[str]]:
    document = json.loads(reconciliation.read_text(encoding="utf-8"))
    genre_ids: set[str] = set()
    tag_names: set[str] = set()
    for disposition in document["dispositions"]:
        for identity in disposition["musicbrainz_identities"]:
            if identity["namespace"] == "musicbrainz_genre_id":
                genre_ids.add(identity["identifier"])
            elif identity["namespace"] == "musicbrainz_tag_name":
                tag_names.add(identity["name"].casefold())
    return genre_ids, tag_names


def main() -> int:
    """Write exact-credit, non-target source tokens from an explicit archive prefix."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    arguments = parser.parse_args()
    archive_sha = _sha256(arguments.archive)
    reconciliation_sha = _sha256(arguments.reconciliation)
    masked_genre_ids, masked_tag_names = _masked_tokens(arguments.reconciliation)
    root = arguments.output_root
    root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "revision": "release-group-context-prefix-pilot-v1",
        "source_archive_sha256": archive_sha,
        "reconciliation_sha256": reconciliation_sha,
        "record_cap": _CAP,
        "sampling": "first-100000-records-in-verified-archive-member-not-representative",
        "mask": "all-reconciliation-musicbrainz-genre-ids-and-tag-names",
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8"
    )
    database = root / "context.sqlite"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """DROP TABLE IF EXISTS context_token;
            CREATE TABLE context_token (
              artist_mbid TEXT NOT NULL, release_group_mbid TEXT NOT NULL,
              token_kind TEXT NOT NULL CHECK(token_kind IN ('genre','tag')),
              token_id TEXT, token_name TEXT NOT NULL,
              PRIMARY KEY(artist_mbid, release_group_mbid, token_kind, token_name)
            ) WITHOUT ROWID;"""
        )
        records = masked = emitted = malformed_records = 0
        lines = iter_json_archive_lines(
            arguments.archive,
            AdapterLimits(max_records=_CAP, max_archive_bytes=2 * 1024**3),
            member_name="release-group",
        )
        try:
            for raw in lines:
                records += 1
                try:
                    release_group = MusicBrainzReleaseGroup.model_validate_json(raw)
                except ValueError:
                    malformed_records += 1
                    continue
                credit_artist_ids = tuple(
                    str(credit.artist.id) for credit in release_group.artist_credit
                )
                tokens: list[tuple[str, str | None, str]] = [
                    ("genre", str(item.id), item.name) for item in release_group.genres
                ]
                tokens.extend(("tag", None, item.name) for item in release_group.tags)
                for kind, token_id, token_name in tokens:
                    if (kind == "genre" and token_id in masked_genre_ids) or (
                        kind == "tag" and token_name.casefold() in masked_tag_names
                    ):
                        masked += len(credit_artist_ids)
                        continue
                    for artist_mbid in credit_artist_ids:
                        connection.execute(
                            "INSERT OR IGNORE INTO context_token VALUES (?, ?, ?, ?, ?)",
                            (artist_mbid, str(release_group.id), kind, token_id, token_name),
                        )
                        emitted += 1
        except MusicBrainzAdapterError as error:
            if str(error) != "MusicBrainz dump exceeds max_records" or records != _CAP:
                raise
        connection.commit()
        artists, stored_rows = connection.execute(
            "SELECT count(DISTINCT artist_mbid), count(*) FROM context_token"
        ).fetchone()
    report = {
        **manifest,
        "records_seen": records,
        "tokens_emitted": emitted,
        "masked_artist_token_occurrences": masked,
        "malformed_records": malformed_records,
        "artists_with_context": artists,
        "stored_rows": stored_rows,
        "training": False,
        "membership_promotion": False,
    }
    (root / "report.json").write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")
    sys.stdout.write(json.dumps(report, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
