"""Export a pinned reference contract and optionally evaluate independent candidate JSON."""

import argparse
import json
import sys
from pathlib import Path

from opennoise.analysis.reference_benchmark import (
    build_reference_contract,
    evaluate_reference_contract,
    parse_archived_artist_page,
)
from opennoise.catalog.musicbrainz_candidate import require_local_candidate_destination
from opennoise.common import canonical_json, sha256_json

MAX_ARCHIVE_PAGES = 100


def main() -> None:
    """Write immutable cache-only evaluation outputs from explicitly supplied inputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--atlas", type=Path, help="Independent named style atlas directory")
    parser.add_argument("--archive-manifest", type=Path)
    parser.add_argument("--neighbor-count", type=int, default=10)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    require_local_candidate_destination(args.output)
    if args.output.exists():
        raise FileExistsError("refusing to replace evaluation output")
    reference = build_reference_contract(
        args.reference.read_bytes(), neighbor_count=args.neighbor_count
    )
    if args.archive_manifest:
        pages = json.loads(args.archive_manifest.read_bytes())
        if len(pages) > MAX_ARCHIVE_PAGES:
            raise ValueError("archive manifest exceeds 100 page bound")
        reference["archive_pages"] = []
        for page in pages:
            path = args.archive_manifest.parent / page["path"]
            if not path.resolve().is_relative_to(args.archive_manifest.parent.resolve()):
                raise ValueError("archive page escapes manifest directory")
            observation = parse_archived_artist_page(
                path.read_bytes(), genre_name=page["genre_name"]
            )
            reference["archive_pages"].append(observation)
            reference["memberships"].extend(
                {"genre_name": page["genre_name"], **row} for row in observation["members"]
            )
        reference["membership_completeness"] = "bounded_positive_observations_not_census"
    result = {"reference": reference}
    if args.candidate and args.atlas:
        raise ValueError("choose candidate JSON or atlas, not both")
    if args.atlas:
        atlas = json.loads((args.atlas / "data.json").read_bytes())
        styles = atlas["styles"]
        candidate = {
            "genres": [row["name"] for row in styles],
            "representatives": [],
            "geometry_neighbors": {},
        }
        positioned = [row for row in styles if row["x"] is not None and row["y"] is not None]
        from scipy.spatial import KDTree  # noqa: PLC0415 - only atlas geometry needs scipy.

        tree = KDTree([(row["x"], row["y"]) for row in positioned])
        for index, row in enumerate(positioned):
            count = min(args.neighbor_count + 1, len(positioned))
            distances, _ = tree.query([row["x"], row["y"]], k=count)
            radius = max(distances) if count > 1 else float(distances)
            nearby = tree.query_ball_point([row["x"], row["y"]], r=float(radius) + 1e-9)
            selected = sorted(
                (other for other in nearby if other != index),
                key=lambda other: (
                    (row["x"] - positioned[other]["x"]) ** 2
                    + (row["y"] - positioned[other]["y"]) ** 2,
                    positioned[other]["name"],
                ),
            )
            candidate["geometry_neighbors"][row["name"]] = [
                positioned[other]["name"] for other in selected[: args.neighbor_count]
            ]
        result["evaluation"] = evaluate_reference_contract(reference, candidate)
        result["candidate_scope"] = "all_named_source_labels_including_raw_candidates"
        result["candidate_data_sha256"] = sha256_json(atlas)
    if args.candidate:
        result["evaluation"] = evaluate_reference_contract(
            reference, json.loads(args.candidate.read_bytes())
        )
    result["output_sha256"] = sha256_json(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_json(result) + b"\n")
    sys.stdout.write(
        json.dumps({"output": str(args.output), "output_sha256": result["output_sha256"]}) + "\n"
    )


if __name__ == "__main__":
    main()
