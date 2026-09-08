"""Launch the loopback-only local MusicBrainz discovery panel."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from scripts.run_dev import resolve_production_paths


def main() -> int:
    """Start the normal dev app with completed local research inputs enabled."""
    root = Path.cwd()
    production = resolve_production_paths(root)
    if production is None:
        sys.stderr.write("Production map unavailable. Run `uv run poe release-certify` first.\n")
        return 2
    inputs = {
        "MUSIX_LOCAL_RESEARCH_ARTIST_EVIDENCE_DATABASE": root
        / ".cache/musicbrainz-release-group-evidence-candidate-v1/evidence.sqlite",
        "MUSIX_LOCAL_RESEARCH_ARTIST_EVIDENCE_ARTIFACT": root
        / ".cache/musicbrainz-release-group-evidence-candidate-v1/artifact.json",
        "MUSIX_LOCAL_RESEARCH_SEED_RECONCILIATION": root
        / ".cache/musicbrainz-full-seed-targets/pipeline/seed-reconciliation.json",
        "MUSIX_LOCAL_RESEARCH_ADAPTER_REPORT": root
        / ".cache/musicbrainz-full-seed-targets/pipeline/musicbrainz-model-adapter-report.json",
        "MUSIX_LOCAL_RESEARCH_PEER_INDEX": root
        / ".cache/musicbrainz-full-seed-targets/pipeline/peer-similarity-local-research.sqlite",
        "MUSIX_LOCAL_RESEARCH_ARTIST_METADATA_DATABASE": root
        / ".cache/musicbrainz-release-group-artist-metadata-v1/metadata.sqlite",
        "MUSIX_LOCAL_RESEARCH_ARTIST_METADATA_ARTIFACT": root
        / ".cache/musicbrainz-release-group-artist-metadata-v1/artifact.json",
    }
    missing = [str(path) for path in inputs.values() if not path.is_file()]
    if missing:
        sys.stderr.write("Local research inputs are unavailable:\n" + "\n".join(missing) + "\n")
        return 2
    environment = os.environ | {
        "MUSIX_DATABASE_PATH": str(production.database),
        "MUSIX_DATABASE_READ_ONLY": "true",
        "MUSIX_PRODUCTION_MAP_PATH": str(production.map_artifact),
        "HOST": "127.0.0.1",
        "PORT": os.environ.get("PORT", "3002"),
        "MUSIX_LOCAL_RESEARCH_ARTIST_EVIDENCE_ENABLED": "true",
        **{key: str(value) for key, value in inputs.items()},
    }
    return subprocess.run(
        [sys.executable, "-m", "musix.cli", "serve"], check=False, env=environment
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
