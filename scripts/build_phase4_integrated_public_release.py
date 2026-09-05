# ruff: noqa: C901, E501, PLR2004
"""Build a custody-ready Phase 4 release from one sealed source-cache copy.

This is deliberately an integration command, not an ingestion command.  It
verifies the exact Phase 3 cache before and after every derived write, then
adds the retained, bounded MusicBrainz *core metadata* slice to the derived
serving SQLite database.  It never fetches sources, audio, or genre research.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen

from musix.musicbrainz_release_hydration import (
    MusicBrainzReleaseHydrationArtifact,
    artifact_counts,
    materialize_hydration_catalog,
)
from musix.open_construction_graph import (
    OpenConstructionGraphArtifact,
    verify_open_construction_graph,
)

_CACHE_SHA256 = "282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866"
_CACHE_BYTES = 153_231_360
_HYDRATION_SHA256 = "30bb3641e6503338121aa9fefb9b973f33c2136fe090f3cde775d786a5e4d519"
_REPRESENTATIVES_SHA256 = "5a85fde3788579f8a00b3c03090ce8a2a61e8a2556056796f66b59f5436142df"
_GRAPH_SHA256 = "94c7a5b3374e17e78aed8c7390e547235e06c041c9d51d803a77cb5d1e4a1d6f"
_GRAPH_LOGICAL_SHA256 = "9c080faae48db9270b4d8546bec003a90b62cd764ee6e233ed2b3a47f10d1957"
_ADDITIONAL_EVIDENCE = (
    ("musicbrainz-core-metadata-hydration", "musicbrainz-release-tracks.json"),
    ("musicbrainz-core-metadata-hydration-report", "musicbrainz-release-tracks.report.json"),
    ("representative-catalog-candidates", "representative-candidates-v1.json"),
    ("representative-catalog-candidates-report", "representative-candidates-v1.report.json"),
    ("open-construction-graph", "open-construction-graph-v1.json"),
    ("open-construction-graph-gate", "open-construction-graph-v1.gate.json"),
    ("open-construction-graph-receipt", "open-construction-graph-v1.receipt.json"),
    ("phase4-api-source-qa", "phase4-api-source-qa.json"),
    ("phase4-integration-report", "phase4-integration-report.json"),
)


class Phase4ReleaseError(RuntimeError):
    """Report an integrated release boundary that fails closed."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_exact(source: Path, destination: Path, expected_sha256: str) -> None:
    """Copy immutable bytes and prove the new path is not a shared hardlink."""
    source = source.resolve(strict=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if _sha256(source) != expected_sha256 or _sha256(destination) != expected_sha256:
        raise Phase4ReleaseError("certified source cache copy does not match its declared hash")
    if source.stat().st_ino == destination.stat().st_ino:
        raise Phase4ReleaseError("certified source cache must not share a mutable hardlink")


def _run(*command: str, environment: dict[str, str] | None = None) -> None:
    subprocess.run(command, check=True, env=environment)  # noqa: S603


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sqlite_checks(path: Path) -> dict[str, object]:
    with closing(sqlite3.connect(path)) as connection:
        integrity = tuple(str(row[0]) for row in connection.execute("PRAGMA integrity_check"))
        foreign_keys = tuple(connection.execute("PRAGMA foreign_key_check"))
        counts = connection.execute(
            """SELECT (SELECT count(*) FROM releases), (SELECT count(*) FROM media),
                      (SELECT count(*) FROM tracks), (SELECT count(*) FROM recordings),
                      (SELECT count(*) FROM album_genre_ranking_items)"""
        ).fetchone()
    return {
        "integrity_check": integrity,
        "foreign_key_violations": len(foreign_keys),
        "catalog_counts": {
            "releases": int(counts[0]),
            "media": int(counts[1]),
            "tracks": int(counts[2]),
            "recordings": int(counts[3]),
            "representative_catalog_candidates": int(counts[4]),
        },
    }


def _policy_id(database: Path) -> int:
    with closing(sqlite3.connect(database)) as connection:
        row = connection.execute(
            "SELECT id FROM rights_policies WHERE policy_key = ? AND policy_version = 1",
            ("musicbrainz-core-metadata-hydration",),
        ).fetchone()
    if row is None:
        raise Phase4ReleaseError("MusicBrainz core-metadata export policy was not materialized")
    return int(row[0])


def _api_qa(database: Path, map_path: Path, graph_path: Path, output: Path, port: int) -> None:
    """Record source/API proof separately from the renderer-owned browser proof."""
    environment = os.environ.copy()
    environment["MUSIX_PRODUCTION_MAP_PATH"] = str(map_path.resolve())
    environment["MUSIX_OPEN_CONSTRUCTION_GRAPH_PATH"] = str(graph_path.resolve())
    process = subprocess.Popen(  # noqa: S603
        [
            sys.executable,
            "-m",
            "musix.cli",
            "serve",
            "--database",
            str(database),
            "--port",
            str(port),
        ],
        env=environment,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 20
        while True:
            try:
                with urlopen(f"{base}/api/health", timeout=0.5) as response:  # noqa: S310
                    if response.status == 200:
                        break
            except OSError:
                if time.monotonic() >= deadline:
                    raise Phase4ReleaseError("Phase 4 API server did not become healthy") from None
                time.sleep(0.1)
        with closing(sqlite3.connect(database)) as connection:
            row = connection.execute(
                "SELECT release_group_id FROM releases ORDER BY id LIMIT 1"
            ).fetchone()
        if row is None:
            raise Phase4ReleaseError("hydrated catalog API probe has no release group")
        endpoints = (
            "/api/health",
            "/api/map",
            "/api/open-construction-map?level=0",
            f"/api/entities/{int(row[0])}/hydrated-release",
        )
        responses: dict[str, object] = {}
        for endpoint in endpoints:
            with urlopen(f"{base}{endpoint}", timeout=10) as response:  # noqa: S310
                payload = response.read()
                responses[endpoint] = {
                    "status": response.status,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "byte_size": len(payload),
                }
        _write_json(output, {"verified": True, "endpoints": responses})
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _bundle_phase4_release(
    root: Path, source_cache: Path, derived: Path, evidence: Path, gates: Path
) -> dict[str, object]:
    """Write, verify, and twice restore a portable bundle for the final derived database."""
    checks = _sqlite_checks(derived)
    manifest_path = root / "release-config" / "phase4-release-manifest.json"
    manifest = {
        "release_id": "phase4-integrated-public-20260904",
        "derived_database": {"sha256": _sha256(derived), "byte_size": derived.stat().st_size},
        "source_cache": {"sha256": _sha256(source_cache), "byte_size": source_cache.stat().st_size},
        "database_checks": checks,
        "source_policy": "exportable public metadata only; no supplementary genre research or audio",
    }
    _write_json(manifest_path, manifest)
    members = [
        (source_cache, "inputs/phase3-public-qualified.sqlite"),
        (derived, "release/phase4-public.sqlite"),
        (manifest_path, "release-config/phase4-release-manifest.json"),
    ]
    members.extend(
        (evidence / filename, f"evidence/{filename}") for _, filename in _ADDITIONAL_EVIDENCE
    )
    members.extend(
        (evidence / filename, f"evidence/{filename}")
        for filename in (
            "public-model.json",
            "production-map-v1.json",
            "production-map-v1.acceptance.json",
            "production-map-v1.seed-report.json",
            "production-map-v1.browser.json",
            "production-map-v1.report.json",
            "receipt.json",
        )
    )
    members.extend(
        (gates / filename, f"objective-gates/{filename}")
        for filename in (
            "public-model-gate-v1.json",
            "metadata-representatives-v1.json",
            "artist-membership-evaluation-v1.json",
            "artist-membership-judgments-v1.json",
        )
    )
    bundle = root / "portable-bundle"
    objects = bundle
    entries: list[dict[str, object]] = []
    for source, destination in members:
        if not source.is_file():
            raise Phase4ReleaseError(f"portable custody input is missing: {source}")
        digest = _sha256(source)
        object_path = objects / "sha256" / digest
        object_path.parent.mkdir(parents=True, exist_ok=True)
        if not object_path.is_file():
            shutil.copyfile(source, object_path)
        if _sha256(object_path) != digest:
            raise Phase4ReleaseError("custody object bytes changed during copy")
        entries.append(
            {
                "destination": destination,
                "sha256": digest,
                "byte_size": source.stat().st_size,
                "object": f"sha256/{digest}",
            }
        )
    receipt_path = root / "custody" / "phase4-custody-receipt.json"
    _write_json(
        receipt_path,
        {
            "revision": "phase4-public-custody-v1",
            "release_id": manifest["release_id"],
            "entries": sorted(entries, key=lambda item: str(item["destination"])),
        },
    )
    shutil.copyfile(receipt_path, bundle / "phase4-custody-receipt.json")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    for entry in receipt["entries"]:
        if _sha256(bundle / str(entry["object"])) != entry["sha256"]:
            raise Phase4ReleaseError("portable bundle checksum verification failed")
    restored = root / "restored"

    def restore() -> dict[str, str]:
        for entry in receipt["entries"]:
            destination = restored / str(entry["destination"])
            if not destination.resolve(strict=False).is_relative_to(restored.resolve()):
                raise Phase4ReleaseError("portable restore destination escapes its root")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(bundle / str(entry["object"]), destination)
            if _sha256(destination) != entry["sha256"]:
                raise Phase4ReleaseError(
                    "portable restored bytes differ from their custody checksum"
                )
        return {
            path.relative_to(restored).as_posix(): _sha256(path)
            for path in restored.rglob("*")
            if path.is_file()
        }

    first = restore()
    second = restore()
    if first != second:
        raise Phase4ReleaseError("portable restore is not byte-identically idempotent")
    return {
        "custody_receipt_sha256": _sha256(receipt_path),
        "bundle_entries": len(entries),
        "restored_files": len(second),
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-cache",
        type=Path,
        default=Path(".cache/phase4-source/phase3-public-qualified.sqlite"),
    )
    parser.add_argument(
        "--release-directory", type=Path, default=Path("config/releases/phase3-public-20260831")
    )
    parser.add_argument(
        "--source-vault",
        type=Path,
        default=Path("../phase3-public-evidence/data/phase3-final-vault"),
    )
    parser.add_argument(
        "--hydration-artifact",
        type=Path,
        default=Path("../../.cache/musicbrainz-20-catalog/release-tracks.json"),
    )
    parser.add_argument(
        "--graph", type=Path, default=Path("data/model/open-construction-graph-v1.json")
    )
    parser.add_argument(
        "--graph-gate", type=Path, default=Path("data/model/open-construction-graph-v1.gate.json")
    )
    parser.add_argument(
        "--graph-receipt",
        type=Path,
        default=Path("data/model/open-construction-graph-v1.receipt.json"),
    )
    parser.add_argument(
        "--output-directory", type=Path, default=Path(".cache/phase4-integrated-public")
    )
    parser.add_argument("--port", type=int, default=3014)
    parser.add_argument("--generated-at", default="2026-09-04T00:00:00+00:00")
    return parser.parse_args()


def main() -> int:
    """Build, verify, custody, bundle, restore, and replay one integrated public release."""
    arguments = _arguments()
    source_cache = arguments.source_cache.resolve(strict=True)
    if source_cache.stat().st_size != _CACHE_BYTES or _sha256(source_cache) != _CACHE_SHA256:
        raise Phase4ReleaseError("source cache is not the exact certified Phase 3 boundary")
    root = arguments.output_directory.resolve()
    evidence = root / "evidence"
    gates = root / "objective-gates"
    derived = root / "phase4-public.sqlite"
    copied_source = root / "source-cache-copy.sqlite"
    _copy_exact(source_cache, copied_source, _CACHE_SHA256)
    _run(
        sys.executable,
        "scripts/release_certify.py",
        "--release-directory",
        str(arguments.release_directory),
        "--cache-database",
        str(copied_source),
        "--serving-database",
        str(derived),
        "--model-output",
        str(evidence / "public-model.json"),
        "--receipt-output",
        str(evidence / "receipt.json"),
        "--map-output",
        str(evidence / "production-map-v1.json"),
        "--acceptance-output",
        str(evidence / "production-map-v1.acceptance.json"),
        "--seed-report-output",
        str(evidence / "production-map-v1.seed-report.json"),
        "--browser-evidence-output",
        str(evidence / "production-map-v1.browser.json"),
        "--report-output",
        str(evidence / "production-map-v1.report.json"),
        "--captures-directory",
        str(root / "captures"),
        "--port",
        str(arguments.port),
    )
    _run(
        sys.executable,
        "scripts/build_metadata_representatives.py",
        str(derived),
        "--output",
        str(gates / "metadata-representatives-v1.json"),
    )
    if _sha256(gates / "metadata-representatives-v1.json") != _REPRESENTATIVES_SHA256:
        raise Phase4ReleaseError(
            "recomputed representative selection differs from retained hydration input"
        )
    _run(
        sys.executable,
        "scripts/evaluate_public_model_gate.py",
        str(evidence / "public-model.json"),
        "--report",
        str(gates / "public-model-gate-v1.json"),
    )
    judgments = Path("tests/fixtures/artist_membership_judgments_v1.json")
    shutil.copyfile(judgments, gates / "artist-membership-judgments-v1.json")
    _run(
        sys.executable,
        "scripts/evaluate_artist_memberships.py",
        str(evidence / "public-model.json"),
        "--judgments",
        str(gates / "artist-membership-judgments-v1.json"),
        "--report",
        str(gates / "artist-membership-evaluation-v1.json"),
        "--database",
        str(root / "artist-membership-evaluations.sqlite"),
        "--object-store",
        str(root / "artist-membership-objects"),
    )
    hydration_source = arguments.hydration_artifact.resolve(strict=True)
    if _sha256(hydration_source) != _HYDRATION_SHA256:
        raise Phase4ReleaseError("retained hydration artifact hash does not match the release plan")
    hydration = MusicBrainzReleaseHydrationArtifact.model_validate_json(
        hydration_source.read_bytes()
    )
    if hydration.source_representative_artifact_sha256 != _REPRESENTATIVES_SHA256:
        raise Phase4ReleaseError("hydration artifact targets another representative selection")
    shutil.copyfile(hydration_source, evidence / "musicbrainz-release-tracks.json")
    materialized = materialize_hydration_catalog(
        hydration, database_path=derived, artifact_sha256=_HYDRATION_SHA256
    )
    replay = materialize_hydration_catalog(
        hydration, database_path=derived, artifact_sha256=_HYDRATION_SHA256
    )
    releases, media, tracks = artifact_counts(hydration)
    hydration_report = {
        "artifact_sha256": _HYDRATION_SHA256,
        "representative_artifact_sha256": _REPRESENTATIVES_SHA256,
        "retained_counts": {"releases": releases, "media": media, "tracks": tracks},
        "materialized": materialized.model_dump(mode="json"),
        "idempotent_replay": replay.model_dump(mode="json"),
        "content_boundary": "MusicBrainz CC0 core metadata only; no audio or supplementary genre research",
    }
    _write_json(evidence / "musicbrainz-release-tracks.report.json", hydration_report)
    _run(
        sys.executable,
        "-m",
        "musix.cli",
        "build-representative-catalog-candidates",
        "--database",
        str(derived),
        "--run-ref",
        "phase4-integrated-public-20260904",
        "--policy-id",
        str(_policy_id(derived)),
        "--generated-at",
        arguments.generated_at,
        "--max-genres",
        "20",
        "--max-candidates-per-genre",
        "10",
        "--output",
        str(evidence / "representative-candidates-v1.json"),
        "--object-store",
        str(root / "representative-candidate-objects"),
        "--report",
        str(evidence / "representative-candidates-v1.report.json"),
    )
    graph = arguments.graph.resolve(strict=True)
    graph_artifact = OpenConstructionGraphArtifact.model_validate_json(graph.read_bytes())
    if _sha256(graph) != _GRAPH_SHA256 or graph_artifact.output_sha256 != _GRAPH_LOGICAL_SHA256:
        raise Phase4ReleaseError(
            "committed open-construction graph does not match the release plan"
        )
    if not verify_open_construction_graph(graph_artifact).no_prohibited_inputs:
        raise Phase4ReleaseError("committed open-construction graph failed its source boundary")
    for source, filename in (
        (graph, "open-construction-graph-v1.json"),
        (arguments.graph_gate.resolve(strict=True), "open-construction-graph-v1.gate.json"),
        (arguments.graph_receipt.resolve(strict=True), "open-construction-graph-v1.receipt.json"),
    ):
        shutil.copyfile(source, evidence / filename)
    _api_qa(
        derived,
        evidence / "production-map-v1.json",
        graph,
        evidence / "phase4-api-source-qa.json",
        arguments.port + 1,
    )
    database_checks = _sqlite_checks(derived)
    if database_checks["integrity_check"] != ("ok",) or database_checks["foreign_key_violations"]:
        raise Phase4ReleaseError(
            "derived SQLite release failed integrity or foreign-key verification"
        )
    if _sha256(copied_source) != _CACHE_SHA256 or _sha256(source_cache) != _CACHE_SHA256:
        raise Phase4ReleaseError("a certified source-cache copy changed during derivation")
    _write_json(
        evidence / "phase4-integration-report.json",
        {
            "release_id": "phase4-integrated-public-20260904",
            "certified_source_cache": {"sha256": _CACHE_SHA256, "byte_size": _CACHE_BYTES},
            "derived_database_sha256": _sha256(derived),
            "database_checks": database_checks,
            "browser_verified": bool(
                json.loads(
                    (evidence / "production-map-v1.browser.json").read_text(encoding="utf-8")
                ).get("labels")
            ),
            "source_policy": "exportable public inputs only; MusicBrainz CC0 core metadata; no supplementary genre research or audio",
        },
    )
    bundle_summary = _bundle_phase4_release(root, copied_source, derived, evidence, gates)
    _write_json(
        root / "phase4-release-summary.json",
        {
            **bundle_summary,
            "source_cache_sha256_after": _sha256(source_cache),
            "derived_database_sha256": _sha256(derived),
            "created_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        },
    )
    sys.stdout.write((root / "phase4-release-summary.json").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError, Phase4ReleaseError) as error:
        raise SystemExit(f"phase4 integrated public release failed: {error}") from error
