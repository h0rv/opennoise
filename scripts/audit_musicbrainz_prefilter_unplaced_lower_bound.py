"""Audit direct retained MusicBrainz seed-tag positives for unplaced seeds.

This is deliberately a lower-bound audit, not a membership builder.  The
input seed-target artifact was filtered to the seed vocabulary during
extraction, so it cannot establish absence from the original MusicBrainz
artist dump.  It can, however, preserve the direct source-positive tag rows
that survived that extraction.  The scan is local-only and streams the large
artifact without retaining its evidence rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import ijson

from opennoise.taxonomy.seeds.universe import normalize_label

if TYPE_CHECKING:
    from collections.abc import Iterator

_SHA256_HEX_LENGTH = 64


@dataclass(frozen=True, slots=True)
class AuditResult:
    """Hash-bound counts from a direct-claim, post-match lower bound."""

    audit_revision: str
    publication_scope: str
    result_kind: str
    source_completeness: str
    layout_path: str
    layout_byte_sha256: str
    layout_output_sha256: str
    seed_target_artifact_path: str
    seed_target_artifact_byte_sha256: str
    seed_target_artifact_output_sha256: str
    unplaced_seed_count: int
    direct_tag_rows_scanned: int
    direct_tag_rows_for_unplaced: int
    unplaced_seeds_with_direct_tag_support: int
    exact_spelling_tag_rows_for_unplaced: int
    exact_spelling_unplaced_seeds_with_tag_support: int
    normalized_or_reviewed_tag_rows_for_unplaced: int
    distinct_supporting_artists: int
    distinct_source_records: int
    publishable_membership_count: int
    missing_input: str
    smallest_bounded_acquisition: str


@dataclass(frozen=True, slots=True)
class DirectTagEvidence:
    """The string fields needed to classify one retained direct tag claim."""

    seed_id: str
    artist_id: str
    record_id: str
    target_name: str
    seed_name: str
    match_kind: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_hash(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) != _SHA256_HEX_LENGTH:
        raise ValueError(f"{name} must be a SHA-256 string")
    return value


def _unplaced_seed_ids(layout_path: Path) -> tuple[frozenset[str], str]:
    raw: object = json.loads(layout_path.read_bytes())
    if not isinstance(raw, dict):
        raise TypeError("layout must be an object")
    unplaced = raw.get("unplaced")
    if not isinstance(unplaced, list):
        raise TypeError("layout must contain an unplaced list")
    seed_ids: set[str] = set()
    for row in unplaced:
        if not isinstance(row, dict) or not isinstance(seed_id := row.get("seed_id"), str):
            raise TypeError("every unplaced row must contain a string seed_id")
        if seed_id in seed_ids:
            raise ValueError("unplaced seed IDs must be unique")
        seed_ids.add(seed_id)
    return frozenset(seed_ids), _require_hash(raw.get("output_sha256"), "layout output_sha256")


def _artifact_output_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        for prefix, event, value in ijson.parse(stream):
            if prefix == "output_sha256" and event == "string":
                return _require_hash(value, "seed-target artifact output_sha256")
    raise ValueError("seed-target artifact has no output_sha256")


def _iter_evidence(path: Path) -> Iterator[dict[str, object]]:
    with path.open("rb") as stream:
        for row in ijson.items(stream, "evidence.item"):
            if not isinstance(row, dict):
                raise TypeError("evidence row must be an object")
            typed_row: dict[str, object] = {}
            for key, value in row.items():
                if not isinstance(key, str):
                    raise TypeError("evidence row keys must be strings")
                typed_row[key] = value
            yield typed_row


def _direct_tag_evidence(row: dict[str, object]) -> DirectTagEvidence:
    """Parse the source fields needed for the bounded direct-tag audit."""
    match (
        row.get("seed_source_item_id"),
        row.get("artist_id"),
        row.get("source_record_id"),
        row.get("target_name"),
        row.get("seed_name"),
        row.get("match_kind"),
    ):
        case (
            str() as seed_id,
            str() as artist_id,
            str() as record_id,
            str() as target_name,
            str() as seed_name,
            str() as match_kind,
        ):
            return DirectTagEvidence(
                seed_id=seed_id,
                artist_id=artist_id,
                record_id=record_id,
                target_name=target_name,
                seed_name=seed_name,
                match_kind=match_kind,
            )
        case _:
            raise TypeError("tag evidence requires string identity, name, and match fields")


def audit(*, layout_path: Path, artifact_path: Path) -> AuditResult:
    """Stream direct tag claims and report a non-publishable lower bound."""
    unplaced_ids, layout_output_sha256 = _unplaced_seed_ids(layout_path)
    direct_tag_rows = 0
    matching_rows = 0
    exact_rows = 0
    nonexact_rows = 0
    matching_seed_ids: set[str] = set()
    exact_seed_ids: set[str] = set()
    artists: set[str] = set()
    records: set[str] = set()
    for row in _iter_evidence(artifact_path):
        if row.get("facet") != "tag":
            continue
        direct_tag_rows += 1
        evidence = _direct_tag_evidence(row)
        if evidence.seed_id not in unplaced_ids:
            continue
        matching_rows += 1
        matching_seed_ids.add(evidence.seed_id)
        artists.add(evidence.artist_id)
        records.add(evidence.record_id)
        if evidence.match_kind == "exact" and evidence.target_name == evidence.seed_name:
            exact_rows += 1
            exact_seed_ids.add(evidence.seed_id)
        elif normalize_label(evidence.target_name) == normalize_label(evidence.seed_name):
            nonexact_rows += 1
        else:
            raise ValueError("matched tag evidence does not normalize to its seed name")
    return AuditResult(
        audit_revision="musicbrainz-prefilter-unplaced-lower-bound-v1",
        publication_scope="local_only_research_audit",
        result_kind="source_positive_lower_bound_from_post_match_artifact",
        source_completeness="not_a_prefilter_slice; absence_is_not_measured",
        layout_path=str(layout_path),
        layout_byte_sha256=_sha256(layout_path),
        layout_output_sha256=layout_output_sha256,
        seed_target_artifact_path=str(artifact_path),
        seed_target_artifact_byte_sha256=_sha256(artifact_path),
        seed_target_artifact_output_sha256=_artifact_output_sha256(artifact_path),
        unplaced_seed_count=len(unplaced_ids),
        direct_tag_rows_scanned=direct_tag_rows,
        direct_tag_rows_for_unplaced=matching_rows,
        unplaced_seeds_with_direct_tag_support=len(matching_seed_ids),
        exact_spelling_tag_rows_for_unplaced=exact_rows,
        exact_spelling_unplaced_seeds_with_tag_support=len(exact_seed_ids),
        normalized_or_reviewed_tag_rows_for_unplaced=nonexact_rows,
        distinct_supporting_artists=len(artists),
        distinct_source_records=len(records),
        publishable_membership_count=0,
        missing_input=(
            "a retained pre-filter MusicBrainz artist JSON source slice containing tag claims for "
            "artists not already selected by seed-target extraction"
        ),
        smallest_bounded_acquisition=(
            "one checksum-bound MusicBrainz artist JSON-dump partition (or an equivalent derived "
            "tag-only partition) with artist MBID, tag name, source-record ID, and "
            "source-record hash; "
            "stream it once against the frozen unplaced-name set"
        ),
    )


def main() -> int:
    """Run the local-only lower-bound audit and write its compact report."""
    parser = argparse.ArgumentParser(prog="audit-musicbrainz-prefilter-unplaced-lower-bound")
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--seed-target-artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = audit(layout_path=arguments.layout, artifact_path=arguments.seed_target_artifact)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(result), sort_keys=True, separators=(",", ":")) + "\n"
    arguments.output.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
