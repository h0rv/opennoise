"""Bind research add-ons without converting suggestions into source observations."""

from __future__ import annotations

import errno
import io
import json
import os
import shutil
from pathlib import Path
from typing import Any

import zstandard

from opennoise.common import sha256_file

RESEARCH_ROLES = {
    "fma_map": ("receipt.json", "fma-map", "fma-sonic-pca-context-v1", "CC-BY-4.0"),
    "fma_memberships": (
        "pack-receipt.json",
        "fma-memberships",
        "fma-component-positive-memberships-v1",
        "CC-BY-4.0",
    ),
    "artist_source_completion": (
        "receipt.json",
        "artist-source-completion",
        "wikidata-artist-completion-v1",
        "CC0-1.0",
    ),
}


def verify_research_files(directory: Path, role: str) -> dict[str, Any]:
    """Verify a closed byte inventory while leaving model and musical validation distinct."""
    receipt_name, _, revision, license_name = RESEARCH_ROLES[role]
    receipt = json.loads((directory / receipt_name).read_bytes())
    if revision is not None and receipt["revision"] != revision:
        raise ValueError("research add-on has an incompatible namespace")
    if role != "artist_source_completion" and receipt["license"] != license_name:
        raise ValueError("research add-on license differs from its input role")
    expected = set(receipt["files"]) | {receipt_name}
    if (directory / "README.md").is_file():
        expected.add("README.md")
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
    if (
        directory.is_symlink()
        or any(p.is_symlink() for p in directory.rglob("*"))
        or actual != expected
    ):
        raise ValueError("research add-on closed file set differs")
    for relative, binding in receipt["files"].items():
        path = directory / relative
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("research add-on path is unsafe")
        if sha256_file(path) != (binding["sha256"], binding["bytes"]):
            raise ValueError("research add-on bytes differ from frozen inventory")
    if role == "fma_map" and receipt["musical_validation_established"] is not False:
        raise ValueError("research map asserts unestablished musical validation")
    return receipt


def export_research_files(directory: Path, role: str, output: Path) -> None:
    """Hardlink a verified immutable artifact into its own namespace."""
    verify_research_files(directory, role)
    namespace = RESEARCH_ROLES[role][1]
    destination = output / namespace
    destination.mkdir(exist_ok=False)
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            target = destination / path.relative_to(directory)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(path, target)
            except OSError as error:
                if error.errno != errno.EXDEV:
                    raise
                shutil.copyfile(path, target)


def descriptor_context(map_directory: Path, artists: dict[str, dict[str, Any]]) -> None:
    """Join native FMA descriptors only through existing exact artist bridges."""
    verify_research_files(map_directory, "fma_map")
    projection = json.loads((map_directory / "coordinates.json").read_bytes())
    if projection["artist_genres_inferred"] is not False:
        raise ValueError("native descriptor context cannot assert inferred artist genres")
    coordinates = {row["artist_id"]: row for row in projection["artists"]}
    receipt_sha = sha256_file(map_directory / "receipt.json")[0]
    for artist in artists.values():
        contexts = []
        for context in artist.get("fma_track_context", []):
            identity = context["fma_artist_id"]
            if identity not in coordinates:
                raise ValueError(
                    "exact bridged FMA artist missing from complete descriptor projection"
                )
            contexts.append(
                {
                    **coordinates[identity],
                    "fma_artist_id": identity,
                    "license": "CC-BY-4.0",
                    "source_receipt_sha256": receipt_sha,
                    "scope": (
                        "native FMA artist descriptor context; not recording equality "
                        "or artist genre membership"
                    ),
                    "musical_axes_available": False,
                }
            )
        if contexts:
            artist["fma_descriptor_context"] = contexts


def source_completion(
    directory: Path, artists: dict[str, dict[str, Any]], source_receipt_sha: str
) -> dict[str, Any]:
    """Attach distinct frozen suggestions after exact-ID and observed-seed checks."""
    verify_research_files(directory, "artist_source_completion")
    report = json.loads((directory / "report.json").read_bytes())
    if (
        report["source_license"] != "CC0-1.0"
        or report["artist_replay"]["receipt_sha256"] != source_receipt_sha
    ):
        raise ValueError("source-completion model does not bind the provided native CC0 entities")
    completion_receipt_sha = sha256_file(directory / "receipt.json")[0]
    requested = set()
    proposal_count = 0
    example = None
    with (
        (directory / "artist-proposals.jsonl.zst").open("rb") as raw,
        zstandard.ZstdDecompressor().stream_reader(raw) as stream,
    ):
        for line in io.TextIOWrapper(stream):
            row = json.loads(line)
            identity = row["artist_mbid"]
            if identity in requested or identity not in artists:
                raise ValueError(
                    "source-completion artist is duplicated or outside verified source facts"
                )
            requested.add(identity)
            if (
                row["namespace"] != "experimental-source-completion-v1"
                or row["default_promotion"] is not False
            ):
                raise ValueError("source-completion artifact silently promotes suggestions")
            if not set(row["observed_genre_qids"]).issubset(artists[identity]["direct_genres"]):
                raise ValueError(
                    "source-completion seeds are not observed exact-identity source genres"
                )
            for proposal in row["proposals"]:
                if (
                    proposal["musical_membership_probability"] is not None
                    or proposal["proposal_probability"] is not None
                ):
                    raise ValueError(
                        "source-completion artifact invents a musical or full-seed probability"
                    )
            artists[identity]["source_completion_proposals"] = row["proposals"]
            artists[identity]["source_completion_evidence"] = {
                "namespace": row["namespace"],
                "abstention": row["abstention"],
                "observed_seed_qids": row["observed_genre_qids"],
                "source_receipt_sha256": completion_receipt_sha,
                "default_promotion": False,
                "musical_probability": None,
            }
            proposal_count += len(row["proposals"])
            if example is None and row["proposals"]:
                example = identity
    return {
        "namespace": "experimental-source-completion-v1",
        "default_promotion": False,
        "artists": len(requested),
        "proposal_count": proposal_count,
        "example_artist_mbid": example,
        "musical_probability": None,
    }


def research_contexts(
    details: Path,
    map_directory: Path | None,
    completion: Path | None,
    source_receipt_sha: str | None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any] | None]:
    """Derive supplemental fields without copying full native fact records into memory."""
    artists = {}
    for path in sorted(details.glob("*.json")):
        row = json.loads(path.read_bytes())
        artists[row["artist_mbid"]] = {
            "artist_mbid": row["artist_mbid"],
            "direct_genres": row["direct_genres"],
            "fma_track_context": row.get("fma_track_context", []),
        }
    summary = None
    if completion is not None:
        if source_receipt_sha is None:
            raise ValueError("source completion requires the exact native entity source")
        summary = source_completion(completion, artists, source_receipt_sha)
    if map_directory is not None:
        descriptor_context(map_directory, artists)
    return {
        identity: {
            key: artist[key]
            for key in (
                "source_completion_proposals",
                "source_completion_evidence",
                "fma_descriptor_context",
            )
            if key in artist
        }
        for identity, artist in artists.items()
        if any(key in artist for key in ("source_completion_proposals", "fma_descriptor_context"))
    }, summary
