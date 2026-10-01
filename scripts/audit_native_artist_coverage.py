"""Write exact-ID source features and inferred memberships for a small cohort."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from opennoise.catalog.artist_coverage import audit_artist_coverage
from opennoise.common import sha256_json


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _rejection_count(path: Path | None, reason: str) -> int | None:
    if path is None:
        return None
    count = 0
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise TypeError(f"{path}:{line_number}: expected JSON object")
            if row.get("reason") == reason:
                count += 1
    return count


def main() -> None:
    """Write the cohort report from portable feature and assignment artifacts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--features-jsonl",
        type=Path,
        default=Path(".cache/microgenre-features-rich-v2/artist-features.jsonl"),
    )
    parser.add_argument(
        "--names-jsonl",
        type=Path,
        default=Path(".cache/microgenre-features-rich-v2/artist-names.jsonl"),
    )
    parser.add_argument(
        "--assignments-jsonl",
        type=Path,
        default=Path(".cache/emergent-topics/rich-20260930-v4/assignments.jsonl"),
    )
    parser.add_argument(
        "--communities-json",
        type=Path,
        default=Path(".cache/emergent-topics/rich-20260930-v4/communities.json"),
    )
    parser.add_argument(
        "--model-report",
        type=Path,
        default=Path(".cache/emergent-topics/rich-20260930-v4/report.json"),
    )
    parser.add_argument(
        "--rejections-jsonl",
        type=Path,
        default=Path(".cache/microgenre-features-rich-v2/rejected.jsonl"),
    )
    parser.add_argument("--catalog-database", type=Path)
    parser.add_argument("--feature-database", type=Path)
    parser.add_argument("--genre-label-directory", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".cache/artist-coverage-rich-v4.json"),
    )
    arguments = parser.parse_args()

    model_receipt = json.loads(arguments.model_report.read_text(encoding="utf-8"))
    bound_receipt = {key: value for key, value in model_receipt.items() if key != "output_sha256"}
    if sha256_json(bound_receipt) != model_receipt.get("output_sha256"):
        raise ValueError("model receipt identity mismatch")
    expected_features = model_receipt.get("features_sha256")
    if _sha256(arguments.features_jsonl) != expected_features:
        raise ValueError("feature JSONL does not match model training receipt")
    for name, path in (
        ("assignments.jsonl", arguments.assignments_jsonl),
        ("communities.json", arguments.communities_json),
    ):
        binding = model_receipt.get("files", {}).get(name)
        if (
            not isinstance(binding, dict)
            or binding.get("sha256") != _sha256(path)
            or binding.get("bytes") != path.stat().st_size
        ):
            raise ValueError(f"{name} does not match model receipt")

    sources = {
        "features": arguments.features_jsonl,
        "names": arguments.names_jsonl,
        "assignments": arguments.assignments_jsonl,
        "communities": arguments.communities_json,
        "model_report": arguments.model_report,
    }
    sources.update(
        {
            name: path
            for name, path in (
                ("catalog", arguments.catalog_database),
                ("open_tag_matrix", arguments.feature_database),
                (
                    "genre_labels",
                    arguments.genre_label_directory / "labels.json"
                    if arguments.genre_label_directory
                    else None,
                ),
            )
            if path is not None
        }
    )
    if arguments.rejections_jsonl is not None:
        sources["rejections"] = arguments.rejections_jsonl
    rows = audit_artist_coverage(
        arguments.catalog_database,
        feature_database=arguments.feature_database,
        genre_label_directory=arguments.genre_label_directory,
        feature_jsonl=arguments.features_jsonl,
        name_jsonl=arguments.names_jsonl,
        assignments_jsonl=arguments.assignments_jsonl,
        communities_json=arguments.communities_json,
    )
    report: dict[str, Any] = {
        "revision": "native-electronic-artist-coverage-v2",
        "scope": "local_research_only",
        "identity_join": "exact_musicbrainz_artist_uuid_only",
        "artist_count": len(rows),
        "all_feature_rows_present": all(row.features is not None for row in rows),
        "all_assignment_rows_present": all(row.assignment_state is not None for row in rows),
        "model_output_sha256": model_receipt["output_sha256"],
        "training_feature_sha256": expected_features,
        "source_vote_policy": (
            "zero and negative numeric source counts are rejected before feature creation"
        ),
        "nonpositive_source_count_rejections": _rejection_count(
            arguments.rejections_jsonl, "nonpositive_source_count"
        ),
        "sources": {
            name: {"path": str(path), "sha256": _sha256(path)} for name, path in sources.items()
        },
        "artists": [asdict(row) for row in rows],
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    arguments.output.write_text(payload, encoding="utf-8")
    print(json.dumps({"output": str(arguments.output), "artist_count": len(rows)}))  # noqa: T201


if __name__ == "__main__":
    main()
