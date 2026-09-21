"""Count literal Last.fm ArtistTags2007 positives for currently unplaced seeds.

The report is an exploratory construction-source candidate only.  It must not
be combined with MusicBrainz counts or promoted while this same pinned archive
is retained as an independent evaluation source.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from dataclasses import asdict, dataclass
from pathlib import Path

_DATA_MEMBER = "Lastfm-ArtistTags2007/ArtistTags.dat"
_PINNED_ARCHIVE_SHA256 = "b2b78000279c00c49ad6c0e764203dfbe4deb18a8012c1f43b7fb64933741c4f"
_SHA256_HEX_LENGTH = 64


@dataclass(frozen=True, slots=True)
class LastFmExploratoryResult:
    """Literal tag-name positives from one pinned archive and one frozen layout."""

    audit_revision: str
    publication_scope: str
    source_role: str
    evaluation_independence_warning: str
    layout_path: str
    layout_output_sha256: str
    archive_path: str
    archive_sha256: str
    unplaced_seed_count: int
    total_physical_rows: int
    accepted_positive_rows: int
    literal_unplaced_tag_rows: int
    literal_unplaced_seed_count: int
    distinct_musicbrainz_artist_count: int
    raw_tag_count_sum: int
    publishable_membership_count: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unplaced_names(layout_path: Path) -> tuple[frozenset[str], str]:
    raw: object = json.loads(layout_path.read_bytes())
    if not isinstance(raw, dict) or not isinstance(unplaced := raw.get("unplaced"), list):
        raise TypeError("layout must contain an unplaced list")
    output_sha256 = raw.get("output_sha256")
    if not isinstance(output_sha256, str) or len(output_sha256) != _SHA256_HEX_LENGTH:
        raise ValueError("layout must contain an output SHA-256")
    names: set[str] = set()
    for row in unplaced:
        if not isinstance(row, dict) or not isinstance(name := row.get("name"), str):
            raise TypeError("every unplaced row must contain a string name")
        if name in names:
            raise ValueError("unplaced names must be literally unique")
        names.add(name)
    return frozenset(names), output_sha256


def audit(*, layout_path: Path, archive_path: Path) -> LastFmExploratoryResult:
    """Stream literal, positive-only tag rows from the pinned Last.fm archive."""
    archive_sha256 = _sha256(archive_path)
    if archive_sha256 != _PINNED_ARCHIVE_SHA256:
        raise ValueError("archive SHA-256 does not match the pinned ArtistTags2007 source")
    unplaced_names, layout_sha256 = _unplaced_names(layout_path)
    total_rows = 0
    accepted_rows = 0
    matching_rows = 0
    matching_names: set[str] = set()
    artists: set[str] = set()
    raw_tag_count_sum = 0
    with tarfile.open(archive_path, mode="r:gz") as archive:
        stream = archive.extractfile(_DATA_MEMBER)
        if stream is None:
            raise ValueError("ArtistTags2007 data member is unavailable")
        for raw in stream:
            total_rows += 1
            try:
                mbid, _artist_name, tag_name, raw_count_text = (
                    raw.rstrip(b"\r\n").decode().split("<sep>")
                )
                raw_count = int(raw_count_text)
            except (UnicodeDecodeError, ValueError):
                continue
            if raw_count <= 0:
                continue
            accepted_rows += 1
            if tag_name not in unplaced_names:
                continue
            matching_rows += 1
            matching_names.add(tag_name)
            artists.add(mbid)
            raw_tag_count_sum += raw_count
    return LastFmExploratoryResult(
        audit_revision="lastfm-artisttags2007-unplaced-exploratory-v1",
        publication_scope="local_only_research_audit",
        source_role="exploratory_construction_source_candidate",
        evaluation_independence_warning=(
            "Do not promote this archive into construction while it remains an independent "
            "evaluation set; doing so forfeits that independence."
        ),
        layout_path=str(layout_path),
        layout_output_sha256=layout_sha256,
        archive_path=str(archive_path),
        archive_sha256=archive_sha256,
        unplaced_seed_count=len(unplaced_names),
        total_physical_rows=total_rows,
        accepted_positive_rows=accepted_rows,
        literal_unplaced_tag_rows=matching_rows,
        literal_unplaced_seed_count=len(matching_names),
        distinct_musicbrainz_artist_count=len(artists),
        raw_tag_count_sum=raw_tag_count_sum,
        publishable_membership_count=0,
    )


def main() -> int:
    """Run the exploratory Last.fm audit and write its compact local report."""
    parser = argparse.ArgumentParser(prog="audit-lastfm-artisttags2007-unplaced-exploratory")
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = audit(layout_path=arguments.layout, archive_path=arguments.archive)
    payload = json.dumps(asdict(result), sort_keys=True, separators=(",", ":")) + "\n"
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
