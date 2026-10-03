"""Assemble a new research extension without replacing verified native source facts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from opennoise.common import canonical_json, sha256_file
from opennoise.pipeline.full_input_research import (
    RESEARCH_ROLES,
    export_research_files,
    research_contexts,
    verify_research_files,
)

if TYPE_CHECKING:
    from opennoise.pipeline.full_input_context import FullInputSources

TOP_ASSETS = (
    "full-foundation.html",
    "full-foundation.css",
    "full-foundation.mjs",
    "full-foundation-normalization.mjs",
    "listening-list.mjs",
)


def addon_directories(inputs: FullInputSources) -> dict[str, Path]:
    """List separately licensed research roles, never native artist genre facts."""
    return {
        name: directory
        for name in RESEARCH_ROLES
        if (directory := getattr(inputs, name)) is not None
    }


def public_genres(genres: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep complete cohorts lazy while preserving every source label and its exact count."""
    return [
        {
            "genre_id": row["genre_id"],
            "name": row["name"],
            "artist_count": len(row["artist_mbids"]),
            "cohort_path": f"genres/{row['genre_id']}.json",
        }
        for row in genres
    ]


def supplemental_contexts(
    source: Path, inputs: FullInputSources
) -> tuple[dict[str, dict[str, Any]], dict[str, Any] | None]:
    """Derive supplements from immutable native facts and pinned research outputs."""
    entity_sha = sha256_file(inputs.entity_pack / "receipt.json")[0] if inputs.entity_pack else None
    if inputs.artist_source_completion is not None:
        if inputs.genre_context_pack is None:
            raise ValueError("source completion requires its native typed genre context")
        report = json.loads((inputs.artist_source_completion / "report.json").read_bytes())
        expected = sha256_file(inputs.genre_context_pack / "receipt.json")[0]
        if report["genre_replay"]["receipt_sha256"] != expected:
            raise ValueError("source-completion model binds a different native genre context")
    return research_contexts(
        source / "details", inputs.fma_map, inputs.artist_source_completion, entity_sha
    )


