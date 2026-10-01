"""Seal a byte-identical inferred-topic export projection without altering frozen runs."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import cast

from opennoise.catalog.musicbrainz_candidate import require_local_candidate_destination
from opennoise.common import canonical_json, sha256_file, sha256_json


def seal_topic_projection(  # noqa: C901, PLR0912 - one receipt-and-role verification boundary.
    source: Path, output: Path
) -> dict[str, object]:
    """Verify source bindings and inference roles before adding an explicit zero native count."""
    require_local_candidate_destination(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing to replace a sealed topic projection")
    receipt = json.loads((source / "report.json").read_bytes())
    identity = receipt.pop("output_sha256")
    if sha256_json(receipt) != identity:
        raise ValueError("source topic receipt identity mismatch")
    receipt["output_sha256"] = identity
    if (
        receipt.get("historical_inputs_used") is not False
        or receipt.get("artist_names_used_for_construction") is not False
        or receipt.get("public_export_authorized") is not False
        or receipt.get("scope") != "local_research_only"
        or receipt.get("native_genre_memberships_added", 0) != 0
    ):
        raise ValueError("source topic projection requires declared source-only local inference")
    files = receipt["files"]
    for name, binding in files.items():
        if Path(name).name != name or (source / name).is_symlink():
            raise ValueError("topic projection source filename is unsafe")
        path = source / name
        digest, size = sha256_file(path)
        if digest != binding["sha256"] or size != binding["bytes"]:
            raise ValueError("source topic artifact byte binding mismatch")
    required = {"communities.json", "assignments.jsonl", "primary-assignments.json"}
    if not required <= set(files):
        raise ValueError("source projection lacks bound community assignments")
    model = json.loads((source / "communities.json").read_bytes())
    if model.get("native_genre_memberships_added", 0) != 0:
        raise ValueError("source model reports native membership mutations")
    if any(item["role"] != "inferred_music_community" for item in model["communities"]):
        raise ValueError("topic projection contains a non-inferred community")
    count = 0
    with (source / "assignments.jsonl").open() as stream:
        for line in stream:
            row = json.loads(line)
            for item in row["memberships"]:
                if item["role"] != "inferred_community_membership":
                    raise ValueError("topic projection contains a native membership role")
                count += 1
    output.mkdir(parents=True)
    for name in files:
        shutil.copyfile(source / name, output / name)
    projected = {
        **receipt,
        "native_genre_memberships_added": 0,
        "source_report_sha256": sha256_file(source / "report.json")[0],
        "source_report_output_sha256": identity,
        "projection_method": "byte_identical_inference_with_explicit_native_zero",
        "verified_inferred_membership_count": count,
    }
    projected.pop("output_sha256")
    projected["output_sha256"] = sha256_json(projected)
    (output / "report.json").write_bytes(canonical_json(projected) + b"\n")
    return cast("dict[str, object]", projected)
