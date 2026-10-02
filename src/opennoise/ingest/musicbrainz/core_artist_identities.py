"""Stream a core-only MusicBrainz artist identity projection, without tag joins."""

from __future__ import annotations

import hashlib
import json
import tarfile
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from uuid import UUID

import zstandard

from opennoise.common import sha256_file
from opennoise.ingest.musicbrainz.derived_entity_tags import _columns

if TYPE_CHECKING:
    from opennoise.ingest.musicbrainz.bulk_artist_tag_evidence import CoreArtistPrefixReceipt

_MEMBER = PurePosixPath("mbdump/artist")
_COLUMN_COUNT = 19
_MAX_ROW_BYTES = 2 * 1024 * 1024


class CoreIdentityError(ValueError):
    """The complete core artist member cannot be reproduced from its receipt."""


def build_core_artist_identities(  # noqa: C901, PLR0912, PLR0915 - one streaming verification boundary.
    source: Path,
    receipt: CoreArtistPrefixReceipt,
    destination: Path,
    *,
    license_capture: Path | None = None,
) -> dict[str, object]:
    """Write names and exact UUIDs into a new directory, bounded in memory.

    A verified prefix can contain a complete artist table even when the rest of
    the compressed archive is absent. Whole-archive verification is never inferred.
    Failed output stays visibly incomplete; existing files are never replaced.
    """
    if not source.is_file() or source.is_symlink():
        raise CoreIdentityError("core prefix must be a regular file")
    digest, byte_count = sha256_file(source)
    if digest != receipt.prefix_sha256 or byte_count != receipt.prefix_bytes:
        raise CoreIdentityError("core prefix size or SHA-256 differs")
    license_digest = None
    if license_capture is not None:
        license_digest, _ = sha256_file(license_capture)
        if license_digest != "5b37894260af675ff117f6921f62bd21963081f22893cf10717991dd930ff2f8":
            raise CoreIdentityError("official core-data license capture differs")
    destination.mkdir(parents=True, exist_ok=False)
    rows_path = destination / "artist-identities.jsonl.zst"
    member_digest = hashlib.sha256()
    count = 0
    found = False
    with (
        rows_path.open("xb") as output,
        zstandard.ZstdCompressor(level=6).stream_writer(output, closefd=False) as writer,
        tarfile.open(source, mode="r|bz2") as archive,
    ):
        for member in archive:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts:
                raise CoreIdentityError("unsafe core archive path")
            if name != _MEMBER:
                continue
            if not member.isfile() or member.size != receipt.artist_member_bytes:
                raise CoreIdentityError("artist member type or size differs")
            stream = archive.extractfile(member)
            if stream is None:
                raise CoreIdentityError("artist member cannot be read")
            remaining = member.size
            with stream:
                while remaining:
                    raw = stream.readline(min(_MAX_ROW_BYTES, remaining + 1))
                    if not raw or len(raw) > remaining or not raw.endswith(b"\n"):
                        raise CoreIdentityError("artist member ended inside a bounded row")
                    remaining -= len(raw)
                    member_digest.update(raw)
                    columns = _columns(raw[:-1], _COLUMN_COUNT, "core artist")
                    try:
                        numeric_id = int(columns[0])
                        identity = str(UUID(columns[1]))
                    except ValueError as error:
                        raise CoreIdentityError("invalid core artist identity") from error
                    if numeric_id <= 0 or columns[1] != identity or not columns[2]:
                        raise CoreIdentityError("noncanonical identity or missing artist name")
                    row = {"artist_mbid": identity, "name": columns[2]}
                    writer.write(
                        (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
                            "utf-8"
                        )
                    )
                    count += 1
            found = True
            break
    if (
        not found
        or count != receipt.artist_row_count
        or member_digest.hexdigest() != receipt.artist_member_sha256
    ):
        raise CoreIdentityError("complete core artist member count or SHA-256 differs")
    output_digest, output_bytes = sha256_file(rows_path)
    facts: dict[str, object] = {
        "revision": "musicbrainz-core-artist-identities-v1",
        "license": "CC0-1.0",
        "license_url": "https://musicbrainz.org/doc/About/Data_License",
        "license_capture_sha256": license_digest,
        "attribution": "MusicBrainz contributors",
        "source_url": receipt.archive_url,
        "snapshot": receipt.snapshot,
        "observed_at": receipt.observed_at,
        "schema_sequence": receipt.schema_sequence,
        "source_prefix_bytes": byte_count,
        "source_prefix_sha256": digest,
        "source_archive_published_sha256": receipt.archive_sha256,
        "source_archive_sha256_verified": False,
        "source_member": str(_MEMBER),
        "source_member_bytes": receipt.artist_member_bytes,
        "source_member_sha256": member_digest.hexdigest(),
        "artist_count": count,
        "fields": ["artist_mbid", "name"],
        "genre_memberships": "absent; identities are not genre evidence",
        "derived_tables_consumed": [],
        "selection": "all core artist rows; no reference-label selection",
        "output_file": rows_path.name,
        "output_bytes": output_bytes,
        "output_sha256": output_digest,
        "verified_complete": True,
    }
    with (destination / "receipt.json").open("x", encoding="utf-8") as output_receipt:
        json.dump(facts, output_receipt, ensure_ascii=False, indent=2)
        output_receipt.write("\n")
    return facts