def context_shards(contexts: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Use fixed 256 exact-ID shards instead of duplicating full native detail records."""
    result: dict[str, dict[str, Any]] = {f"{number:02x}": {} for number in range(256)}
    for identity, row in sorted(contexts.items()):
        result[identity[:2]][identity] = row
    return result


def copy_native_facts(source: Path, output: Path, receipt: dict[str, Any]) -> None:
    """Hardlink verified native payloads; top UI/profile/genre index are regenerated."""
    excluded = {"profile.json", "genres.json", "index.html", *TOP_ASSETS}
    output.mkdir(parents=True, exist_ok=False)
    for relative in receipt["files"]:
        if relative in excluded:
            continue
        original, target = source / relative, output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        os.link(original, target)


def export_addons(
    output: Path,
    inputs: FullInputSources,
    contexts: dict[str, dict[str, Any]],
    reuse: Path | None = None,
) -> None:
    """Create immutable namespaces and exact-ID supplement shards."""
    for role, directory in addon_directories(inputs).items():
        export_research_files(directory, role, output)
    if contexts:
        directory = output / "research-contexts"
        directory.mkdir(exist_ok=False)
        for key, rows in context_shards(contexts).items():
            payload = canonical_json(rows)
            target = directory / f"{key}.json"
            existing = reuse / "research-contexts" / f"{key}.json" if reuse else None
            if existing is not None and existing.is_file():
                if existing.is_symlink() or existing.read_bytes() != payload:
                    raise ValueError("reuse shard differs from recomputed exact research context")
                os.link(existing, target)
            else:
                with target.open("xb") as stream:
                    stream.write(payload)


def research_profile(
    profile: dict[str, Any],
    inputs: FullInputSources,
    summary: dict[str, Any] | None,
    contexts: dict[str, dict[str, Any]],
) -> None:
    """Expose experimental outputs separately, with musical validation unclaimed."""
    if inputs.fma_map:
        profile["fma_map"] = {
            "path": "fma-map/",
            "license": "CC-BY-4.0",
            "musical_axes_available": False,
        }
    if inputs.fma_memberships:
        profile["fma_memberships"] = {
            "path": "fma-memberships/",
            "namespace": "fma-track-source-model-v1",
            "musical_probability": None,
        }
    if summary is not None:
        profile["source_completion"] = summary
    if contexts:
        profile["research_contexts"] = {"path": "research-contexts/", "prefix_length": 2}


def validate_addons(  # noqa: C901, PLR0912 - three separate namespace and native-fact boundaries.
    output: Path, inputs: FullInputSources
) -> None:
    """Re-derive every supplement while preserving the native observation boundary."""
    for role, directory in addon_directories(inputs).items():
        receipt = verify_research_files(directory, role)
        target = output / RESEARCH_ROLES[role][1]
        verify_research_files(target, role)
        for relative in [*receipt["files"], RESEARCH_ROLES[role][0]]:
            if sha256_file(directory / relative) != sha256_file(target / relative):
                raise ValueError("nested research bytes differ from their source artifact")
    if addon_directories(inputs):
        construction = json.loads((output / "construction.json").read_bytes())
        for relative, digest in construction["implementation_files"].items():
            if sha256_file(Path(__file__).resolve().parents[3] / relative)[0] != digest:
                raise ValueError("construction implementation source bytes have changed")
        expected_inputs = {
            name: {"path": str(getattr(inputs, name)), "receipt_sha256": digest}
            for name, digest in inputs.bindings().items()
            if digest is not None
        }
        if construction["input_roles"] != expected_inputs:
            raise ValueError("construction input recipe differs from exact replay roles")
    contexts, summary = supplemental_contexts(output, inputs)
    profile = json.loads((output / "profile.json").read_bytes())
    expected_profile: dict[str, Any] = {}
    research_profile(expected_profile, inputs, summary, contexts)
    for key in ("source_completion", "fma_map", "fma_memberships", "research_contexts"):
        if profile.get(key) != expected_profile.get(key):
            raise ValueError(
                "research profile role or promotion boundary differs from frozen outputs"
            )
    if summary is not None and profile.get("source_completion") != summary:
        raise ValueError("source-completion denominator or example differs from frozen proposals")
    if contexts:
        for key, expected in context_shards(contexts).items():
            if json.loads((output / f"research-contexts/{key}.json").read_bytes()) != expected:
                raise ValueError("research supplements differ from frozen exact-ID model context")
    for path in (output / "details").glob("*.json"):
        row = json.loads(path.read_bytes())
        if any(key in row for key in ("source_completion_proposals", "fma_descriptor_context")):
            raise ValueError("research supplements overwritten immutable native source facts")


def construction_manifest(root: Path, inputs: FullInputSources) -> dict[str, Any]:
    """Record actual Git base, dirty source bytes, input bindings and deterministic recipe."""

    def git(*arguments: str) -> str:
        return subprocess.check_output(  # noqa: S603 - literal read-only Git subcommands.
            ["git", "-C", str(root), *arguments],  # noqa: S607 - Git from PATH.
            text=True,
        )

    changed = set(git("diff", "--name-only", "HEAD").splitlines())
    changed.update(git("ls-files", "--others", "--exclude-standard").splitlines())
    source_changes = {
        path: {"sha256": sha256_file(root / path)[0], "bytes": (root / path).stat().st_size}
        for path in sorted(changed)
        if (root / path).is_file()
        and (
            path.startswith(("src/", "scripts/", "tests/", "docs/"))
            or path in {"pyproject.toml", "AGENTS.md", "poetry.lock"}
        )
    }
    implementation = [
        *sorted((root / "src/opennoise/pipeline").glob("full_input*.py")),
        *(root / "src/opennoise/static" / asset for asset in TOP_ASSETS),
        root / "scripts/build_full_input_foundation.py",
        root / "src/opennoise/ml/fma_sonic_map.py",
        root / "src/opennoise/ml/fma_memberships.py",
        root / "src/opennoise/ml/wikidata_artist_completion.py",
    ]
    return {
        "revision": "full-input-construction-recipe-v1",
        "git_base_commit": git("rev-parse", "HEAD").strip(),
        "git_status_porcelain": git("status", "--porcelain=v1"),
        "clean_worktree_claimed": False,
        "changed_source_files": source_changes,
        "implementation_files": {
            str(p.relative_to(root)): sha256_file(p)[0] for p in implementation
        },
        "invocation_argv": list(sys.argv),
        "input_roles": {
            name: {"path": str(getattr(inputs, name)), "receipt_sha256": digest}
            for name, digest in inputs.bindings().items()
            if digest is not None
        },
        "parameters": {
            "page_size": 500,
            "normalization": "NFKC casefold",
            "research_context_shards": 256,
            "core_projection_sha256": (
                "fd8d5d9cc36f1b90a200bf79c6316b5d2410045b31d2559a0d19c3f2ac2b8bbd"
            ),
            "core_artist_count": 2999670,
            "profile_revision": "open-foundation-full-input-v3",
        },
        "construction_randomness": "none; stable sorted source rows and fixed exact-ID shards",
        "model_parameters": (
            "frozen additive artifacts; their declarations/reports and code snapshots retained "
            "in separate namespaces; no refit or retuning during assembly"
        ),
    }
