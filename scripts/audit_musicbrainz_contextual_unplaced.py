"""Measure exact contextual MusicBrainz tag coverage for explicit unplaced seeds.

This is a local, read-only checkpoint tool.  It does not infer memberships,
consume historical Every Noise data beyond the retained seed names, or write a
public artifact.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import ijson

from opennoise.taxonomy.seeds.universe import normalize_label

_SHA256_HEX_LENGTH = 64


@dataclass(frozen=True, slots=True)
class ContextualUnplacedCoverage:
    """Counts for one exact spelling-normalized, review-only overlap."""

    unplaced_seed_count: int
    matched_unplaced_seed_count: int
    unmatched_unplaced_seed_count: int
    contextual_row_count: int
    matching_contextual_row_count: int
    matching_artist_count: int
    matching_tag_identity_count: int
    layout_output_sha256: str
    source_artifact_output_sha256: str


def _unplaced_seed_names(layout_path: Path) -> tuple[dict[str, str], str]:
    raw: object = json.loads(layout_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("unplaced"), list):
        raise TypeError("layout must contain an unplaced list")
    layout_output_sha256 = raw.get("output_sha256")
    if not isinstance(layout_output_sha256, str) or len(layout_output_sha256) != _SHA256_HEX_LENGTH:
        raise ValueError("layout must contain a SHA-256 output hash")
    names: dict[str, str] = {}
    for item in raw["unplaced"]:
        if not isinstance(item, dict):
            raise TypeError("unplaced entry must be an object")
        seed_id, name = item.get("seed_id"), item.get("name")
        if not isinstance(seed_id, str) or not isinstance(name, str):
            raise TypeError("unplaced entry needs string seed_id and name")
        normalized = normalize_label(name)
        if not normalized or normalized in names:
            raise ValueError("unplaced names must have unique nonempty normalized spellings")
        names[normalized] = seed_id
    return names, layout_output_sha256


def measure_contextual_unplaced_coverage(
    *, layout_path: Path, source_artifact_path: Path, source_artifact_output_sha256: str
) -> ContextualUnplacedCoverage:
    """Stream source rows once and count only exact normalized tag-name matches."""
    if len(source_artifact_output_sha256) != _SHA256_HEX_LENGTH:
        raise ValueError("source artifact output hash must be SHA-256")
    unplaced_by_name, layout_output_sha256 = _unplaced_seed_names(layout_path)
    matched_seed_ids: set[str] = set()
    matching_artists: set[str] = set()
    matching_tag_identities: set[str] = set()
    matching_rows = 0
    contextual_rows = 0
    with source_artifact_path.open("rb") as stream:
        for row in ijson.items(stream, "contextual_tags.item"):
            if not isinstance(row, dict):
                raise TypeError("contextual tag entry must be an object")
            artist_id = row.get("artist_id")
            tag_name = row.get("tag_name")
            tag_identity = row.get("tag_identity")
            if not all(isinstance(value, str) for value in (artist_id, tag_name, tag_identity)):
                raise TypeError("contextual tag entry requires string artist and tag fields")
            contextual_rows += 1
            seed_id = unplaced_by_name.get(normalize_label(tag_name))
            if seed_id is None:
                continue
            matched_seed_ids.add(seed_id)
            matching_artists.add(artist_id)
            matching_tag_identities.add(tag_identity)
            matching_rows += 1
    return ContextualUnplacedCoverage(
        unplaced_seed_count=len(unplaced_by_name),
        matched_unplaced_seed_count=len(matched_seed_ids),
        unmatched_unplaced_seed_count=len(unplaced_by_name) - len(matched_seed_ids),
        contextual_row_count=contextual_rows,
        matching_contextual_row_count=matching_rows,
        matching_artist_count=len(matching_artists),
        matching_tag_identity_count=len(matching_tag_identities),
        layout_output_sha256=layout_output_sha256,
        source_artifact_output_sha256=source_artifact_output_sha256,
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the read-only audit command-line interface."""
    parser = argparse.ArgumentParser(prog="audit-musicbrainz-contextual-unplaced")
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--source-artifact", type=Path, required=True)
    parser.add_argument("--source-artifact-output-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    """Write one compact local-only coverage report."""
    arguments = build_parser().parse_args()
    result = measure_contextual_unplaced_coverage(
        layout_path=arguments.layout,
        source_artifact_path=arguments.source_artifact,
        source_artifact_output_sha256=arguments.source_artifact_output_sha256,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(asdict(result), sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
